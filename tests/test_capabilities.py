from __future__ import annotations

from typing import cast

from ha_mqtt_agent.capabilities import capability_snapshot_from_payload, sensor_registry
from ha_mqtt_agent.config import AppConfig, PingTarget


def test_sensor_registry_keeps_current_macos_entities_by_default() -> None:
    config = AppConfig(
        ping_targets=(PingTarget(id="router", host="192.0.2.1", name="Router"),),
        publish_location=False,
    )

    definitions = {definition.id: definition for definition in sensor_registry(config)}

    assert definitions["power"].group == "power"
    assert definitions["power"].payload_key == "power_w"
    assert definitions["wifi_signal_dbm"].group == "wifi"
    assert definitions["home_network_present"].component == "binary_sensor"
    assert definitions["ping_router"].payload_key == "ping_router_ms"
    assert "latitude" not in definitions


def test_sensor_registry_adds_location_entities_when_enabled() -> None:
    config = AppConfig(publish_location=True)

    definitions = {definition.id: definition for definition in sensor_registry(config)}

    assert definitions["latitude"].payload_key == "latitude"
    assert definitions["location"].component == "device_tracker"
    assert definitions["location_cached"].component == "binary_sensor"


def test_capability_snapshot_adds_per_entity_availability_to_state_payload() -> None:
    config = AppConfig(
        ping_targets=(PingTarget(id="router", host="192.0.2.1", name="Router"),),
        publish_location=True,
    )
    snapshot = capability_snapshot_from_payload(
        config=config,
        provider="macos",
        payload={
            "power_w": 12.5,
            "energy_kwh": 0.001,
            "wifi_bssid": None,
            "wifi_signal_dbm": None,
            "home_network_present": False,
            "location_error": None,
            "ping_router_ms": None,
        },
    )

    payload = snapshot.state_payload()
    availability = cast(dict[str, str], payload["availability"])
    power = snapshot.result("power")

    assert availability["power"] == "online"
    assert availability["wifi_signal_dbm"] == "offline"
    assert availability["wifi_bssid"] == "online"
    assert availability["home_network_present"] == "online"
    assert availability["location_error"] == "online"
    assert availability["ping_router"] == "offline"
    assert power is not None
    assert power.source == "macos"


def test_capability_snapshot_omits_unsupported_capabilities() -> None:
    snapshot = capability_snapshot_from_payload(
        config=AppConfig(),
        provider="minimal",
        capability_ids=("uptime",),
        payload={
            "uptime_seconds": 123,
            "power_w": None,
        },
    )

    payload = snapshot.state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert availability == {"uptime": "online"}
    assert snapshot.result("power") is None


def test_location_tracker_capability_requires_both_coordinates() -> None:
    config = AppConfig(publish_location=True)

    latitude_only = capability_snapshot_from_payload(
        config=config,
        provider="macos",
        capability_ids=("location",),
        payload={"latitude": 45.4642, "longitude": None},
    )
    longitude_only = capability_snapshot_from_payload(
        config=config,
        provider="macos",
        capability_ids=("location",),
        payload={"latitude": None, "longitude": 9.19},
    )
    complete = capability_snapshot_from_payload(
        config=config,
        provider="macos",
        capability_ids=("location",),
        payload={"latitude": 45.4642, "longitude": 9.19},
    )

    assert cast(dict[str, str], latitude_only.state_payload()["availability"]) == {
        "location": "offline"
    }
    assert cast(dict[str, str], longitude_only.state_payload()["availability"]) == {
        "location": "offline"
    }
    assert cast(dict[str, str], complete.state_payload()["availability"]) == {"location": "online"}
