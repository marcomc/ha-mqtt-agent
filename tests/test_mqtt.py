from __future__ import annotations

import json

import paho.mqtt.client as paho_mqtt
import pytest
from paho.mqtt.enums import MQTTErrorCode

from ha_mqtt_agent.config import AppConfig
from ha_mqtt_agent.mqtt import MqttMessage, discovery_messages, publish_messages, state_message


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

    ethernet = messages["homeassistant/sensor/workstation_ethernet_active_interfaces/config"]
    assert ethernet["value_template"] == "{{ value_json.ethernet_active_interfaces }}"

    ping = messages["homeassistant/sensor/workstation_ping_cloudflare_dns/config"]
    assert ping["device_class"] == "duration"
    assert ping["unit_of_measurement"] == "ms"
    assert ping["value_template"] == "{{ value_json.ping_cloudflare_dns_ms }}"


def test_discovery_messages_expire_entities_after_configured_window() -> None:
    config = AppConfig(device_id="workstation", expire_after_seconds=15)

    messages = [json.loads(message.payload) for message in discovery_messages(config)]

    assert messages
    assert {message["expire_after"] for message in messages} == {15}


def test_state_message_uses_compact_json_and_configured_topic() -> None:
    config = AppConfig(device_id="workstation")

    message = state_message(config, {"power_w": 12.5, "energy_kwh": 0.01})

    assert message.topic == "ha_mqtt_agent/workstation/state"
    assert json.loads(message.payload) == {"energy_kwh": 0.01, "power_w": 12.5}


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
