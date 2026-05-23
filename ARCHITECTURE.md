# Architecture

This document captures the high-level design of `kagura-code` and the
reasoning behind the major decisions. Implementation lives in `src/kagura_code/`;
this file is the map.

## Goal

Run **Claude Code CLI** against backends that are not the Anthropic API,
without modifying Claude Code itself. The user keeps the CLI's UX,
agentic workflow, slash commands, and skill/plugin ecosystem; we redirect
where the `/v1/messages` requests go.

## Constraints we inherit

1. **Claude Code only speaks the Anthropic Messages API.** It will not
   negotiate, it will not fall back. Whatever we put in front of it must
   accept `/v1/messages` and return Anthropic-shaped responses.
2. **Claude Code reads `ANTHROPIC_BASE_URL` once at startup.** Mid-session
   `/model` switches do not re-export env vars; the status bar shows whatever
   we set at launch. This is a hard limit on per-model display.
3. **Tool catalogs are huge.** The full Claude Code tool stack with skills,
   AskUserQuestion, Bash, etc. runs ~40-50K tokens per turn. We cannot
   afford to send the full catalog on every request to a model with a 256K
   window.
4. **`claude.ai`-hosted MCP connectors are host-gated.** When Claude Code
   talks to a non-Anthropic backend, it strips Gmail/Calendar/Drive/
   kagura-memory tool schemas from the outgoing `tools` array. The picker
   still shows them as "connected" — this is cosmetic. We can't fix it
   from Claude Code's side; we have to inject the schemas ourselves.

## Components

```
Claude Code CLI
   │  Anthropic Messages API
   │  ANTHROPIC_BASE_URL = http://127.0.0.1:<middleware_port>
   ▼
kagura-code middleware (FastAPI)
   │  - Session store (per-x-anthropic-session-id state)
   │  - Tool catalog filter (CORE ∪ router prediction)
   │  - Context compression (background summarizer)
   │  - Model-name rewrite (claude-* → kagura aliases)
   │  - Authorization rewrite (→ LiteLLM master_key)
   │  ANTHROPIC_BASE_URL → http://127.0.0.1:<litellm_port>
   ▼
LiteLLM proxy
   │  - drop_params (cache_control stripped)
   │  - num_ctx injection (ollama_chat provider)
   │  ollama_chat/ → http://localhost:11434
   ▼
Ollama daemon
   │  Cloud-hosted models on demand
   ▼
Ollama Cloud
```

## Key design decisions

### 1. Middleware sits between Claude Code and LiteLLM

We could have written a LiteLLM custom provider, but the middleware
layer is where session-scoped state lives (tool filtering, compression).
LiteLLM is stateless per-request; we need a place to remember "this
session has seen tool X already, don't filter it next turn."

### 2. On-demand tool filtering uses a cloud-side router model

Each `/v1/messages` request asks a small cheap model (qwen3-coder) which
tools from the catalog the user's current turn actually needs. The
filtered request shrinks from ~50K tokens to ~10K. If the main model
calls a tool that wasn't predicted, we record a "miss" and promote that
session to full-load mode for the rest of the turn.

CORE tools (Bash, Read, Edit, Write, Glob, Grep, TodoWrite, Skill,
AskUserQuestion) are always loaded — they're called in nearly every
turn and predicting them is wasted work.

### 3. Compression runs in the background, summary cached per session

When the active context exceeds the threshold (40% of the model's
declared context window), the older half of messages is sent to a
dedicated summarizer model (qwen3.5:397b by default). The summary
replaces those messages on the next turn; the original messages are
discarded from the forwarded request but the model has the summary as a
system-level reference. The summarizer call is fire-and-forget — if it
times out (180s default, tunable), the next request just goes through
uncompressed.

### 4. Status-bar honesty over auto-compaction

Claude Code's status bar reads `CLAUDE_CODE_MAX_CONTEXT_TOKENS` once at
launch. We set it to the **Ollama daemon-reported context window** for
the launched model (not Anthropic's 200K default), so users see the real
capacity. To make this stick, we also set `DISABLE_COMPACT=1` —
otherwise Claude Code ignores `MAX_CONTEXT_TOKENS` for non-Anthropic
gateway models and falls back to 200K. Trade-off: no auto-compaction,
which is fine because we have our own compression layer.

### 5. We do not override `ANTHROPIC_AUTH_TOKEN`

Earlier iterations set a dummy token, which forced Claude Code into "API
Usage Billing" mode and hid `claude.ai`-hosted MCP connectors. We now
leave the auth source alone and rewrite the `Authorization` header
inside the middleware (→ LiteLLM master_key). The user's real auth
token never leaves the middleware boundary.

## What lives where

(Filled in as Phase 2 ports each module.)
