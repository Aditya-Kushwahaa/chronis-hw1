"""
Shared interfaces and types for HW Track 1.

These types are the enforcement mechanism for the sprint's non-negotiable rules:

  Rule 1: Storage-write functions accept ONLY EncryptedPayload, never raw bytes.
  Rule 2: The canonical record store is append-only. No overwrites, no edits.
  Rule 3: An unavailable sensor returns SensorUnavailable, never a fake zero.
  Rule 4: Daemons talk to each other only through the interfaces defined here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Union


# ---------------------------------------------------------------------------
# Rule 3: explicit "unavailable" sentinel
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SensorUnavailable:
    """
    Explicit sentinel returned instead of a reading when a sensor cannot
    produce a value. Never substitute a zero, None, or NaN for this --
    every consumer must handle this type explicitly.
    """
    sensor_name: str
    reason: str = "unavailable"

    def __repr__(self) -> str:
        return f"SensorUnavailable(sensor={self.sensor_name!r}, reason={self.reason!r})"


# A reading is either a real value or an explicit unavailable marker.
Reading = Union[float, tuple, SensorUnavailable]


def is_available(reading: Reading) -> bool:
    """Type-guard helper: True if `reading` is a real value, not SensorUnavailable."""
    return not isinstance(reading, SensorUnavailable)


# ---------------------------------------------------------------------------
# Rule 1: only encrypted payloads may reach storage
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EncryptedPayload:
    """
    Opaque, encrypted blob produced by the HW-2 encryption daemon.
    This is the ONLY type the storage-write function will accept.

    In this simulation-first repo, HW-2's real encryption daemon doesn't
    exist yet, so `encryption_stub.py` provides a stand-in that produces
    real EncryptedPayload objects with a clearly-fake "encryption" scheme.
    This keeps every daemon's write path already Rule-1-compliant, so
    swapping in the real HW-2 daemon later requires no daemon code changes.
    """
    ciphertext: bytes
    source_daemon: str
    record_type: str
    written_at: float = field(default_factory=time.time)


class RawBytesRejected(TypeError):
    """Raised when something tries to push raw (non-encrypted) data to storage."""


class AppendOnlyStore:
    """
    Rule 1 + Rule 2 enforcement point.

    * write() only accepts EncryptedPayload -- passing anything else raises
      RawBytesRejected immediately (Rule 1).
    * There is deliberately NO update() or delete() method of any kind, and
      the internal list is name-mangled so daemons cannot reach in and
      mutate history directly (Rule 2 + Rule 4).
    """

    def __init__(self) -> None:
        self.__records: List[EncryptedPayload] = []

    def write(self, payload: EncryptedPayload) -> None:
        if not isinstance(payload, EncryptedPayload):
            raise RawBytesRejected(
                f"AppendOnlyStore.write() only accepts EncryptedPayload, "
                f"got {type(payload).__name__}. Raw data must never reach storage (Rule 1)."
            )
        self.__records.append(payload)

    def read_all(self) -> List[EncryptedPayload]:
        """Read-only snapshot. Returns a copy so callers can't mutate history."""
        return list(self.__records)

    def __len__(self) -> int:
        return len(self.__records)


# ---------------------------------------------------------------------------
# Rule 4: capture-level control surface
#
# The state machine is the ONLY thing allowed to change capture level.
# Everything else (notably the Anchor Gesture Detector) is given a
# READ-ONLY view of the current level, never a setter, so it is
# structurally impossible for it to change capture behavior.
# ---------------------------------------------------------------------------

class CaptureLevelReadPort:
    """Read-only view of the current capture level, safe to hand to any daemon."""

    def __init__(self, get_level: Callable[[], Any]) -> None:
        self._get_level = get_level

    def current_level(self) -> Any:
        return self._get_level()
