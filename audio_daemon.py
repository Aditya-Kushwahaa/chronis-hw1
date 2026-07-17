"""
Audio Daemon.

Captures mock audio chunks, timestamps them, and hands off to the
encryption daemon exactly like the Camera Daemon (Rule 1). Supports the
five capture modes the state machine assigns per level:

    8kHz buffer-only, 8kHz saved, 16kHz continuous,
    16kHz full quality, 48kHz lossless
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Union

from interfaces import AppendOnlyStore, EncryptedPayload, SensorUnavailable, is_available
from encryption_stub import EncryptionDaemonStub
from mock_hal import MockMicrophone


class AudioMode(str, Enum):
    HZ8_BUFFER_ONLY = "8khz_buffer_only"   # L0: ring buffer, not persisted
    HZ8_SAVED = "8khz_saved"               # L1
    HZ16_CONTINUOUS = "16khz_continuous"   # L2
    HZ16_FULL = "16khz_full"               # L3: + speaker separation
    HZ48_LOSSLESS = "48khz_lossless"       # L5


class AudioDaemon:
    def __init__(self, microphone: MockMicrophone, encryption_daemon: EncryptionDaemonStub, store: AppendOnlyStore) -> None:
        self._microphone = microphone
        self._encryption_daemon = encryption_daemon
        self._store = store
        self.mode = AudioMode.HZ8_SAVED

    def set_mode(self, mode: AudioMode) -> None:
        self.mode = mode

    def capture_and_store(self, timestamp: float) -> Union[EncryptedPayload, SensorUnavailable, None]:
        chunk = self._microphone.audio_chunk()
        if not is_available(chunk):
            return chunk  # Rule 3: propagate, nothing gets written

        if self.mode == AudioMode.HZ8_BUFFER_ONLY:
            # Ring-buffer-only mode never persists to the canonical store,
            # by design (this is what L0 / not-worn falls back to).
            return None

        raw = json.dumps({"timestamp": timestamp, "mode": self.mode.value, "chunk": chunk}).encode("utf-8")
        payload = self._encryption_daemon.encrypt(raw, source_daemon="audio", record_type=f"audio:{self.mode.value}")

        # Rule 1: only write path, only accepts EncryptedPayload.
        self._store.write(payload)
        return payload
