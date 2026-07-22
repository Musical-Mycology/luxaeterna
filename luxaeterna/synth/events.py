"""Lux Aeterna — session events: the ONLY structure shared between threads.

Producers (the o2lite poll thread, any caller thread) enqueue; the render
thread drains everything once per frame and applies events in arrival order.
Everything downstream of the drain is render-thread-only by construction."""

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
    def __init__(self) -> None:
        self._items: deque = deque()
        self._lock = threading.Lock()

    def put(self, event) -> None:
        with self._lock:
            self._items.append(event)

    def drain(self) -> list:
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items
