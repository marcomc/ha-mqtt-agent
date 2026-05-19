from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ha_mqtt_agent.energy import EnergyAccumulator


def test_energy_accumulator_integrates_power_between_samples(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    accumulator = EnergyAccumulator(state_path, max_gap_seconds=300)
    start = datetime(2026, 5, 17, 10, 0, tzinfo=UTC)

    first = accumulator.update(timestamp=start, power_w=100)
    second = accumulator.update(timestamp=start + timedelta(seconds=60), power_w=100)

    assert first == 0
    assert round(second, 6) == 0.001667


def test_energy_accumulator_ignores_large_gaps(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    accumulator = EnergyAccumulator(state_path, max_gap_seconds=60)
    start = datetime(2026, 5, 17, 10, 0, tzinfo=UTC)

    accumulator.update(timestamp=start, power_w=100)
    energy = accumulator.update(timestamp=start + timedelta(seconds=120), power_w=100)

    assert energy == 0


def test_energy_accumulator_resets_unreadable_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{not json", encoding="utf-8")

    accumulator = EnergyAccumulator(state_path, max_gap_seconds=60)

    assert accumulator.energy_kwh == 0


def test_energy_accumulator_preserves_unrelated_runtime_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "energy_kwh": 1.5,
                "last_location": {
                    "latitude": 45.4642,
                    "longitude": 9.19,
                    "accuracy_m": 35.0,
                    "timestamp": "2026-05-17T10:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )

    accumulator = EnergyAccumulator(state_path, max_gap_seconds=60)
    accumulator.update(timestamp=datetime(2026, 5, 17, 10, 1, tzinfo=UTC), power_w=100)

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["last_location"] == {
        "latitude": 45.4642,
        "longitude": 9.19,
        "accuracy_m": 35.0,
        "timestamp": "2026-05-17T10:00:00+00:00",
    }
