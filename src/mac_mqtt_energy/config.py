"""Configuration support for Mac MQTT Energy."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "mac-mqtt-energy" / "config.toml"
DEFAULT_STATE_PATH = Path.home() / ".local" / "state" / "mac-mqtt-energy" / "state.json"


@dataclass(frozen=True)
class AppConfig:
    mqtt_host: str = "mqtt.example.local"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_client_id: str = "mac-mqtt-energy"
    discovery_prefix: str = "homeassistant"
    topic_prefix: str = "mac_mqtt_energy"
    device_id: str = "mac"
    device_name: str = "Mac"
    sample_interval_seconds: float = 30.0
    max_energy_gap_seconds: float = 300.0
    state_path: Path = DEFAULT_STATE_PATH
    publish_retain: bool = True
    verbose: bool = False

    def with_cli_overrides(self, *, verbose: bool) -> "AppConfig":
        if not verbose:
            return self
        return replace(self, verbose=True)

    @property
    def state_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/state"

    @property
    def availability_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/availability"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a TOML table at the root.")
    return data


def load_config(path: Path) -> AppConfig:
    data = _read_toml(path)
    return AppConfig(
        mqtt_host=str(data.get("mqtt_host", "mqtt.example.local")),
        mqtt_port=int(data.get("mqtt_port", 1883)),
        mqtt_username=_optional_str(data.get("mqtt_username")),
        mqtt_password=_optional_str(data.get("mqtt_password")),
        mqtt_client_id=str(data.get("mqtt_client_id", "mac-mqtt-energy")),
        discovery_prefix=str(data.get("discovery_prefix", "homeassistant")),
        topic_prefix=str(data.get("topic_prefix", "mac_mqtt_energy")).strip("/"),
        device_id=str(data.get("device_id", "mac")),
        device_name=str(data.get("device_name", "Mac")),
        sample_interval_seconds=float(data.get("sample_interval_seconds", 30.0)),
        max_energy_gap_seconds=float(data.get("max_energy_gap_seconds", 300.0)),
        state_path=Path(str(data.get("state_path", DEFAULT_STATE_PATH))).expanduser(),
        publish_retain=bool(data.get("publish_retain", True)),
        verbose=bool(data.get("verbose", False)),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
