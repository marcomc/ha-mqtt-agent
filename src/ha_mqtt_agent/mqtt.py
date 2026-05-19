"""MQTT publishing and Home Assistant discovery payloads."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, SupportsFloat, SupportsIndex

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
    always_sensors = [
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
        {
            "object": "wifi_ssid",
            "name": "Wi-Fi SSID",
            "unique": "wifi_ssid",
            "template": "{{ value_json.wifi_ssid }}",
        },
        {
            "object": "wifi_bssid",
            "name": "Wi-Fi BSSID",
            "unique": "wifi_bssid",
            "template": (
                "{{ value_json.wifi_bssid if value_json.wifi_bssid is not none "
                "else 'not_available' }}"
            ),
        },
        {
            "object": "wifi_signal_dbm",
            "name": "Wi-Fi signal",
            "unique": "wifi_signal_dbm",
            "device_class": "signal_strength",
            "state_class": "measurement",
            "unit": "dBm",
            "template": "{{ value_json.wifi_signal_dbm }}",
        },
        {
            "object": "wifi_signal_percent",
            "name": "Wi-Fi signal percent",
            "unique": "wifi_signal_percent",
            "state_class": "measurement",
            "unit": "%",
            "template": "{{ value_json.wifi_signal_percent }}",
        },
        {
            "object": "ipv4_addresses",
            "name": "IPv4 addresses",
            "unique": "ipv4_addresses",
            "template": "{{ value_json.ipv4_addresses }}",
        },
        {
            "object": "default_gateways",
            "name": "Default gateways",
            "unique": "default_gateways",
            "template": "{{ value_json.default_gateways }}",
        },
        {
            "object": "default_gateway_interfaces",
            "name": "Default gateway interfaces",
            "unique": "default_gateway_interfaces",
            "template": "{{ value_json.default_gateway_interfaces }}",
        },
        {
            "object": "gateway_macs",
            "name": "Gateway MACs",
            "unique": "gateway_macs",
            "template": "{{ value_json.gateway_macs }}",
        },
        {
            "object": "ethernet_active_count",
            "name": "Ethernet active count",
            "unique": "ethernet_active_count",
            "state_class": "measurement",
            "template": "{{ value_json.ethernet_active_count }}",
        },
        {
            "object": "ethernet_active_interfaces",
            "name": "Ethernet active interfaces",
            "unique": "ethernet_active_interfaces",
            "template": "{{ value_json.ethernet_active_interfaces }}",
        },
    ]
    sensors = list(always_sensors)
    if config.publish_location:
        sensors.extend(_location_sensor_specs())
    sensors.extend(_ping_sensor_specs(config))
    binary_sensors = [
        {
            "object": "home_network_present",
            "name": "Home network present",
            "unique": "home_network_present",
            "device_class": "presence",
            "template": "{{ value_json.home_network_present | tojson }}",
        },
    ]
    if config.publish_location:
        binary_sensors.extend(_location_binary_sensor_specs())
    messages = [
        *[_sensor_discovery_message(config, sensor) for sensor in sensors],
        *[_binary_sensor_discovery_message(config, sensor) for sensor in binary_sensors],
    ]
    if config.publish_location:
        messages.append(_device_tracker_discovery_message(config))
    return messages


def _location_sensor_specs() -> list[dict[str, str]]:
    return [
        {
            "object": "latitude",
            "name": "Latitude",
            "unique": "latitude",
            "state_class": "measurement",
            "unit": "°",
            "template": "{{ value_json.latitude }}",
        },
        {
            "object": "longitude",
            "name": "Longitude",
            "unique": "longitude",
            "state_class": "measurement",
            "unit": "°",
            "template": "{{ value_json.longitude }}",
        },
        {
            "object": "location_accuracy",
            "name": "Location accuracy",
            "unique": "location_accuracy",
            "device_class": "distance",
            "state_class": "measurement",
            "unit": "m",
            "template": "{{ value_json.location_accuracy_m }}",
        },
        {
            "object": "location_last_seen",
            "name": "Location last seen",
            "unique": "location_last_seen",
            "device_class": "timestamp",
            "template": "{{ value_json.location_last_seen }}",
        },
        {
            "object": "location_error",
            "name": "Location error",
            "unique": "location_error",
            "template": (
                "{{ value_json.location_error if value_json.location_error is not none "
                "else 'none' }}"
            ),
        },
        {
            "object": "geocoded_location",
            "name": "Geocoded location",
            "unique": "geocoded_location",
            "template": "{{ value_json.geocoded_location }}",
            "attributes_template": (
                "{{ {"
                "'Location': [value_json.latitude, value_json.longitude], "
                "'Name': value_json.geocoded_location_name, "
                "'Country': value_json.geocoded_location_country, "
                "'ISOCountryCode': value_json.geocoded_location_iso_country_code, "
                "'TimeZone': value_json.geocoded_location_time_zone, "
                "'AdministrativeArea': value_json.geocoded_location_administrative_area, "
                "'SubAdministrativeArea': "
                "value_json.geocoded_location_sub_administrative_area, "
                "'PostalCode': value_json.geocoded_location_postal_code, "
                "'Locality': value_json.geocoded_location_locality, "
                "'SubLocality': value_json.geocoded_location_sub_locality, "
                "'Thoroughfare': value_json.geocoded_location_thoroughfare, "
                "'SubThoroughfare': value_json.geocoded_location_sub_thoroughfare, "
                "'AreasOfInterest': value_json.geocoded_location_areas_of_interest, "
                "'Ocean': value_json.geocoded_location_ocean, "
                "'InlandWater': value_json.geocoded_location_inland_water, "
                "'Error': value_json.geocoded_location_error, "
                "'Cached': value_json.geocoded_location_cached, "
                "'LastSeen': value_json.location_last_seen"
                "} | tojson }}"
            ),
        },
        {
            "object": "geocoded_location_error",
            "name": "Geocoded location error",
            "unique": "geocoded_location_error",
            "template": (
                "{{ value_json.geocoded_location_error if "
                "value_json.geocoded_location_error is not none else 'none' }}"
            ),
        },
    ]


def _location_binary_sensor_specs() -> list[dict[str, str]]:
    return [
        {
            "object": "location_cached",
            "name": "Location cached",
            "unique": "location_cached",
            "template": "{{ value_json.location_cached | tojson }}",
        },
        {
            "object": "geocoded_location_cached",
            "name": "Geocoded location cached",
            "unique": "geocoded_location_cached",
            "template": "{{ value_json.geocoded_location_cached | tojson }}",
        },
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
    if "attributes_template" in spec:
        payload["json_attributes_topic"] = config.state_topic
        payload["json_attributes_template"] = spec["attributes_template"]

    topic = f"{config.discovery_prefix}/sensor/{unique_id}/config"
    return MqttMessage(topic=topic, payload=json.dumps(payload, sort_keys=True), retain=True)


def _device_tracker_discovery_message(config: AppConfig) -> MqttMessage:
    unique_id = f"{config.device_id}_location"
    payload: dict[str, Any] = {
        "name": "Location",
        "unique_id": unique_id,
        "object_id": unique_id,
        "source_type": "gps",
        "json_attributes_topic": config.location_attributes_topic,
        "availability_topic": config.availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": _device_payload(config),
        "origin": {
            "name": "ha-mqtt-agent",
            "sw": __version__,
            "url": "https://github.com/marcomc/ha-mqtt-agent",
        },
    }
    topic = f"{config.discovery_prefix}/device_tracker/{unique_id}/config"
    return MqttMessage(topic=topic, payload=json.dumps(payload, sort_keys=True), retain=True)


def _binary_sensor_discovery_message(config: AppConfig, spec: dict[str, str]) -> MqttMessage:
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
    if "device_class" in spec:
        payload["device_class"] = spec["device_class"]

    topic = f"{config.discovery_prefix}/binary_sensor/{unique_id}/config"
    return MqttMessage(topic=topic, payload=json.dumps(payload, sort_keys=True), retain=True)


def _ping_sensor_specs(config: AppConfig) -> list[dict[str, str]]:
    return [
        {
            "object": f"ping_{target.id}",
            "name": f"Ping {target.name}",
            "unique": f"ping_{target.id}",
            "device_class": "duration",
            "state_class": "measurement",
            "unit": "ms",
            "template": f"{{{{ value_json.ping_{target.id}_ms }}}}",
        }
        for target in config.ping_targets
    ]


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
