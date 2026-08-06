"""Art-Net III backend: packet construction, socket lifecycle, error paths."""

from __future__ import annotations

import socket
import struct

import pytest

from luxaeterna.backends.artnet import ArtNet
from luxaeterna.constants import (
    ARTNET_HEADER,
    ARTNET_OPCODE_DMX,
    ARTNET_PORT,
    ARTNET_PROTOCOL_VERSION,
    DMX_CHANNELS,
)
from luxaeterna.exceptions import BackendError


class FakeSocket:
    """Stands in for a UDP socket; records everything the backend does to it."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.opts: list[tuple[int, int, int]] = []
        self.blocking: bool | None = None
        self.closed = False
        self.raise_on_send: OSError | None = None

    def setsockopt(self, level, opt, value):
        self.opts.append((level, opt, value))

    def setblocking(self, flag):
        self.blocking = flag

    def sendto(self, data, addr):
        if self.raise_on_send is not None:
            raise self.raise_on_send
        self.sent.append((bytes(data), addr))

    def close(self):
        self.closed = True


@pytest.fixture
def sockets(monkeypatch):
    """Replace socket.socket with a factory recording every FakeSocket made."""
    made: list[FakeSocket] = []

    def factory(family, type_):
        assert family == socket.AF_INET
        assert type_ == socket.SOCK_DGRAM
        s = FakeSocket()
        made.append(s)
        return s

    monkeypatch.setattr(socket, "socket", factory)
    return made


def full_frame(value: int = 0) -> bytearray:
    return bytearray([value]) * DMX_CHANNELS


# --- lifecycle ---

def test_send_before_open_raises_backend_error(sockets):
    a = ArtNet()
    with pytest.raises(BackendError, match="not open"):
        a.send(full_frame())


def test_open_sets_broadcast_and_nonblocking(sockets):
    a = ArtNet()
    a.open()
    assert a.is_open is True
    s = sockets[0]
    assert (socket.SOL_SOCKET, socket.SO_BROADCAST, 1) in s.opts
    assert s.blocking is False


def test_open_is_idempotent(sockets):
    a = ArtNet()
    a.open()
    a.open()
    assert len(sockets) == 1


def test_close_is_idempotent_and_clears_is_open(sockets):
    a = ArtNet()
    a.open()
    a.close()
    a.close()
    assert a.is_open is False
    assert sockets[0].closed is True


def test_context_manager_opens_and_closes(sockets):
    with ArtNet() as a:
        assert a.is_open is True
    assert a.is_open is False


# --- packet structure ---

def test_packet_starts_with_header_opcode_and_version(sockets):
    a = ArtNet()
    a.open()
    a.send(full_frame())
    packet, _ = sockets[0].sent[0]
    assert packet[0:8] == ARTNET_HEADER
    assert struct.unpack("<H", packet[8:10])[0] == ARTNET_OPCODE_DMX
    assert struct.unpack(">H", packet[10:12])[0] == ARTNET_PROTOCOL_VERSION


def test_universe_is_little_endian_at_offset_14(sockets):
    a = ArtNet()
    a.open()
    a.send(full_frame(), universe_id=6)
    packet, _ = sockets[0].sent[0]
    assert struct.unpack("<H", packet[14:16])[0] == 6


def test_length_field_is_big_endian_and_matches_frame_length(sockets):
    a = ArtNet()
    a.open()
    a.send(full_frame())
    packet, _ = sockets[0].sent[0]
    assert struct.unpack(">H", packet[16:18])[0] == DMX_CHANNELS
    assert len(packet) == 18 + DMX_CHANNELS


def test_short_frame_length_field_tells_the_truth(sockets):
    """The defect this task fixes: the header used to claim 512 regardless."""
    a = ArtNet()
    a.open()
    a.send(bytearray(64))
    packet, _ = sockets[0].sent[0]
    assert struct.unpack(">H", packet[16:18])[0] == 64
    assert len(packet) == 18 + 64


def test_odd_length_frame_is_rejected(sockets):
    """Art-Net requires an even data length in 2..512."""
    a = ArtNet()
    a.open()
    with pytest.raises(BackendError, match="even"):
        a.send(bytearray(63))


def test_oversized_frame_is_rejected(sockets):
    a = ArtNet()
    a.open()
    with pytest.raises(BackendError, match="length"):
        a.send(bytearray(DMX_CHANNELS + 2))


def test_empty_frame_is_rejected(sockets):
    a = ArtNet()
    a.open()
    with pytest.raises(BackendError, match="length"):
        a.send(bytearray(0))


# --- sequence ---

def test_sequence_increments_per_send(sockets):
    a = ArtNet()
    a.open()
    a.send(full_frame())
    a.send(full_frame())
    first, _ = sockets[0].sent[0]
    second, _ = sockets[0].sent[1]
    assert first[12] == 1
    assert second[12] == 2


def test_sequence_wraps_at_256(sockets):
    a = ArtNet()
    a.open()
    for _ in range(255):
        a.send(full_frame())
    a.send(full_frame())
    last, _ = sockets[0].sent[-1]
    assert last[12] == 0


def test_physical_byte_is_zero(sockets):
    a = ArtNet()
    a.open()
    a.send(full_frame())
    packet, _ = sockets[0].sent[0]
    assert packet[13] == 0


# --- addressing and safety ---

def test_defaults_to_broadcast_on_artnet_port(sockets):
    a = ArtNet()
    a.open()
    a.send(full_frame())
    _, addr = sockets[0].sent[0]
    assert addr == ("255.255.255.255", ARTNET_PORT)


def test_unicast_host_is_honoured(sockets):
    a = ArtNet(host="10.0.0.42")
    a.open()
    a.send(full_frame())
    _, addr = sockets[0].sent[0]
    assert addr == ("10.0.0.42", ARTNET_PORT)


def test_send_does_not_mutate_the_caller_frame(sockets):
    a = ArtNet()
    a.open()
    frame = full_frame(7)
    a.send(frame)
    assert frame == bytearray([7]) * DMX_CHANNELS


def test_os_error_becomes_backend_error(sockets):
    a = ArtNet()
    a.open()
    sockets[0].raise_on_send = OSError("network unreachable")
    with pytest.raises(BackendError, match="send failed"):
        a.send(full_frame())
