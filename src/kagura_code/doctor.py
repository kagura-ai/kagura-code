"""Diagnostics for `kagura-code --doctor`.

Read-only. Does not modify config, install dependencies, or sign in.
"""
from __future__ import annotations

import shutil
import sys
from importlib.metadata import PackageNotFoundError, version

import httpx
from rich.console import Console

from .config import Config

_COMPROMISED_LITELLM = {"1.82.7", "1.82.8"}
_MIN_PYTHON = (3, 11)
_OLLAMA_API_BASE = "http://localhost:11434"


def _litellm_version() -> str:
    try:
        return version("litellm")
    except PackageNotFoundError:
        return "not installed"


def check_python_version() -> tuple[bool, str]:
    v = sys.version_info
    ok = v[:2] >= _MIN_PYTHON
    return ok, f"{v[0]}.{v[1]}.{v[2]}"


def check_litellm_version() -> tuple[bool, str]:
    v = _litellm_version()
    if v == "not installed":
        return False, "litellm not installed"
    if v in _COMPROMISED_LITELLM:
        return False, f"{v} is compromised (credential-stealing malware). Upgrade to >=1.83.0"
    return True, v


def check_claude_installed() -> tuple[bool, str]:
    path = shutil.which("claude")
    if not path:
        return False, "'claude' not in PATH. Install Claude Code: https://docs.claude.com/code"
    return True, path


def check_ollama_cli_installed() -> tuple[bool, str]:
    path = shutil.which("ollama")
    if not path:
        return False, "'ollama' not in PATH. Install from https://ollama.com/download"
    return True, path


def check_ollama_daemon_reachable() -> tuple[bool, str]:
    try:
        r = httpx.get(f"{_OLLAMA_API_BASE}/api/version", timeout=3.0)
        r.raise_for_status()
        data = r.json()
        v = data.get("version", "?")
        return True, f"daemon v{v} at {_OLLAMA_API_BASE}"
    except httpx.RequestError as e:
        msg = (
            f"daemon unreachable at {_OLLAMA_API_BASE}: {e}. "
            "Run `ollama serve` (or start the desktop app)."
        )
        return False, msg
    except Exception as e:
        return False, f"daemon error at {_OLLAMA_API_BASE}: {e}"


def check_cloud_model_pulled() -> tuple[bool, str]:
    """At least one :cloud model is pulled — implies `ollama signin` was done."""
    try:
        r = httpx.get(f"{_OLLAMA_API_BASE}/api/tags", timeout=5.0)
        r.raise_for_status()
        models = r.json().get("models", [])
    except Exception as e:
        return False, f"cannot list models: {e}"
    cloud = [
        m["name"] for m in models
        if m.get("name", "").endswith(":cloud") or m.get("name", "").endswith("-cloud")
    ]
    if not cloud:
        return False, (
            "no :cloud models pulled. Run `ollama signin` then "
            "`ollama pull qwen3-coder:480b-cloud` (or another cloud model)."
        )
    return True, f"found {len(cloud)} cloud model(s); e.g. {cloud[0]}"


def check_rtk_integration(cfg: Config) -> tuple[bool, str]:
    """Report whether RTK (Rust Token Killer) is available for bash-tool savings."""
    enabled = cfg.rtk.enabled
    if enabled == "false":
        return True, "disabled by config"
    path = shutil.which("rtk")
    if path:
        return True, (
            f"{path} — bash commands will benefit if your "
            "~/.claude/settings.json has the rtk hook"
        )
    if enabled == "true":
        return False, (
            "rtk required by config but not on PATH. "
            "Install from https://github.com/reachingforthejack/rtk "
            "or set [rtk].enabled = false"
        )
    # enabled == "auto" and not found: optional
    return True, "not installed (optional). Install rtk for 60-90% bash-tool token savings."


def check_router_alias_configured(cfg: Config, router_model: str) -> tuple[bool, str]:
    aliases = {m.alias for m in cfg.models}
    if router_model in aliases:
        return True, f"router alias '{router_model}' is configured"
    return False, (
        f"router alias '{router_model}' is not in config; --list-models shows the valid set"
    )


def check_proxy_boot_smoke(cfg: Config) -> tuple[bool, str]:
    """Start LiteLLM proxy, wait for ready, stop it. Quick sanity check."""
    import os
    from pathlib import Path

    from .proxy import ProxyManager

    log_dir = Path(os.environ.get("HOME", "~")).expanduser() / ".cache" / "kagura-code" / "logs"
    pm = ProxyManager(
        models=cfg.models,
        api_base=cfg.ollama_cloud.api_base,
        master_key="kagura-code-dummy",
        log_dir=log_dir,
    )
    try:
        h = pm.start()
        pm.stop(h)
        return True, f"started on :{h.port}, stopped cleanly"
    except Exception as e:
        return False, f"proxy boot failed: {e}"


def run_diagnostics(
    cfg: Config,
    *,
    router_model: str = "claude-gemma4-31b",
) -> bool:
    """Run all checks. Return True iff every check passes."""
    console = Console()
    checks = [
        ("Python version >= 3.11", check_python_version),
        ("litellm version safe", check_litellm_version),
        ("claude CLI found", check_claude_installed),
        ("ollama CLI found", check_ollama_cli_installed),
        ("ollama daemon reachable", check_ollama_daemon_reachable),
        ("cloud model pulled (signin OK)", check_cloud_model_pulled),
        ("proxy boot smoke test", lambda: check_proxy_boot_smoke(cfg)),
        ("rtk token-saving proxy", lambda: check_rtk_integration(cfg)),
        (
            f"middleware router alias ({router_model})",
            lambda: check_router_alias_configured(cfg, router_model),
        ),
    ]
    all_ok = True
    for i, (label, fn) in enumerate(checks, 1):
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"raised {type(e).__name__}: {e}"
        marker = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f"[{i}/{len(checks)}] {label:<32} {marker} {detail}")
        all_ok = all_ok and ok
    if all_ok:
        console.print("\n[green]All checks passed.[/green] Run 'kagura-code' to start a session.")
    else:
        console.print("\n[red]Some checks failed.[/red] Address the items above and re-run.")
    return all_ok
