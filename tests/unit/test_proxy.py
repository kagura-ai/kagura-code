from __future__ import annotations

import socket

from kagura_code.proxy import find_free_port


def test_find_free_port_returns_unique_bindable_port():
    p1 = find_free_port()
    p2 = find_free_port()
    assert 1024 < p1 < 65536
    assert 1024 < p2 < 65536
    # Both should be bindable (no one else has claimed them yet).
    with socket.socket() as s1, socket.socket() as s2:
        s1.bind(("127.0.0.1", p1))
        s2.bind(("127.0.0.1", p2))
