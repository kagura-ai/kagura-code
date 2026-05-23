"""Unit tests for tool_catalog.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kagura_code.tool_catalog import CORE_TOOLS, ToolCatalog

FIXTURE = Path(__file__).parent / "fixtures" / "anthropic_messages_request.json"


@pytest.fixture
def request_body() -> dict:
    return json.loads(FIXTURE.read_text())


def test_from_request_parses_all_tools(request_body):
    cat = ToolCatalog.from_request(request_body)
    assert len(cat.all_names()) == 22
    assert "Read" in cat.all_names()
    assert "mcp__github__create_issue" in cat.all_names()


def test_core_tools_constant_excludes_mcp():
    assert "Read" in CORE_TOOLS
    assert "Edit" in CORE_TOOLS
    assert "Write" in CORE_TOOLS
    assert "Bash" in CORE_TOOLS
    assert "Glob" in CORE_TOOLS
    assert "Grep" in CORE_TOOLS
    assert "Task" in CORE_TOOLS
    assert "TodoWrite" in CORE_TOOLS
    assert "WebFetch" in CORE_TOOLS
    assert "WebSearch" in CORE_TOOLS
    # mcp tools are NOT core
    assert "mcp__github__create_issue" not in CORE_TOOLS


def test_from_request_with_missing_tools_field():
    cat = ToolCatalog.from_request({"messages": [], "model": "x"})
    assert cat.all_names() == []


def test_stub_text_lists_only_non_core_tools(request_body):
    cat = ToolCatalog.from_request(request_body)
    stub = cat.stub_text()
    # Non-core MCP tools must appear
    assert "mcp__github__create_issue" in stub
    assert "mcp__postgres__query" in stub
    # Core tools are sent to the router regardless, so they don't need
    # to be in the stub (saves tokens).
    assert "Read:" not in stub
    assert "Bash:" not in stub
    # The stub should include one-line descriptions
    assert "create a github issue" in stub.lower() or "Create a GitHub issue" in stub


def test_stub_text_under_token_budget(request_body):
    cat = ToolCatalog.from_request(request_body)
    stub = cat.stub_text()
    # Crude token estimate: 1 token ≈ 4 chars; budget 700 tokens
    assert len(stub) < 700 * 4, f"stub too long: {len(stub)} chars"


def test_stub_text_with_empty_non_core_returns_empty():
    cat = ToolCatalog(schemas={
        "Read": {"name": "Read", "description": "Read", "input_schema": {}},
        "Bash": {"name": "Bash", "description": "Bash", "input_schema": {}},
    })
    assert cat.stub_text() == ""


def test_filter_returns_only_named_schemas(request_body):
    cat = ToolCatalog.from_request(request_body)
    result = cat.filter(["Read", "mcp__github__create_issue"])
    assert len(result) == 2
    names = {t["name"] for t in result}
    assert names == {"Read", "mcp__github__create_issue"}


def test_filter_silently_drops_unknown_names(request_body):
    cat = ToolCatalog.from_request(request_body)
    result = cat.filter(["Read", "DoesNotExist"])
    assert len(result) == 1
    assert result[0]["name"] == "Read"


def test_filter_with_core_includes_all_core_plus_named(request_body):
    cat = ToolCatalog.from_request(request_body)
    result = cat.filter_with_core(["mcp__github__create_issue"])
    names = {t["name"] for t in result}
    # All core tools present in the fixture should appear
    assert CORE_TOOLS <= names
    # Plus the requested non-core tool
    assert "mcp__github__create_issue" in names
    # Other non-core tools must NOT appear
    assert "mcp__postgres__query" not in names


def test_all_returns_every_schema(request_body):
    cat = ToolCatalog.from_request(request_body)
    assert len(cat.all()) == 22
