"""MQTT publishing and Home Assistant discovery payloads."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from . import __version__
from .config import AppConfig


@dataclass(frozen=True)
class MqttMessage:
    topic: str
    payload: str
    retain: bool = True


def discovery_messages(config: AppConfig) -> list[MqttMessage]:
    sensors = [
        {
            "object": "power",
            "name": "Power",
            "unique": "power",
            "device_class": "power",
            "state_class": "measurement",
            "unit": "W",
            "template": "{{ value_json.power_w }}",
        },
        {
            "object": "energy",
            "name": "Energy",
            "unique": "energy",
            "device_class": "energy",
            "state_class": "total_increasing",
            "unit": "kWh",
            "template": "{{ value_json.energy_kwh }}",
        },
        {
            "object": "battery",
            "name": "Battery",
            "unique": "battery",
            "device_class": "battery",
            "state_class": "measurement",
            "unit": "%",
            "template": "{{ value_json.battery_percent }}",
        },
        {
            "object": "battery_max_capacity",
            "name": "Battery maximum capacity",
            "unique": "battery_max_capacity",
            "device_class": "battery",
            "state_class": "measurement",
            "unit": "%",
            "template": "{{ value_json.battery_max_capacity_percent }}",
        },
        {
            "object": "battery_max_capacity_mah",
            "name": "Battery maximum capacity mAh",
            "unique": "battery_max_capacity_mah",
            "state_class": "measurement",
            "unit": "mAh",
            "template": "{{ value_json.battery_max_capacity_mah }}",
        },
        {
            "object": "battery_design_capacity",
            "name": "Battery design capacity",
            "unique": "battery_design_capacity",
            "state_class": "measurement",
            "unit": "mAh",
            "template": "{{ value_json.battery_design_capacity_mah }}",
        },
        {
            "object": "battery_temperature",
            "name": "Battery temperature",
            "unique": "battery_temperature",
            "device_class": "temperature",
            "state_class": "measurement",
            "unit": "°C",
            "template": "{{ value_json.battery_temperature_c }}",
        },
        {
            "object": "battery_virtual_temperature",
            "name": "Battery virtual temperature",
            "unique": "battery_virtual_temperature",
            "device_class": "temperature",
            "state_class": "measurement",
            "unit": "°C",
            "template": "{{ value_json.battery_virtual_temperature_c }}",
        },
        {
            "object": "battery_cycle_count",
            "name": "Battery cycle count",
            "unique": "battery_cycle_count",
            "state_class": "total_increasing",
            "template": "{{ value_json.battery_cycle_count }}",
        },
        {
            "object": "battery_status",
            "name": "Battery status",
            "unique": "battery_status",
            "template": "{{ value_json.battery_status }}",
        },
        {
            "object": "uptime",
            "name": "Uptime",
            "unique": "uptime",
            "device_class": "duration",
            "state_class": "measurement",
            "unit": "s",
            "template": "{{ value_json.uptime_seconds }}",
        },
    ]
    return [_sensor_discovery_message(config, sensor) for sensor in sensors]


def state_message(config: AppConfig, payload: dict[str, object]) -> MqttMessage:
    return MqttMessage(
        topic=config.state_topic,
        payload=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        retain=config.publish_retain,
    )


def availability_message(config: AppConfig, payload: str) -> MqttMessage:
    return MqttMessage(
        topic=config.availability_topic,
        payload=payload,
        retain=config.publish_retain,
    )


def publish_messages(config: AppConfig, messages: Iterable[MqttMessage]) -> None:
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=config.mqtt_client_id)
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
        client.loop_stop()
        client.disconnect()


def _raise_for_mqtt_error(rc: int, action: str) -> None:
    if rc == mqtt.MQTT_ERR_SUCCESS:
        return
    raise RuntimeError(f"MQTT {action} failed: {mqtt.error_string(rc)}")


def _sensor_discovery_message(config: AppConfig, spec: dict[str, str]) -> MqttMessage:
    unique_id = f"{config.device_id}_{spec['unique']}"
    payload: dict[str, Any] = {
        "name": spec["name"],
        "unique_id": unique_id,
        "object_id": unique_id,
        "state_topic": config.state_topic,
        "availability_topic": config.availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "value_template": spec["template"],
        "expire_after": _expire_after_seconds(config),
        "device": _device_payload(config),
        "origin": {
            "name": "ha-mqtt-agent",
            "sw": __version__,
            "url": "https://github.com/marcomc/ha-mqtt-agent",
        },
    }
    if "device_class" in spec:
        payload["device_class"] = spec["device_class"]
    if "state_class" in spec:
        payload["state_class"] = spec["state_class"]
    if "unit" in spec:
        payload["unit_of_measurement"] = spec["unit"]

    topic = f"{config.discovery_prefix}/sensor/{unique_id}/config"
    return MqttMessage(topic=topic, payload=json.dumps(payload, sort_keys=True), retain=True)


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
