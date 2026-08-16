"""MQTT publishing and Home Assistant discovery payloads."""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, SupportsFloat, SupportsIndex

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from . import __version__
from .capabilities import CapabilityDefinition, capability_definitions
from .config import AppConfig

MQTT_PROBE_CONNACK_TIMEOUT_SECONDS = 5.0
LEGACY_0_1_CAPABILITY_IDS = {
    "power",
    "energy",
    "battery",
    "battery_max_capacity",
    "battery_max_capacity_mah",
    "battery_design_capacity",
    "battery_temperature",
    "battery_virtual_temperature",
    "battery_cycle_count",
    "battery_status",
    "uptime",
    "wifi_ssid",
    "wifi_bssid",
    "wifi_signal_dbm",
    "wifi_signal_percent",
    "ipv4_addresses",
    "default_gateways",
    "default_gateway_interfaces",
    "gateway_macs",
    "ethernet_active_count",
    "ethernet_active_interfaces",
    "home_network_present",
    "latitude",
    "longitude",
    "location_accuracy",
    "location_last_seen",
    "location_error",
    "geocoded_location",
    "geocoded_location_error",
    "location",
    "location_cached",
    "geocoded_location_cached",
}


@dataclass(frozen=True)
class MqttMessage:
    topic: str
    payload: str
    retain: bool = True


def discovery_messages(
    config: AppConfig,
    *,
    capability_ids: Iterable[str] | None = None,
) -> list[MqttMessage]:
    messages: list[MqttMessage] = []
    for definition in capability_definitions(config, capability_ids=capability_ids):
        if definition.component == "sensor":
            messages.append(_sensor_discovery_message(config, definition))
        elif definition.component == "binary_sensor":
            messages.append(_binary_sensor_discovery_message(config, definition))
        elif definition.component == "device_tracker":
            messages.append(_device_tracker_discovery_message(config, definition))
    return messages


def legacy_0_1_discovery_cleanup_messages(config: AppConfig) -> list[MqttMessage]:
    cleanup_config = replace(config, publish_location=True)
    messages: list[MqttMessage] = []
    for definition in capability_definitions(cleanup_config):
        if definition.id not in LEGACY_0_1_CAPABILITY_IDS and not definition.id.startswith("ping_"):
            continue
        unique_id = f"{config.device_id}_{definition.id}"
        topic = f"{config.discovery_prefix}/{definition.component}/{unique_id}/config"
        messages.append(MqttMessage(topic=topic, payload="", retain=True))
    return messages


def current_discovery_cleanup_messages(config: AppConfig) -> list[MqttMessage]:
    cleanup_config = replace(config, publish_location=True)
    return [
        MqttMessage(topic=message.topic, payload="", retain=True)
        for message in discovery_messages(cleanup_config)
    ]


def state_message(config: AppConfig, payload: dict[str, object]) -> MqttMessage:
    return MqttMessage(
        topic=config.state_topic,
        payload=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        retain=config.publish_retain,
    )


def location_attributes_message(
    config: AppConfig,
    payload: dict[str, object],
) -> MqttMessage | None:
    latitude = _float_payload_value(payload.get("latitude"))
    longitude = _float_payload_value(payload.get("longitude"))
    if latitude is None or longitude is None:
        return None

    attributes: dict[str, object] = {
        "latitude": latitude,
        "longitude": longitude,
    }
    accuracy = _float_payload_value(payload.get("location_accuracy_m"))
    if accuracy is not None:
        attributes["gps_accuracy"] = accuracy
    for key in ("location_cached", "location_last_seen", "location_error"):
        value = payload.get(key)
        if value is not None:
            attributes[key] = value
    if "location_last_seen" in attributes:
        attributes["last_seen"] = attributes["location_last_seen"]

    return MqttMessage(
        topic=config.location_attributes_topic,
        payload=json.dumps(attributes, separators=(",", ":"), sort_keys=True),
        retain=config.publish_retain,
    )


def availability_message(config: AppConfig, payload: str) -> MqttMessage:
    return MqttMessage(
        topic=config.availability_topic,
        payload=payload,
        retain=config.publish_retain,
    )


def publish_messages(
    config: AppConfig,
    messages: Iterable[MqttMessage],
    *,
    client_id_suffix: str = "",
) -> None:
    client = mqtt.Client(
        CallbackAPIVersion.VERSION2,
        client_id=config.resolved_mqtt_client_id_with_suffix(client_id_suffix),
    )
    if config.mqtt_username is not None:
        client.username_pw_set(config.mqtt_username, config.mqtt_password)

    client.will_set(config.availability_topic, payload="offline", retain=True)
    _raise_for_mqtt_error(
        client.connect(config.mqtt_host, config.mqtt_port, keepalive=60),
        "connect",
    )
    client.loop_start()
    try:
        for message in messages:
            result = client.publish(
                message.topic,
                payload=message.payload,
                qos=0,
                retain=message.retain,
            )
            _raise_for_mqtt_error(result.rc, f"publish to {message.topic}")
            result.wait_for_publish()
    finally:
        try:
            client.disconnect()
        finally:
            client.loop_stop()


def probe_mqtt_connection(config: AppConfig, *, client_id_suffix: str = "") -> None:
    connack_received = threading.Event()
    connack_reason_code: list[object] = []

    def on_connect(
        _client: mqtt.Client,
        _userdata: object,
        _flags: object,
        reason_code: object,
        _properties: object,
    ) -> None:
        connack_reason_code.append(reason_code)
        connack_received.set()

    client = mqtt.Client(
        CallbackAPIVersion.VERSION2,
        client_id=config.resolved_mqtt_client_id_with_suffix(client_id_suffix),
    )
    client.on_connect = on_connect
    if config.mqtt_username is not None:
        client.username_pw_set(config.mqtt_username, config.mqtt_password)

    _raise_for_mqtt_error(
        client.connect(config.mqtt_host, config.mqtt_port, keepalive=20),
        "connect",
    )
    loop_started = False
    try:
        _raise_for_mqtt_error(client.loop_start(), "loop start")
        loop_started = True
        if not connack_received.wait(MQTT_PROBE_CONNACK_TIMEOUT_SECONDS):
            raise TimeoutError("MQTT connect timed out waiting for CONNACK")
        _raise_for_mqtt_connack(connack_reason_code[0])
    finally:
        if loop_started:
            client.loop_stop()
        client.disconnect()


def _raise_for_mqtt_error(rc: int, action: str) -> None:
    if rc == mqtt.MQTT_ERR_SUCCESS:
        return
    raise RuntimeError(f"MQTT {action} failed: {mqtt.error_string(rc)}")


def _raise_for_mqtt_connack(reason_code: object) -> None:
    if reason_code == 0 or str(reason_code) == "Success":
        return
    raise RuntimeError(f"MQTT CONNACK failed: {reason_code}")


def _sensor_discovery_message(config: AppConfig, definition: CapabilityDefinition) -> MqttMessage:
    unique_id = f"{config.device_id}_{definition.id}"
    payload: dict[str, Any] = {
        "name": definition.name,
        "unique_id": unique_id,
        "object_id": unique_id,
        "state_topic": config.state_topic,
        **_availability_payload(config, definition),
        "value_template": definition.value_template,
        "expire_after": _expire_after_seconds(config),
        "device": _device_payload(config),
        "origin": {
            "name": "ha-mqtt-agent",
            "sw": __version__,
            "url": "https://github.com/marcomc/ha-mqtt-agent",
        },
    }
    if definition.device_class is not None:
        payload["device_class"] = definition.device_class
    if definition.state_class is not None:
        payload["state_class"] = definition.state_class
    if definition.unit is not None:
        payload["unit_of_measurement"] = definition.unit
    if definition.entity_category is not None:
        payload["entity_category"] = definition.entity_category
    if definition.attributes_template is not None:
        payload["json_attributes_topic"] = config.state_topic
        payload["json_attributes_template"] = definition.attributes_template

    topic = f"{config.discovery_prefix}/sensor/{unique_id}/config"
    return MqttMessage(topic=topic, payload=json.dumps(payload, sort_keys=True), retain=True)


def _device_tracker_discovery_message(
    config: AppConfig,
    definition: CapabilityDefinition,
) -> MqttMessage:
    unique_id = f"{config.device_id}_{definition.id}"
    payload: dict[str, Any] = {
        "name": definition.name,
        "unique_id": unique_id,
        "object_id": unique_id,
        "source_type": "gps",
        "json_attributes_topic": config.location_attributes_topic,
        **_availability_payload(config, definition),
        "device": _device_payload(config),
        "origin": {
            "name": "ha-mqtt-agent",
            "sw": __version__,
            "url": "https://github.com/marcomc/ha-mqtt-agent",
        },
    }
    topic = f"{config.discovery_prefix}/device_tracker/{unique_id}/config"
    return MqttMessage(topic=topic, payload=json.dumps(payload, sort_keys=True), retain=True)


def _binary_sensor_discovery_message(
    config: AppConfig,
    definition: CapabilityDefinition,
) -> MqttMessage:
    unique_id = f"{config.device_id}_{definition.id}"
    payload: dict[str, Any] = {
        "name": definition.name,
        "unique_id": unique_id,
        "object_id": unique_id,
        "state_topic": config.state_topic,
        **_availability_payload(config, definition),
        "value_template": definition.value_template,
        "payload_on": "true",
        "payload_off": "false",
        "expire_after": _expire_after_seconds(config),
        "device": _device_payload(config),
        "origin": {
            "name": "ha-mqtt-agent",
            "sw": __version__,
            "url": "https://github.com/marcomc/ha-mqtt-agent",
        },
    }
    if definition.device_class is not None:
        payload["device_class"] = definition.device_class
    if definition.entity_category is not None:
        payload["entity_category"] = definition.entity_category

    topic = f"{config.discovery_prefix}/binary_sensor/{unique_id}/config"
    return MqttMessage(topic=topic, payload=json.dumps(payload, sort_keys=True), retain=True)


def _availability_payload(
    config: AppConfig,
    definition: CapabilityDefinition,
) -> dict[str, object]:
    return {
        "availability": [
            {"topic": config.availability_topic},
            {
                "topic": config.state_topic,
                "value_template": f"{{{{ value_json.availability.{definition.id} }}}}",
            },
        ],
        "availability_mode": "all",
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _device_payload(config: AppConfig) -> dict[str, object]:
    return {
        "identifiers": [f"ha_mqtt_agent_{config.device_id}"],
        "name": config.device_name,
        "manufacturer": "Home Assistant MQTT Agent",
        "model": "Host",
        "sw_version": __version__,
    }


def _expire_after_seconds(config: AppConfig) -> int:
    return math.ceil(config.expire_after_seconds)


def _float_payload_value(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str | bytes | SupportsFloat | SupportsIndex):
        return None
    try:
        return float(value)
    except ValueError:
        return None
