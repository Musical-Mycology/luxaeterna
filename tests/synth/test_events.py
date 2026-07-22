"""Tests for session events: the one structure shared between threads."""

from __future__ import annotations

import threading

from luxaeterna.synth.events import ClearEvent, EventQueue, MidiEvent


def test_fifo_order_and_drain_empties():
    q = EventQueue()
    q.put(MidiEvent(1))
    q.put(ClearEvent())
    q.put(MidiEvent(2))
    items = q.drain()
    assert [type(i) for i in items] == [MidiEvent, ClearEvent, MidiEvent]
    assert items[0].packed == 1 and items[2].packed == 2
    assert q.drain() == []


def test_concurrent_puts_all_arrive():
    q = EventQueue()

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
