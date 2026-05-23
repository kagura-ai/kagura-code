"""Tests for the on-demand middleware subprocess lifecycle."""
from __future__ import annotations

import time

import httpx

from kagura_code.middleware import MiddlewareManager


def test_start_stop_lifecycle():
    mgr = MiddlewareManager(
        proxy_url="http://127.0.0.1:1",
        router_model="claude-gemma4-31b",
        master_key="dummy",
    )
    h = mgr.start()
    try:
        r = httpx.get(f"http://127.0.0.1:{h.port}/health", timeout=5.0)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
    finally:
        mgr.stop(h)
        time.sleep(0.5)
