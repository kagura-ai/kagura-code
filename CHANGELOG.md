# Changelog

All notable changes to this project will be documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/).

## v0.1.0a5 — 2026-05-23

**Router timeout 5s → 15s; document auth-mode and status-bar trade-offs
in README.**

Symptom (regression from ollama-code-era 5s budget): on the first turn
of a session, `gemma4:31b-cloud` cold-start sometimes exceeds 5s,
producing `router: HTTP error (ReadTimeout('')); falling back to full
tool list`. The session continues fine (FALLBACK_ALL forwards the full
catalog for that one turn), but the warning is noisy.

Bumped `ToolRouter.timeout_s` default 5.0 → 15.0, mirrored in
`MiddlewareManager.router_timeout_s` and `KAGURA_CODE_ROUTER_TIMEOUT`
env-var fallback in `middleware.runner`. Override via
`KAGURA_CODE_ROUTER_TIMEOUT=<seconds>` in the launching shell for
slower paths.

README adds a "Known trade-offs" section documenting:
- Auth mode: `/model` picker (API billing) vs. claude.ai MCP
  connectors (claude.ai session). Mutually exclusive; kagura-code
  picks the latter by default.
- Status bar `ctx` doesn't refresh on mid-session `/model` switch.
  Relaunch with `--model <alias>` for honest display.
- Router cold-start guidance and how to tune the timeout.

## v0.1.0a4 — 2026-05-23

**`--list-models`: add `Recommended use` column; show Context/Max out
in human units with %.**

The previous table had a verbose `Ollama model` column (e.g.
`deepseek-v4-pro:cloud`) but no hint about which model to pick for
which task. The new layout drops the redundant column and replaces
the absolute token counts with human units plus the output/context
ratio:

```
│ Alias                            │ Display name            │ Context │   Max out │ Recommended use                │
│ claude-deepseek-v4-pro (default) │ DeepSeek V4 Pro [1M]    │    1.0M │  64K (6%) │ Long-context agentic, analysis │
│ claude-qwen3-coder               │ Qwen3 Coder 480B [256K] │    256K │ 64K (25%) │ Code generation, long writes   │
│ claude-kimi-k2                   │ Kimi K2.6 [256K]        │    256K │ 64K (25%) │ General agentic, tool-heavy    │
│ claude-gemma4-31b                │ Gemma 4 31B [256K]      │    256K │   8K (3%) │ Quick QA, lightweight tasks    │
│ claude-qwen35-summ               │ Qwen3.5 397B            │    256K │   8K (3%) │ Context compression (internal) │
```

Added `recommended_use: str = ""` field to `ModelSpec` (empty-string
default preserves backward compat). User configs can override the
recommendation per-alias.

The shipped defaults categorize models by output ratio:

- 5-10% → Agentic / Long-context (DeepSeek)
- 20-25% → Code & Long-form (Qwen3 Coder, Kimi K2)
- 3-5% → Quick / Lightweight + Summarizer (Gemma 4, Qwen3.5 summ)

## v0.1.0a3 — 2026-05-23

**Normalize `max_output_tokens` across tier-1 models.**

The shipped defaults had DeepSeek V4 Pro (1M context) capped at 32K
output while Qwen3 Coder (256K context) had 65K — a clear asymmetry
inherited from incremental ollama-code config edits. The 1M context
of DeepSeek was wasted by the 32K output ceiling, and users hit
truncation on long writing/analysis tasks.

Tier-1 (large reasoning/code) models now share `max_output_tokens = 65_536`:
- `claude-deepseek-v4-pro`: 32K → **65K**
- `claude-qwen3-coder`: 65K (unchanged)
- `claude-kimi-k2`: 32K → **65K**

Tier-2 (small / summarizer) unchanged:
- `claude-gemma4-31b`: 8K
- `claude-qwen35-summ`: 8K

This only changes what `CLAUDE_CODE_MAX_OUTPUT_TOKENS` is set to for
the launched claude subprocess — the actual output ceiling is still
bounded by the model's native cap; raising the request limit just
means Claude Code stops asking for an artificially low ceiling.

## v0.1.0a2 — 2026-05-23

**Feature-complete alpha.** Phase 2 of the migration: all modules
ported from `ollama-code v0.3.0a7` with refactor improvements.

Module layout (24 source files, 182 tests):

- `models.py`, `signals.py`, `redact.py`, `logging.py` — primitives
- `config.py`, `litellm_config.py`, `_vendor/` — config layer
  (env var: `KAGURA_CODE_CONFIG`; user path: `~/.config/kagura-code/`)
- `env.py`, `health.py`, `lean.py` — env builder + process helpers
- `log_watcher.py` — LiteLLM proxy log tailer (quota, unknown-model)
- `proxy.py` — LiteLLM subprocess lifecycle
- `tool_catalog.py`, `tool_router.py` — on-demand tool filtering
- `compression.py` — background context compression with **single retry**
  on transient HTTP errors (5s backoff, then pass-through fallback)
- `session_state.py` — per-session in-memory state
- `middleware/` subpackage — was `on_demand_*` flat modules:
  - `middleware/app.py` (FastAPI app + handlers)
  - `middleware/proc.py` (subprocess manager — `MiddlewareManager`)
  - `middleware/runner.py` (`python -m kagura_code.middleware.runner`)
- `cli.py` — full typer launcher, `--no-on-demand` flag retired
  (middleware is unconditional)
- `doctor.py` — `kagura-code --doctor` diagnostics

Env vars (rename from `OLLAMA_CODE_ONDEMAND_*`):
`KAGURA_CODE_PROXY_URL`, `KAGURA_CODE_ROUTER_MODEL`, `KAGURA_CODE_MASTER_KEY`,
`KAGURA_CODE_ROUTER_TIMEOUT`, `KAGURA_CODE_PORT`, `KAGURA_CODE_KNOWN_ALIASES`,
`KAGURA_CODE_DEFAULT_ALIAS`, `KAGURA_CODE_SUMMARIZER_MODEL`,
`KAGURA_CODE_MODEL_INDEX`, `KAGURA_CODE_SUMMARIZER_TIMEOUT`,
`KAGURA_CODE_CONFIG`.

master_key default: `kagura-code-dummy`.

Log subsystem prefixes: `middleware:` (was `on-demand:`), `router:`
(was `on-demand: router`).

ported via subagent-driven development (8 groups A–H, each
implementer + self-review, controller-side review + commit).

## v0.1.0a1 — 2026-05-23

Initial alpha. Repository skeleton only — no functional code yet.

`kagura-code` succeeds `ollama-code` (https://github.com/jfk/ollama-code).
The migration is intentionally a fresh `git init` rather than a history
transplant: the new repository is the canonical home, and the old
`ollama-code` repository remains as the historical record of decisions,
bug fixes, and design iteration through `v0.3.0a7`.

Key prior art carried forward (to be re-implemented module by module):

- On-demand tool filtering middleware (FastAPI between Claude Code and LiteLLM)
- Context compression via background summarizer (qwen3.5:397b)
- Authorization rewrite to LiteLLM master_key (preserves user's claude.ai auth)
- LiteLLM `/v1/models` `*` wildcard strip
- Model-name rewrite for Claude Code's native `/model` picks
- Per-model `daemon_context_max` for honest `num_ctx` headroom
- Honest status-bar display (`CLAUDE_CODE_MAX_CONTEXT_TOKENS` = Ollama daemon-reported window)

Carried forward as design knowledge (saved to kagura-memory):

- Claude Code's host-gating of claude.ai MCP tools when `ANTHROPIC_BASE_URL`
  is non-Anthropic. The picker shows the connectors as "connected" but the
  tool schemas are stripped from `/v1/messages` `tools` array.
- `--no-on-demand` mode is intentionally not ported (the Authorization
  rewrite only happens in the middleware path; without it, LiteLLM rejects
  the user's real auth token).
