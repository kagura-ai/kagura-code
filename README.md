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

## Prerequisites

`kagura-code` is a launcher — it spawns three things you must have installed
locally:

| Dependency | Why | How to install |
|---|---|---|
| Python ≥ 3.11 | The launcher itself | system package manager / pyenv / uv |
| `claude` CLI | Claude Code TUI that we route | https://docs.claude.com/code |
| `ollama` daemon | Cloud model gateway | https://ollama.com/download |

Additionally, the Ollama daemon needs:

1. **A signed-in cloud account** — `ollama signin` (once per machine). The
   daemon handles cloud auth transparently for the proxy; no API key needs
   to live in `kagura-code` config.
2. **At least one `:cloud` model pulled** — for example:
   ```bash
   ollama pull deepseek-v4-pro:cloud   # default model
   ollama pull qwen3.5:397b-cloud      # default summarizer
   ```
   See `kagura-code --list-models` after install for the full default set.

Optional but recommended: **`rtk`** (Rust Token Killer) for 60-90% bash-tool
token savings. `kagura-code --doctor` detects it and recommends installing
if missing.

## Quick start

> ⚠️ **PyPI publication is in progress** — see
> [#6](https://github.com/kagura-ai/kagura-code/issues/6) for status.
> Once published you'll be able to `pip install kagura-code` (or
> `uv tool install kagura-code`). For now, install from GitHub:

```bash
# 1. Install (from GitHub until PyPI publication lands)
pip install git+https://github.com/kagura-ai/kagura-code.git@v0.1.0a6
# After PyPI is live, this becomes:
#   pip install kagura-code
#   # or: uv tool install kagura-code

# 2. Verify environment
kagura-code --doctor

# 3. See available models
kagura-code --list-models

# 4. Launch a session (default: claude-deepseek-v4-pro, 1M context)
kagura-code

# Pick a model — positional shorthand or --model both work:
kagura-code claude-kimi-k2
kagura-code --model claude-qwen3-coder
```

If `--doctor` reports a failed check, fix the underlying issue (install the
missing binary, run `ollama serve`, run `ollama signin`, pull a cloud model)
and re-run until all 9 checks pass.

### Shell completion (optional)

Tab-complete subcommands, flags, and configured model aliases:

```bash
kagura-code --install-completion bash   # or: zsh, fish, powershell
# Restart your shell, then:
kagura-code <TAB>                       # lists configured model aliases
kagura-code --<TAB>                     # lists options
```

The model-alias completion reads your effective config (shipped defaults
+ `~/.config/kagura-code/config.toml` overrides), so custom aliases
appear too.

## Configuration

The shipped defaults work out of the box. To override (e.g. add your own
model alias, change the default, pin to a different Ollama daemon URL),
create `~/.config/kagura-code/config.toml`. Only the keys you set override
the shipped defaults; everything else inherits.

Example minimal override (change the default model + add a custom alias):

```toml
[default]
model = "claude-kimi-k2"

[[models]]
alias             = "claude-my-custom"
display_name      = "My Custom Cloud Model"
ollama_model      = "some-model:cloud"
context_window    = 262_144
max_output_tokens = 65_536
recommended_use   = "My experimental setup"
```

Run `kagura-code --list-models` again to confirm the merged set.

## CLI reference

```
kagura-code [OPTIONS] [MODEL_ARG] [-- claude-args...]

Arguments:
  [MODEL_ARG]               Model alias (positional shorthand).
                            Overridden by --model if both are given.

Options:
  -m, --model TEXT          Model alias to use (overrides default).
      --list-models         List available models and exit.
      --doctor              Run setup diagnostics and exit.
      --proxy-only          Start the proxy without launching claude.
      --config PATH         Explicit config.toml path.
      --port INT            Pin proxy to a specific port (default: random).
      --log-level [debug|info|warn|error]
                            Default: warn.
      --lean                Reduced-overhead session (no agents/skills/plugins/MCP, ~50K token savings).
      --router-model TEXT   LiteLLM alias used as middleware router (default: claude-gemma4-31b).
      --summarizer-model TEXT
                            LiteLLM alias used for compression (default: claude-qwen35-summ).
                            Pass "" to disable compression.
      --install-completion [bash|zsh|fish|powershell|pwsh]
                            Install shell completion (auto-detects shell if omitted).
      --show-completion [bash|zsh|fish|powershell|pwsh]
                            Print the completion script without installing.
  -V, --version             Show version and exit.

Arguments after `--` are forwarded to the spawned `claude` process.
```

## Tunable env vars

| Variable | Default | Purpose |
|---|---|---|
| `KAGURA_CODE_CONFIG` | — | Path to user config.toml (overrides search path) |
| `KAGURA_CODE_ROUTER_TIMEOUT` | `15.0` | Per-call seconds budget for the on-demand router model |
| `KAGURA_CODE_SUMMARIZER_TIMEOUT` | `180.0` | Per-call seconds budget for the context summarizer |
| `ANTHROPIC_AUTH_TOKEN` | unset | Set to any value to flip Claude Code into API billing mode (enables `/model` picker; loses claude.ai MCP connectors) |

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
