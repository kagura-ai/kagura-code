"""Watches the LiteLLM proxy log for actionable error patterns.

Two patterns are detected:

- **Session quota exhausted** (``reached your session usage limit``).
  Ollama Cloud returns 429; LiteLLM forwards it, Claude Code retries
  with exponential backoff indefinitely. We surface this so the launcher
  can shut down rather than spin forever.

- **Unknown model alias** (``Invalid model name passed in model=<x>``).
  Claude Code asked for a model not in the proxy's ``model_list`` — most
  commonly an Anthropic-native alias (``claude-opus-4-7``) picked from
  ``/model`` in the TUI. We surface it so the launcher can tell the user
  which aliases are actually configured.

The watcher itself is dumb: it tails the file, matches lines, and calls
an ``on_event`` callback. Policy (shut down or warn) lives in the caller.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_QUOTA_PAT = re.compile(r"reached your session usage limit")
# Stop before the trailing ". Call ..." in the LiteLLM error template by
# excluding '.' from the alias charset. kagura-code aliases never contain
# a period anyway (the `claude-` prefix is required, see ModelSpec).
_UNKNOWN_MODEL_PAT = re.compile(
    r"Invalid model name passed in model=([A-Za-z0-9_\-:]+)"
)


@dataclass(frozen=True)
class WatcherEvent:
    kind: str  # "quota" | "unknown_model"
    detail: str  # model alias for unknown_model, "" for quota


def classify(line: str) -> WatcherEvent | None:
    """Match a single log line against known patterns."""
    if _QUOTA_PAT.search(line):
        return WatcherEvent(kind="quota", detail="")
    m = _UNKNOWN_MODEL_PAT.search(line)
    if m:
        return WatcherEvent(kind="unknown_model", detail=m.group(1))
    return None


class ProxyLogWatcher:
    """Background daemon thread that tails a proxy log file.

    Dedup: the quota event fires at most once; each distinct unknown
    model alias fires at most once. Callers don't need to track state.
    """

    POLL_INTERVAL_S = 0.5

    def __init__(
        self,
        log_path: Path,
        *,
        on_event: Callable[[WatcherEvent], None],
        poll_interval_s: float | None = None,
    ) -> None:
        self.log_path = log_path
        self.on_event = on_event
        self.poll_interval_s = poll_interval_s or self.POLL_INTERVAL_S
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen_quota = False
        self._seen_unknown: set[str] = set()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("watcher already started")
        self._thread = threading.Thread(
            target=self._run, name="proxy-log-watcher", daemon=True
        )
        self._thread.start()

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)

    def _run(self) -> None:
        # Wait until the proxy actually creates the file.
        while not self._stop_event.is_set() and not self.log_path.exists():
            self._stop_event.wait(self.poll_interval_s)
        if self._stop_event.is_set():
            return
        try:
            with self.log_path.open("r", encoding="utf-8", errors="replace") as f:
                buf = ""
                while not self._stop_event.is_set():
                    chunk = f.read()
                    if chunk:
                        buf += chunk
                        *lines, buf = buf.split("\n")
                        for line in lines:
                            self._inspect(line)
                    else:
                        self._stop_event.wait(self.poll_interval_s)
        except OSError:
            return

    def _inspect(self, line: str) -> None:
        ev = classify(line)
        if ev is None:
            return
        if ev.kind == "quota":
            if self._seen_quota:
                return
            self._seen_quota = True
        elif ev.kind == "unknown_model":
            if ev.detail in self._seen_unknown:
                return
            self._seen_unknown.add(ev.detail)
        self.on_event(ev)
