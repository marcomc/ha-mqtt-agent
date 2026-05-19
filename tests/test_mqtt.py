from __future__ import annotations

import json

import paho.mqtt.client as paho_mqtt
import pytest
from paho.mqtt.enums import MQTTErrorCode

from ha_mqtt_agent.config import AppConfig
from ha_mqtt_agent.mqtt import (
    MqttMessage,
    discovery_messages,
    location_attributes_message,
    publish_messages,
    state_message,
)


def test_discovery_messages_define_home_assistant_energy_sensor() -> None:
    config = AppConfig(device_id="workstation", device_name="Workstation")

    energy = next(
        message
        for message in discovery_messages(config)
        if message.topic == "homeassistant/sensor/workstation_energy/config"
    )
    payload = json.loads(energy.payload)

    assert payload["device"]["name"] == "Workstation"
    assert payload["device_class"] == "energy"
    assert payload["state_class"] == "total_increasing"
    assert payload["unit_of_measurement"] == "kWh"
    assert payload["state_topic"] == "ha_mqtt_agent/workstation/state"


def test_discovery_messages_define_temperature_and_uptime_sensors() -> None:
    config = AppConfig(device_id="workstation", device_name="Workstation")
    messages = {
        message.topic: json.loads(message.payload) for message in discovery_messages(config)
    }

    temperature = messages["homeassistant/sensor/workstation_battery_temperature/config"]
    assert temperature["device_class"] == "temperature"
    assert temperature["unit_of_measurement"] == "°C"
    assert temperature["value_template"] == "{{ value_json.battery_temperature_c }}"

    uptime = messages["homeassistant/sensor/workstation_uptime/config"]
    assert uptime["device_class"] == "duration"
    assert uptime["unit_of_measurement"] == "s"
    assert uptime["value_template"] == "{{ value_json.uptime_seconds }}"


def test_discovery_messages_define_network_and_ping_sensors() -> None:
    config = AppConfig(device_id="workstation", device_name="Workstation")
    messages = {
        message.topic: json.loads(message.payload) for message in discovery_messages(config)
    }

    wifi_signal = messages["homeassistant/sensor/workstation_wifi_signal_dbm/config"]
    assert wifi_signal["device_class"] == "signal_strength"
    assert wifi_signal["unit_of_measurement"] == "dBm"
    assert wifi_signal["value_template"] == "{{ value_json.wifi_signal_dbm }}"

    wifi_percent = messages["homeassistant/sensor/workstation_wifi_signal_percent/config"]
    assert wifi_percent["unit_of_measurement"] == "%"
    assert wifi_percent["value_template"] == "{{ value_json.wifi_signal_percent }}"

    wifi_bssid = messages["homeassistant/sensor/workstation_wifi_bssid/config"]
    assert wifi_bssid["value_template"] == "{{ value_json.wifi_bssid }}"

    gateway_macs = messages["homeassistant/sensor/workstation_gateway_macs/config"]
    assert gateway_macs["value_template"] == "{{ value_json.gateway_macs }}"

    home_network = messages["homeassistant/binary_sensor/workstation_home_network_present/config"]
    assert home_network["device_class"] == "presence"
    assert home_network["payload_on"] == "true"
    assert home_network["payload_off"] == "false"
    assert home_network["value_template"] == "{{ value_json.home_network_present | tojson }}"

    ethernet = messages["homeassistant/sensor/workstation_ethernet_active_interfaces/config"]
    assert ethernet["value_template"] == "{{ value_json.ethernet_active_interfaces }}"

    ping = messages["homeassistant/sensor/workstation_ping_cloudflare_dns/config"]
    assert ping["device_class"] == "duration"
    assert ping["unit_of_measurement"] == "ms"
    assert ping["value_template"] == "{{ value_json.ping_cloudflare_dns_ms }}"


def test_discovery_messages_skip_location_entities_when_location_is_disabled() -> None:
    config = AppConfig(device_id="workstation", publish_location=False)
    topics = {message.topic for message in discovery_messages(config)}

    assert "homeassistant/sensor/workstation_latitude/config" not in topics
    assert "homeassistant/sensor/workstation_geocoded_location/config" not in topics
    assert "homeassistant/binary_sensor/workstation_location_cached/config" not in topics
    assert "homeassistant/device_tracker/workstation_location/config" not in topics


def test_discovery_messages_define_location_entities_when_location_is_enabled() -> None:
    config = AppConfig(
        device_id="workstation",
        device_name="Workstation",
        publish_location=True,
    )
    messages = {
        message.topic: json.loads(message.payload) for message in discovery_messages(config)
    }

    latitude = messages["homeassistant/sensor/workstation_latitude/config"]
    assert latitude["unit_of_measurement"] == "°"
    assert latitude["value_template"] == "{{ value_json.latitude }}"

    accuracy = messages["homeassistant/sensor/workstation_location_accuracy/config"]
    assert accuracy["device_class"] == "distance"
    assert accuracy["unit_of_measurement"] == "m"
    assert accuracy["value_template"] == "{{ value_json.location_accuracy_m }}"

    location_error = messages["homeassistant/sensor/workstation_location_error/config"]
    assert location_error["value_template"] == "{{ value_json.location_error }}"

    location_last_seen = messages["homeassistant/sensor/workstation_location_last_seen/config"]
    assert location_last_seen["device_class"] == "timestamp"
    assert location_last_seen["value_template"] == "{{ value_json.location_last_seen }}"

    location_cached = messages["homeassistant/binary_sensor/workstation_location_cached/config"]
    assert location_cached["value_template"] == "{{ value_json.location_cached | tojson }}"

    geocoded_location = messages["homeassistant/sensor/workstation_geocoded_location/config"]
    assert geocoded_location["value_template"] == "{{ value_json.geocoded_location }}"
    assert geocoded_location["json_attributes_topic"] == "ha_mqtt_agent/workstation/state"
    assert (
        "'Location': [value_json.latitude, value_json.longitude]"
        in (geocoded_location["json_attributes_template"])
    )
    assert (
        "'Name': value_json.geocoded_location_name"
        in (geocoded_location["json_attributes_template"])
    )
    assert (
        "'Country': value_json.geocoded_location_country"
        in (geocoded_location["json_attributes_template"])
    )

    location_tracker = messages["homeassistant/device_tracker/workstation_location/config"]
    assert location_tracker["name"] == "Location"
    assert location_tracker["unique_id"] == "workstation_location"
    assert location_tracker["source_type"] == "gps"
    assert location_tracker["json_attributes_topic"] == (
        "ha_mqtt_agent/workstation/location/attributes"
    )
    assert location_tracker["availability_topic"] == "ha_mqtt_agent/workstation/availability"


def test_discovery_messages_expire_entities_after_configured_window() -> None:
    config = AppConfig(device_id="workstation", expire_after_seconds=15)

    messages = [json.loads(message.payload) for message in discovery_messages(config)]
    expiring_messages = [message for message in messages if "expire_after" in message]

    assert expiring_messages
    assert {message["expire_after"] for message in expiring_messages} == {15}


def test_state_message_uses_compact_json_and_configured_topic() -> None:
    config = AppConfig(device_id="workstation")

    message = state_message(config, {"power_w": 12.5, "energy_kwh": 0.01})

    assert message.topic == "ha_mqtt_agent/workstation/state"
    assert json.loads(message.payload) == {"energy_kwh": 0.01, "power_w": 12.5}


def test_location_attributes_message_uses_home_assistant_tracker_attribute_names() -> None:
    config = AppConfig(device_id="workstation")

    message = location_attributes_message(
        config,
        {
            "latitude": 45.4642,
            "longitude": 9.19,
            "location_accuracy_m": 35.0,
            "location_cached": True,
            "location_last_seen": "2026-05-17T10:00:00+00:00",
            "location_error": "The operation could not be completed.",
        },
    )

    assert message is not None
    assert message.topic == "ha_mqtt_agent/workstation/location/attributes"
    assert json.loads(message.payload) == {
        "gps_accuracy": 35.0,
        "latitude": 45.4642,
        "last_seen": "2026-05-17T10:00:00+00:00",
        "location_cached": True,
        "location_error": "The operation could not be completed.",
        "location_last_seen": "2026-05-17T10:00:00+00:00",
        "longitude": 9.19,
    }


def test_location_attributes_message_is_skipped_without_coordinates() -> None:
    config = AppConfig(device_id="workstation")

    message = location_attributes_message(config, {"latitude": None, "longitude": None})

    assert message is None


def test_publish_messages_uses_derived_client_id_with_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def client_factory(*args: object, **kwargs: object) -> _FakeClient:
        _ = args
        captured["client_id"] = str(kwargs["client_id"])
        return _FakeClient()

    monkeypatch.setattr("ha_mqtt_agent.mqtt.mqtt.Client", client_factory)

    publish_messages(
        AppConfig(device_id="workstation"),
        [],
        client_id_suffix="-manual-123",
    )

    assert captured["client_id"] == "ha-mqtt-agent-d67a39a1"
    assert len(captured["client_id"].encode("utf-8")) <= 23


def test_publish_messages_keeps_manual_client_id_with_suffix_broker_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def client_factory(*args: object, **kwargs: object) -> _FakeClient:
        _ = args
        captured["client_id"] = str(kwargs["client_id"])
        return _FakeClient()

    monkeypatch.setattr("ha_mqtt_agent.mqtt.mqtt.Client", client_factory)

    publish_messages(
        AppConfig(device_id="host"),
        [],
        client_id_suffix="-manual-12345",
    )

    assert captured["client_id"] == "ha-mqtt-agent-82a37b77"
    assert len(captured["client_id"].encode("utf-8")) <= 23


def test_publish_messages_raises_on_connect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(connect_rc=paho_mqtt.MQTT_ERR_NO_CONN)
    monkeypatch.setattr("ha_mqtt_agent.mqtt.mqtt.Client", lambda *args, **kwargs: client)

    with pytest.raises(RuntimeError, match="MQTT connect failed"):
        publish_messages(AppConfig(), [MqttMessage("topic", "payload")])

    assert client.loop_started is False
    assert client.disconnected is False


def test_publish_messages_raises_on_publish_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(publish_rc=paho_mqtt.MQTT_ERR_NO_CONN)
    monkeypatch.setattr("ha_mqtt_agent.mqtt.mqtt.Client", lambda *args, **kwargs: client)

    with pytest.raises(RuntimeError, match="MQTT publish to topic failed"):
        publish_messages(AppConfig(), [MqttMessage("topic", "payload")])

    assert client.loop_stopped is True
    assert client.disconnected is True


class _FakePublishResult:
    def __init__(self, rc: MQTTErrorCode) -> None:
        self.rc = rc
        self.waited = False

    def wait_for_publish(self) -> None:
        self.waited = True


class _FakeClient:
    def __init__(
        self,
        *,
        connect_rc: MQTTErrorCode = paho_mqtt.MQTT_ERR_SUCCESS,
        publish_rc: MQTTErrorCode = paho_mqtt.MQTT_ERR_SUCCESS,
    ) -> None:
        self.connect_rc = connect_rc
        self.publish_rc = publish_rc
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False

    def username_pw_set(self, username: str, password: str | None = None) -> None:
        _ = (username, password)

    def will_set(self, topic: str, payload: str, retain: bool) -> None:
        _ = (topic, payload, retain)

    def connect(self, host: str, port: int, keepalive: int) -> MQTTErrorCode:
        _ = (host, port, keepalive)
        return self.connect_rc

    def loop_start(self) -> None:
        self.loop_started = True

    def publish(
        self,
        topic: str,
        payload: str,
        qos: int,
        retain: bool,
    ) -> _FakePublishResult:
        _ = (topic, payload, qos, retain)
        return _FakePublishResult(self.publish_rc)

    def loop_stop(self) -> None:
        self.loop_stopped = True

    def disconnect(self) -> None:
        self.disconnected = True
