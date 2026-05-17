"""macOS power and battery sensor collection."""

from __future__ import annotations

import re
import socket
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class SensorSample:
    timestamp: datetime
    host_name: str
    power_w: float | None
    battery_percent: int | None
    battery_max_capacity_percent: int | None
    battery_max_capacity_mah: int | None
    battery_design_capacity_mah: int | None
    battery_cycle_count: int | None
    battery_status: str | None
    external_power: bool | None

    def payload(self, *, energy_kwh: float) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "host_name": self.host_name,
            "power_w": _round_optional(self.power_w, 3),
            "energy_kwh": round(energy_kwh, 6),
            "battery_percent": self.battery_percent,
            "battery_max_capacity_percent": self.battery_max_capacity_percent,
            "battery_max_capacity_mah": self.battery_max_capacity_mah,
            "battery_design_capacity_mah": self.battery_design_capacity_mah,
            "battery_cycle_count": self.battery_cycle_count,
            "battery_status": self.battery_status,
            "external_power": self.external_power,
        }


class IoregSensorReader:
    """Read battery and system power telemetry exposed by AppleSmartBattery."""

    def read(self) -> SensorSample:
        output = subprocess.check_output(
            ["/usr/sbin/ioreg", "-rn", "AppleSmartBattery"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return parse_ioreg_sample(output, host_name=socket.gethostname())


def parse_ioreg_sample(output: str, *, host_name: str = "mac") -> SensorSample:
    is_charging = _bool_field(output, "IsCharging")
    external_power = _bool_field(output, "ExternalConnected")
    fully_charged = _bool_field(output, "FullyCharged")

    return SensorSample(
        timestamp=datetime.now(UTC),
        host_name=host_name,
        power_w=_power_watts(output),
        battery_percent=_int_field(output, "CurrentCapacity"),
        battery_max_capacity_percent=_int_field(output, "MaxCapacity"),
        battery_max_capacity_mah=_int_field(output, "AppleRawMaxCapacity"),
        battery_design_capacity_mah=_int_field(output, "DesignCapacity"),
        battery_cycle_count=_int_field(output, "CycleCount"),
        battery_status=_battery_status(
            is_charging=is_charging,
            external_power=external_power,
            fully_charged=fully_charged,
        ),
        external_power=external_power,
    )


def _power_watts(output: str) -> float | None:
    system_power_mw = _int_field(output, "SystemPowerIn")
    if system_power_mw is not None:
        return system_power_mw / 1000

    amperage_ma = _int_field(output, "InstantAmperage") or _int_field(output, "Amperage")
    voltage_mv = _int_field(output, "Voltage")
    if amperage_ma is None or voltage_mv is None:
        return None
    return abs(amperage_ma * voltage_mv) / 1_000_000


def _battery_status(
    *,
    is_charging: bool | None,
    external_power: bool | None,
    fully_charged: bool | None,
) -> str | None:
    if fully_charged:
        return "charged"
    if is_charging:
        return "charging"
    if external_power:
        return "plugged_in"
    if external_power is False:
        return "discharging"
    return None


def _int_field(output: str, key: str) -> int | None:
    match = re.search(rf'"{re.escape(key)}"\s*=\s*(-?\d+)', output)
    if match is None:
        return None
    return int(match.group(1))


def _bool_field(output: str, key: str) -> bool | None:
    match = re.search(rf'"{re.escape(key)}"\s*=\s*(Yes|No)', output)
    if match is None:
        return None
    return match.group(1) == "Yes"


def _round_optional(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)
