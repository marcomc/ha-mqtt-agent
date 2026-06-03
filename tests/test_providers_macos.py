from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import Mock

from ha_mqtt_agent.config import AppConfig
from ha_mqtt_agent.network import NetworkSample, WifiStatus
from ha_mqtt_agent.providers.macos import MacOSProvider
from ha_mqtt_agent.sensors import SensorSample


def test_macos_provider_wraps_current_sensor_network_and_energy_payload(
    tmp_path: Path,
) -> None:
    config = AppConfig(state_path=tmp_path / "state.json", ping_targets=())
    sensor_reader = Mock()
    sensor_reader.read.return_value = SensorSample(
        timestamp=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
        host_name="macbook",
        uptime_seconds=123,
        power_w=12.5,
        battery_percent=80,
        battery_max_capacity_percent=90,
        battery_max_capacity_mah=4500,
        battery_design_capacity_mah=5000,
        battery_reported_max_capacity_percent=100,
        battery_temperature_c=32.5,
        battery_virtual_temperature_c=33.5,
        battery_cycle_count=20,
        battery_status="charging",
        external_power=True,
    )
    network_reader = Mock()
    network_reader.read.return_value = NetworkSample(
        wifi=WifiStatus(
            interface="en0",
            ssid="Office",
            signal_dbm=-55,
            signal_percent=90,
        ),
        ethernet=(),
        pings=(),
    )

    snapshot = MacOSProvider(
        sensor_reader=sensor_reader,
        network_reader=network_reader,
    ).sample(config, update_energy=False)
    payload = snapshot.state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert payload["host_name"] == "macbook"
    assert payload["power_w"] == 12.5
    assert payload["energy_kwh"] == 0
    assert payload["wifi_ssid"] == "Office"
    assert availability["power"] == "online"
    assert availability["wifi_signal_dbm"] == "online"
    assert snapshot.provider == "macos"
    assert not config.state_path.exists()
