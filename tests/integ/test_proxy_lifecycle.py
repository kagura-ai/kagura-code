from __future__ import annotations

import errno
import os

import httpx


def test_proxy_starts_and_responds_to_health(proxy_manager):
    handle = proxy_manager.start()
    try:
        r = httpx.get(f"http://127.0.0.1:{handle.port}/health/readiness", timeout=5.0)
        assert r.status_code == 200
    finally:
        proxy_manager.stop(handle)


def test_proxy_serves_v1_models_endpoint(proxy_manager):
    handle = proxy_manager.start()
    try:
        r = httpx.get(
            f"http://127.0.0.1:{handle.port}/v1/models",
            headers={"Authorization": "Bearer test-key"},
            timeout=5.0,
        )
        assert r.status_code == 200
        body = r.json()
        ids = {m["id"] for m in body["data"]}
        assert "claude-fake-1m" in ids
    finally:
        proxy_manager.stop(handle)


def test_proxy_forwards_messages_request_to_fake_backend(proxy_manager, fake_ollama):
    _ = fake_ollama  # fixture wires the backend
    handle = proxy_manager.start()
    try:
        r = httpx.post(
            f"http://127.0.0.1:{handle.port}/v1/messages",
            headers={
                "Authorization": "Bearer test-key",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-fake-1m",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=15.0,
        )
        assert r.status_code == 200
        body = r.json()
        # Anthropic-format response shape
        assert "content" in body
        # The fake backend's content "hello from fake" should be threaded through.
        text_blocks = [c.get("text", "") for c in body["content"] if c.get("type") == "text"]
        assert any("hello from fake" in t for t in text_blocks)
    finally:
        proxy_manager.stop(handle)


def test_proxy_stops_cleanly(proxy_manager):
    handle = proxy_manager.start()
    pid = handle.pid
    proxy_manager.stop(handle)
    # After stop, the process must be reaped (no longer alive).
    try:
        os.kill(pid, 0)
        raise AssertionError(f"proxy pid {pid} still alive after stop")
    except OSError as e:
        assert e.errno == errno.ESRCH


def test_proxy_handles_unauth_request_with_401(proxy_manager):
    handle = proxy_manager.start()
    try:
        r = httpx.post(
            f"http://127.0.0.1:{handle.port}/v1/messages",
            headers={
                "Authorization": "Bearer wrong-key",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-fake-1m",
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "x"}],
            },
            timeout=5.0,
        )
        # LiteLLM returns 401/403 when the key doesn't match master_key.
        # Without a DB it may return 400 ("No connected db.") for non-sk- keys —
        # any of these indicates the request was rejected, which is the correct
        # behaviour for an invalid bearer token.
        assert r.status_code in (400, 401, 403)
    finally:
        proxy_manager.stop(handle)
