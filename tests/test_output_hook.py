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


def test_on_frame_exception_is_routed_to_on_error_and_loop_survives():
    uni = Universe()
    errors = []
    def boom(u):
        raise ValueError("render blew up")
    loop = OutputLoop(uni, FakeBackend(), on_frame=boom, on_error=errors.append)
    loop._loop_once()          # must NOT raise
    loop._loop_once()          # still callable a second time (loop would survive)
    assert len(errors) == 2
    assert isinstance(errors[0], ValueError)


def test_default_error_logging_is_throttled(caplog):
    import logging as _logging
    uni = Universe()

    class _BoomBackend:
        def open(self):
            pass

        def close(self):
            pass

        def send(self, frame, universe_id=0):
            raise RuntimeError("dead backend")

        @property
        def is_open(self):
            return True

    loop = OutputLoop(uni, _BoomBackend(), always_send=True)
    with caplog.at_level(_logging.ERROR, logger="luxaeterna.output"):
        for _ in range(50):
            loop._loop_once()
    assert len(caplog.records) == 1        # first logs; 49 suppressed within 5 s
