"""
Anchor Gesture Detector.

Deliberately a SEPARATE module from the state machine / capture-level
control path. Takes the double-tap signal from the Motion Daemon and opens
a 30-second annotation window centered on that timestamp.

Structural guarantee: this class is never given a writable handle to
capture level, camera trigger, or audio mode -- only, optionally, a
CaptureLevelReadPort (read-only) for logging/debugging. Its constructor
does not accept and its methods do not expose any way to mutate capture
state. See tests/test_anchor_gesture_negative.py for the negative-test
suite that proves this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from interfaces import CaptureLevelReadPort

ANNOTATION_WINDOW_S = 30.0


@dataclass(frozen=True)
class Annotation:
    center_timestamp: float
    window_start: float
    window_end: float
    note: Optional[str] = None


class AnchorGestureDetector:
    def __init__(self, capture_level_view: Optional[CaptureLevelReadPort] = None) -> None:
        # `capture_level_view`, if provided, is READ-ONLY (see CaptureLevelReadPort).
        # There is no parameter, attribute, or method anywhere on this class
        # that can set/change capture level, trigger the camera, or alter
        # audio mode. This is intentional and load-bearing for Rule 4 and
        # for the "annotation only, never capture control" guarantee.
        self._capture_level_view = capture_level_view
        self.annotations: List[Annotation] = []

    def on_double_tap(self, timestamp: float, note: Optional[str] = None) -> Annotation:
        annotation = Annotation(
            center_timestamp=timestamp,
            window_start=timestamp - ANNOTATION_WINDOW_S / 2,
            window_end=timestamp + ANNOTATION_WINDOW_S / 2,
            note=note,
        )
        self.annotations.append(annotation)
        return annotation

    def capture_level_at_time_of_annotation(self, annotation_index: int = -1):
        """
        Read-only convenience for logs: reports what capture level the
        system happened to be at, purely for display. Cannot be used to
        change anything -- there is no corresponding setter.
        """
        if self._capture_level_view is None:
            return None
        return self._capture_level_view.current_level()
