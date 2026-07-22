"""Tests for session events: bounded MIDI lane, never-dropped control lane."""

from __future__ import annotations

import threading

from luxaeterna.synth.events import (ClearEvent, EventQueue, MidiEvent,
                                     StatusEvent, SwapEvent)


def test_fifo_within_lanes_and_drain_empties():
    q = EventQueue()
    q.put(MidiEvent(1))
    q.put(ClearEvent())
    q.put(MidiEvent(2))
    items = q.drain()
    # MIDI lane first (arrival order), control lane last.
    assert [type(i) for i in items] == [MidiEvent, MidiEvent, ClearEvent]
    assert items[0].packed == 1 and items[1].packed == 2
    assert q.drain() == []


def test_midi_lane_bounded_drop_oldest():
    q = EventQueue(midi_capacity=8)
    for i in range(20):
        q.put(MidiEvent(i))
    items = q.drain()
    assert [e.packed for e in items] == list(range(12, 20))
    assert q.take_dropped() == 12
    assert q.take_dropped() == 0


def test_control_never_dropped_during_flood():
    q = EventQueue(midi_capacity=4)
    control = [SwapEvent(None), ClearEvent(), StatusEvent("error", "boom")]
    q.put(control[0])
    for i in range(5000):
        q.put(MidiEvent(i))
        if i == 2500:
            q.put(control[1])
    q.put(control[2])
    items = q.drain()
    assert all(a is b for a, b in zip(items[-3:], control))
    assert sum(isinstance(e, MidiEvent) for e in items) == 4


def test_concurrent_puts_all_arrive():
    q = EventQueue(midi_capacity=4000)

    def put_many(base):
        for i in range(1000):
            q.put(MidiEvent(base + i))

    threads = [threading.Thread(target=put_many, args=(k * 1000,))
               for k in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(q.drain()) == 4000
    assert q.take_dropped() == 0
