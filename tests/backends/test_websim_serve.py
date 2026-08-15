"""WebSimBackend serving: a real websocket client receives the capability
handshake, then each sent frame as a binary message."""

from __future__ import annotations

import json

import pytest

from luxaeterna.backends.websim import WebSimBackend, PAGE_HTML
from luxaeterna.synth.capability import shroom_capability


def test_page_is_self_contained_canvas():
    lower = PAGE_HTML.lower()
    assert "<canvas" in lower
    assert "websocket" in lower          # connects itself, no external libs
    assert "http" not in lower.split("</style>")[0] or "cdn" not in lower


def test_client_receives_capability_then_frame():
    pytest.importorskip("websockets")
    from websockets.sync.client import connect

    b = WebSimBackend(capability=shroom_capability(), host="127.0.0.1", port=0)
    b.open()
    try:
        with connect(f"ws://127.0.0.1:{b.port}/ws") as c:
            cap = json.loads(c.recv())               # capability arrives first
            assert cap["type"] == "capability"
            assert cap["pixel_count"] == 12
            b.send(bytearray(range(36)) + bytearray(512 - 36))
            frame = c.recv()                         # binary frame follows
            assert bytes(frame) == bytes(range(36))
    finally:
        b.close()


def test_label_appends_to_title():
    b = WebSimBackend(capability=shroom_capability(), label="sim-room")
    assert ("<title>Lux Aeterna — Shroom LED Simulator — sim-room</title>"
            in b._page_html)


def test_label_is_html_escaped():
    b = WebSimBackend(capability=shroom_capability(), label="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in b._page_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in b._page_html
