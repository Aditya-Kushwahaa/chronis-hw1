"""
Worn / Not-Worn Detector.

Weighted vote across three signals:
    - HR signal quality      (highest weight)
    - orientation variance   (medium weight)
    - accel activity         (lowest weight)

Not-worn for 5+ minutes -> camera off, audio ring-buffer only, motion/HR
sampling rates dropped (enforced by the state machine dropping to L0, see
state_machine.py). Worn again -> 15s gradual wake-up + quick self-test,
then resume at capture level L1. Every state transition is emitted as an
event so it can be logged on the next metadata write.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

NOT_WORN_HOLD_S = 5 * 60      # 5 minutes below threshold -> officially not-worn
WAKE_UP_S = 15.0              # gradual wake-up duration once worn again

WEIGHT_HR = 0.5
WEIGHT_ORIENTATION = 0.3
WEIGHT_ACCEL = 0.2

WORN_SCORE_THRESHOLD = 0.35   # instantaneous score below this counts as "not worn" this tick

_ORIENTATION_VARIANCE_NORM = 40.0   # degrees; scales orientation variance into 0..1
_ACCEL_ACTIVITY_NORM = 1.0          # g-ish RMS; scales gesture energy into 0..1


class WornState(str, Enum):
    WORN = "worn"
    WAKING_UP = "waking_up"
    NOT_WORN = "not_worn"


@dataclass
class WornDetectorEvent:
    timestamp: float
    state: WornState
    score: float
    changed: bool
    reason: str


class WornDetector:
    def __init__(self) -> None:
        self.state = WornState.WORN
        self._not_worn_since: Optional[float] = None
        self._waking_since: Optional[float] = None

    @staticmethod
    def _normalize_orientation_variance(variance: float) -> float:
        return max(0.0, min(1.0, variance / _ORIENTATION_VARIANCE_NORM))

    @staticmethod
    def _normalize_accel_activity(gesture_energy: float) -> float:
        return max(0.0, min(1.0, gesture_energy / _ACCEL_ACTIVITY_NORM))

    def score(self, hr_quality: float, orientation_variance: float, accel_gesture_energy: float) -> float:
        hr_term = WEIGHT_HR * max(0.0, min(1.0, hr_quality))
        orient_term = WEIGHT_ORIENTATION * self._normalize_orientation_variance(orientation_variance)
        accel_term = WEIGHT_ACCEL * self._normalize_accel_activity(accel_gesture_energy)
        return round(hr_term + orient_term + accel_term, 4)

    def update(
        self,
        timestamp: float,
        hr_quality: float,
        orientation_variance: float,
        accel_gesture_energy: float,
    ) -> WornDetectorEvent:
        s = self.score(hr_quality, orientation_variance, accel_gesture_energy)
        instantaneous_worn = s >= WORN_SCORE_THRESHOLD
        prev_state = self.state

        if self.state == WornState.WORN:
            if not instantaneous_worn:
                if self._not_worn_since is None:
                    self._not_worn_since = timestamp
                elif timestamp - self._not_worn_since >= NOT_WORN_HOLD_S:
                    self.state = WornState.NOT_WORN
                    self._not_worn_since = None
                    return self._event(timestamp, s, prev_state, "worn_score_below_threshold_for_5min")
            else:
                self._not_worn_since = None

        elif self.state == WornState.NOT_WORN:
            if instantaneous_worn:
                self.state = WornState.WAKING_UP
                self._waking_since = timestamp
                return self._event(timestamp, s, prev_state, "worn_score_recovered_beginning_wakeup")

        elif self.state == WornState.WAKING_UP:
            if not instantaneous_worn:
                # Dropped again mid-wakeup: back to not-worn, no partial credit,
                # full self-test must run again once it recovers.
                self.state = WornState.NOT_WORN
                self._waking_since = None
                return self._event(timestamp, s, prev_state, "dropped_during_wakeup_self_test")
            elif timestamp - self._waking_since >= WAKE_UP_S:
                self.state = WornState.WORN
                self._waking_since = None
                return self._event(timestamp, s, prev_state, "wakeup_self_test_passed_restart_at_L1")

        return self._event(timestamp, s, prev_state, "no_state_change")

    def _event(self, timestamp: float, score: float, prev_state: WornState, reason: str) -> WornDetectorEvent:
        return WornDetectorEvent(
            timestamp=timestamp,
            state=self.state,
            score=score,
            changed=(self.state != prev_state),
            reason=reason,
        )
