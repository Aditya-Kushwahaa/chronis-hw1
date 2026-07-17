"""
Extended Simulated Run (Day 4 deliverable).

Chains all four synthetic scenario traces back-to-back through the full
daemon stack: Motion Daemon, Heart Rate Daemon, Anchor Gesture Detector,
Camera Daemon, Audio Daemon, Worn Detector, and the Capture State Machine.

Logs every capture-level transition with its exact triggering cause to a
JSONL run log clean enough to double as stand-in session data for later
calibration work. Verifies (via run_extended_simulation()'s return value
and the accompanying tests): zero crashes, hysteresis respected, and
SensorUnavailable propagated correctly rather than faked (Rule 3).
"""

from __future__ import annotations

import json
import os
from typing import List

from interfaces import AppendOnlyStore, SensorUnavailable, is_available
from mock_hal import MockCamera, MockMicrophone
from motion_daemon import MotionDaemon, MotionState
from heart_rate_daemon import HeartRateDaemon
from anchor_gesture import AnchorGestureDetector
from encryption_stub import EncryptionDaemonStub
from camera_daemon import CameraDaemon
from audio_daemon import AudioDaemon, AudioMode
from worn_detector import WornDetector
from state_machine import CaptureStateMachine
from trace_generator import load_trace_json, write_traces

TRACE_ORDER = ["idle_dormant", "ambient_alone", "active_conversation", "multi_party"]


def _orientation_variance_signal(motion_out: dict) -> float:
    """
    Cheap proxy for "orientation variance" fed to the Worn Detector: uses
    the instantaneous |pitch| + |roll| from this tick's orientation reading.
    A production implementation would track a proper rolling variance; this
    is enough to drive realistic worn/not-worn behavior in simulation.
    """
    orientation = motion_out["orientation"]
    if not is_available(orientation):
        return 0.0
    return abs(orientation.pitch) + abs(orientation.roll)


def run_extended_simulation(traces_dir: str, log_path: str) -> dict:
    motion_daemon = MotionDaemon()
    hr_daemon = HeartRateDaemon()
    anchor_detector = AnchorGestureDetector()
    encryption_daemon = EncryptionDaemonStub()
    store = AppendOnlyStore()
    camera_daemon = CameraDaemon(
        MockCamera(value_fn=lambda i: {"synthetic": True, "frame_index": i}),
        encryption_daemon,
        store,
    )
    audio_daemon = AudioDaemon(
        MockMicrophone(value_fn=lambda i: {"synthetic": True, "chunk_index": i}),
        encryption_daemon,
        store,
    )
    worn_detector = WornDetector()
    state_machine = CaptureStateMachine()

    run_log: List[dict] = []
    crash_count = 0
    global_elapsed = 0.0

    for scenario_name in TRACE_ORDER:
        path = os.path.join(traces_dir, f"synthetic_{scenario_name}.json")
        records = load_trace_json(path)
        global_ts = global_elapsed

        for rec in records:
            global_ts = round(global_elapsed + rec.timestamp, 3)
            try:
                accel = tuple(rec.accel_xyz)
                gyro = tuple(rec.gyro_xyz)
                motion_out = motion_daemon.process(global_ts, accel, gyro)

                hr_input = (
                    SensorUnavailable("heart_rate", "trace_dropout")
                    if rec.heart_rate_unavailable
                    else rec.heart_rate
                )
                hr_out = hr_daemon.process(hr_input)
                hr_quality = hr_out.quality if is_available(hr_out) else 0.0

                if motion_out["double_tap"]:
                    anchor_detector.on_double_tap(global_ts, note=f"double_tap_during_{scenario_name}")

                gesture_energy = (
                    motion_out["gesture_energy"] if is_available(motion_out["gesture_energy"]) else 0.0
                )
                motion_state = (
                    motion_out["motion_state"] if is_available(motion_out["motion_state"]) else MotionState.STILL
                )
                orientation_variance = _orientation_variance_signal(motion_out)

                worn_event = worn_detector.update(
                    timestamp=global_ts,
                    hr_quality=hr_quality,
                    orientation_variance=orientation_variance,
                    accel_gesture_energy=gesture_energy,
                )

                transition = state_machine.update(
                    timestamp=global_ts,
                    worn_state=worn_event.state,
                    motion_state=motion_state,
                    gesture_energy=gesture_energy,
                    audio_energy=rec.audio_energy,
                    voice_count=rec.voice_count,
                )

                settings = state_machine.current_settings()
                audio_mode = settings["audio_mode"]
                if isinstance(audio_mode, AudioMode):
                    audio_daemon.set_mode(audio_mode)
                    if audio_mode != AudioMode.HZ8_BUFFER_ONLY:
                        audio_daemon.capture_and_store(global_ts)
                else:
                    # L4's "dual_boosted" isn't a literal AudioMode enum value
                    # (see audio_daemon.py); still exercise a capture on the
                    # richest defined mode so the daemon path is covered.
                    audio_daemon.set_mode(AudioMode.HZ16_FULL)
                    audio_daemon.capture_and_store(global_ts)

                if settings["camera_fps"] not in (0,):
                    camera_daemon.capture_and_store(global_ts)

                if transition is not None:
                    run_log.append(
                        {
                            "timestamp": transition.timestamp,
                            "scenario": scenario_name,
                            "from_level": transition.from_level.name,
                            "to_level": transition.to_level.name,
                            "cause": transition.cause,
                        }
                    )
            except Exception as exc:  # extended run must never crash silently
                crash_count += 1
                run_log.append({"timestamp": global_ts, "scenario": scenario_name, "error": repr(exc)})

        global_elapsed = global_ts + 0.5  # advance past this scenario's duration

    with open(log_path, "w") as f:
        for entry in run_log:
            f.write(json.dumps(entry) + "\n")

    return {
        "transitions_logged": sum(1 for e in run_log if "cause" in e),
        "crashes": crash_count,
        "final_level": state_machine.level.name,
        "annotations_created": len(anchor_detector.annotations),
        "store_size": len(store),
        "log_path": log_path,
    }


if __name__ == "__main__":
    here = os.path.dirname(__file__)
    traces_dir = os.path.join(here, "traces")
    write_traces(traces_dir)  # regenerate so this script is standalone-runnable
    summary = run_extended_simulation(traces_dir, os.path.join(here, "extended_run.log.jsonl"))
    print(json.dumps(summary, indent=2))
