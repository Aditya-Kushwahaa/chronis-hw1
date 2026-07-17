"""
Synthetic trace generator.

Produces four scenario trace files: idle/dormant, ambient alone,
active conversation, multi-party high-energy.

Every record contains the four required channels:
    timestamp, accel_xyz, gyro_xyz, heart_rate, audio_energy

Plus one auxiliary, CLEARLY-SYNTHETIC-ONLY field, `voice_count`, which is
NOT a real sensor channel -- it's ground truth baked into the trace so the
multi-party / active-conversation scenarios can be told apart deterministically
in tests. A real Audio Daemon would derive something like this via speaker
separation (see L3 in the state machine); here it's just scripted.

All output is explicitly labeled synthetic in both the filename and an
embedded "synthetic": true marker, so it can never be mistaken for a real
capture session.
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
from dataclasses import asdict, dataclass
from typing import List, Optional

from interfaces import SensorUnavailable

SAMPLE_RATE_HZ = 2  # one record every 0.5s, matches state machine's 500ms tick


@dataclass
class TraceRecord:
    timestamp: float
    accel_xyz: List[float]
    gyro_xyz: List[float]
    heart_rate: Optional[float]  # None serializes SensorUnavailable, see to_serializable()
    audio_energy: float
    voice_count: int  # synthetic-only ground truth, NOT a real sensor channel
    heart_rate_unavailable: bool = False

    def to_serializable(self) -> dict:
        d = asdict(self)
        return d


def _jitter(base: float, spread: float, rng: random.Random) -> float:
    return base + rng.uniform(-spread, spread)


def _gen_scenario(
    name: str,
    duration_s: int,
    rng: random.Random,
    accel_base: float,
    accel_spread: float,
    gyro_spread: float,
    hr_base: float,
    hr_spread: float,
    audio_base: float,
    audio_spread: float,
    voice_count: int,
    hr_dropout_prob: float = 0.0,
    inject_double_tap_at: Optional[float] = None,
) -> List[TraceRecord]:
    records: List[TraceRecord] = []
    n_samples = duration_s * SAMPLE_RATE_HZ
    for i in range(n_samples):
        t = round(i / SAMPLE_RATE_HZ, 3)

        accel = [
            _jitter(accel_base, accel_spread, rng),
            _jitter(accel_base, accel_spread, rng),
            _jitter(1.0, accel_spread, rng),  # ~1g resting on one axis
        ]

        # Inject a clean double-tap: two sharp accel spikes within 300ms
        if inject_double_tap_at is not None:
            tap_window = (inject_double_tap_at, inject_double_tap_at + 0.3)
            if tap_window[0] <= t <= tap_window[1]:
                spike = 4.0 if abs(t - inject_double_tap_at) < 0.05 or abs(t - (inject_double_tap_at + 0.25)) < 0.05 else 0.0
                accel[2] += spike

        gyro = [_jitter(0.0, gyro_spread, rng) for _ in range(3)]

        heart_rate_unavailable = rng.random() < hr_dropout_prob
        heart_rate = None if heart_rate_unavailable else round(_jitter(hr_base, hr_spread, rng), 1)

        audio_energy = max(0.0, round(_jitter(audio_base, audio_spread, rng), 4))

        records.append(
            TraceRecord(
                timestamp=t,
                accel_xyz=[round(v, 4) for v in accel],
                gyro_xyz=[round(v, 4) for v in gyro],
                heart_rate=heart_rate,
                audio_energy=audio_energy,
                voice_count=voice_count,
                heart_rate_unavailable=heart_rate_unavailable,
            )
        )
    return records


def generate_all_scenarios(seed: int = 42) -> dict:
    """Returns {scenario_name: List[TraceRecord]} for all four scenarios."""
    rng = random.Random(seed)

    scenarios = {}

    scenarios["idle_dormant"] = _gen_scenario(
        "idle_dormant", duration_s=60, rng=rng,
        accel_base=0.02, accel_spread=0.02, gyro_spread=0.01,
        hr_base=58, hr_spread=2, audio_base=0.01, audio_spread=0.01,
        voice_count=0,
    )

    scenarios["ambient_alone"] = _gen_scenario(
        "ambient_alone", duration_s=60, rng=rng,
        accel_base=0.08, accel_spread=0.05, gyro_spread=0.03,
        hr_base=68, hr_spread=4, audio_base=0.05, audio_spread=0.03,
        voice_count=0,
        inject_double_tap_at=20.0,  # exercise the anchor gesture path
    )

    scenarios["active_conversation"] = _gen_scenario(
        "active_conversation", duration_s=60, rng=rng,
        accel_base=0.3, accel_spread=0.15, gyro_spread=0.12,
        hr_base=82, hr_spread=6, audio_base=0.35, audio_spread=0.12,
        voice_count=2,
        hr_dropout_prob=0.05,  # occasional flaky reading, exercises Rule 3
    )

    scenarios["multi_party"] = _gen_scenario(
        "multi_party", duration_s=60, rng=rng,
        accel_base=0.55, accel_spread=0.25, gyro_spread=0.2,
        hr_base=95, hr_spread=8, audio_base=0.65, audio_spread=0.2,
        voice_count=4,
    )

    return scenarios


def write_traces(output_dir: str, seed: int = 42) -> None:
    os.makedirs(output_dir, exist_ok=True)
    scenarios = generate_all_scenarios(seed=seed)

    for name, records in scenarios.items():
        base = os.path.join(output_dir, f"synthetic_{name}")

        json_payload = {
            "synthetic": True,
            "scenario": name,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "records": [r.to_serializable() for r in records],
        }
        with open(base + ".json", "w") as f:
            json.dump(json_payload, f, indent=2)

        with open(base + ".csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "synthetic", "timestamp", "accel_x", "accel_y", "accel_z",
                "gyro_x", "gyro_y", "gyro_z", "heart_rate", "heart_rate_unavailable",
                "audio_energy", "voice_count",
            ])
            for r in records:
                writer.writerow([
                    True, r.timestamp, *r.accel_xyz, *r.gyro_xyz,
                    "" if r.heart_rate is None else r.heart_rate,
                    r.heart_rate_unavailable, r.audio_energy, r.voice_count,
                ])

    print(f"Wrote {len(scenarios)} synthetic traces (JSON + CSV) to {output_dir}/")


def load_trace_json(path: str) -> List[TraceRecord]:
    with open(path) as f:
        data = json.load(f)
    assert data.get("synthetic") is True, "Refusing to load a trace not labeled synthetic"
    return [TraceRecord(**rec) for rec in data["records"]]


if __name__ == "__main__":
    write_traces(os.path.join(os.path.dirname(__file__), "traces"))
