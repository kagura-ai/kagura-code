"""Unit tests for tool_router.py."""
from __future__ import annotations

import asyncio

from pytest_httpserver import HTTPServer

from kagura_code.tool_router import ToolRouter


def _ok_response(content: str) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "claude-router",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content},
             "finish_reason": "stop"},
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_predict_returns_router_json_list(httpserver: HTTPServer):
    httpserver.expect_request(
        "/v1/chat/completions", method="POST",
    ).respond_with_json(_ok_response('["Read", "Bash"]'))

    router = ToolRouter(
        proxy_url=httpserver.url_for(""),
        router_model="claude-router",
        master_key="dummy",
        timeout_s=5.0,
    )
    result = asyncio.run(router.predict(
        user_message="refactor src/auth.py",
        catalog_stub="- mcp__github__create_issue: create issue",
    ))
    assert result == ["Read", "Bash"]


def test_predict_strips_markdown_code_fences(httpserver: HTTPServer):
    httpserver.expect_request(
        "/v1/chat/completions", method="POST",
    ).respond_with_json(_ok_response('```json\n["Read"]\n```'))

    router = ToolRouter(
        proxy_url=httpserver.url_for(""),
        router_model="claude-router",
        master_key="dummy",
    )
    result = asyncio.run(router.predict(
        user_message="read the readme",
        catalog_stub="- mcp__github__create_issue: x",
    ))
    assert result == ["Read"]


def test_predict_falls_back_on_http_500(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_data(
        "internal error", status=500,
    )
    router = ToolRouter(
        proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
    )
    result = asyncio.run(router.predict(
        user_message="anything",
        catalog_stub="- mcp__x__y: z",
    ))
    assert result == ToolRouter.FALLBACK_ALL


def test_predict_falls_back_on_non_json_content(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_json(
        _ok_response("Sure, I'll use Read and Bash to do that.")
    )
    router = ToolRouter(
        proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
    )
    result = asyncio.run(router.predict(
        user_message="anything",
        catalog_stub="- mcp__x__y: z",
    ))
    assert result == ToolRouter.FALLBACK_ALL


def test_predict_falls_back_on_dict_response(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_json(
        _ok_response('{"tools": ["Read"]}')
    )
    router = ToolRouter(
        proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
    )
    result = asyncio.run(router.predict(
        user_message="anything",
        catalog_stub="- mcp__x__y: z",
    ))
    assert result == ToolRouter.FALLBACK_ALL


def test_predict_falls_back_on_list_with_nonstrings(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions").respond_with_json(
        _ok_response('["Read", 42]')
    )
    router = ToolRouter(
        proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
    )
    result = asyncio.run(router.predict(
        user_message="anything",
        catalog_stub="- mcp__x__y: z",
    ))
    assert result == ToolRouter.FALLBACK_ALL


def test_predict_empty_stub_returns_empty_list_without_request():
    router = ToolRouter(
        proxy_url="http://127.0.0.1:1", router_model="claude-router", master_key="dummy"
    )
    result = asyncio.run(router.predict(
        user_message="anything",
        catalog_stub="",
    ))
    assert result == []


def test_predict_falls_back_on_timeout(httpserver: HTTPServer):
    import json
    import time as _time

    def slow_handler(_req):
        _time.sleep(2.0)
        from werkzeug.wrappers import Response

        return Response(json.dumps(_ok_response('["Read"]')), content_type="application/json")

    httpserver.expect_request("/v1/chat/completions").respond_with_handler(slow_handler)

    router = ToolRouter(
        proxy_url=httpserver.url_for(""),
        router_model="claude-router",
        master_key="dummy",
        timeout_s=0.3,
    )
    t0 = asyncio.run(_time_predict(router))
    assert t0 < 1.0, f"timeout not enforced; took {t0:.2f}s"


async def _time_predict(router: ToolRouter) -> float:
    import time as _time

    t0 = _time.perf_counter()
    result = await router.predict(user_message="x", catalog_stub="- a: b")
    assert result == ToolRouter.FALLBACK_ALL
    return _time.perf_counter() - t0


def test_predict_sends_authorization_header(httpserver: HTTPServer):
    httpserver.expect_request(
        "/v1/chat/completions",
        method="POST",
        headers={"Authorization": "Bearer expected-key"},
    ).respond_with_json(_ok_response('["Read"]'))

    router = ToolRouter(
        proxy_url=httpserver.url_for(""),
        router_model="claude-router",
        master_key="expected-key",
    )
    result = asyncio.run(router.predict(
        user_message="read a file",
        catalog_stub="- mcp__github__create_issue: x",
    ))
    assert result == ["Read"]
