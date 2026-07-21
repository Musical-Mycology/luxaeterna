"""Abstract base for DMX output backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class DMXBackend(ABC):
    """Interface that every output backend must implement.

    Backends are intentionally synchronous — the output loop already
    runs on its own thread, so blocking I/O here is fine and avoids
    the overhead of an async event-loop per backend.
    """

    @abstractmethod
    def open(self) -> None:
        """Establish the underlying connection (serial port, socket, …)."""

    @abstractmethod
    def close(self) -> None:
        """Release resources. Safe to call multiple times."""

    @abstractmethod
    def send(self, frame: bytearray, universe_id: int = 0) -> None:
        """Transmit a 512-byte DMX frame.

        Implementations may prepend protocol headers, but must not
        mutate *frame*.
        """

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Return True if the backend is ready to send."""

    # --- context manager support ---

    def __enter__(self) -> DMXBackend:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
