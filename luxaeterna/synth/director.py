"""Lux Aeterna — StatusDirector: the session state machine.

Decides which state the session is in, which status signature is playing, and
what binding list + global gain the engine should render each frame. All
methods run on the render thread (called by LightSession at drain time)."""

from __future__ import annotations

import logging

from ..logutil import ThrottledLog
from . import registry
from .binding import ActiveBinding, resolve
from .capability import SurfaceCapability
from .manifest import LightManifest
from .status import Signature

log = logging.getLogger(__name__)
_throttle = ThrottledLog(log)

IDLE = "idle"
LOADING = "loading"
RUNNING = "running"
CLOSING = "closing"
ERROR = "error"
DISCONNECTED = "disconnected"
SELFTEST = "selftest"

QUARANTINE_FRAMES = 44          # ~1 s of consecutive failures at 44 Hz


class StatusDirector:
    def __init__(self, cap: SurfaceCapability) -> None:
        self.cap = cap
        self.state = IDLE
        self.bit_bindings: list[ActiveBinding] = []
        self.bit_name = ""
        self.role = ""
        self.pending: LightManifest | None = None
        self._signature: Signature | None = None
        self._sig_binding: ActiveBinding | None = None
        self._overlay: Signature | None = None
        self._overlay_binding: ActiveBinding | None = None
        self._prior = IDLE                    # state to restore after SELFTEST
        self._fails: dict[int, int] = {}
        self._enter_idle()

    # -- internals ----------------------------------------------------------

    def _wrap(self, sig: Signature) -> ActiveBinding:
        return ActiveBinding(obj=sig, zone=self.cap.zone("primary"),
                             blend="add", routes={})

    def _set_signature(self, sig: Signature | None) -> None:
        self._signature = sig
        self._sig_binding = self._wrap(sig) if sig is not None and sig.renders else None

    def _drop_bit(self) -> None:
        self.bit_bindings = []
        self._fails = {}
        self.bit_name = ""
        self.role = ""

    def _enter_idle(self) -> None:
        self.state = IDLE
        self._set_signature(registry.build("sys:idle"))

    def _enter_error(self) -> None:
        self._drop_bit()
        self.state = ERROR
        self._set_signature(registry.build("sys:error"))

    def _enter_closing(self) -> None:
        for b in self.bit_bindings:
            stop = getattr(b.obj, "all_notes_off", None)
            if stop is not None:
                stop()
        self.state = CLOSING
        self._set_signature(registry.build("sys:closing"))

    def _resolve_and_load(self, manifest: LightManifest) -> None:
        try:
            bindings = [resolve(d, self.cap) for d in manifest.instruments]
        except Exception as exc:
            log.warning("manifest resolve failed (bit=%r role=%r): %s",
                        manifest.bit_name, manifest.role, exc)
            self._enter_error()
            return
        self.bit_bindings = bindings
        self._fails = {}
        self.bit_name = manifest.bit_name
        self.role = manifest.role
        self.state = LOADING
        w = manifest.welcome
        if w is not None:
            self._set_signature(
                Signature(registry.build(w.instrument, **w.params), w.duration))
        else:
            self._set_signature(registry.build("sys:loaded"))

    # -- event handlers (drain time) ----------------------------------------

    def swap(self, manifest: LightManifest) -> None:
        if self.state == RUNNING:
            self.pending = manifest
            self._enter_closing()
        elif self.state in (IDLE, LOADING):
            self._drop_bit()
            self._resolve_and_load(manifest)
        else:                       # CLOSING/ERROR/DISCONNECTED/SELFTEST: latest wins
            self.pending = manifest

    def clear(self) -> None:
        self.pending = None
        if self.state == RUNNING:
            self._enter_closing()
        elif self.state == LOADING:
            self._drop_bit()
            self._enter_idle()

    def error(self, reason: str = "") -> None:
        if reason:
            log.warning("session error (bit=%r role=%r): %s",
                        self.bit_name, self.role, reason)
        self._enter_error()

    def disconnect(self) -> None:
        self._drop_bit()
        self.state = DISCONNECTED
        self._set_signature(registry.build("sys:disconnected"))

    def reconnect(self) -> None:
        if self.state != DISCONNECTED:
            return
        if self.pending is not None:
            manifest, self.pending = self.pending, None
            self._resolve_and_load(manifest)
        else:
            self._enter_idle()

    def identify(self, duration: float = 3.0) -> None:
        sig = registry.build("sys:identify")
        sig.duration = float(duration)
        self._overlay = sig
        self._overlay_binding = self._wrap(sig)

    def selftest(self) -> None:
        if self.state not in (IDLE, DISCONNECTED):
            _throttle.log("selftest-ignored", logging.INFO,
                          "selftest ignored in state %s", self.state)
            return
        self._prior = self.state
        self.state = SELFTEST
        self._set_signature(registry.build("sys:selftest"))

    # -- per-frame ----------------------------------------------------------

    def frame(self, dt: float) -> tuple[list[ActiveBinding], float]:
        if self._overlay is not None:
            self._overlay.advance(dt)
            if self._overlay.done:
                self._overlay = None
                self._overlay_binding = None
        gain = 1.0
        if self._signature is not None:
            self._signature.advance(dt)
            gain = self._signature.gain
            if self._signature.done:
                self._on_signature_done()
                gain = self._signature.gain if self._signature is not None else 1.0

        render: list[ActiveBinding] = []
        if self.state in (RUNNING, CLOSING):
            render.extend(self.bit_bindings)
        if self._sig_binding is not None:
            render.append(self._sig_binding)
        if self._overlay_binding is not None:
            render.append(self._overlay_binding)
        return render, gain

    def _on_signature_done(self) -> None:
        if self.state == LOADING:
            self.state = RUNNING
            self._set_signature(None)
        elif self.state in (CLOSING, ERROR):
            if self.state == CLOSING:
                self._drop_bit()
            if self.pending is not None:
                manifest, self.pending = self.pending, None
                self._resolve_and_load(manifest)
            else:
                self._enter_idle()
        elif self.state == SELFTEST:
            if self._prior == DISCONNECTED:
                self.state = DISCONNECTED
                self._set_signature(registry.build("sys:disconnected"))
            else:
                self._enter_idle()

    def note_failures(self, failed: list) -> None:
        failed_ids = {id(b) for b in failed}
        for b in list(self.bit_bindings):
            if id(b) in failed_ids:
                n = self._fails.get(id(b), 0) + 1
                self._fails[id(b)] = n
                if n >= QUARANTINE_FRAMES:
                    self.bit_bindings.remove(b)
                    self._fails.pop(id(b), None)
                    _throttle.log(f"quarantine:{id(b)}", logging.ERROR,
                                  "binding quarantined (bit=%r role=%r)",
                                  self.bit_name, self.role)
            else:
                self._fails.pop(id(b), None)
        if self.state == RUNNING and not self.bit_bindings:
            self.error("all bindings quarantined")
