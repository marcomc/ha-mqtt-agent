"""macOS power and battery sensor collection."""

from __future__ import annotations

import re
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class SensorSample:
    timestamp: datetime
    host_name: str
    uptime_seconds: float
    power_w: float | None
    battery_percent: int | None
    battery_max_capacity_percent: float | None
    battery_max_capacity_mah: int | None
    battery_design_capacity_mah: int | None
    battery_reported_max_capacity_percent: int | None
    battery_temperature_c: float | None
    battery_virtual_temperature_c: float | None
    battery_cycle_count: int | None
    battery_status: str | None
    external_power: bool | None

    def payload(self, *, energy_kwh: float) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "host_name": self.host_name,
            "uptime_seconds": round(self.uptime_seconds, 3),
            "power_w": _round_optional(self.power_w, 3),
            "energy_kwh": round(energy_kwh, 6),
            "battery_percent": self.battery_percent,
            "battery_max_capacity_percent": _round_optional(
                self.battery_max_capacity_percent,
                2,
            ),
            "battery_max_capacity_mah": self.battery_max_capacity_mah,
            "battery_design_capacity_mah": self.battery_design_capacity_mah,
            "battery_reported_max_capacity_percent": (self.battery_reported_max_capacity_percent),
            "battery_temperature_c": _round_optional(self.battery_temperature_c, 2),
            "battery_virtual_temperature_c": _round_optional(
                self.battery_virtual_temperature_c,
                2,
            ),
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


def parse_ioreg_sample(
    output: str,
    *,
    host_name: str = "mac",
    uptime_seconds: float | None = None,
) -> SensorSample:
    is_charging = _bool_field(output, "IsCharging")
    external_power = _bool_field(output, "ExternalConnected")
    fully_charged = _bool_field(output, "FullyCharged")
    max_capacity_mah = _int_field(output, "AppleRawMaxCapacity") or _int_field(
        output,
        "NominalChargeCapacity",
    )
    design_capacity_mah = _int_field(output, "DesignCapacity")

    return SensorSample(
        timestamp=datetime.now(UTC),
        host_name=host_name,
        uptime_seconds=uptime_seconds if uptime_seconds is not None else time.monotonic(),
        power_w=_power_watts(output, external_power=external_power),
        battery_percent=_int_field(output, "CurrentCapacity"),
        battery_max_capacity_percent=_capacity_percent(
            max_capacity_mah=max_capacity_mah,
            design_capacity_mah=design_capacity_mah,
        ),
        battery_max_capacity_mah=max_capacity_mah,
        battery_design_capacity_mah=design_capacity_mah,
        battery_reported_max_capacity_percent=_int_field(output, "MaxCapacity"),
        battery_temperature_c=_kelvin_tenths_to_celsius(_int_field(output, "Temperature")),
        battery_virtual_temperature_c=_kelvin_tenths_to_celsius(
            _int_field(output, "VirtualTemperature"),
        ),
        battery_cycle_count=_int_field(output, "CycleCount"),
        battery_status=_battery_status(
            is_charging=is_charging,
            external_power=external_power,
            fully_charged=fully_charged,
        ),
        external_power=external_power,
    )


def _power_watts(output: str, *, external_power: bool | None) -> float | None:
    system_power_mw = _signed_int_field(output, "SystemPowerIn")
    if external_power is not False and system_power_mw is not None:
        return system_power_mw / 1000

    battery_power_mw = _signed_int_field(output, "BatteryPower")
    if battery_power_mw is not None and battery_power_mw > 0:
        return battery_power_mw / 1000

    amperage_ma = _signed_int_field(output, "InstantAmperage") or _signed_int_field(
        output,
        "Amperage",
    )
    voltage_mv = _signed_int_field(output, "Voltage")
    if amperage_ma is None or voltage_mv is None:
        return None
    return abs(amperage_ma * voltage_mv) / 1_000_000


def _capacity_percent(
    *,
    max_capacity_mah: int | None,
    design_capacity_mah: int | None,
) -> float | None:
    if max_capacity_mah is None or design_capacity_mah is None or design_capacity_mah <= 0:
        return None
    return max_capacity_mah / design_capacity_mah * 100


def _kelvin_tenths_to_celsius(value: int | None) -> float | None:
    if value is None:
        return None
    return value / 10 - 273.15


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


def _signed_int_field(output: str, key: str) -> int | None:
    value = _int_field(output, key)
    if value is None:
        return None
    if value >= 2**63:
        return value - 2**64
    return value


def _bool_field(output: str, key: str) -> bool | None:
    match = re.search(rf'"{re.escape(key)}"\s*=\s*(Yes|No)', output)
    if match is None:
        return None
    return match.group(1) == "Yes"


def _round_optional(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)
