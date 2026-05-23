# Changelog

All notable changes to this project will be documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/).

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
