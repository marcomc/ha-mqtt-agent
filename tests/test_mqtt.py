from __future__ import annotations

import json

from ha_mqtt_agent.config import AppConfig
from ha_mqtt_agent.mqtt import discovery_messages, state_message


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
