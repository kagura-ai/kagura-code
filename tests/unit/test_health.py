from __future__ import annotations

import pytest

from kagura_code.health import HealthCheckTimeout, wait_for_ready


def test_wait_for_ready_returns_when_endpoint_ok(httpserver):
    httpserver.expect_request("/health/readiness").respond_with_data("ok")
    port = httpserver.port
    wait_for_ready(port, timeout_s=2.0, interval_s=0.05)


def test_wait_for_ready_raises_timeout_on_no_response():
    # Bind to a free port that nobody is listening on.
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(HealthCheckTimeout):
        wait_for_ready(port, timeout_s=0.5, interval_s=0.05)


def test_wait_for_ready_retries_until_endpoint_comes_up(httpserver):
    # httpserver responds 503 a few times, then 200
    calls = {"n": 0}

    def handler(req):
        from werkzeug.wrappers import Response
        calls["n"] += 1
        if calls["n"] < 3:
            return Response("not ready", status=503)
        return Response("ok", status=200)

    httpserver.expect_request("/health/readiness").respond_with_handler(handler)
    wait_for_ready(httpserver.port, timeout_s=3.0, interval_s=0.05)
    assert calls["n"] >= 3
