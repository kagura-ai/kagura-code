"""FastAPI middleware that sits between Claude Code and the LiteLLM proxy.

For each /v1/messages request:
  1. Snapshot the tool catalog into the session state.
  2. If the session is in full-load mode, skip routing and forward unchanged.
  3. Otherwise, ask the router which non-core tools are needed and shrink the
     tools array to CORE union predictions.
  4. Forward to LiteLLM and return the response to Claude Code.
  5. Inspect tool_use blocks in the response; any non-filtered tool name
     bumps the miss counter and promotes the session to full-load.

The /health endpoint is for readiness probes from `MiddlewareManager.start()`.

A FastAPI lifespan task periodically calls SessionStore.gc() so sessions that
go idle past the TTL are evicted; without this the dict grows unbounded over
the middleware process's lifetime.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx as _httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..compression import (
    CompressionPolicy,
    CompressionState,
    Summarizer,
    maybe_compress,
)
from ..session_state import SessionStore
from ..tool_catalog import ToolCatalog
from ..tool_router import ToolRouter

log = logging.getLogger(__name__)

# How often the GC task wakes; sessions older than the store's max_age_s are
# evicted on each pass. 5 minutes balances cleanup latency against wasted work.
_GC_INTERVAL_S = 300.0


def extract_session_id(headers: dict[str, str], body: dict[str, Any]) -> str:
    """Stable session key.

    Primary: x-anthropic-session-id header. Fallback (when header is absent):
    SHA-256 of body.system (first 4KB) with prefix `fb-`.
    """
    sid = headers.get("x-anthropic-session-id") or headers.get("X-Anthropic-Session-Id")
    if sid:
        return sid
    system = str(body.get("system") or "")[:4096]
    digest = hashlib.sha256(system.encode("utf-8", errors="ignore")).hexdigest()
    return f"fb-{digest[:16]}"


def _last_user_message(body: dict[str, Any]) -> str:
    messages = body.get("messages") or []
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                return " ".join(texts)
    return ""


def _check_for_misses(
    resp_json: dict[str, Any],
    forwarded_names: set[str],
    store: SessionStore,
    session_id: str,
) -> None:
    blocks = resp_json.get("content") or []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            name = b.get("name")
            if name and name not in forwarded_names:
                store.record_miss(session_id)
                log.warning(
                    "middleware: miss — model called %r which was not in the filtered tool list",
                    name,
                )


async def _gc_loop(store: SessionStore, interval_s: float) -> None:
    """Periodically evict expired sessions. Cancelled on app shutdown."""
    try:
        while True:
            await asyncio.sleep(interval_s)
            try:
                removed = store.gc()
                if removed:
                    log.info("middleware: gc evicted %d stale session(s)", removed)
            except Exception as e:
                log.warning("middleware: gc pass failed (%r); continuing", e)
    except asyncio.CancelledError:
        pass


def build_app(
    *,
    router: ToolRouter,
    store: SessionStore,
    proxy_url: str,
    known_aliases: frozenset[str] = frozenset(),
    default_alias: str | None = None,
    summarizer: Summarizer | None = None,
    compression_policy_factory: Callable[[str], CompressionPolicy] | None = None,
    gc_interval_s: float = _GC_INTERVAL_S,
) -> FastAPI:
    """Construct the FastAPI app. `proxy_url` is the URL of the LiteLLM proxy
    that the middleware forwards filtered requests to.

    When `default_alias` is set, any `model` field in /v1/messages that is not
    in `known_aliases` is silently rewritten to `default_alias`.  This catches
    Claude Code's native `/model` picks (`claude-opus-4-5`, etc.) and routes
    them to the configured default rather than letting LiteLLM 404 the alias.
    Doing the rewrite here keeps the LiteLLM `/v1/models` list clean — adding
    a wildcard entry to the LiteLLM config would pollute that endpoint and
    confuse the picker's enumeration.

    A periodic GC task wakes every `gc_interval_s` seconds and calls
    `store.gc()` to evict idle sessions; pass `gc_interval_s=0` to disable
    (useful for tests).
    """
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        gc_task: asyncio.Task[None] | None = None
        if gc_interval_s > 0:
            gc_task = asyncio.create_task(_gc_loop(store, gc_interval_s))
        try:
            yield
        finally:
            if gc_task is not None:
                gc_task.cancel()

    app = FastAPI(title="kagura-code middleware", lifespan=lifespan)
    app.state.router = router
    app.state.store = store
    app.state.proxy_url = proxy_url.rstrip("/")
    app.state.known_aliases = known_aliases
    app.state.default_alias = default_alias
    app.state.summarizer = summarizer
    app.state.compression_policy_factory = compression_policy_factory or (
        lambda _model: CompressionPolicy(
            threshold_tokens=50_000,
            threshold_cap_pct=0.4,
            model_context_window=200_000,
        )
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def list_models(req: Request) -> JSONResponse:
        headers = {
            k: v
            for k, v in req.headers.items()
            if k.lower() not in {"host", "content-length", "authorization"}
        }
        # See /v1/messages: client's Authorization is replaced with LiteLLM's
        # master_key so the request authenticates regardless of what Claude
        # Code put on the wire.
        headers["Authorization"] = "Bearer kagura-code-dummy"
        async with _httpx.AsyncClient(timeout=30.0) as c:
            upstream = await c.get(f"{app.state.proxy_url}/v1/models", headers=headers)
        try:
            body = upstream.json()
        except ValueError:
            body = {"raw": upstream.text}
        # LiteLLM 1.82.x always appends an `id: "*"` wildcard entry to its
        # /v1/models output regardless of whether the config declares one.
        # Claude Code's /model picker reads that response and the `*` entry
        # poisons its enumeration, collapsing the visible list of custom
        # Ollama aliases down to just the launch model. Strip the wildcard
        # here so the picker sees a clean list of real aliases.
        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, list):
                body["data"] = [
                    m for m in data
                    if not (isinstance(m, dict) and m.get("id") == "*")
                ]
        return JSONResponse(content=body, status_code=upstream.status_code)

    @app.post("/v1/messages")
    async def messages(req: Request) -> JSONResponse:
        headers = {k.lower(): v for k, v in req.headers.items()}
        body = await req.json()
        if (
            app.state.default_alias is not None
            and isinstance(body.get("model"), str)
            and body["model"] not in app.state.known_aliases
        ):
            log.info(
                "middleware: rewriting unknown model %r → %r",
                body["model"],
                app.state.default_alias,
            )
            body["model"] = app.state.default_alias
        sid = extract_session_id(headers, body)
        session = app.state.store.get_or_create(sid)

        if app.state.summarizer is not None:
            if session.compression is None:
                session.compression = CompressionState()
            policy = app.state.compression_policy_factory(body.get("model", ""))
            raw_messages = body.get("messages")
            # `messages` from a malformed client can be a non-list (str/dict/None);
            # passing those into maybe_compress would explode in approx_tokens'
            # iteration. Coerce to [] at the boundary.
            messages_in = raw_messages if isinstance(raw_messages, list) else []
            body["messages"] = await maybe_compress(
                messages_in,
                state=session.compression,
                policy=policy,
                summarizer=app.state.summarizer,
            )

        catalog = ToolCatalog.from_request(body)

        if session.full_load or not catalog.non_core_names():
            filtered = catalog.all() if session.full_load else (body.get("tools") or [])
        else:
            stub = catalog.stub_text()
            user_msg = _last_user_message(body)
            prediction = await app.state.router.predict(
                user_message=user_msg, catalog_stub=stub,
            )
            if prediction == ToolRouter.FALLBACK_ALL:
                filtered = catalog.all()
            else:
                filtered = catalog.filter_with_core(prediction)

        forwarded_body = {**body, "tools": filtered}
        forwarded_body["stream"] = False

        upstream_headers = {
            k: v
            for k, v in headers.items()
            if k.lower() not in {"host", "content-length", "authorization"}
        }
        # LiteLLM validates Authorization against its configured master_key.
        # Whatever token Claude Code put on the wire (its claude.ai-derived
        # OAuth token, an ANTHROPIC_API_KEY, etc.) is irrelevant to LiteLLM,
        # so replace it with the master_key here.
        upstream_headers["Authorization"] = "Bearer kagura-code-dummy"
        async with _httpx.AsyncClient(timeout=300.0) as c:
            upstream = await c.post(
                f"{app.state.proxy_url}/v1/messages",
                json=forwarded_body,
                headers=upstream_headers,
            )

        try:
            resp_json = upstream.json()
        except ValueError:
            resp_json = None

        if resp_json is not None:
            forwarded_names = {t["name"] for t in filtered}
            _check_for_misses(resp_json, forwarded_names, app.state.store, sid)

        passthrough_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in {"content-length", "content-encoding", "transfer-encoding"}
        }
        return JSONResponse(
            content=resp_json if resp_json is not None else {"raw": upstream.text},
            status_code=upstream.status_code,
            headers=passthrough_headers,
        )

    return app
