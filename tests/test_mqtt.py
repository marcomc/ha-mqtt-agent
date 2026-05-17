from __future__ import annotations

import json

from mac_mqtt_energy.config import AppConfig
from mac_mqtt_energy.mqtt import discovery_messages, state_message


def test_discovery_messages_define_home_assistant_energy_sensor() -> None:
    config = AppConfig(device_id="work_mac", device_name="Work Mac")

    energy = next(
        message
        for message in discovery_messages(config)
        if message.topic == "homeassistant/sensor/work_mac_energy/config"
    )
    payload = json.loads(energy.payload)

    assert payload["device"]["name"] == "Work Mac"
    assert payload["device_class"] == "energy"
    assert payload["state_class"] == "total_increasing"
    assert payload["unit_of_measurement"] == "kWh"
    assert payload["state_topic"] == "mac_mqtt_energy/work_mac/state"


def test_state_message_uses_compact_json_and_configured_topic() -> None:
    config = AppConfig(device_id="work_mac")

    message = state_message(config, {"power_w": 12.5, "energy_kwh": 0.01})

    assert message.topic == "mac_mqtt_energy/work_mac/state"
    assert json.loads(message.payload) == {"energy_kwh": 0.01, "power_w": 12.5}
