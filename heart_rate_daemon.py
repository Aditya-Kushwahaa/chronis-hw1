"""
Heart Rate Daemon.

Owns the running signal-quality scorer for the PPG heart-rate sensor: a
continuous 0-1 confidence estimate on how trustworthy the current reading
is. Low-quality readings are FLAGGED, never silently treated as confident --
this score feeds the Worn Detector's weighted vote (Day 4) with the
highest weight of the three input signals.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Union

from interfaces import SensorUnavailable, is_available

LOW_QUALITY_THRESHOLD = 0.4


@dataclass
class HeartRateReading:
    heart_rate: float
    quality: float  # 0.0 (untrustworthy) .. 1.0 (high confidence)
    low_quality: bool


class HeartRateDaemon:
    """
    Signal quality is estimated from two things a real PPG front-end also
    reports: sample-to-sample stability (a wildly jumping HR is usually
    motion artifact, not a real heartbeat change) and physiological
    plausibility (30-220 bpm).
    """

    def __init__(self, window_size: int = 5, max_plausible_delta: float = 25.0) -> None:
        self._window: Deque[float] = deque(maxlen=window_size)
        self.max_plausible_delta = max_plausible_delta

    def process(self, heart_rate: Union[float, SensorUnavailable]) -> Union[HeartRateReading, SensorUnavailable]:
        if not is_available(heart_rate):
            return heart_rate  # Rule 3: propagate, never fabricate a reading

        if not (30.0 <= heart_rate <= 220.0):
            # Physiologically implausible reading: report it, but flag as
            # zero-confidence rather than discarding it (still real data).
            self._window.append(heart_rate)
            return HeartRateReading(heart_rate=heart_rate, quality=0.0, low_quality=True)

        stability_score = 1.0
        if self._window:
            last = self._window[-1]
            delta = abs(heart_rate - last)
            stability_score = max(0.0, 1.0 - (delta / self.max_plausible_delta))

        self._window.append(heart_rate)

        quality = round(stability_score, 3)
        return HeartRateReading(
            heart_rate=heart_rate,
            quality=quality,
            low_quality=quality < LOW_QUALITY_THRESHOLD,
        )
