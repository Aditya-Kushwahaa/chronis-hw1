"""
6-Level Capture-Intensity State Machine.

Recalculated every 500ms (callers are expected to call update() on that
cadence, matching the trace generator's 2Hz sample rate). Each level sets
camera FPS and audio sample rate/mode:

    L0 dormant  : off-body or asleep       -> camera off,  8kHz buffer-only
    L1 ambient  : worn, alone, silent      -> 0.5 fps,      8kHz saved
    L2 passive  : activity nearby          -> 1 fps,       16kHz continuous
    L3 active   : user engaged             -> 10+ fps,     16kHz full + speaker sep.
    L4 engaged  : multi-person, animated   -> max fps,     dual-boosted audio
    L5 peak     : 3+ signals converge      -> 30 fps,      48kHz lossless

Step-UP transitions are immediate (no delay climbing to a higher level).
Step-DOWN transitions are hysteresis-gated, one level at a time, using the
timer belonging to the level being stepped down FROM:

    L5 -> L4   45s
    L4 -> L3   60s
    L3 -> L2   90s
    L2 -> L1  120s
    L1 -> L0  300s (5 min) -- in practice this is superseded by the
                              Worn Detector's own 5-minute not-worn timer;
                              see the NOT_WORN special-case below.

A battery-critical signal (wired from HW-2's Power Daemon on Day 5) can cap
the machine at L3 regardless of what the natural target level would be --
the lower ceiling always wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional

from audio_daemon import AudioMode
from motion_daemon import MotionState
from worn_detector import WornState


class Level(IntEnum):
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4
    L5 = 5


LEVEL_SETTINGS = {
    Level.L0: {"camera_fps": 0, "audio_mode": AudioMode.HZ8_BUFFER_ONLY},
    Level.L1: {"camera_fps": 0.5, "audio_mode": AudioMode.HZ8_SAVED},
    Level.L2: {"camera_fps": 1, "audio_mode": AudioMode.HZ16_CONTINUOUS},
    Level.L3: {"camera_fps": 10, "audio_mode": AudioMode.HZ16_FULL},
    Level.L4: {"camera_fps": "max", "audio_mode": "dual_boosted"},  # no single AudioMode enum value; see audio_daemon
    Level.L5: {"camera_fps": 30, "audio_mode": AudioMode.HZ48_LOSSLESS},
}

# Hold time required, at the CURRENT level, before stepping down one level.
STEP_DOWN_HOLD_S = {
    Level.L5: 45.0,
    Level.L4: 60.0,
    Level.L3: 90.0,
    Level.L2: 120.0,
    Level.L1: 300.0,
}

BATTERY_CRITICAL_CEILING = Level.L3

# Thresholds for target-level computation. Tuned against the four synthetic
# scenarios in trace_generator.py (idle_dormant / ambient_alone /
# active_conversation / multi_party).
#
# NOTE: motion_daemon.gesture_energy_score() is the windowed RMS of the raw
# accelerometer magnitude, which always includes the ~1g gravity component
# sitting on the resting axis. A device lying perfectly still still reports
# gesture_energy ~= 1.0, not 0.0. So here we compare against the ACTIVITY
# LEVEL -- gesture_energy with that ~1g baseline subtracted out -- rather
# than against gesture_energy directly. See _activity_level() below.
_GRAVITY_BASELINE_G = 1.0
GESTURE_ENERGY_HIGH = 0.20
GESTURE_ENERGY_MED = 0.10
GESTURE_ENERGY_LOW = 0.03
AUDIO_ENERGY_HIGH = 0.5
AUDIO_ENERGY_ACTIVE = 0.25
AUDIO_ENERGY_AMBIENT = 0.05


def _activity_level(gesture_energy: float) -> float:
    """Gesture energy with the resting ~1g gravity baseline removed."""
    return max(0.0, (gesture_energy or 0.0) - _GRAVITY_BASELINE_G)


@dataclass
class LevelTransition:
    timestamp: float
    from_level: Level
    to_level: Level
    cause: str


class CaptureStateMachine:
    def __init__(self, initial_level: Level = Level.L1) -> None:
        self.level = initial_level
        self.battery_critical = False
        self._below_target_since: Optional[float] = None
        self.transitions: List[LevelTransition] = []

    # ------------------------------------------------------------------
    # Target-level computation (pure function of the current context)
    # ------------------------------------------------------------------
    def _compute_target(
        self,
        worn_state: WornState,
        motion_state: MotionState,
        gesture_energy: float,
        audio_energy: float,
        voice_count: int,
    ) -> "tuple[Level, str]":
        if worn_state == WornState.NOT_WORN:
            return Level.L0, "not_worn"
        if worn_state == WornState.WAKING_UP:
            return Level.L1, "waking_up_restart_at_L1"

        # From here, worn_state == WORN.
        ge = _activity_level(gesture_energy)
        signals_converged = sum([
            voice_count >= 2,
            ge > GESTURE_ENERGY_HIGH,
            audio_energy > AUDIO_ENERGY_HIGH,
        ])

        if signals_converged >= 3:
            return Level.L5, "three_plus_signals_converge"
        if voice_count >= 2 and ge > GESTURE_ENERGY_MED:
            return Level.L4, "multi_person_animated"
        if voice_count >= 1 or ge > GESTURE_ENERGY_LOW or audio_energy > AUDIO_ENERGY_ACTIVE:
            return Level.L3, "user_actively_engaged"
        if motion_state != MotionState.STILL or audio_energy > AUDIO_ENERGY_AMBIENT:
            return Level.L2, "activity_nearby"
        return Level.L1, "ambient_worn_alone_silent"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_battery_critical(self, critical: bool) -> None:
        self.battery_critical = critical

    def current_settings(self) -> dict:
        return LEVEL_SETTINGS[self.level]

    def update(
        self,
        timestamp: float,
        worn_state: WornState,
        motion_state: MotionState,
        gesture_energy: float,
        audio_energy: float,
        voice_count: int,
    ) -> Optional[LevelTransition]:
        target, cause = self._compute_target(
            worn_state, motion_state, gesture_energy, audio_energy, voice_count
        )

        effective_target = target
        if self.battery_critical and target > BATTERY_CRITICAL_CEILING:
            effective_target = BATTERY_CRITICAL_CEILING
            cause = f"{cause}+battery_critical_ceiling_L3"

        # Special case: the Worn Detector already enforces its own 5-minute
        # not-worn hold before reporting NOT_WORN, so once that fires we drop
        # to L0 immediately rather than making the device wait through a
        # second, redundant hysteresis window.
        if effective_target == Level.L0 and cause == "not_worn":
            if self.level != Level.L0:
                old = self.level
                self.level = Level.L0
                self._below_target_since = None
                t = LevelTransition(timestamp, old, self.level, "not_worn_5min_confirmed_immediate_drop_to_L0")
                self.transitions.append(t)
                return t
            self._below_target_since = None
            return None

        if effective_target > self.level:
            old = self.level
            self.level = effective_target
            self._below_target_since = None
            t = LevelTransition(timestamp, old, self.level, cause)
            self.transitions.append(t)
            return t

        if effective_target < self.level:
            hold = STEP_DOWN_HOLD_S[self.level]
            if self._below_target_since is None:
                self._below_target_since = timestamp
                return None
            if timestamp - self._below_target_since >= hold:
                old = self.level
                self.level = Level(self.level - 1)  # step down ONE level at a time
                self._below_target_since = timestamp  # restart timer for the new level
                t = LevelTransition(timestamp, old, self.level, f"{cause}_step_down_after_{hold:.0f}s_hysteresis")
                self.transitions.append(t)
                return t
            return None

        # effective_target == self.level: at rest, reset any pending step-down
        self._below_target_since = None
        return None
