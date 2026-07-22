"""Lux Aeterna — WebSimBackend: a DMX backend that records frames and (when
serving) streams them to a self-contained browser canvas — an on-screen LED
simulator for the canonical Shroom. websockets is imported lazily so record-only
mode and this import work without the optional 'websim' extra installed."""

from __future__ import annotations

import json
import threading

from .base import DMXBackend
from ..synth.capability import SurfaceCapability, shroom_capability


def capability_message(cap: SurfaceCapability) -> dict:
    """The connect-time handshake: enough geometry for a browser to lay out and
    color the pixels from raw DMX frames."""
    return {
        "type": "capability",
        "surface_id": cap.surface_id,
        "pixel_count": cap.pixel_count,
        "color_order": cap.color_order,
        "zones": [{"name": z.name, "start": z.start, "count": z.count}
                  for z in cap.zones],
    }


class WebSimBackend(DMXBackend):
    def __init__(self, capability: SurfaceCapability | None = None,
                 host: str = "127.0.0.1", port: int = 0,
                 serve: bool = True) -> None:
        self._cap = capability or shroom_capability()
        self._n = self._cap.pixel_count * 3          # bytes we care about
        self._host = host
        self._port = port
        self._serve = serve
        self.frames: list[bytes] = []
        self._open = False
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self._clients: set = set()

    # --- DMXBackend ---------------------------------------------------------
    def open(self) -> None:
        self._open = True                            # serving added in Task A3

    def close(self) -> None:
        self._open = False

    def send(self, frame, universe_id: int = 0) -> None:
        payload = bytes(frame[:self._n])             # copy; never mutate frame
        self.frames.append(payload)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def port(self) -> int:
        return self._port
