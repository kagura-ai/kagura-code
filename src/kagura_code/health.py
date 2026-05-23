"""Proxy readiness probe."""
from __future__ import annotations

import time

import httpx


class HealthCheckTimeout(TimeoutError):
    """Proxy did not become ready within the allowed window."""


def wait_for_ready(port: int, *, timeout_s: float = 15.0, interval_s: float = 0.3) -> None:
    """Poll GET /health/readiness on 127.0.0.1:port until 200 or timeout."""
    url = f"http://127.0.0.1:{port}/health/readiness"
    deadline = time.monotonic() + timeout_s
    last_err: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200:
                return
            last_err = RuntimeError(f"status={r.status_code}")
        except httpx.RequestError as e:
            last_err = e
        time.sleep(interval_s)
    raise HealthCheckTimeout(f"proxy on :{port} not ready within {timeout_s}s (last: {last_err!r})")
