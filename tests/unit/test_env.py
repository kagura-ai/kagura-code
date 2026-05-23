from __future__ import annotations

from kagura_code.env import build_claude_env
from kagura_code.models import ModelSpec


def spec(ctx: int = 1_000_000) -> ModelSpec:
    return ModelSpec(
        alias="claude-x-1m",
        display_name="X",
        ollama_model="x:cloud",
        context_window=ctx,
        max_output_tokens=8192,
    )


def test_build_env_sets_anthropic_base_url():
    env = build_claude_env(proxy_port=12345, model=spec(), parent_env={})
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:12345"


def test_build_env_sets_auto_compact_window_to_context_window():
    env = build_claude_env(proxy_port=1, model=spec(ctx=1_000_000), parent_env={})
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "1000000"


def test_build_env_sets_max_context_tokens_to_context_window():
    """MAX_CONTEXT_TOKENS = context_window (matches the Ollama daemon's
    reported size for honest status-bar display). The Claude Code 2.1.146+
    pre-flight check fires at ~62.5% of this value — see docs/verification.md.
    """
    env = build_claude_env(proxy_port=1, model=spec(ctx=1_000_000), parent_env={})
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "1000000"


def test_build_env_disables_compact():
    """DISABLE_COMPACT=1 is required for CLAUDE_CODE_MAX_CONTEXT_TOKENS to
    take effect on custom gateway models.
    """
    env = build_claude_env(proxy_port=1, model=spec(), parent_env={})
    assert env["DISABLE_COMPACT"] == "1"


def test_build_env_does_not_set_anthropic_auth_token():
    """The on-demand middleware rewrites Authorization to LiteLLM's master_key
    before forwarding, so Claude Code is free to use whatever auth source it
    prefers (claude.ai session, ANTHROPIC_API_KEY, etc.). Setting a dummy
    AUTH_TOKEN forced Claude Code into 'API Usage Billing' mode and hid the
    claude.ai-hosted MCP connectors — see env.py for the full reasoning.
    """
    env = build_claude_env(proxy_port=1, model=spec(), parent_env={})
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_build_env_does_not_clobber_parent_auth_token():
    """If the user's environment already has ANTHROPIC_AUTH_TOKEN set (e.g.,
    from a Claude Code login flow), it must pass through to the subprocess.
    """
    parent = {"ANTHROPIC_AUTH_TOKEN": "user-real-token"}
    env = build_claude_env(proxy_port=1, model=spec(), parent_env=parent)
    assert env.get("ANTHROPIC_AUTH_TOKEN") == "user-real-token"


def test_build_env_enables_gateway_discovery():
    env = build_claude_env(proxy_port=1, model=spec(), parent_env={})
    assert env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"


def test_build_env_does_not_set_disable_prompt_caching():
    """We don't set DISABLE_PROMPT_CACHING because Claude Code emits a
    confusing warning banner when it sees that var. The proxy strips
    cache_control blocks via drop_params instead.
    """
    env = build_claude_env(proxy_port=1, model=spec(), parent_env={})
    assert "DISABLE_PROMPT_CACHING" not in env


def test_build_env_sets_anthropic_model_to_alias():
    env = build_claude_env(proxy_port=1, model=spec(), parent_env={})
    assert env["ANTHROPIC_MODEL"] == "claude-x-1m"


def test_build_env_merges_with_parent_env():
    parent = {"PATH": "/usr/bin", "HOME": "/home/u", "SHELL": "/bin/bash"}
    env = build_claude_env(proxy_port=1, model=spec(), parent_env=parent)
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/u"
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:1"


def test_build_env_overrides_parent_anthropic_vars():
    parent = {"ANTHROPIC_BASE_URL": "https://api.anthropic.com", "ANTHROPIC_MODEL": "opus"}
    env = build_claude_env(proxy_port=1, model=spec(), parent_env=parent)
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:1"
    assert env["ANTHROPIC_MODEL"] == "claude-x-1m"


def test_build_env_lean_sets_disable_vars():
    env = build_claude_env(proxy_port=1, model=spec(), parent_env={}, lean=True)
    assert env["CLAUDE_CODE_DISABLE_AGENT_VIEW"] == "1"
    assert env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    assert env["CLAUDE_CODE_DISABLE_POLICY_SKILLS"] == "1"
    assert env["CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL"] == "1"


def test_build_env_lean_off_does_not_set_disable_vars():
    env = build_claude_env(proxy_port=1, model=spec(), parent_env={}, lean=False)
    assert "CLAUDE_CODE_DISABLE_AGENT_VIEW" not in env
    assert "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS" not in env


def test_build_env_lean_sets_home_when_provided(tmp_path):
    env = build_claude_env(
        proxy_port=1,
        model=spec(),
        parent_env={"HOME": "/orig"},
        lean=True,
        lean_home=tmp_path / "fake-home",
    )
    assert env["HOME"] == str(tmp_path / "fake-home")


def test_build_claude_env_uses_middleware_port_when_provided():
    env = build_claude_env(
        proxy_port=8000,
        model=spec(),
        parent_env={"PATH": "/usr/bin"},
        middleware_port=9000,
    )
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9000"


def test_build_claude_env_falls_back_to_proxy_port_when_middleware_none():
    env = build_claude_env(
        proxy_port=8000,
        model=spec(),
        parent_env={"PATH": "/usr/bin"},
    )
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8000"
