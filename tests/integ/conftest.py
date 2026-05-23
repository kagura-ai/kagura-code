"""Shared fixtures for integration tests.

These tests run a real LiteLLM proxy subprocess against a pytest-httpserver
that stands in for the Ollama daemon. With LiteLLM's ollama_chat/ provider,
upstream calls go to Ollama's native /api/chat endpoint (not OpenAI-compat
/v1/chat/completions), so fixtures here register /api/chat and respond in
the Ollama-native JSON shape.
"""
from __future__ import annotations

import json

import pytest
from werkzeug.wrappers import Response

from kagura_code.models import ModelSpec
from kagura_code.proxy import ProxyManager


@pytest.fixture
def fake_ollama(httpserver):
    """Fake Ollama daemon: /api/chat returns a non-streaming reply."""

    def handler(_req):
        body = {
            "model": "fake-model:latest",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": "hello from fake"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 1,
            "eval_count": 3,
        }
        return Response(json.dumps(body), status=200, mimetype="application/json")

    httpserver.expect_request("/api/chat", method="POST").respond_with_handler(handler)
    return httpserver


@pytest.fixture
def model_specs() -> list[ModelSpec]:
    return [
        ModelSpec("claude-fake-1m", "Fake [1M]", "fake-model:latest", 1_000_000, 8_192),
    ]


@pytest.fixture
def proxy_manager(model_specs, fake_ollama, tmp_path) -> ProxyManager:
    # ollama_chat/ provider expects the Ollama daemon's native root (no /v1)
    api_base = fake_ollama.url_for("").rstrip("/")
    return ProxyManager(
        models=model_specs,
        api_base=api_base,
        master_key="test-key",
        log_dir=tmp_path / "logs",
    )


@pytest.fixture
def fake_ollama_with_tool_call(httpserver):
    """Fake Ollama daemon that emits a tool_calls response (native format)."""

    def handler(_req):
        body = {
            "model": "fake-model:latest",
            "created_at": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "Read",
                            "arguments": {"path": "/etc/hostname"},
                        }
                    }
                ],
            },
            "done": True,
            "done_reason": "tool_calls",
            "prompt_eval_count": 5,
            "eval_count": 10,
        }
        return Response(json.dumps(body), status=200, mimetype="application/json")

    httpserver.expect_request("/api/chat", method="POST").respond_with_handler(handler)
    return httpserver


@pytest.fixture
def fake_ollama_streaming(httpserver):
    """Fake Ollama daemon that emits an NDJSON stream of native chat chunks."""

    def handler(_req):
        def gen():
            chunks = [
                {"message": {"role": "assistant", "content": "Hello"}, "done": False},
                {"message": {"role": "assistant", "content": " world"}, "done": False},
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                },
            ]
            for c in chunks:
                yield (json.dumps(c) + "\n").encode()

        return Response(gen(), status=200, mimetype="application/x-ndjson")

    httpserver.expect_request("/api/chat", method="POST").respond_with_handler(handler)
    return httpserver
