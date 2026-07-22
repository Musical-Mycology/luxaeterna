# tests/synth/test_lifecycle_stress.py
"""The review's headline regressions: 100 bit swaps must leave exactly one
o2lite handler and zero retained graphs; concurrent producers must never
crash the render thread (the old voices-dict race)."""

from __future__ import annotations

import gc
import threading
import weakref

from fakes import FakeO2Lite
from luxaeterna.synth.capability import shroom_capability
from luxaeterna.synth.manifest import LightManifest
from luxaeterna.synth.session import LightSession
from luxaeterna.universe import Universe

MANIFEST = {
    "instruments": [{
        "instrument": "bloom", "target": "primary",
        "lanes": [{"source": "note", "dest": "trigger"}],
    }]
}


class _StepClock:
    def __init__(self, dt=0.05):
        self.t = 0.0
        self.dt = dt

    def __call__(self):
        self.t += self.dt
        return self.t


def _drive(session, uni, seconds, dt=0.05):
    for _ in range(int(seconds / dt)):
        session.render_into(uni)


def test_hundred_swaps_leave_one_handler_and_no_garbage():
    session = LightSession(shroom_capability("ie3"), clock=_StepClock())
    fake = FakeO2Lite()
    session.attach(fake)
    uni = Universe()
    refs = []

    for _ in range(100):
        session.swap(LightManifest.from_dict(MANIFEST))
        _drive(session, uni, 3.0)          # close fade + load signature + settle
        assert session.state == "running"
        refs.append(weakref.ref(session._director.bit_bindings[0]))

    assert len(fake.handlers) == 1          # attach-once held across 100 bits

    session.clear()
    _drive(session, uni, 2.0)
    assert session.state == "idle"
    gc.collect()
    assert all(r() is None for r in refs)   # every bit's graph was collected


def test_threaded_producers_never_crash_render():
    session = LightSession(shroom_capability("ie3"), clock=_StepClock(dt=0.01))
    uni = Universe()
    session.swap(LightManifest.from_dict(MANIFEST))
    _drive(session, uni, 3.0, dt=0.01)
    assert session.state == "running"

    stop = threading.Event()

    def hammer_midi():
        for i in range(5000):
            if stop.is_set():
                return
            session._bridge.on_midi((0x90 << 16) | ((60 + i % 12) << 8) | 100)
            session._bridge.on_midi((0x80 << 16) | ((60 + i % 12) << 8) | 0)

    def hammer_swaps():
        for _ in range(500):
            if stop.is_set():
                return
            session.swap(LightManifest.from_dict(MANIFEST))

    threads = [threading.Thread(target=hammer_midi),
               threading.Thread(target=hammer_swaps)]
    for th in threads:
        th.start()
    try:
        for _ in range(500):
            session.render_into(uni)        # a raise here fails the test
    finally:
        stop.set()
        for th in threads:
            th.join(timeout=2)
