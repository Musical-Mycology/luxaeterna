"""python -m luxaeterna.websim_demo — watch a canned bloom manifest render to
the Web LED simulator. Requires the 'websim' extra:  pip install luxaeterna[websim]
Then open the printed URL and watch the Shroom bloom and sweep hue."""

from __future__ import annotations

import time

from .backends.websim import WebSimBackend
from .output import OutputLoop
from .synth.capability import shroom_capability
from .synth.manifest import LightManifest
from .synth.session import build_session
from .universe import Universe

_MANIFEST = {
    "instruments": [{
        "instrument": "bloom", "target": "primary", "params": {"hue": 1.0 / 3.0},
        "lanes": [{"source": "note", "dest": "trigger"},
                  {"source": "cc:74", "dest": "hue"}],
    }],
    "welcome": {"instrument": "bloom", "params": {"hue": 1.0 / 3.0}, "duration": 1.5},
}


def build_demo(host: str = "127.0.0.1", port: int = 8770, serve: bool = True):
    """Construct the pipeline without starting the loop. Returns (loop, session)."""
    cap = shroom_capability()
    session = build_session(LightManifest.from_dict(_MANIFEST), cap)
    uni = Universe()
    backend = WebSimBackend(capability=cap, host=host, port=port, serve=serve)
    loop = OutputLoop(uni, backend, on_frame=session.render_into, always_send=True)
    return loop, session


def main() -> None:
    loop, session = build_demo()
    loop.start()
    print(f"Watch the Shroom at http://127.0.0.1:{loop.backend.port}/  (Ctrl-C to stop)")
    try:
        while session.state != "running":
            time.sleep(0.02)
        cc = 0
        while True:
            session.feed_midi(0xB0, 74, cc)          # cc:74 -> hue
            session.feed_midi(0x90, 60, 100)         # new voice at current hue
            cc = (cc + 8) % 128
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    finally:
        loop.stop()


if __name__ == "__main__":
    main()
