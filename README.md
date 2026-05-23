# kagura-code

Run **Claude Code CLI** against non-Anthropic LLM backends.

`kagura-code` is a thin launcher + middleware that lets you keep Claude Code's
agentic workflow, tool ecosystem, and UX while routing the underlying API
calls to whichever LLM you choose.

**Status:** alpha. The Ollama Cloud backend is functional and used daily.
Other backends are on the roadmap.

## Supported backends

| Backend | Status |
|---|---|
| Ollama Cloud (1M-context models: DeepSeek V4 Pro, Kimi K2, Qwen3 Coder, …) | ✅ working |
| OpenAI-compatible (Codex, vLLM, Together, …) | 🛠 planned (v0.2) |
| Anthropic API direct | n/a — use Claude Code directly |
| Google Gemini | ❌ not planned (LiteLLM Anthropic→Google bridge is immature) |

## What it does

```
Claude Code CLI
   │  (Anthropic Messages API, ANTHROPIC_BASE_URL = localhost)
   ▼
kagura-code middleware (FastAPI)
   │  - on-demand tool filtering (small router model picks needed tools)
   │  - background context compression (qwen3.5 summarizer)
   │  - model-name rewrite (claude-* → kagura aliases)
   ▼
LiteLLM proxy
   │  - drop_params (Anthropic cache_control → stripped)
   │  - per-request num_ctx (Ollama daemon param)
   ▼
Ollama Cloud (or other backend)
```

The middleware is the interesting part: it intercepts every
`/v1/messages` request, decides which tools the model actually needs for this
turn (full tool catalog runs ~50K tokens), forwards a filtered request to
LiteLLM, and runs a background summarizer to keep the context window from
overflowing.

## Quick start

```bash
pip install kagura-code  # not yet on PyPI
kagura-code              # launches Claude Code against the default model
```

Configuration lives in `~/.config/kagura-code/config.toml` (override the
defaults shipped in the package).

## Why?

Claude Code's CLI ergonomics, plugin/skill ecosystem, and tool design are
exceptional, but you're locked to Anthropic's models and pricing. With
`kagura-code`, you can:

- Use Ollama Cloud's 1M-context DeepSeek V4 Pro for long-form work
- Mix and match: route summarization to a cheap model, agentic loops to a
  capable one
- Stay independent of API pricing changes from a single vendor

## Known trade-offs

### Auth mode: `/model` picker vs. claude.ai MCP connectors

Claude Code behaves differently depending on whether `ANTHROPIC_AUTH_TOKEN`
is set in the subprocess environment. `kagura-code` intentionally leaves it
unset so that Claude Code uses the user's `claude.ai` session, which keeps
the `/mcp` picker populated with claude.ai-hosted connectors (Gmail,
Calendar, Drive, kagura-memory, …).

The cost: in this mode Claude Code does **not** call `/v1/models` for
gateway discovery, so the in-TUI `/model` picker only shows the launch
model plus the built-in Anthropic aliases (`claude-opus-*`,
`claude-sonnet-*`, …). To switch models mid-workflow you have to relaunch:

```bash
kagura-code --model claude-kimi-k2
kagura-code --model claude-qwen3-coder
kagura-code --model claude-deepseek-v4-pro   # default
```

Run `kagura-code --list-models` to see every configured alias with its
context window, max output, and recommended use.

If you'd rather have the in-TUI picker over the connectors, set
`ANTHROPIC_AUTH_TOKEN=kagura-code-dummy` in your shell before launch —
gateway discovery turns back on but the `/mcp` picker loses claude.ai
connectors (local stdio MCP servers in `~/.claude.json` continue to work).

### Status bar `ctx` doesn't update on `/model` switch

`CLAUDE_CODE_MAX_CONTEXT_TOKENS` is read once at subprocess start. If you
launch with the 1M-context DeepSeek and then switch to a 256K model via
`/model`, the status bar will keep showing 1.0M. Relaunch with the
target model via `--model` to get an honest display.

### Router cold-start

The first turn of each session calls the small router model
(`claude-gemma4-31b` by default). Cold-start on Ollama Cloud can take
~10s; we default the per-call timeout to 15s. On timeout the middleware
falls back to forwarding the full tool catalog for that one turn — the
session continues, just with a larger first request. Override the budget
via `kagura-code --router-model <alias>` or
`KAGURA_CODE_ROUTER_TIMEOUT=30` in the launching shell.

## License

Apache License 2.0. See `LICENSE`.

## Related projects

- [`kagura-ai`](https://github.com/kagura-ai/kagura) — Universal AI Memory Platform
- [`kagura-memory`](https://memory.kagura-ai.com) — MCP-native context management

`kagura-code` is part of the kagura-ai ecosystem.
