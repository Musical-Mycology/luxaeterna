"""The websim demo wires a canned bloom manifest into the full render pipeline."""

from __future__ import annotations

import time

from luxaeterna import websim_demo


def test_build_demo_constructs_running_pipeline():
    loop, session = websim_demo.build_demo(serve=False)
    uni = loop.universe
    # build_demo lets the session clock default to time.monotonic (real time),
    # so the 1.5s welcome signature takes real wall-clock time to complete;
    # loop._loop_once() has no sleep of its own, so poll against a real
    # deadline rather than a fixed iteration count.
    deadline = time.monotonic() + 5.0
    while session.state != "running" and time.monotonic() < deadline:
        loop._loop_once()
    assert session.state == "running"
    session.feed_midi(0x90, 60, 100)               # note-on via the demo seam
    time.sleep(0.01)   # let real wall-clock time pass so the bloom's attack
                        # envelope (real-clock dt) has a nonzero level to render
    loop._loop_once()
    assert max(uni.get_frame()[:36]) > 0
