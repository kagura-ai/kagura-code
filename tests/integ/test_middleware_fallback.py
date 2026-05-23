"""Integration tests for miss tracking and full-load promotion."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpserver import HTTPServer

from kagura_code.middleware import build_app
from kagura_code.session_state import SessionStore
from kagura_code.tool_router import ToolRouter

FIXTURE = Path(__file__).parent.parent / "unit" / "fixtures" / "anthropic_messages_request.json"


def _router_response(tools: list[str]) -> dict:
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": "claude-router",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(tools)},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _anthropic_tool_use_response(tool_name: str) -> dict:
    return {
        "id": "msg_y", "type": "message", "role": "assistant",
        "model": "claude-deepseek-v4-pro",
        "content": [
            {"type": "text", "text": "calling tool"},
            {"type": "tool_use", "id": "tool_1", "name": tool_name, "input": {}},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }


@pytest.mark.asyncio
async def test_miss_promotes_session_to_full_load(httpserver: HTTPServer):
    store = SessionStore()

    httpserver.expect_ordered_request("/v1/chat/completions").respond_with_json(
        _router_response(["mcp__github__create_issue"])
    )

    def main_turn1(req):
        from werkzeug.wrappers import Response
        return Response(
            json.dumps(_anthropic_tool_use_response("mcp__postgres__query")),
            content_type="application/json",
        )
    httpserver.expect_ordered_request("/v1/messages").respond_with_handler(main_turn1)

    received_turn2: list[dict] = []

    def main_turn2(req):
        received_turn2.append(req.get_json())
        from werkzeug.wrappers import Response
        return Response(
            json.dumps({
                "id": "msg_z", "type": "message", "role": "assistant",
                "model": "claude-deepseek-v4-pro",
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }),
            content_type="application/json",
        )
    httpserver.expect_ordered_request("/v1/messages").respond_with_handler(main_turn2)

    app = build_app(
        router=ToolRouter(
            proxy_url=httpserver.url_for(""), router_model="claude-router", master_key="dummy"
        ),
        store=store,
        proxy_url=httpserver.url_for(""),
    )

    body = json.loads(FIXTURE.read_text())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://middleware") as c:
        r1 = await c.post("/v1/messages", json=body, headers={"x-anthropic-session-id": "s"})
        r2 = await c.post("/v1/messages", json=body, headers={"x-anthropic-session-id": "s"})

    assert r1.status_code == 200
    assert r2.status_code == 200

    assert store.get_or_create("s").miss_count == 1
    assert store.get_or_create("s").full_load is True

    assert len(received_turn2) == 1
    assert len(received_turn2[0]["tools"]) == 22
