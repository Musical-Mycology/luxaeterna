"""Lux Aeterna — session events: the ONLY structure shared between threads.

Producers (the o2lite poll thread, any caller thread) enqueue; the render
thread drains once per frame and applies events in arrival order per lane:
a bounded MIDI lane (drop-oldest) and an unbounded control lane that never
drops. Everything downstream of the drain is render-thread-only by
construction."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from .manifest import LightManifest


@dataclass
class MidiEvent:
    packed: int                 # (status << 16) | (data1 << 8) | data2


@dataclass
class SwapEvent:
    manifest: LightManifest


@dataclass
class ClearEvent:
    pass


@dataclass
class StatusEvent:
    kind: str                   # "error" | "disconnect" | "reconnect" | "identify" | "selftest"
    arg: object = None


class EventQueue:
    """put() from any thread; drain() on the render thread once per frame.

    MIDI lands in a bounded lane (drop-oldest at ``midi_capacity``) so a
    burst can never balloon frame time or memory. Control-plane events
    (SwapEvent, ClearEvent, StatusEvent) land in an unbounded lane and are
    never dropped. drain() returns MIDI first, control last — the control
    plane gets the final word within a frame; cross-lane arrival order is
    intentionally not preserved (bounded by one 44 Hz frame)."""

    def __init__(self, midi_capacity: int = 256) -> None:
        self._midi: deque = deque(maxlen=midi_capacity)
        self._control: deque = deque()
        self._dropped = 0
        self._lock = threading.Lock()

    def put(self, event) -> None:
        with self._lock:
            if isinstance(event, MidiEvent):
                if len(self._midi) == self._midi.maxlen:
                    self._dropped += 1
                self._midi.append(event)
            else:
                self._control.append(event)

    def drain(self) -> list:
        with self._lock:
            items = list(self._midi)
            items.extend(self._control)
            self._midi.clear()
            self._control.clear()
        return items

    def take_dropped(self) -> int:
        with self._lock:
            n = self._dropped
            self._dropped = 0
            return n
