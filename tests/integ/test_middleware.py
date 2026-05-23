"""Integration tests for the middleware FastAPI app.

Each test starts a real FastAPI app via httpx.ASGITransport (no port binding),
backed by a pytest-httpserver stub standing in for LiteLLM.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpserver import HTTPServer

from kagura_code.compression import CompressionPolicy, LiteLLMSummarizer
from kagura_code.middleware import build_app
from kagura_code.session_state import SessionStore
from kagura_code.tool_router import ToolRouter

FIXTURE = Path(__file__).parent.parent / "unit" / "fixtures" / "anthropic_messages_request.json"


def _router_response(tools: list[str]) -> dict:
    return {
        "id": "chatcmpl",
        "object": "chat.completion",
        "created": 0,
        "model": "claude-router",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": json.dumps(tools)},
             "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _anthropic_response(text: str = "ok") -> dict:
    return {
        "id": "msg_x",
        "type": "message",
        "role": "assistant",
        "model": "claude-deepseek-v4-pro",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


def test_session_id_from_header():
    from kagura_code.middleware import extract_session_id

    headers = {"x-anthropic-session-id": "sess-abc"}
    body: dict = {"messages": []}
    assert extract_session_id(headers, body) == "sess-abc"


def test_session_id_fallback_when_header_absent():
    from kagura_code.middleware import extract_session_id

    headers: dict = {}
    body = {
        "system": "You are Claude Code...",
        "messages": [{"role": "user", "content": "hello"}],
    }
    sid = extract_session_id(headers, body)
    assert sid == extract_session_id(headers, body)
    assert sid.startswith("fb-")
    assert len(sid) > 10


@pytest.mark.asyncio
async def test_messages_route_filters_tools_per_router_prediction(httpserver: HTTPServer):
    received_bodies: list[dict] = []

    httpserver.expect_ordered_request(
        "/v1/chat/completions", method="POST",
    ).respond_with_json(_router_response(["mcp__github__create_issue"]))

    def capture_main(req):
        received_bodies.append(req.get_json())
        from werkzeug.wrappers import Response
        return Response(json.dumps(_anthropic_response()), content_type="application/json")

    httpserver.expect_ordered_request(
        "/v1/messages", method="POST",
    ).respond_with_handler(capture_main)

    app = build_app(
        router=ToolRouter(
            proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
        ),
        store=SessionStore(),
        proxy_url=httpserver.url_for(""),
    )

    body = json.loads(FIXTURE.read_text())
    body["messages"] = [{"role": "user", "content": "open a github issue"}]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
        r = await c.post(
            "/v1/messages",
            json=body,
            headers={"x-anthropic-session-id": "sess-1"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["content"][0]["text"] == "ok"

    assert len(received_bodies) == 1
    forwarded = received_bodies[0]
    forwarded_names = {t["name"] for t in forwarded["tools"]}
    assert "Read" in forwarded_names
    assert "Bash" in forwarded_names
    assert "mcp__github__create_issue" in forwarded_names
    assert "mcp__postgres__query" not in forwarded_names
    assert "mcp__slack__send_message" not in forwarded_names


@pytest.mark.asyncio
async def test_health_endpoint(httpserver: HTTPServer):
    app = build_app(
        router=ToolRouter(
            proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
        ),
        store=SessionStore(),
        proxy_url=httpserver.url_for(""),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_unknown_model_rewritten_to_default_alias(httpserver: HTTPServer):
    """Anthropic-native /model picks (e.g. claude-opus-4-5) should be silently
    rewritten to the configured default before forwarding to LiteLLM.
    """
    received: list[dict] = []

    def capture_main(req):
        received.append(req.get_json())
        from werkzeug.wrappers import Response
        return Response(json.dumps(_anthropic_response()), content_type="application/json")

    httpserver.expect_request("/v1/messages", method="POST").respond_with_handler(capture_main)

    app = build_app(
        router=ToolRouter(
            proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
        ),
        store=SessionStore(),
        proxy_url=httpserver.url_for(""),
        known_aliases=frozenset({"claude-deepseek-v4-pro", "claude-qwen3-coder"}),
        default_alias="claude-deepseek-v4-pro",
    )

    body = {
        "model": "claude-opus-4-5",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [],
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
        r = await c.post("/v1/messages", json=body)

    assert r.status_code == 200
    assert received[-1]["model"] == "claude-deepseek-v4-pro"


@pytest.mark.asyncio
async def test_known_model_alias_passes_through_unchanged(httpserver: HTTPServer):
    received: list[dict] = []

    def capture_main(req):
        received.append(req.get_json())
        from werkzeug.wrappers import Response
        return Response(json.dumps(_anthropic_response()), content_type="application/json")

    httpserver.expect_request("/v1/messages", method="POST").respond_with_handler(capture_main)

    app = build_app(
        router=ToolRouter(
            proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
        ),
        store=SessionStore(),
        proxy_url=httpserver.url_for(""),
        known_aliases=frozenset({"claude-deepseek-v4-pro", "claude-qwen3-coder"}),
        default_alias="claude-deepseek-v4-pro",
    )

    body = {
        "model": "claude-qwen3-coder",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [],
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
        r = await c.post("/v1/messages", json=body)

    assert r.status_code == 200
    assert received[-1]["model"] == "claude-qwen3-coder"


@pytest.mark.asyncio
async def test_v1_models_endpoint_proxies_upstream(httpserver: HTTPServer):
    upstream_payload = {
        "data": [
            {"id": "claude-deepseek-v4-pro", "object": "model"},
            {"id": "claude-qwen3-coder", "object": "model"},
        ],
        "object": "list",
    }
    httpserver.expect_request("/v1/models", method="GET").respond_with_json(upstream_payload)

    app = build_app(
        router=ToolRouter(
            proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
        ),
        store=SessionStore(),
        proxy_url=httpserver.url_for(""),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
        r = await c.get("/v1/models")

    assert r.status_code == 200
    body = r.json()
    ids = {m["id"] for m in body["data"]}
    assert ids == {"claude-deepseek-v4-pro", "claude-qwen3-coder"}
    assert "*" not in ids


@pytest.mark.asyncio
async def test_middleware_strips_litellm_wildcard_from_models_list(httpserver: HTTPServer):
    """LiteLLM 1.82.x always appends an `id: "*"` entry to /v1/models output;
    the middleware must strip it so Claude Code's /model picker sees only
    the real configured aliases (else the picker collapses to one entry).
    """
    upstream_payload = {
        "data": [
            {"id": "claude-deepseek-v4-pro", "object": "model"},
            {"id": "claude-qwen3-coder", "object": "model"},
            {"id": "*", "object": "model"},
        ],
        "object": "list",
    }
    httpserver.expect_request("/v1/models", method="GET").respond_with_json(upstream_payload)

    app = build_app(
        router=ToolRouter(
            proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy",
        ),
        store=SessionStore(),
        proxy_url=httpserver.url_for(""),
        gc_interval_s=0,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
        r = await c.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    ids = {m["id"] for m in body["data"]}
    assert ids == {"claude-deepseek-v4-pro", "claude-qwen3-coder"}
    assert "*" not in ids


@pytest.mark.asyncio
async def test_middleware_compresses_messages_when_over_threshold(httpserver: HTTPServer):
    """End-to-end: large messages → middleware → summarizer call → cached
    summary applied → forwarded body has fewer messages with summary at head.
    """
    httpserver.expect_request(
        "/v1/chat/completions", method="POST"
    ).respond_with_json({
        "id": "x", "object": "chat.completion", "created": 0, "model": "summ",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "S_SUMMARY"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })

    forwarded_bodies: list[dict] = []

    def capture_main(req):
        forwarded_bodies.append(req.get_json())
        from werkzeug.wrappers import Response
        return Response(
            json.dumps(_anthropic_response()), content_type="application/json",
        )

    httpserver.expect_request("/v1/messages", method="POST").respond_with_handler(capture_main)

    summ = LiteLLMSummarizer(
        proxy_url=httpserver.url_for(""), model="claude-qwen3-5", master_key="dummy",
    )

    def policy_factory(_model: str) -> CompressionPolicy:
        return CompressionPolicy(
            threshold_tokens=5_000, threshold_cap_pct=0.4,
            model_context_window=1_000_000,
        )

    app = build_app(
        router=ToolRouter(
            proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy",
        ),
        store=SessionStore(),
        proxy_url=httpserver.url_for(""),
        summarizer=summ,
        compression_policy_factory=policy_factory,
        gc_interval_s=0,  # disable periodic GC in tests for determinism
    )

    big = "x" * 500
    body = {
        "model": "claude-deepseek-v4-pro",
        "messages": [{"role": "user", "content": big} for _ in range(50)],
        "tools": [],
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
        # First turn: fires background task, returns uncompressed.
        await c.post("/v1/messages", json=body, headers={"x-anthropic-session-id": "sess-c"})
        # Deterministically wait for the background task to finish instead of
        # racing on a fixed sleep.
        session = app.state.store.get_or_create("sess-c")
        assert session.compression is not None
        if session.compression.compress_task is not None:
            await session.compression.compress_task
        # Second turn: cache hit, body forwarded should have summary at head.
        body2 = dict(body)
        body2["messages"] = [*body["messages"], {"role": "user", "content": "follow-up"}]
        await c.post("/v1/messages", json=body2, headers={"x-anthropic-session-id": "sess-c"})

    second_forwarded = forwarded_bodies[-1]
    first_msg = second_forwarded["messages"][0]
    assert first_msg["role"] == "user"
    assert "S_SUMMARY" in first_msg["content"][0]["text"]
    # Recent tail preserved
    assert second_forwarded["messages"][-1]["content"] == "follow-up"


@pytest.mark.asyncio
async def test_middleware_pass_through_when_summarizer_none(httpserver: HTTPServer):
    forwarded: list[dict] = []

    def capture_main(req):
        forwarded.append(req.get_json())
        from werkzeug.wrappers import Response
        return Response(json.dumps(_anthropic_response()), content_type="application/json")

    httpserver.expect_request("/v1/messages", method="POST").respond_with_handler(capture_main)

    app = build_app(
        router=ToolRouter(
            proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy",
        ),
        store=SessionStore(),
        proxy_url=httpserver.url_for(""),
        summarizer=None,
    )
    big = "x" * 500
    body = {
        "model": "claude-deepseek-v4-pro",
        "messages": [{"role": "user", "content": big} for _ in range(50)],
        "tools": [],
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
        await c.post("/v1/messages", json=body, headers={"x-anthropic-session-id": "sess-d"})

    # No compression, all 50 messages forwarded as-is.
    assert len(forwarded[0]["messages"]) == 50
