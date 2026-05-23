"""Unit tests for session_state.py."""
from __future__ import annotations

import threading
import time

from kagura_code.compression import CompressionState
from kagura_code.session_state import SessionState, SessionStore


def test_get_or_create_returns_same_object_for_same_id():
    store = SessionStore()
    s1 = store.get_or_create("abc")
    s2 = store.get_or_create("abc")
    assert s1 is s2


def test_get_or_create_returns_distinct_for_different_ids():
    store = SessionStore()
    s1 = store.get_or_create("abc")
    s2 = store.get_or_create("def")
    assert s1 is not s2


def test_initial_state_is_empty():
    store = SessionStore()
    s = store.get_or_create("abc")
    assert s.miss_count == 0
    assert s.router_cache == {}
    assert s.full_load is False


def test_concurrent_get_or_create_is_thread_safe():
    store = SessionStore()
    results: list[SessionState] = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(store.get_or_create("shared"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({id(r) for r in results}) == 1


def test_record_miss_increments_and_sets_full_load_on_first_miss():
    store = SessionStore()
    s = store.get_or_create("abc")
    assert store.record_miss("abc") == 1
    assert s.miss_count == 1
    # Any miss promotes immediately — wrong prediction means full-load for rest of session.
    assert s.full_load is True
    assert store.record_miss("abc") == 2
    assert store.record_miss("abc") == 3
    assert s.full_load is True


def test_record_miss_evicts_router_cache_entry():
    store = SessionStore()
    s = store.get_or_create("abc")
    s.router_cache["hash_xyz"] = ["Read", "Bash"]
    store.record_miss("abc", user_message_hash="hash_xyz")
    assert "hash_xyz" not in s.router_cache


def test_record_miss_on_unknown_session_is_noop():
    store = SessionStore()
    assert store.record_miss("never_seen") == 0


def test_gc_removes_stale_sessions():
    store = SessionStore()
    store.get_or_create("old")
    store.get_or_create("new")
    # Backdate "old" to 2 hours ago
    store._sessions["old"].last_seen_at = time.time() - 7200.0

    removed = store.gc(max_age_s=3600.0)
    assert removed == 1
    assert "old" not in store._sessions
    assert "new" in store._sessions


def test_gc_no_op_when_all_fresh():
    store = SessionStore()
    store.get_or_create("a")
    store.get_or_create("b")
    assert store.gc(max_age_s=3600.0) == 0


def test_session_state_compression_field_starts_none():
    store = SessionStore()
    s = store.get_or_create("sid-A")
    assert s.compression is None


def test_session_state_compression_can_be_set():
    store = SessionStore()
    s = store.get_or_create("sid-B")
    s.compression = CompressionState()
    same = store.get_or_create("sid-B")
    assert same.compression is s.compression
