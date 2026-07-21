"""ENTTEC USB-to-DMX backends (Open DMX and DMX USB Pro)."""

from __future__ import annotations

import struct
import time

from ..constants import (
    DMX_CHANNELS,
    DMX_START_CODE,
    ENTTEC_BAUDRATE,
    ENTTEC_PRO_DMX_LABEL,
    ENTTEC_PRO_END,
    ENTTEC_PRO_START,
)
from ..exceptions import BackendError
from .base import DMXBackend

try:
    import serial  # pyserial
except ImportError:
    serial = None  # type: ignore[assignment]


class ENTTECOpen(DMXBackend):
    """ENTTEC Open DMX USB (FTDI bit-bang, no framing protocol).

    Requires ``pyserial`` (``pip install pyserial``).

    Parameters
    ----------
    port : str
        Serial port path, e.g. ``"/dev/ttyUSB0"`` or ``"COM3"``.
    """

    def __init__(self, port: str = "/dev/ttyUSB0") -> None:
        if serial is None:
            raise ImportError("pyserial is required for ENTTEC backends: pip install pyserial")
        self.port = port
        self._serial: serial.Serial | None = None  # type: ignore[name-defined]

    def open(self) -> None:
        if self._serial is not None:
            return
        self._serial = serial.Serial(  # type: ignore[attr-defined]
            port=self.port,
            baudrate=ENTTEC_BAUDRATE,
            bytesize=serial.EIGHTBITS,  # type: ignore[attr-defined]
            stopbits=serial.STOPBITS_TWO,  # type: ignore[attr-defined]
            parity=serial.PARITY_NONE,  # type: ignore[attr-defined]
        )

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def send(self, frame: bytearray, universe_id: int = 0) -> None:
        if self._serial is None:
            raise BackendError("Serial port not open")
        try:
            # DMX break: drop line low for ≥88µs
            self._serial.break_condition = True
            time.sleep(0.000092)
            self._serial.break_condition = False
            time.sleep(0.000012)  # MAB (Mark After Break)

            # Start code + 512 channel values
            self._serial.write(bytes([DMX_START_CODE]) + bytes(frame))
        except OSError as exc:
            raise BackendError(f"ENTTEC Open send failed: {exc}") from exc

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open


class ENTTECPro(DMXBackend):
    """ENTTEC DMX USB Pro (message-framed protocol).

    Requires ``pyserial`` (``pip install pyserial``).

    Parameters
    ----------
    port : str
        Serial port path.
    """

    def __init__(self, port: str = "/dev/ttyUSB0") -> None:
        if serial is None:
            raise ImportError("pyserial is required for ENTTEC backends: pip install pyserial")
        self.port = port
        self._serial: serial.Serial | None = None  # type: ignore[name-defined]

    def open(self) -> None:
        if self._serial is not None:
            return
        self._serial = serial.Serial(  # type: ignore[attr-defined]
            port=self.port,
            baudrate=ENTTEC_BAUDRATE,
        )

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def send(self, frame: bytearray, universe_id: int = 0) -> None:
        if self._serial is None:
            raise BackendError("Serial port not open")
        try:
            # Pro protocol: [START][LABEL][LEN_LO][LEN_HI][START_CODE + DATA][END]
            data = bytes([DMX_START_CODE]) + bytes(frame)
            length = len(data)
            packet = (
                bytes([ENTTEC_PRO_START, ENTTEC_PRO_DMX_LABEL])
                + struct.pack("<H", length)
                + data
                + bytes([ENTTEC_PRO_END])
            )
            self._serial.write(packet)
        except OSError as exc:
            raise BackendError(f"ENTTEC Pro send failed: {exc}") from exc

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open
