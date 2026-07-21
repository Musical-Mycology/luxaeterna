"""sACN / E1.31 output backend (UDP multicast or unicast)."""

from __future__ import annotations

import socket
import struct
import uuid

from ..constants import DMX_CHANNELS, SACN_MULTICAST_BASE, SACN_PORT
from ..exceptions import BackendError
from .base import DMXBackend

# E1.31 constants
_PREAMBLE_SIZE = 0x0010
_POSTAMBLE_SIZE = 0x0000
_ACN_PACKET_ID = b"\x00\x10\x00\x00\x41\x53\x43\x2D\x45\x31\x2E\x31\x37\x00\x00\x00"
_VECTOR_ROOT = 0x00000004
_VECTOR_FRAME = 0x00000002
_VECTOR_DMP = 0x02


class SACN(DMXBackend):
    """Send DMX frames over sACN / E1.31 (UDP port 5568).

    Parameters
    ----------
    host : str or None
        Unicast target IP address. If *None*, multicast is used.
    port : int
        UDP port (default 5568).
    source_name : str
        Human-readable source name (max 64 bytes).
    priority : int
        sACN priority (0-200, default 100).
    """

    def __init__(
        self,
        host: str | None = None,
        port: int = SACN_PORT,
        source_name: str = "LuxAeterna",
        priority: int = 100,
    ) -> None:
        self.host = host
        self.port = port
        self.source_name = source_name.encode("utf-8")[:64].ljust(64, b"\x00")
        self.priority = priority
        self._cid = uuid.uuid4().bytes  # 16-byte sender ID
        self._sock: socket.socket | None = None
        self._sequence: int = 0

    def open(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        if self.host is None:
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 20)
        self._sock.setblocking(False)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def send(self, frame: bytearray, universe_id: int = 0) -> None:
        if self._sock is None:
            raise BackendError("sACN socket not open")

        self._sequence = (self._sequence + 1) % 256
        packet = self._build_packet(frame, universe_id)
        target = self.host or self._multicast_addr(universe_id)
        try:
            self._sock.sendto(packet, (target, self.port))
        except OSError as exc:
            raise BackendError(f"sACN send failed: {exc}") from exc

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    @staticmethod
    def _multicast_addr(universe: int) -> str:
        high = (universe >> 8) & 0xFF
        low = universe & 0xFF
        return SACN_MULTICAST_BASE.format(high, low)

    def _build_packet(self, frame: bytearray, universe: int) -> bytes:
        """Build a full E1.31 Data Packet."""
        dmx_data = b"\x00" + bytes(frame)  # start code + 512 channels
        dmp_length = 10 + 1 + DMX_CHANNELS  # DMP layer
        frame_length = 77 + dmp_length       # Framing layer
        root_length = 22 + frame_length      # Root layer

        # Root layer
        root = (
            struct.pack(">HH", _PREAMBLE_SIZE, _POSTAMBLE_SIZE)
            + _ACN_PACKET_ID
            + struct.pack(">H", 0x7000 | root_length)
            + struct.pack(">I", _VECTOR_ROOT)
            + self._cid
        )

        # Framing layer
        framing = (
            struct.pack(">H", 0x7000 | frame_length)
            + struct.pack(">I", _VECTOR_FRAME)
            + self.source_name
            + bytes([self.priority])
            + struct.pack(">H", 0)  # sync address
            + bytes([self._sequence])
            + bytes([0])           # options
            + struct.pack(">H", universe)
        )

        # DMP layer
        dmp = (
            struct.pack(">H", 0x7000 | dmp_length)
            + bytes([_VECTOR_DMP])
            + bytes([0xA1])        # address & data type
            + struct.pack(">H", 0) # first property address
            + struct.pack(">H", 1) # address increment
            + struct.pack(">H", 1 + DMX_CHANNELS)  # property value count
            + dmx_data
        )

        return root + framing + dmp
