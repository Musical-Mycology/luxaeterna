"""WebSimBackend: records DMX frames (record-only mode) and describes the
surface to browser clients via a capability handshake."""

from __future__ import annotations

from luxaeterna.backends.websim import WebSimBackend, capability_message
from luxaeterna.synth.capability import shroom_capability


def test_capability_message_describes_the_shroom():
    msg = capability_message(shroom_capability())
    assert msg["type"] == "capability"
    assert msg["pixel_count"] == 12
    assert msg["color_order"] == "GRB"
    assert {"name": "ring", "start": 0, "count": 8} in msg["zones"]
    assert {"name": "stem", "start": 8, "count": 4} in msg["zones"]


def test_record_only_backend_records_pixel_slice_without_serving():
    b = WebSimBackend(capability=shroom_capability(), serve=False)
    assert b.is_open is False
    b.open()
    assert b.is_open is True
    frame = bytearray(range(36)) + bytearray(512 - 36)   # 12 px * 3 = 36
    b.send(frame)
    assert len(b.frames) == 1
    assert b.frames[0] == bytes(range(36))               # sliced to pixel_count*3
    b.close()
    assert b.is_open is False


def test_send_does_not_mutate_frame():
    b = WebSimBackend(capability=shroom_capability(), serve=False)
    b.open()
    frame = bytearray([7]) * 512
    b.send(frame)
    assert frame == bytearray([7]) * 512
