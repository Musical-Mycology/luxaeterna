"""ENTTEC backends must open pyserial with a write timeout so a wedged USB
device cannot block the output thread indefinitely."""

from __future__ import annotations

import types

from luxaeterna.backends import serial_enttec


def _fake_serial_module(calls):
    class _FakeSerial:
        def __init__(self, **kwargs):
            calls.update(kwargs)
            self.is_open = True

        def close(self):
            pass

    return types.SimpleNamespace(Serial=_FakeSerial, EIGHTBITS=8,
                                 STOPBITS_TWO=2, PARITY_NONE="N")


def test_enttec_open_sets_write_timeout(monkeypatch):
    calls = {}
    monkeypatch.setattr(serial_enttec, "serial", _fake_serial_module(calls))
    b = serial_enttec.ENTTECOpen("/dev/fake")
    b.open()
    assert calls["write_timeout"] == 0.05


def test_enttec_pro_sets_write_timeout(monkeypatch):
    calls = {}
    monkeypatch.setattr(serial_enttec, "serial", _fake_serial_module(calls))
    b = serial_enttec.ENTTECPro("/dev/fake", write_timeout=0.1)
    b.open()
    assert calls["write_timeout"] == 0.1
