"""Signal handling for the launcher.

ShutdownCoordinator records the first shutdown signal and ignores
subsequent ones. The launcher main loop polls .shutdown_requested
between subprocess.wait() iterations to forward the signal to the
child claude process exactly once.
"""
from __future__ import annotations

import signal as _signal
import threading
from dataclasses import dataclass, field


@dataclass
class ShutdownCoordinator:
    shutdown_requested: bool = False
    first_signal: int | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def request_shutdown(self, sig: int) -> None:
        with self._lock:
            if not self.shutdown_requested:
                self.shutdown_requested = True
                self.first_signal = sig


def install_handlers(coord: ShutdownCoordinator) -> None:
    def handler(sig: int, _frame: object) -> None:
        coord.request_shutdown(sig)

    _signal.signal(_signal.SIGINT, handler)
    _signal.signal(_signal.SIGTERM, handler)
