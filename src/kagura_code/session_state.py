"""Per-session in-memory state for the on-demand middleware.

State is bounded by TTL-based GC and never persisted.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .compression import CompressionState


@dataclass
class SessionState:
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    miss_count: int = 0
    router_cache: dict[str, list[str]] = field(default_factory=dict)
    full_load: bool = False
    compression: CompressionState | None = None


class SessionStore:
    """Thread-safe dict-of-SessionState keyed by session ID."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str) -> SessionState:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                s = SessionState(session_id=session_id)
                self._sessions[session_id] = s
            else:
                s.last_seen_at = time.time()
            return s

    def record_miss(self, session_id: str, *, user_message_hash: str | None = None) -> int:
        """Increment miss counter, mark session full-load, invalidate cache entry.

        Returns the new miss count (0 if the session does not exist).
        """
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return 0
            s.miss_count += 1
            s.full_load = True  # ANY miss → don't trust the router for this session
            if user_message_hash is not None:
                s.router_cache.pop(user_message_hash, None)
            return s.miss_count

    def gc(self, *, max_age_s: float = 3600.0) -> int:
        """Remove sessions whose last_seen_at is older than max_age_s.

        Returns the number of sessions removed.
        """
        cutoff = time.time() - max_age_s
        with self._lock:
            stale = [sid for sid, s in self._sessions.items() if s.last_seen_at < cutoff]
            for sid in stale:
                del self._sessions[sid]
            return len(stale)
