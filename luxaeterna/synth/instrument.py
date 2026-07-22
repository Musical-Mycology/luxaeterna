"""Lux Aeterna — Instrument/Synth layer (client-side composition, mirroring
pyarco's arco_instr.py)."""

from __future__ import annotations

import numpy as np

from .signal import LightUgen, RenderContext


class Param:
    """A named, settable binding backed by a Const/Smooth control uGen."""

    __slots__ = ("name", "ugen")

    def __init__(self, name: str, ugen) -> None:
        self.name = name
        self.ugen = ugen

    def set(self, value) -> None:
        self.ugen.set_target(value)


class LightInstrument:
    """A graph with a designated output field-uGen and named params."""

    def __init__(self, output: LightUgen, params: dict[str, Param]) -> None:
        self.output = output
        self.params = params

    def set(self, name: str, value) -> None:
        if name not in self.params:
            raise KeyError(f"no param {name!r} on instrument")
        self.params[name].set(value)

    def param_names(self) -> set[str]:
        """Known param names — the dests a cc lane may target via .set()."""
        return set(self.params)

    def render(self, ctx: RenderContext) -> np.ndarray:
        return self.output.render(ctx)


class LightSynth:
    """A voice pool: note-on spawns a transient voice instrument, additively
    composited and pruned when its envelope finishes (Arco Synth analog)."""

    def __init__(self, voice_factory, max_voices: int = 8, shared: dict | None = None) -> None:
        self.voice_factory = voice_factory
        self.max_voices = max_voices
        self.shared = shared if shared is not None else {}
        self.voices: dict = {}       # note_id -> (LightInstrument, Envelope)
        self._auto = 0

    def noteon(self, pitch: int, vel: float, note_id=None):
        if note_id is None:
            note_id = ("auto", self._auto)
            self._auto += 1
        self.voices.pop(note_id, None)                     # re-trigger: remove stale entry so re-insert lands newest
        if len(self.voices) >= self.max_voices:
            self.voices.pop(next(iter(self.voices)))       # drop oldest
        inst, env = self.voice_factory(pitch, vel, self.shared)
        env.gate_on()
        self.voices[note_id] = (inst, env)
        return note_id

    def noteoff(self, note_id):
        v = self.voices.get(note_id)
        if v is not None:
            v[1].gate_off()

    def all_notes_off(self) -> None:
        """Gate off every active voice (releases play out, then prune)."""
        for _inst, env in self.voices.values():
            env.gate_off()

    def set(self, name: str, value) -> None:
        # The initial ``shared`` dict declares the known params; reject typos so
        # a bad manifest lane fails loudly instead of silently writing garbage
        # (mirrors LightInstrument.set's strictness against self.params).
        if name not in self.shared:
            raise KeyError(
                f"no shared param {name!r} on synth (known: {sorted(self.shared)})")
        self.shared[name] = value

    def param_names(self) -> set[str]:
        """Known param names — the declared shared-param keys a cc lane may target."""
        return set(self.shared)

    def render(self, ctx: RenderContext) -> np.ndarray:
        out = np.zeros((ctx.n, ctx.channels))
        finished = []
        for note_id, (inst, env) in self.voices.items():
            out = out + inst.render(ctx)
            if env.done:
                finished.append(note_id)
        for note_id in finished:
            del self.voices[note_id]
        return np.clip(out, 0.0, 1.0)
