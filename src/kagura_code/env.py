"""Build the environment dict passed to the claude subprocess."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .models import ModelSpec


def build_claude_env(
    *,
    proxy_port: int,
    model: ModelSpec,
    parent_env: Mapping[str, str],
    lean: bool = False,
    lean_home: Path | None = None,
    middleware_port: int | None = None,
) -> dict[str, str]:
    """Return the env dict to pass to `claude`.

    Inherits parent env then overlays the kagura-code-specific vars.
    See spec §4.5.

    When *lean* is True, additional env vars are set to disable background
    agents, background tasks, managed/policy skills, and marketplace
    auto-install, reducing session-start token overhead by ~50-80K.
    When *lean_home* is provided (a Path), HOME is overridden to that
    directory so that user plugins, skills, and MCP servers are not loaded.
    When *middleware_port* is provided, ANTHROPIC_BASE_URL points at the
    kagura-code middleware instead of the LiteLLM proxy directly.
    """
    effective_port = middleware_port if middleware_port is not None else proxy_port
    overrides = {
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{effective_port}",
        # ANTHROPIC_AUTH_TOKEN is intentionally NOT set. When set to a dummy
        # value, Claude Code interprets the session as "API Usage Billing"
        # mode and hides claude.ai-hosted MCP connectors (Gmail, Calendar,
        # Drive, kagura-memory, ...) from the /mcp picker. Leaving it unset
        # lets Claude Code use the user's existing claude.ai session for the
        # auth token; the kagura-code middleware strips and rewrites the
        # Authorization header to LiteLLM's master_key before forwarding,
        # so the upstream value Claude Code sends doesn't matter.
        "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
        # MAX_CONTEXT_TOKENS + DISABLE_COMPACT together unlock the status-bar
        # display for unknown gateway models. Without DISABLE_COMPACT=1, Claude
        # Code ignores MAX_CONTEXT_TOKENS and falls back to its built-in 200K
        # default. Trade-off: no auto-compaction. Users can /compact manually.
        # The value matches what the Ollama daemon reports for the model, so
        # the status-bar number is honest. Claude Code 2.1.146+ applies a
        # client-side pre-flight check at roughly 62.5% of this value — see
        # docs/verification.md for the effective user-prompt caps per model.
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(model.context_window),
        "DISABLE_COMPACT": "1",
        # Kept as a defensive default in case MAX_CONTEXT_TOKENS semantics
        # change upstream; harmless when DISABLE_COMPACT=1.
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": str(model.context_window),
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(model.max_output_tokens),
        "ANTHROPIC_MODEL": model.alias,
        # DISABLE_PROMPT_CACHING is NOT set here. Claude Code emits a
        # warning banner when it sees that env var, which confuses users.
        # The LiteLLM proxy already strips Anthropic-only cache_control
        # blocks via drop_params: true, so cache markers are silently
        # ignored without us having to tell Claude Code to stop adding them.
        #
        # CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS is intentionally NOT set.
        # Setting it disables Claude Code's claude.ai-hosted MCP "connector"
        # listings (Gmail, Calendar, Drive, kagura-memory, …) which users
        # expect to see in /mcp even when the API is routed to Ollama. The
        # connectors authenticate against claude.ai (not via ANTHROPIC_BASE_URL),
        # so they work independently of which API backend handles /v1/messages.
    }
    if lean:
        overrides.update(
            {
                "CLAUDE_CODE_DISABLE_AGENT_VIEW": "1",
                "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
                "CLAUDE_CODE_DISABLE_POLICY_SKILLS": "1",
                "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL": "1",
            }
        )
    if lean_home is not None:
        overrides["HOME"] = str(lean_home)
    return {**parent_env, **overrides}
