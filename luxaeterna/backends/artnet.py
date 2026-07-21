"""Art-Net III output backend (UDP broadcast/unicast)."""

from __future__ import annotations

import socket
import struct

from ..constants import ARTNET_HEADER, ARTNET_OPCODE_DMX, ARTNET_PORT, ARTNET_PROTOCOL_VERSION, DMX_CHANNELS
from ..exceptions import BackendError
from .base import DMXBackend


class ArtNet(DMXBackend):
    """Send DMX frames over Art-Net III (UDP port 6454).

    Parameters
    ----------
    host : str
        Target IP. Use ``"255.255.255.255"`` for broadcast or a
        specific node IP for unicast.
    port : int
        UDP port (default 6454).
    """

    def __init__(self, host: str = "255.255.255.255", port: int = ARTNET_PORT) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._sequence: int = 0

    def open(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.setblocking(False)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def send(self, frame: bytearray, universe_id: int = 0) -> None:
        if self._sock is None:
            raise BackendError("Art-Net socket not open")

        self._sequence = (self._sequence + 1) % 256
        packet = self._build_packet(frame, universe_id)
        try:
            self._sock.sendto(packet, (self.host, self.port))
        except OSError as exc:
            raise BackendError(f"Art-Net send failed: {exc}") from exc

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def _build_packet(self, frame: bytearray, universe: int) -> bytes:
        """Construct an ArtDmx packet (opcode 0x5000)."""
        return (
            ARTNET_HEADER
            + struct.pack("<H", ARTNET_OPCODE_DMX)
            + struct.pack(">H", ARTNET_PROTOCOL_VERSION)
            + bytes([self._sequence, 0])          # sequence, physical
            + struct.pack("<H", universe)          # universe (low byte first)
            + struct.pack(">H", DMX_CHANNELS)     # length (high byte first)
            + bytes(frame)
        )
