"""Lux Aeterna — O2 input bridge: decode packed-int32 MIDI and dispatch to bindings.

Wire format (ratified): one int32 = (status << 16) | (data1 << 8) | data2,
since o2lite lacks O2's native 'm' MIDI type.
"""

from __future__ import annotations

import logging

from .binding import ActiveBinding

log = logging.getLogger(__name__)


def decode_midi(packed: int) -> tuple[int, int, int]:
    return (packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF


def dispatch_midi(bindings: list[ActiveBinding], status: int, d1: int, d2: int) -> None:
    kind = status & 0xF0
    if kind == 0x90 and d2 > 0:                       # note-on
        for b in bindings:
            fn = b.routes.get("note")
            if fn is not None:
                fn(d1, d2 / 127.0)
    elif kind == 0x80 or (kind == 0x90 and d2 == 0):  # note-off
        for b in bindings:
            noteoff = getattr(b.obj, "noteoff", None)
            if noteoff is not None:
                noteoff(d1)                           # pitch-addressed: matches note_id=pitch from the note route
    elif kind == 0xB0:                                # control change
        key = f"cc:{d1}"
        for b in bindings:
            fn = b.routes.get(key)
            if fn is not None:
                fn(d2 / 127.0)


class O2Bridge:
    """Holds the active bindings and turns inbound packed-int32 MIDI into route calls."""

    def __init__(self, bindings: list[ActiveBinding]) -> None:
        self.bindings = bindings

    def on_midi(self, packed: int) -> None:
        try:
            status, d1, d2 = decode_midi(packed)
            dispatch_midi(self.bindings, status, d1, d2)
        except Exception as exc:
            log.warning("dropped MIDI packet %r: %s", packed, exc)

    def attach(self, o2lite_client, address: str = "/light/midi") -> None:
        """Subscribe on_midi to an o2lite address. Thin transport glue; the
        decode/dispatch above is what tests exercise."""
        o2lite_client.method_new(address, "i", True,
                                 lambda ts, addr, types, *args: self.on_midi(args[0]))
