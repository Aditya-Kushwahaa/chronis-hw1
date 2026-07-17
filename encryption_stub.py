"""
Stand-in for HW-2's encryption daemon.

HW Track 1 doesn't own encryption -- HW-2 does. But Camera and Audio daemons
need something real to hand frames/chunks off to so their write paths are
already Rule-1-compliant (accepting ONLY EncryptedPayload) before HW-2's
actual daemon exists. This stub has the exact interface the real daemon will
expose (`encrypt(raw_bytes, source_daemon, record_type) -> EncryptedPayload`)
so swapping it out later is a one-line change, not a rewrite.

The "encryption" here is intentionally trivial (XOR with a fixed key) --
it exists to prove the handoff contract, not to provide real security.
"""

from __future__ import annotations

from interfaces import EncryptedPayload

_FAKE_KEY = 0x5A


def _xor(data: bytes, key: int = _FAKE_KEY) -> bytes:
    return bytes(b ^ key for b in data)


class EncryptionDaemonStub:
    """Mimics the HW-2 encryption daemon's handoff interface."""

    def encrypt(self, raw_bytes: bytes, source_daemon: str, record_type: str) -> EncryptedPayload:
        if not isinstance(raw_bytes, (bytes, bytearray)):
            raise TypeError("EncryptionDaemonStub.encrypt() expects raw bytes as input")
        return EncryptedPayload(
            ciphertext=_xor(bytes(raw_bytes)),
            source_daemon=source_daemon,
            record_type=record_type,
        )

    def decrypt(self, payload: EncryptedPayload) -> bytes:
        """Only used by tests / calibration tooling, never by daemons."""
        return _xor(payload.ciphertext)
