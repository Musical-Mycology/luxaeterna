"""Lux Aeterna — LightSession: the attach-once facade.

Owns the event queue, O2 bridge, status director, and engine. Input reaches the
queue by either of two paths, depending on where the session is deployed
(docs/deployment.md): direct calls — feed_midi() and the lifecycle methods —
when the session lives in the driver's own process, or o2lite when it does not.
Where attach() is used, the o2lite handler is registered exactly once per
process and closes over this session — never over bindings — so bit swaps can
never leak into o2litepy's append-only handler table. All graph mutation happens
on the render thread at frame boundaries (queue drain), on both paths."""

from __future__ import annotations

import logging
import time

from ..logutil import ThrottledLog
from .capability import SurfaceCapability
from .director import RUNNING, StatusDirector
from .engine import LightEngine
from .events import ClearEvent, EventQueue, MidiEvent, StatusEvent, SwapEvent
from .manifest import LightManifest
from .o2bridge import O2Bridge, decode_midi, dispatch_midi

log = logging.getLogger(__name__)
_throttle = ThrottledLog(log)


class LightSession:
    def __init__(self, cap: SurfaceCapability, clock=time.monotonic,
                 midi_capacity: int = 256) -> None:
        self.cap = cap
        self._clock = clock
        self._queue = EventQueue(midi_capacity=midi_capacity)
        self._bridge = O2Bridge(lambda packed: self._queue.put(MidiEvent(packed)))
        self._director = StatusDirector(cap)
        self._engine = LightEngine(cap)
        self._frame = 0
        self._last: float | None = None    # previous clock reading, for dt

    # -- wiring (once, at device startup) -----------------------------------

    def attach(self, o2lite_client, address: str = "/light/midi") -> None:
        """Wire this session to an o2lite client — for the deployments where the
        driver is in another process (a Tuneshroom, or a split-out Terrarium
        renderer). Do not call it when the driver constructs this session
        in-process: use feed_midi() instead, or the message round-trips through
        the O2 host to reach a caller it shares a process with."""
        self._bridge.attach(o2lite_client, address)

    def feed_midi(self, status: int, data1: int, data2: int) -> None:
        """Feed a MIDI message in by direct call — the input path for
        in-process consumers (today's Terrarium, where Control constructs the
        session itself), and for device simulators and tests with no live
        o2lite client. Packed and enqueued exactly like a packet off the wire,
        so it is gated to RUNNING and drained on the render thread like any
        other MIDI event."""
        packed = ((status & 0xFF) << 16) | ((data1 & 0xFF) << 8) | (data2 & 0xFF)
        self._bridge.on_midi(packed)

    # -- lifecycle (thread-safe: applied at the next frame boundary) --------

    def swap(self, manifest: LightManifest) -> None:
        self._queue.put(SwapEvent(manifest))

    def clear(self) -> None:
        self._queue.put(ClearEvent())

    def error(self, reason: str = "") -> None:
        self._queue.put(StatusEvent("error", reason))

    def notify_disconnect(self) -> None:
        self._queue.put(StatusEvent("disconnect"))

    def notify_reconnect(self) -> None:
        self._queue.put(StatusEvent("reconnect"))

    def identify(self, duration: float = 3.0) -> None:
        self._queue.put(StatusEvent("identify", duration))

    def selftest(self) -> None:
        self._queue.put(StatusEvent("selftest"))

    # -- introspection ------------------------------------------------------

    @property
    def state(self) -> str:
        return self._director.state

    @property
    def bit_name(self) -> str:
        return self._director.bit_name

    # -- render thread (wire as OutputLoop's on_frame) ----------------------

    def render_into(self, universe) -> None:
        # t is the injected clock's own reading, not elapsed time since this
        # session's first frame. Every session handed the same clock (every
        # Room fixture session on a Terrarium, in o2lite mode) therefore
        # agrees on t, which is what lets one rainbow declaration paint a
        # continuous gradient across fixtures rendered by different
        # sessions. Anything that needs a local origin integrates dt
        # (Envelope, SegmentLevel, Smooth, the status signatures); nothing
        # may assume t starts near zero.
        now = self._clock()
        if self._last is None:
            dt = 1e-6                        # first frame: no previous read
        else:
            dt = max(now - self._last, 1e-6)  # floor: stalled or reset clock
        self._last = now
        t = now

        for ev in self._queue.drain():
            self._apply(ev)
        dropped = self._queue.take_dropped()
        if dropped:
            _throttle.log("midi-overflow", logging.WARNING,
                          "MIDI lane overflow: %d events dropped", dropped)

        bindings, gain = self._director.frame(dt)
        failed = self._engine.render_into(universe, bindings, t, dt,
                                          self._frame, gain)
        self._director.note_failures(failed)
        self._frame += 1

    def _apply(self, ev) -> None:
        if isinstance(ev, MidiEvent):
            if self._director.state == RUNNING:
                status, d1, d2 = decode_midi(ev.packed)
                dispatch_midi(self._director.bit_bindings, status, d1, d2)
            else:
                _throttle.log("midi-dropped", logging.DEBUG,
                              "MIDI dropped in state %s", self._director.state)
        elif isinstance(ev, SwapEvent):
            self._director.swap(ev.manifest)
        elif isinstance(ev, ClearEvent):
            self._director.clear()
        elif isinstance(ev, StatusEvent):
            if ev.kind == "error":
                self._director.error(ev.arg or "")
            elif ev.kind == "disconnect":
                self._director.disconnect()
            elif ev.kind == "reconnect":
                self._director.reconnect()
            elif ev.kind == "identify":
                self._director.identify(ev.arg if ev.arg is not None else 3.0)
            elif ev.kind == "selftest":
                self._director.selftest()


def build_session(manifest: LightManifest, cap: SurfaceCapability,
                  clock=time.monotonic,
                  midi_capacity: int = 256) -> LightSession:
    """Construct a session with the initial bit swap already enqueued."""
    session = LightSession(cap, clock=clock, midi_capacity=midi_capacity)
    session.swap(manifest)
    return session
