"""Lux Aeterna — O2 input bridge: decode packed-int32 MIDI and dispatch to bindings.

O2 is *an* input path, not *the* input path. This bridge serves the deployments
where the renderer is in a different process from whatever is driving it — a
Tuneshroom, or a split-out Terrarium renderer — and each note/CC costs 2 hops
(Control -> Arco -> renderer). When the renderer lives in the driver's own
process (today's Terrarium, where Control constructs the LightSession
in-process), MIDI arrives by direct call via LightSession.feed_midi() and
attach() is never called: addressing an o2lite service from inside the process
that offers it would round-trip through the O2 host for nothing. See
docs/deployment.md. decode_midi/dispatch_midi below are transport-agnostic and
serve both paths.

Wire format (ratified): one int32 = (status << 16) | (data1 << 8) | data2,
since o2lite lacks O2's native 'm' MIDI type.

o2litepy contract (verified against rbdannenberg/o2 and the copy vendored in
rbdannenberg/arco@498e4ab): ``method_new(path, typespec, full, handler,
info)`` takes five required args, and handlers are called ``handler(address,
types, info)``, pulling payload values via ``client.get_int32()``. There is NO
handler-removal API — registration is permanent for the life of the client,
which is why attach() refuses to run twice."""

from __future__ import annotations

import logging
from typing import Callable

from ..logutil import ThrottledLog

log = logging.getLogger(__name__)
_throttle = ThrottledLog(log)


def decode_midi(packed: int) -> tuple[int, int, int]:
    return (packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF


def _call(fn, *args, key: str) -> None:
    try:
        fn(*args)
    except Exception as exc:
        _throttle.log(key, logging.WARNING, "binding route error: %s", exc)


def dispatch_midi(bindings, status: int, d1: int, d2: int) -> None:
    kind = status & 0xF0
    if kind == 0x90 and d2 > 0:                       # note-on
        for b in bindings:
            fn = b.routes.get("note")
            if fn is not None:
                _call(fn, d1, d2 / 127.0, key=f"note:{id(b)}")
    elif kind == 0x80 or (kind == 0x90 and d2 == 0):  # note-off
        for b in bindings:
            noteoff = getattr(b.obj, "noteoff", None)
            if noteoff is not None:
                _call(noteoff, d1, key=f"noteoff:{id(b)}")
    elif kind == 0xB0:                                # control change
        key = f"cc:{d1}"
        for b in bindings:
            fn = b.routes.get(key)
            if fn is not None:
                _call(fn, d2 / 127.0, key=f"{key}:{id(b)}")


class O2Bridge:
    """Receives packed-int32 MIDI and enqueues it for the render thread;
    decode/dispatch runs later, at drain time.

    on_midi() is the transport-neutral entry point — an attached o2lite handler
    and an in-process caller both land here, and everything downstream is
    identical. attach() is only for the cross-process and on-device
    deployments; in-process consumers skip it entirely (docs/deployment.md)."""

    def __init__(self, enqueue: Callable[[int], None]) -> None:
        self._enqueue = enqueue
        self._attached = False

    def on_midi(self, packed) -> None:
        try:
            self._enqueue(int(packed))
        except Exception as exc:
            _throttle.log("midi-enqueue", logging.WARNING,
                          "dropped MIDI packet %r: %s", packed, exc)

    def attach(self, o2lite_client, address: str = "/light/midi") -> None:
        if self._attached:
            raise RuntimeError(
                "O2Bridge.attach() called twice: o2litepy has no handler "
                "removal, so re-attaching would leak the old handler forever")

        def _handler(addr, types, info):
            self.on_midi(o2lite_client.get_int32())

        o2lite_client.method_new(address, "i", True, _handler, None)
        self._attached = True
