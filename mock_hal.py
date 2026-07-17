"""
Mock Hardware Abstraction Layer (HAL).

Each mock class exposes the same method names the real hardware driver will
expose later (i2c_read, gpio_read, camera_frame), so daemons built against
this layer port to real hardware by swapping the adapter, not by rewriting
daemon logic.

Every mock can be configured to return realistic fake values OR an explicit
SensorUnavailable (Rule 3) -- never a fake zero for a broken sensor.
"""

from __future__ import annotations

import itertools
from typing import Callable, Iterable, Optional, Union

from interfaces import SensorUnavailable, Reading


class _ScriptedSensor:
    """
    Shared base: replays a sequence of pre-scripted readings, or calls a
    generator function, so tests can drive exact sensor behavior over time
    (including going unavailable mid-run).
    """

    def __init__(
        self,
        name: str,
        values: Optional[Iterable[Reading]] = None,
        value_fn: Optional[Callable[[int], Reading]] = None,
        default: Optional[Reading] = None,
    ) -> None:
        self._name = name
        self._iter = iter(values) if values is not None else None
        self._value_fn = value_fn
        self._default = default if default is not None else SensorUnavailable(name, "no_data_configured")
        self._call_count = 0

    def _next_reading(self) -> Reading:
        reading: Reading
        if self._value_fn is not None:
            reading = self._value_fn(self._call_count)
        elif self._iter is not None:
            try:
                reading = next(self._iter)
            except StopIteration:
                reading = SensorUnavailable(self._name, "trace_exhausted")
        else:
            reading = self._default
        self._call_count += 1
        return reading

    def force_unavailable(self, reason: str = "forced_unavailable") -> None:
        """Test helper: makes every subsequent read return SensorUnavailable."""
        self._value_fn = lambda _i: SensorUnavailable(self._name, reason)
        self._iter = None


class MockI2C(_ScriptedSensor):
    """Stands in for I2C-bus sensors: accelerometer, gyroscope, heart rate (PPG)."""

    def __init__(self, name: str = "i2c", **kwargs) -> None:
        super().__init__(name=name, **kwargs)

    def i2c_read(self) -> Reading:
        return self._next_reading()


class MockGPIO(_ScriptedSensor):
    """Stands in for simple digital-pin sensors (e.g. worn-detector contact switch)."""

    def __init__(self, name: str = "gpio", **kwargs) -> None:
        super().__init__(name=name, **kwargs)

    def gpio_read(self) -> Reading:
        return self._next_reading()


class MockCamera(_ScriptedSensor):
    """Stands in for the camera sensor. Frames are simple dict stand-ins, not real images."""

    def __init__(self, name: str = "camera", **kwargs) -> None:
        super().__init__(name=name, **kwargs)
        self._frame_id = itertools.count()

    def camera_frame(self) -> Reading:
        reading = self._next_reading()
        if isinstance(reading, SensorUnavailable):
            return reading
        return {"frame_id": next(self._frame_id), "payload": reading}


class MockMicrophone(_ScriptedSensor):
    """Stands in for the microphone / audio front-end."""

    def __init__(self, name: str = "microphone", **kwargs) -> None:
        super().__init__(name=name, **kwargs)

    def audio_chunk(self) -> Reading:
        return self._next_reading()
