"""WebSimBackend's inbound seam: browser -> on_input.

Drives _handle() directly with a fake connection, mirroring how
tests/backends/test_websim.py already avoids real sockets. The fake
yields inbound messages exactly as websockets' sync connection does:
str for text frames, bytes for binary."""

from __future__ import annotations

from luxaeterna.backends.websim import WebSimBackend


class FakeConnection:
    def __init__(self, inbound):
        self._inbound = list(inbound)
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)

    def __iter__(self):
        return iter(self._inbound)


def test_text_message_reaches_on_input():
    got = []
    backend = WebSimBackend(serve=False, on_input=got.append)
    backend._handle(FakeConnection(['{"type": "tap", "count": 2}']))
    assert got == [{"type": "tap", "count": 2}]


def test_malformed_json_and_non_dict_are_dropped():
    got = []
    backend = WebSimBackend(serve=False, on_input=got.append)
    backend._handle(FakeConnection(["{not json", "[1, 2]", '"str"']))
    assert got == []


def test_binary_inbound_is_ignored():
    got = []
    backend = WebSimBackend(serve=False, on_input=got.append)
    backend._handle(FakeConnection([b"\x00\x01", '{"type": "tilt", "gamma": 3}']))
    assert got == [{"type": "tilt", "gamma": 3}]


def test_raising_callback_does_not_kill_the_handler():
    calls = []

    def bad(msg):
        calls.append(msg)
        raise RuntimeError("boom")

    backend = WebSimBackend(serve=False, on_input=bad)
    # Two messages: the first raises, the second must still be delivered.
    backend._handle(FakeConnection(['{"a": 1}', '{"b": 2}']))
    assert calls == [{"a": 1}, {"b": 2}]


def test_default_on_input_none_still_drains_inbound():
    backend = WebSimBackend(serve=False)
    conn = FakeConnection(['{"type": "tap"}'])
    backend._handle(conn)  # must not raise
    # The capability handshake still went out.
    assert conn.sent
