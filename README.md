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

## License

Apache License 2.0. See `LICENSE`.

## Related projects

- [`kagura-ai`](https://github.com/kagura-ai/kagura) — Universal AI Memory Platform
- [`kagura-memory`](https://memory.kagura-ai.com) — MCP-native context management

`kagura-code` is part of the kagura-ai ecosystem.
