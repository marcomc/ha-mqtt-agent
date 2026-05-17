"""Persistent energy accumulation from power samples."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, SupportsFloat, SupportsIndex


@dataclass(frozen=True)
class EnergyState:
    energy_kwh: float = 0.0
    last_timestamp: datetime | None = None
    last_power_w: float | None = None


class EnergyAccumulator:
    def __init__(self, path: Path, *, max_gap_seconds: float) -> None:
        self.path = path
        self.max_gap_seconds = max_gap_seconds
        self.state = self._load()

    def update(self, *, timestamp: datetime, power_w: float | None) -> float:
        energy_kwh = self.state.energy_kwh
        last_timestamp = self.state.last_timestamp
        last_power_w = self.state.last_power_w

        if (
            power_w is not None
            and power_w >= 0
            and last_timestamp is not None
            and last_power_w is not None
        ):
            elapsed_seconds = (timestamp - last_timestamp).total_seconds()
            if 0 < elapsed_seconds <= self.max_gap_seconds:
                average_power_w = (last_power_w + power_w) / 2
                energy_kwh += average_power_w * elapsed_seconds / 3_600_000

        self.state = EnergyState(
            energy_kwh=energy_kwh,
            last_timestamp=timestamp,
            last_power_w=power_w,
        )
        self._save()
        return energy_kwh

    @property
    def energy_kwh(self) -> float:
        return self.state.energy_kwh

    def _load(self) -> EnergyState:
        if not self.path.exists():
            return EnergyState()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return EnergyState()
            return EnergyState(
                energy_kwh=float(data.get("energy_kwh", 0.0)),
                last_timestamp=_parse_timestamp(data.get("last_timestamp")),
                last_power_w=_parse_float(data.get("last_power_w")),
            )
        except (OSError, ValueError, TypeError):
            return EnergyState()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "energy_kwh": self.state.energy_kwh,
            "last_timestamp": (
                self.state.last_timestamp.isoformat() if self.state.last_timestamp else None
            ),
            "last_power_w": self.state.last_power_w,
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value)


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str | bytes):
        return float(value)
    if isinstance(value, SupportsFloat | SupportsIndex):
        return float(value)
    raise TypeError(f"Cannot parse float from {type(value).__name__}.")
