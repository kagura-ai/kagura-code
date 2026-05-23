from __future__ import annotations

import time
from pathlib import Path

from kagura_code.log_watcher import ProxyLogWatcher, WatcherEvent, classify

# Real lines copied from a live proxy-*.log (anonymized).
QUOTA_LINE = (
    'litellm.exceptions.APIConnectionError: litellm.APIConnectionError: '
    'Ollama_chatException - {"error":"you (user) have reached your session '
    'usage limit, upgrade for higher limits: https://ollama.com/upgrade '
    '(ref: abc-123)"}'
)
UNKNOWN_MODEL_LINE = (
    "litellm.proxy.proxy_server.anthropic_response(): Exception occured - "
    "litellm.BadRequestError: 400: {'error': 'anthropic_messages: "
    "Invalid model name passed in model=claude-opus-4-7. "
    "Call `/v1/models` to view available models for your key.'}"
)
UNRELATED_LINE = "INFO:     127.0.0.1:54321 - \"POST /v1/messages HTTP/1.1\" 200 OK"


class TestClassify:
    def test_matches_quota(self):
        ev = classify(QUOTA_LINE)
        assert ev == WatcherEvent(kind="quota", detail="")

    def test_matches_unknown_model_and_extracts_alias(self):
        ev = classify(UNKNOWN_MODEL_LINE)
        assert ev is not None
        assert ev.kind == "unknown_model"
        assert ev.detail == "claude-opus-4-7"

    def test_unknown_model_supports_versioned_aliases(self):
        ev = classify(
            "Invalid model name passed in model=claude-haiku-4-5-20251001. blah"
        )
        assert ev is not None
        assert ev.detail == "claude-haiku-4-5-20251001"

    def test_ignores_unrelated(self):
        assert classify(UNRELATED_LINE) is None
        assert classify("") is None


class TestProxyLogWatcher:
    def _drain(self, events: list[WatcherEvent], expected: int, timeout_s: float = 2.0) -> None:
        deadline = time.monotonic() + timeout_s
        while len(events) < expected and time.monotonic() < deadline:
            time.sleep(0.05)

    def test_detects_quota_once(self, tmp_path: Path):
        log = tmp_path / "proxy.log"
        log.touch()
        events: list[WatcherEvent] = []
        w = ProxyLogWatcher(log_path=log, on_event=events.append, poll_interval_s=0.05)
        w.start()
        try:
            with log.open("a") as f:
                f.write(QUOTA_LINE + "\n")
                f.write(QUOTA_LINE + "\n")  # second hit is dedup'd
                f.flush()
            self._drain(events, expected=1)
        finally:
            w.stop()
        assert len(events) == 1
        assert events[0].kind == "quota"

    def test_detects_unknown_models_dedup_per_alias(self, tmp_path: Path):
        log = tmp_path / "proxy.log"
        log.touch()
        events: list[WatcherEvent] = []
        w = ProxyLogWatcher(log_path=log, on_event=events.append, poll_interval_s=0.05)
        w.start()
        try:
            with log.open("a") as f:
                f.write(UNKNOWN_MODEL_LINE + "\n")
                f.write(UNKNOWN_MODEL_LINE + "\n")  # same alias -> dedup'd
                f.write(
                    "Invalid model name passed in model=claude-sonnet-4-6. x\n"
                )
                f.flush()
            self._drain(events, expected=2)
        finally:
            w.stop()
        assert {e.detail for e in events} == {"claude-opus-4-7", "claude-sonnet-4-6"}

    def test_waits_for_file_to_appear(self, tmp_path: Path):
        log = tmp_path / "delayed.log"
        events: list[WatcherEvent] = []
        w = ProxyLogWatcher(log_path=log, on_event=events.append, poll_interval_s=0.05)
        w.start()
        try:
            time.sleep(0.1)  # file doesn't exist yet
            log.write_text(QUOTA_LINE + "\n")
            self._drain(events, expected=1)
        finally:
            w.stop()
        assert len(events) == 1

    def test_stop_is_idempotent(self, tmp_path: Path):
        log = tmp_path / "proxy.log"
        log.touch()
        w = ProxyLogWatcher(log_path=log, on_event=lambda _e: None)
        w.start()
        w.stop()
        w.stop()  # no error

    def test_start_twice_raises(self, tmp_path: Path):
        log = tmp_path / "proxy.log"
        log.touch()
        w = ProxyLogWatcher(log_path=log, on_event=lambda _e: None)
        w.start()
        try:
            import pytest

            with pytest.raises(RuntimeError):
                w.start()
        finally:
            w.stop()

    def test_partial_lines_are_buffered(self, tmp_path: Path):
        """A line written without a trailing newline must not be matched
        until the newline arrives — otherwise we'd miss patterns split
        across read() chunks."""
        log = tmp_path / "proxy.log"
        log.touch()
        events: list[WatcherEvent] = []
        w = ProxyLogWatcher(log_path=log, on_event=events.append, poll_interval_s=0.05)
        w.start()
        try:
            with log.open("a") as f:
                f.write("reached your session usage limit")  # no newline
                f.flush()
            time.sleep(0.2)
            assert events == []  # not matched yet
            with log.open("a") as f:
                f.write("\n")
                f.flush()
            self._drain(events, expected=1)
        finally:
            w.stop()
        assert len(events) == 1
