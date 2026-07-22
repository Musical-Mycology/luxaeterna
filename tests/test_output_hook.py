"""Lux Aeterna — tests for the OutputLoop on_frame hook."""

from __future__ import annotations

from luxaeterna.universe import Universe
from luxaeterna.output import OutputLoop
from luxaeterna.backends.base import DMXBackend


class FakeBackend(DMXBackend):
    def __init__(self):
        self.frames = []
        self._open = False

    def open(self):
        self._open = True

    def close(self):
        self._open = False

    def send(self, frame, universe_id):
        self.frames.append(bytes(frame))

    @property
    def is_open(self):
        return self._open


def test_on_frame_called_before_send():
    uni = Universe()
    marks = []
    def on_frame(u):
        marks.append("called")
        u.set(0, 200)
    loop = OutputLoop(uni, FakeBackend(), on_frame=on_frame)
    loop._loop_once()                              # single tick helper
    assert marks == ["called"]
    assert uni.get(0) == 200
