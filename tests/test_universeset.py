"""UniverseSet: a PixelSpan's universes written and sent as one coherent frame."""

from __future__ import annotations

import pytest

from luxaeterna.backends.base import DMXBackend
from luxaeterna.constants import DMX_CHANNELS
from luxaeterna.exceptions import ChannelError
from luxaeterna.pixelspan import PixelSpan
from luxaeterna.universeset import MultiUniverseOutputLoop, UniverseSet

TERRARIUM = 864


class RecordingBackend(DMXBackend):
    def __init__(self) -> None:
        self.sent: list[tuple[int, bytes]] = []
        self._open = False
        self.fail_on_universe: int | None = None

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def send(self, frame, universe_id: int = 0) -> None:
        if self.fail_on_universe == universe_id:
            raise RuntimeError(f"universe {universe_id} exploded")
        self.sent.append((universe_id, bytes(frame)))

    @property
    def is_open(self) -> bool:
        return self._open


# --- UniverseSet ---

def test_allocates_one_universe_per_span_universe():
    us = UniverseSet(PixelSpan(TERRARIUM))
    assert len(us.universes) == 7
    assert [u.universe_id for u in us.universes] == [0, 1, 2, 3, 4, 5, 6]


def test_honours_start_universe():
    us = UniverseSet(PixelSpan(TERRARIUM, start_universe=10))
    assert [u.universe_id for u in us.universes] == [10, 11, 12, 13, 14, 15, 16]


def test_set_pixels_writes_across_the_universe_boundary():
    us = UniverseSet(PixelSpan(TERRARIUM))
    values = bytearray(3456)
    values[508:516] = bytes([1, 2, 3, 4, 5, 6, 7, 8])   # pixel 127 then 128
    us.set_pixels(values)
    assert us.universes[0].get(508) == 1
    assert us.universes[0].get(511) == 4
    assert us.universes[1].get(0) == 5
    assert us.universes[1].get(3) == 8


def test_set_pixels_zero_fills_the_tail_of_the_last_universe():
    us = UniverseSet(PixelSpan(TERRARIUM))
    us.set_pixels(bytearray([255]) * 3456)
    last = us.universes[6]
    assert last.get(383) == 255          # final real channel
    assert last.get(384) == 0            # padding begins
    assert last.get(511) == 0


def test_set_pixels_rejects_a_wrong_length_buffer():
    us = UniverseSet(PixelSpan(TERRARIUM))
    with pytest.raises(ChannelError, match="3456"):
        us.set_pixels(bytearray(3455))


def test_fill_pixel_writes_one_pixel_in_the_right_universe():
    us = UniverseSet(PixelSpan(TERRARIUM))
    us.fill_pixel(863, bytes([9, 8, 7, 6]))
    assert us.universes[6].get(380) == 9
    assert us.universes[6].get(383) == 6


def test_fill_pixel_rejects_wrong_channel_count():
    us = UniverseSet(PixelSpan(TERRARIUM))
    with pytest.raises(ChannelError):
        us.fill_pixel(0, bytes([1, 2, 3]))


def test_frames_returns_one_full_dmx_frame_per_universe():
    us = UniverseSet(PixelSpan(TERRARIUM))
    frames = us.frames()
    assert len(frames) == 7
    assert [uid for uid, _ in frames] == [0, 1, 2, 3, 4, 5, 6]
    assert all(len(f) == DMX_CHANNELS for _, f in frames)


def test_reset_zeroes_every_universe():
    us = UniverseSet(PixelSpan(TERRARIUM))
    us.set_pixels(bytearray([200]) * 3456)
    us.reset()
    assert all(u.get(0) == 0 for u in us.universes)


# --- MultiUniverseOutputLoop ---

def test_one_tick_sends_every_universe_exactly_once():
    us = UniverseSet(PixelSpan(TERRARIUM))
    backend = RecordingBackend()
    loop = MultiUniverseOutputLoop(us, backend)
    backend.open()
    assert loop._loop_once() == 7
    assert [uid for uid, _ in backend.sent] == [0, 1, 2, 3, 4, 5, 6]


def test_on_frame_hook_runs_before_the_send():
    us = UniverseSet(PixelSpan(TERRARIUM))
    backend = RecordingBackend()
    seen: list[int] = []

    def paint(universe_set):
        seen.append(len(backend.sent))
        universe_set.fill_pixel(0, bytes([1, 2, 3, 4]))

    loop = MultiUniverseOutputLoop(us, backend, on_frame=paint)
    backend.open()
    loop._loop_once()
    assert seen == [0]                       # hook ran before anything was sent
    assert backend.sent[0][1][0] == 1        # and its paint reached the wire


def test_a_failing_universe_does_not_stop_the_others():
    us = UniverseSet(PixelSpan(TERRARIUM))
    backend = RecordingBackend()
    backend.fail_on_universe = 3
    errors: list[Exception] = []
    loop = MultiUniverseOutputLoop(us, backend, on_error=errors.append)
    backend.open()
    assert loop._loop_once() == 6
    assert [uid for uid, _ in backend.sent] == [0, 1, 2, 4, 5, 6]
    assert len(errors) == 1


def test_a_failing_on_frame_hook_does_not_stop_the_send():
    us = UniverseSet(PixelSpan(TERRARIUM))
    backend = RecordingBackend()
    errors: list[Exception] = []

    def boom(_):
        raise RuntimeError("paint failed")

    loop = MultiUniverseOutputLoop(us, backend, on_frame=boom,
                                   on_error=errors.append)
    backend.open()
    assert loop._loop_once() == 7
    assert len(errors) == 1


def test_start_opens_the_backend_and_stop_closes_it():
    us = UniverseSet(PixelSpan(TERRARIUM))
    backend = RecordingBackend()
    loop = MultiUniverseOutputLoop(us, backend)
    loop.start()
    assert backend.is_open is True
    assert loop.running is True
    loop.stop()
    assert backend.is_open is False
    assert loop.running is False


def test_start_is_idempotent():
    us = UniverseSet(PixelSpan(TERRARIUM))
    loop = MultiUniverseOutputLoop(us, RecordingBackend())
    loop.start()
    loop.start()
    loop.stop()


def test_stop_before_start_is_harmless():
    us = UniverseSet(PixelSpan(TERRARIUM))
    loop = MultiUniverseOutputLoop(us, RecordingBackend())
    loop.stop()
    assert loop.running is False


# --- the dirty-flag path ---
#
# get_frame() clears the dirty flag, so a naive implementation that snapshots
# every universe and *then* asks whether it was dirty sees them all clean and
# never sends. These pin the ordering.

def test_always_send_false_skips_clean_universes():
    us = UniverseSet(PixelSpan(TERRARIUM))
    backend = RecordingBackend()
    loop = MultiUniverseOutputLoop(us, backend, always_send=False)
    backend.open()
    loop._loop_once()                    # first tick: all dirty from construction
    backend.sent.clear()
    assert loop._loop_once() == 0        # nothing changed, so nothing sent


def test_always_send_false_still_sends_a_dirtied_universe():
    us = UniverseSet(PixelSpan(TERRARIUM))
    backend = RecordingBackend()
    loop = MultiUniverseOutputLoop(us, backend, always_send=False)
    backend.open()
    loop._loop_once()
    backend.sent.clear()
    us.fill_pixel(200, bytes([1, 2, 3, 4]))      # pixel 200 lives in universe 1
    assert loop._loop_once() == 1
    assert [uid for uid, _ in backend.sent] == [1]


def test_always_send_true_sends_clean_universes_anyway():
    us = UniverseSet(PixelSpan(TERRARIUM))
    backend = RecordingBackend()
    loop = MultiUniverseOutputLoop(us, backend, always_send=True)
    backend.open()
    loop._loop_once()
    backend.sent.clear()
    assert loop._loop_once() == 7
