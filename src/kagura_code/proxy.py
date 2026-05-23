"""LiteLLM proxy subprocess lifecycle.

The proxy runs locally on a dynamically allocated port. Auth flows
through the local Ollama daemon (via `ollama signin`), so the proxy
itself does not need to manage cloud credentials.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .health import wait_for_ready
from .litellm_config import render_litellm_config
from .models import ModelSpec


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class ProxyHandle:
    port: int
    pid: int
    proc: subprocess.Popen[bytes]
    config_path: Path
    log_path: Path


class ProxyManager:
    """Start/stop a LiteLLM proxy subprocess scoped to a single session.

    The subprocess is placed in its own process group via os.setsid so
    that SIGTERM / SIGKILL can be applied to the entire group, guaranteeing
    reap of any litellm worker processes.
    """

    READY_TIMEOUT_S = 30.0
    STOP_GRACE_S = 5.0

    def __init__(
        self,
        models: list[ModelSpec],
        *,
        api_base: str,
        master_key: str,
        log_dir: Path,
        extra_env: dict[str, str] | None = None,
        wildcard_fallback_alias: str | None = None,
    ) -> None:
        self.models = models
        self.api_base = api_base
        self.master_key = master_key
        self.log_dir = log_dir
        self.extra_env: dict[str, str] = extra_env or {}
        self.wildcard_fallback_alias = wildcard_fallback_alias

    def start(
        self, *, port: int | None = None, extra_env: dict[str, str] | None = None
    ) -> ProxyHandle:
        port = port or find_free_port()
        config_path = self._write_config()
        self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        log_path = self.log_dir / f"proxy-{os.getpid()}.log"

        # Defaults applied to the litellm subprocess env. Callers may override
        # via __init__ extra_env or start() extra_env.
        # - LITELLM_USE_CHAT_COMPLETIONS_URL_FOR_ANTHROPIC_MESSAGES=true:
        #   force the legacy /v1/chat/completions path upstream instead of
        #   LiteLLM 1.85's new /v1/responses routing. The latter does not
        #   forward extra_body params (including the per-model num_ctx that
        #   unlocks the daemon's full context window), so without this the
        #   1M context claim fails through the proxy.
        defaults = {
            "LITELLM_USE_CHAT_COMPLETIONS_URL_FOR_ANTHROPIC_MESSAGES": "true",
        }
        env = {**os.environ, **defaults, **self.extra_env, **(extra_env or {})}

        log_file = log_path.open("ab")
        proc = subprocess.Popen(  # noqa: S603
            ["litellm", "--config", str(config_path),  # noqa: S607
             "--port", str(port), "--host", "127.0.0.1"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=env,
        )

        try:
            wait_for_ready(port, timeout_s=self.READY_TIMEOUT_S)
        except Exception:
            self._terminate(proc)
            raise

        return ProxyHandle(
            port=port,
            pid=proc.pid,
            proc=proc,
            config_path=config_path,
            log_path=log_path,
        )

    def stop(self, handle: ProxyHandle) -> None:
        self._terminate(handle.proc)

    def _terminate(self, proc: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=self.STOP_GRACE_S)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=2.0)

    def _write_config(self) -> Path:
        yaml_text = render_litellm_config(
            self.models,
            ollama_api_base=self.api_base,
            master_key=self.master_key,
            wildcard_fallback_alias=self.wildcard_fallback_alias,
        )
        self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(
            prefix=f"litellm-{os.getpid()}-",
            suffix=".yaml",
            dir=str(self.log_dir),
        )
        os.close(fd)
        path = Path(name)
        path.write_text(yaml_text)
        return path
