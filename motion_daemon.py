"""
Motion Daemon.

Owns everything derived from accelerometer + gyroscope:
  - orientation filter (complementary filter -> pitch/roll/yaw)
  - motion-state classifier (still / walking / active)
  - posture classifier (lying down / upright)
  - gesture-energy score (windowed RMS of acceleration)
  - change-point detection (sudden shift in motion pattern)
  - double-tap detection (two accel spikes within 300ms)

Consumes SensorUnavailable-aware readings (Rule 3): any classifier fed an
unavailable input returns SensorUnavailable itself rather than guessing.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, List, Optional, Tuple, Union

from interfaces import SensorUnavailable, is_available

Vec3 = Tuple[float, float, float]


class MotionState(str, Enum):
    STILL = "still"
    WALKING = "walking"
    ACTIVE = "active"


class Posture(str, Enum):
    LYING_DOWN = "lying_down"
    UPRIGHT = "upright"


# ---------------------------------------------------------------------------
# Orientation filter: complementary filter fusing accel + gyro
# ---------------------------------------------------------------------------

@dataclass
class Orientation:
    pitch: float  # degrees
    roll: float   # degrees
    yaw: float    # degrees


class OrientationFilter:
    """
    Complementary filter: trusts the gyro's integrated angle for fast
    changes, and slowly corrects drift using the accelerometer's gravity
    vector (which is only reliable when the device isn't accelerating hard).
    """

    def __init__(self, alpha: float = 0.98, dt: float = 0.5) -> None:
        self.alpha = alpha
        self.dt = dt
        self._pitch = 0.0
        self._roll = 0.0
        self._yaw = 0.0  # gyro-only; accel can't observe yaw

    def update(
        self, accel_xyz: Union[Vec3, SensorUnavailable], gyro_xyz: Union[Vec3, SensorUnavailable]
    ) -> Union[Orientation, SensorUnavailable]:
        if not is_available(accel_xyz):
            return accel_xyz  # propagate the SensorUnavailable, don't guess
        if not is_available(gyro_xyz):
            return gyro_xyz

        ax, ay, az = accel_xyz
        gx, gy, gz = gyro_xyz

        # Accelerometer-derived tilt (only valid near-static; still useful as
        # the slow-correcting reference in a complementary filter).
        accel_pitch = math.degrees(math.atan2(ay, math.sqrt(ax ** 2 + az ** 2) + 1e-9))
        accel_roll = math.degrees(math.atan2(-ax, az + 1e-9))

        gyro_pitch = self._pitch + gx * self.dt
        gyro_roll = self._roll + gy * self.dt
        gyro_yaw = self._yaw + gz * self.dt

        self._pitch = self.alpha * gyro_pitch + (1 - self.alpha) * accel_pitch
        self._roll = self.alpha * gyro_roll + (1 - self.alpha) * accel_roll
        self._yaw = gyro_yaw  # no accel reference for yaw

        return Orientation(pitch=self._pitch, roll=self._roll, yaw=self._yaw)


# ---------------------------------------------------------------------------
# Motion state + posture classifiers
# ---------------------------------------------------------------------------

STILL_THRESHOLD = 0.06     # accel magnitude variance below this = still
WALKING_THRESHOLD = 0.30   # below this (and above still) = walking, else active

UPRIGHT_PITCH_DEG = 45.0   # |pitch| above this => treated as upright


def accel_magnitude(accel_xyz: Vec3) -> float:
    ax, ay, az = accel_xyz
    return math.sqrt(ax ** 2 + ay ** 2 + az ** 2)


def classify_motion_state(
    recent_accel: Deque[Vec3],
) -> Union[MotionState, SensorUnavailable]:
    if not recent_accel:
        return SensorUnavailable("motion_state", "no_samples_yet")
    if any(not is_available(a) for a in recent_accel):
        return SensorUnavailable("motion_state", "accel_unavailable_in_window")

    mags = [accel_magnitude(a) for a in recent_accel]
    variance = sum((m - sum(mags) / len(mags)) ** 2 for m in mags) / len(mags)

    if variance < STILL_THRESHOLD:
        return MotionState.STILL
    elif variance < WALKING_THRESHOLD:
        return MotionState.WALKING
    else:
        return MotionState.ACTIVE


def classify_posture(orientation: Union[Orientation, SensorUnavailable]) -> Union[Posture, SensorUnavailable]:
    if not is_available(orientation):
        return orientation
    return Posture.UPRIGHT if abs(orientation.pitch) > UPRIGHT_PITCH_DEG else Posture.LYING_DOWN


# ---------------------------------------------------------------------------
# Gesture-energy score: windowed RMS of acceleration
# ---------------------------------------------------------------------------

def gesture_energy_score(recent_accel: Deque[Vec3]) -> Union[float, SensorUnavailable]:
    if not recent_accel:
        return SensorUnavailable("gesture_energy", "no_samples_yet")
    if any(not is_available(a) for a in recent_accel):
        return SensorUnavailable("gesture_energy", "accel_unavailable_in_window")
    mags = [accel_magnitude(a) for a in recent_accel]
    rms = math.sqrt(sum(m ** 2 for m in mags) / len(mags))
    return round(rms, 4)


# ---------------------------------------------------------------------------
# Change-point detection: flags a sudden shift in motion pattern
# ---------------------------------------------------------------------------

def detect_change_point(
    older_window: Deque[Vec3], newer_window: Deque[Vec3], threshold: float = 0.35
) -> Union[bool, SensorUnavailable]:
    if not older_window or not newer_window:
        return SensorUnavailable("change_point", "insufficient_history")
    if any(not is_available(a) for a in list(older_window) + list(newer_window)):
        return SensorUnavailable("change_point", "accel_unavailable_in_window")

    older_mean = sum(accel_magnitude(a) for a in older_window) / len(older_window)
    newer_mean = sum(accel_magnitude(a) for a in newer_window) / len(newer_window)
    return abs(newer_mean - older_mean) > threshold


# ---------------------------------------------------------------------------
# Double-tap detection: two accel spikes within a 300ms window
# ---------------------------------------------------------------------------

SPIKE_THRESHOLD = 2.5      # magnitude jump considered a "tap"
DOUBLE_TAP_WINDOW_S = 0.3


class DoubleTapDetector:
    """Stateful: call feed() once per sample in timestamp order."""

    def __init__(self, spike_threshold: float = SPIKE_THRESHOLD, window_s: float = DOUBLE_TAP_WINDOW_S) -> None:
        self.spike_threshold = spike_threshold
        self.window_s = window_s
        self._last_baseline = 1.0  # ~1g at rest
        self._pending_tap_ts: Optional[float] = None

    def feed(self, timestamp: float, accel_xyz: Union[Vec3, SensorUnavailable]) -> bool:
        """Returns True exactly on the sample that completes a double-tap."""
        if not is_available(accel_xyz):
            return False  # unavailable sensor never fabricates a gesture event

        mag = accel_magnitude(accel_xyz)
        is_spike = (mag - self._last_baseline) > self.spike_threshold
        self._last_baseline = 0.9 * self._last_baseline + 0.1 * mag

        if is_spike:
            if self._pending_tap_ts is None:
                self._pending_tap_ts = timestamp
                return False
            elif timestamp - self._pending_tap_ts <= self.window_s:
                self._pending_tap_ts = None
                return True
            else:
                # too late to pair with the pending tap; this spike starts a new pair
                self._pending_tap_ts = timestamp
                return False
        return False


# ---------------------------------------------------------------------------
# Motion Daemon: ties the above together over a rolling window
# ---------------------------------------------------------------------------

class MotionDaemon:
    def __init__(self, window_size: int = 6) -> None:
        self.window_size = window_size
        self._accel_window: Deque[Vec3] = deque(maxlen=window_size)
        self._older_accel_window: Deque[Vec3] = deque(maxlen=window_size)
        self.orientation_filter = OrientationFilter()
        self.double_tap_detector = DoubleTapDetector()

    def process(
        self, timestamp: float, accel_xyz: Union[Vec3, SensorUnavailable], gyro_xyz: Union[Vec3, SensorUnavailable]
    ) -> dict:
        if self._accel_window:
            self._older_accel_window.append(self._accel_window[0])

        self._accel_window.append(accel_xyz)

        orientation = self.orientation_filter.update(accel_xyz, gyro_xyz)

        return {
            "timestamp": timestamp,
            "orientation": orientation,
            "motion_state": classify_motion_state(self._accel_window),
            "posture": classify_posture(orientation),
            "gesture_energy": gesture_energy_score(self._accel_window),
            "change_point": detect_change_point(self._older_accel_window, self._accel_window),
            "double_tap": self.double_tap_detector.feed(timestamp, accel_xyz),
        }
