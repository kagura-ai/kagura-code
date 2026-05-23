from __future__ import annotations

import signal

from kagura_code.signals import ShutdownCoordinator


def test_request_shutdown_is_idempotent():
    sc = ShutdownCoordinator()
    sc.request_shutdown(signal.SIGTERM)
    sc.request_shutdown(signal.SIGTERM)
    sc.request_shutdown(signal.SIGINT)
    assert sc.shutdown_requested is True
    assert sc.first_signal == signal.SIGTERM


def test_initial_state_no_shutdown():
    sc = ShutdownCoordinator()
    assert sc.shutdown_requested is False
    assert sc.first_signal is None
