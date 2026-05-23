"""Subprocess lifecycle for the kagura-code middleware uvicorn server.

Mirrors the pattern in proxy.py: dynamically allocate a port, spawn the server
in its own process group, wait for /health to return 200, expose a handle for
clean teardown.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class MiddlewareHandle:
    port: int
    pid: int
    proc: subprocess.Popen[bytes]


class MiddlewareManager:
    READY_TIMEOUT_S = 30.0
    STOP_GRACE_S = 5.0

    def __init__(
        self,
        *,
        proxy_url: str,
        router_model: str,
        master_key: str = "kagura-code-dummy",
        router_timeout_s: float = 5.0,
        known_aliases: frozenset[str] = frozenset(),
        default_alias: str | None = None,
        summarizer_model: str | None = None,
        model_index: dict[str, int] | None = None,
    ) -> None:
        self.proxy_url = proxy_url
        self.router_model = router_model
        self.master_key = master_key
        self.router_timeout_s = router_timeout_s
        self.known_aliases = known_aliases
        self.default_alias = default_alias
        self.summarizer_model = summarizer_model
        self.model_index = model_index or {}

    def start(self, *, port: int | None = None) -> MiddlewareHandle:
        port = port or _find_free_port()
        env = {
            **os.environ,
            "KAGURA_CODE_PROXY_URL": self.proxy_url,
            "KAGURA_CODE_ROUTER_MODEL": self.router_model,
            "KAGURA_CODE_MASTER_KEY": self.master_key,
            "KAGURA_CODE_ROUTER_TIMEOUT": str(self.router_timeout_s),
            "KAGURA_CODE_PORT": str(port),
            "KAGURA_CODE_KNOWN_ALIASES": ",".join(sorted(self.known_aliases)),
            "KAGURA_CODE_DEFAULT_ALIAS": self.default_alias or "",
            "KAGURA_CODE_SUMMARIZER_MODEL": self.summarizer_model or "",
            "KAGURA_CODE_MODEL_INDEX": json.dumps(self.model_index),
        }
        proc = subprocess.Popen(
            [sys.executable, "-m", "kagura_code.middleware.runner"],
            preexec_fn=os.setsid,
            env=env,
        )
        deadline = time.time() + self.READY_TIMEOUT_S
        while time.time() < deadline:
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
                if r.status_code == 200:
                    return MiddlewareHandle(port=port, pid=proc.pid, proc=proc)
            except httpx.RequestError:
                pass
            time.sleep(0.2)
        self._terminate(proc)
        raise RuntimeError(f"kagura-code middleware did not become ready on :{port}")

    def stop(self, handle: MiddlewareHandle) -> None:
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
