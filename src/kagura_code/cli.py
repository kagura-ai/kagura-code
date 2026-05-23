"""Typer CLI for kagura-code."""
from __future__ import annotations

import os
import signal as _signal
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import Config, ConfigError, load_config
from .doctor import run_diagnostics
from .env import build_claude_env
from .lean import cleanup_lean_home, make_lean_home
from .log_watcher import ProxyLogWatcher, WatcherEvent
from .logging import setup_logging
from .models import UnknownModelError, resolve_model
from .proxy import ProxyManager
from .signals import ShutdownCoordinator, install_handlers

app = typer.Typer(
    name="kagura-code",
    help="Run Claude Code CLI against non-Anthropic LLM backends (Ollama Cloud + more).",
    add_completion=False,
    no_args_is_help=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"kagura-code {__version__}")
        raise typer.Exit()


def _cache_dir() -> Path:
    return Path(os.environ.get("HOME", "~")).expanduser() / ".cache" / "kagura-code"


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def main(
    ctx: typer.Context,
    model: str | None = typer.Option(None, "--model", "-m", help="Model alias to use."),
    list_models: bool = typer.Option(
        False, "--list-models", help="List available models and exit."
    ),
    doctor: bool = typer.Option(False, "--doctor", help="Run setup diagnostics and exit."),
    port: int | None = typer.Option(
        None, "--port", help="Pin proxy to a specific port (default: random)."
    ),
    proxy_only: bool = typer.Option(
        False, "--proxy-only", help="Start the proxy without launching claude."
    ),
    config: Path | None = typer.Option(None, "--config", help="Explicit config.toml path."),  # noqa: B008
    log_level: str = typer.Option("warn", "--log-level", help="debug|info|warn|error"),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True
    ),
    lean: bool = typer.Option(
        False,
        "--lean",
        help=(
            "Reduced-overhead session: disable agents/skills/plugins/MCP for ~50K token"
            " savings. Trade-off: no Task subagent, no user plugins/skills, no MCP servers"
            " in this session."
        ),
    ),
    router_model: str = typer.Option(
        "claude-gemma4-31b",
        "--router-model",
        help="LiteLLM alias to use as the middleware router (default: claude-gemma4-31b).",
    ),
    summarizer_model: str = typer.Option(
        "claude-qwen35-summ",
        "--summarizer-model",
        help=(
            "LiteLLM alias used for context compression. Empty string disables"
            " compression while keeping the rest of the middleware running."
            " Default: claude-qwen35-summ (qwen3.5:397b-cloud)."
        ),
    ),
) -> None:
    # Config load
    try:
        cfg = load_config(explicit_path=config)
    except ConfigError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e

    if list_models:
        _print_models(cfg)
        raise typer.Exit(0)

    if doctor:
        ok = run_diagnostics(cfg, router_model=router_model)
        raise typer.Exit(0 if ok else 1)

    # Resolve model
    selected_alias = model or cfg.default_model
    try:
        spec = resolve_model(selected_alias, cfg.models)
    except UnknownModelError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e

    # Logging
    log_dir = _cache_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = setup_logging(level=log_level, log_file=log_dir / f"launcher-{os.getpid()}.log")

    # Proxy (no api_key — local daemon handles cloud auth via ollama signin).
    # No wildcard_fallback_alias: rewriting unknown aliases happens in the
    # middleware so LiteLLM's /v1/models stays a clean enumeration of
    # configured aliases — adding "*" to LiteLLM pollutes that list and
    # confuses Claude Code's /model picker.
    pm = ProxyManager(
        models=cfg.models,
        api_base=cfg.ollama_cloud.api_base,
        master_key="kagura-code-dummy",
        log_dir=log_dir,
    )

    coord = ShutdownCoordinator()
    install_handlers(coord)

    log.info("starting proxy")
    try:
        handle = pm.start(port=port)
    except Exception as e:
        typer.echo(f"error: proxy did not start: {e}", err=True)
        raise typer.Exit(3) from e

    log.info("proxy ready on :%d", handle.port)

    # Validate the summarizer alias exists in the configured model list.
    # A user config that drops claude-qwen35-summ while keeping the default
    # flag would otherwise produce silent background 404s on every
    # threshold-crossing request.
    effective_summarizer = summarizer_model or None
    if effective_summarizer is not None and effective_summarizer not in {
        m.alias for m in cfg.models
    }:
        typer.echo(
            f"warning: --summarizer-model {effective_summarizer!r} not in"
            " configured models; disabling compression for this session."
            " Add the alias to your config or pass --summarizer-model ''"
            " to silence this warning.",
            err=True,
        )
        effective_summarizer = None

    from .middleware import MiddlewareManager
    mw_mgr = MiddlewareManager(
        proxy_url=f"http://127.0.0.1:{handle.port}",
        router_model=router_model,
        master_key="kagura-code-dummy",
        known_aliases=frozenset(m.alias for m in cfg.models),
        default_alias=cfg.default_model,
        summarizer_model=effective_summarizer,
        model_index={m.alias: m.context_window for m in cfg.models},
    )
    try:
        mw_handle = mw_mgr.start()
        log.info("middleware ready on :%d", mw_handle.port)
    except Exception as e:
        typer.echo(f"error: middleware did not start: {e}", err=True)
        pm.stop(handle)
        raise typer.Exit(3) from e

    if proxy_only:
        typer.echo(f"proxy running on http://127.0.0.1:{handle.port}")
        typer.echo(
            f"middleware running on http://127.0.0.1:{mw_handle.port}"
        )
        typer.echo("press Ctrl+C to stop")
        try:
            handle.proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            mw_mgr.stop(mw_handle)
            pm.stop(handle)
        raise typer.Exit(0)

    # Lean mode: create an ephemeral isolated HOME
    lean_home_dir = None
    if lean:
        lean_home_dir = make_lean_home(_cache_dir())
        log.info("lean mode: ephemeral HOME at %s", lean_home_dir)

    # Spawn claude
    env = build_claude_env(
        proxy_port=handle.port,
        model=spec,
        parent_env=os.environ,
        lean=lean,
        lean_home=lean_home_dir,
        middleware_port=mw_handle.port,
    )
    extra_args = ctx.args  # everything after --
    log.info("launching claude with model=%s", spec.alias)
    try:
        claude_proc = subprocess.Popen(  # noqa: S603
            ["claude", *extra_args], env=env,  # noqa: S607
        )
    except FileNotFoundError as e:
        typer.echo("error: 'claude' command not found. Install Claude Code first.", err=True)
        mw_mgr.stop(mw_handle)
        pm.stop(handle)
        if lean_home_dir is not None:
            cleanup_lean_home(lean_home_dir)
        raise typer.Exit(2) from e

    # Watch the proxy log for quota / unknown-model patterns. We collect
    # the events and surface them after claude exits, since stderr written
    # during the TUI session is overwritten by Claude Code's redraws.
    quota_hit = False
    unknown_models: list[str] = []

    def _on_watcher_event(ev: WatcherEvent) -> None:
        nonlocal quota_hit
        if ev.kind == "quota":
            quota_hit = True
            log.warning("Ollama Cloud session usage limit reached; requesting shutdown")
            coord.request_shutdown(_signal.SIGTERM)
        elif ev.kind == "unknown_model":
            unknown_models.append(ev.detail)
            log.warning("Claude Code requested unknown model alias: %s", ev.detail)

    watcher = ProxyLogWatcher(log_path=handle.log_path, on_event=_on_watcher_event)
    watcher.start()

    # Wait, forwarding signals once
    rc = 0
    try:
        while True:
            try:
                rc = claude_proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if coord.shutdown_requested:
                    log.info("forwarding %s to claude", coord.first_signal)
                    claude_proc.send_signal(coord.first_signal or 15)
                    try:
                        rc = claude_proc.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        claude_proc.kill()
                        rc = claude_proc.wait()
                    break
    finally:
        mw_mgr.stop(mw_handle)
        log.info("middleware stopped")
        log.info("claude exited with %d; stopping proxy", rc)
        watcher.stop()
        pm.stop(handle)
        if lean_home_dir is not None:
            cleanup_lean_home(lean_home_dir)
            log.info("lean mode: removed ephemeral HOME %s", lean_home_dir)

    if quota_hit:
        typer.echo(
            "\nkagura-code: Ollama Cloud session usage limit reached.\n"
            "  • Quota resets later in the day (see https://ollama.com/settings).\n"
            "  • Upgrade or add extra usage: https://ollama.com/upgrade",
            err=True,
        )
    if unknown_models:
        aliases = ", ".join(m.alias for m in cfg.models)
        typer.echo(
            "\nkagura-code: Claude Code asked for unsupported model(s): "
            f"{', '.join(unknown_models)}.\n"
            f"  Only these aliases are routed by kagura-code: {aliases}.\n"
            "  Anthropic-native models (claude-opus-*, claude-sonnet-*, etc.)\n"
            "  cannot be reached — all traffic goes through the local proxy.\n"
            "  Pick a configured alias via Claude Code's /model command.",
            err=True,
        )

    raise typer.Exit(rc)


def _print_models(cfg: Config) -> None:
    console = Console(width=130)
    t = Table(title="Available models")
    t.add_column("Alias")
    t.add_column("Display name")
    t.add_column("Context", justify="right")
    t.add_column("Max out", justify="right")
    t.add_column("Recommended use")
    for m in cfg.models:
        marker = " (default)" if m.alias == cfg.default_model else ""
        ctx_str = (
            f"{m.context_window / 1_048_576:.1f}M"
            if m.context_window >= 1_048_576
            else f"{m.context_window // 1024}K"
        )
        pct = round(m.max_output_tokens / m.context_window * 100)
        max_out_str = f"{m.max_output_tokens // 1024}K ({pct}%)"
        t.add_row(
            m.alias + marker,
            m.display_name,
            ctx_str,
            max_out_str,
            m.recommended_use,
        )
    console.print(t)
