"""Entry point for the kagura-code middleware subprocess.

Reads KAGURA_CODE_* env vars, builds the FastAPI app, runs uvicorn.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable

import uvicorn

from ..compression import CompressionPolicy, LiteLLMSummarizer
from ..session_state import SessionStore
from ..tool_router import ToolRouter
from .app import build_app

log = logging.getLogger(__name__)


def _policy_factory(model_index_json: str) -> Callable[[str], CompressionPolicy]:
    """Return a callable that maps an alias to a CompressionPolicy.

    model_index_json maps alias → context_window (set by the parent process
    so each per-request CompressionPolicy uses the right model_context_window).
    Malformed JSON falls back to an empty index — the per-alias lookup then
    uses its built-in default rather than crashing the subprocess at startup.
    """
    try:
        index: dict[str, int] = (
            json.loads(model_index_json) if model_index_json else {}
        )
    except (json.JSONDecodeError, TypeError) as e:
        log.warning(
            "middleware: KAGURA_CODE_MODEL_INDEX malformed (%r); "
            "falling back to empty index", e,
        )
        index = {}

    def make(alias: str) -> CompressionPolicy:
        ctx = index.get(alias, 200_000)
        return CompressionPolicy(
            threshold_tokens=50_000,
            threshold_cap_pct=0.4,
            model_context_window=ctx,
        )

    return make


def main() -> None:
    proxy_url = os.environ["KAGURA_CODE_PROXY_URL"]
    router_model = os.environ["KAGURA_CODE_ROUTER_MODEL"]
    master_key = os.environ["KAGURA_CODE_MASTER_KEY"]
    router_timeout = float(os.environ.get("KAGURA_CODE_ROUTER_TIMEOUT", "5.0"))
    port = int(os.environ["KAGURA_CODE_PORT"])
    raw_aliases = os.environ.get("KAGURA_CODE_KNOWN_ALIASES", "")
    known_aliases = frozenset(a for a in raw_aliases.split(",") if a)
    default_alias = os.environ.get("KAGURA_CODE_DEFAULT_ALIAS") or None
    summarizer_model = os.environ.get("KAGURA_CODE_SUMMARIZER_MODEL") or None
    model_index_json = os.environ.get("KAGURA_CODE_MODEL_INDEX", "{}")

    summarizer = None
    if summarizer_model:
        summarizer_timeout = float(
            os.environ.get("KAGURA_CODE_SUMMARIZER_TIMEOUT", "180.0")
        )
        summarizer = LiteLLMSummarizer(
            proxy_url=proxy_url,
            model=summarizer_model,
            master_key=master_key,
            timeout_s=summarizer_timeout,
        )

    app = build_app(
        router=ToolRouter(
            proxy_url=proxy_url,
            router_model=router_model,
            master_key=master_key,
            timeout_s=router_timeout,
        ),
        store=SessionStore(),
        proxy_url=proxy_url,
        known_aliases=known_aliases,
        default_alias=default_alias,
        summarizer=summarizer,
        compression_policy_factory=_policy_factory(model_index_json),
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
