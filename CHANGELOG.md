# Changelog

All notable changes to this project will be documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/).

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
