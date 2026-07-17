"""
Camera Daemon.

Captures mock frames, timestamps them, and hands them off to the
encryption daemon (HW-2 in production, encryption_stub here) BEFORE any
disk write. The storage-write path only ever touches EncryptedPayload
(Rule 1) -- there is no method on this class that writes raw frame bytes
anywhere.
"""

from __future__ import annotations

import json
from typing import Union

from interfaces import AppendOnlyStore, EncryptedPayload, SensorUnavailable, is_available
from encryption_stub import EncryptionDaemonStub
from mock_hal import MockCamera


class CameraDaemon:
    def __init__(self, camera: MockCamera, encryption_daemon: EncryptionDaemonStub, store: AppendOnlyStore) -> None:
        self._camera = camera
        self._encryption_daemon = encryption_daemon
        self._store = store  # AppendOnlyStore.write() rejects anything but EncryptedPayload

    def capture_and_store(self, timestamp: float) -> Union[EncryptedPayload, SensorUnavailable]:
        frame = self._camera.camera_frame()
        if not is_available(frame):
            return frame  # Rule 3: propagate, nothing gets written

        raw = json.dumps({"timestamp": timestamp, "frame": frame}).encode("utf-8")
        payload = self._encryption_daemon.encrypt(raw, source_daemon="camera", record_type="frame")

        # Rule 1: this is the ONLY write path, and it only accepts EncryptedPayload.
        # There is deliberately no other method anywhere on this class that
        # writes frame data to storage -- see tests/test_rule1_enforcement.py.
        self._store.write(payload)
        return payload
