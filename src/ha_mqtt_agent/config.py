"""Configuration support for Home Assistant MQTT Agent."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from hashlib import sha1
from ipaddress import ip_network
from pathlib import Path
from typing import Any, SupportsFloat, SupportsIndex

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "ha-mqtt-agent" / "config.toml"
DEFAULT_STATE_PATH = Path.home() / ".local" / "state" / "ha-mqtt-agent" / "state.json"
DEFAULT_WIFI_HELPER_PATH = (
    Path.home()
    / ".local"
    / "share"
    / "ha-mqtt-agent"
    / "HaMqttAgentWifiHelper.app"
    / "Contents"
    / "MacOS"
    / "HaMqttAgentWifiHelper"
)
MIN_SAMPLE_INTERVAL_SECONDS = 1.0
MIN_NETWORK_INTERVAL_SECONDS = 1.0
MIN_PING_TIMEOUT_SECONDS = 0.1
MIN_LOCATION_TIMEOUT_SECONDS = 0.1
MQTT_CLIENT_ID_MAX_BYTES = 23


@dataclass(frozen=True)
class PingTarget:
    id: str
    host: str
    name: str


DEFAULT_PING_TARGETS = (
    PingTarget(id="cloudflare_dns", host="1.1.1.1", name="Cloudflare DNS"),
    PingTarget(id="cloudflare_dns_secondary", host="1.0.0.1", name="Cloudflare DNS secondary"),
    PingTarget(id="google_dns", host="8.8.8.8", name="Google DNS"),
    PingTarget(id="google_dns_secondary", host="8.8.4.4", name="Google DNS secondary"),
)


@dataclass(frozen=True)
class AppConfig:
    mqtt_host: str = "mqtt.example.local"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_client_id: str | None = None
    discovery_prefix: str = "homeassistant"
    topic_prefix: str = "ha_mqtt_agent"
    device_id: str = "host"
    device_name: str = "Host"
    sample_interval_seconds: float = 5.0
    expire_after_seconds: float = 15.0
    max_energy_gap_seconds: float = 300.0
    network_interval_seconds: float = 60.0
    ping_timeout_seconds: float = 1.0
    ping_targets: tuple[PingTarget, ...] = DEFAULT_PING_TARGETS
    wifi_helper_path: Path = DEFAULT_WIFI_HELPER_PATH
    home_ssids: tuple[str, ...] = ()
    home_ipv4_cidrs: tuple[str, ...] = ()
    home_gateways: tuple[str, ...] = ()
    home_bssids: tuple[str, ...] = ()
    home_gateway_macs: tuple[str, ...] = ()
    publish_location: bool = False
    location_timeout_seconds: float = 3.0
    state_path: Path = DEFAULT_STATE_PATH
    publish_retain: bool = True
    verbose: bool = False

    def with_cli_overrides(self, *, verbose: bool) -> "AppConfig":
        if not verbose:
            return self
        return replace(self, verbose=True)

    @property
    def resolved_mqtt_client_id(self) -> str:
        return self.mqtt_client_id or _bounded_mqtt_client_id(f"ha-mqtt-agent-{self.device_id}")

    def resolved_mqtt_client_id_with_suffix(self, suffix: str) -> str:
        if not suffix:
            return self.resolved_mqtt_client_id
        return _bounded_mqtt_client_id(f"{self.resolved_mqtt_client_id}{suffix}")

    @property
    def state_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/state"

    @property
    def availability_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/availability"

    @property
    def location_attributes_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/location/attributes"


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
        mqtt_client_id=_optional_str(data.get("mqtt_client_id")),
        discovery_prefix=str(data.get("discovery_prefix", "homeassistant")),
        topic_prefix=str(data.get("topic_prefix", "ha_mqtt_agent")).strip("/"),
        device_id=str(data.get("device_id", "host")),
        device_name=str(data.get("device_name", "Host")),
        sample_interval_seconds=_float_at_least(
            data.get("sample_interval_seconds", 5.0),
            minimum=MIN_SAMPLE_INTERVAL_SECONDS,
            key="sample_interval_seconds",
        ),
        expire_after_seconds=_float_at_least(
            data.get("expire_after_seconds", 15.0),
            minimum=1.0,
            key="expire_after_seconds",
        ),
        max_energy_gap_seconds=_float_at_least(
            data.get("max_energy_gap_seconds", 300.0),
            minimum=1.0,
            key="max_energy_gap_seconds",
        ),
        network_interval_seconds=_float_at_least(
            data.get("network_interval_seconds", 60.0),
            minimum=MIN_NETWORK_INTERVAL_SECONDS,
            key="network_interval_seconds",
        ),
        ping_timeout_seconds=_float_at_least(
            data.get("ping_timeout_seconds", 1.0),
            minimum=MIN_PING_TIMEOUT_SECONDS,
            key="ping_timeout_seconds",
        ),
        ping_targets=_parse_ping_targets(data.get("ping_targets", DEFAULT_PING_TARGETS)),
        wifi_helper_path=Path(
            str(data.get("wifi_helper_path", DEFAULT_WIFI_HELPER_PATH))
        ).expanduser(),
        home_ssids=_parse_string_list(data.get("home_ssids", ()), key="home_ssids"),
        home_ipv4_cidrs=_parse_ipv4_cidrs(data.get("home_ipv4_cidrs", ())),
        home_gateways=_parse_string_list(data.get("home_gateways", ()), key="home_gateways"),
        home_bssids=_parse_mac_list(data.get("home_bssids", ()), key="home_bssids"),
        home_gateway_macs=_parse_mac_list(
            data.get("home_gateway_macs", ()),
            key="home_gateway_macs",
        ),
        publish_location=bool(data.get("publish_location", False)),
        location_timeout_seconds=_float_at_least(
            data.get("location_timeout_seconds", 3.0),
            minimum=MIN_LOCATION_TIMEOUT_SECONDS,
            key="location_timeout_seconds",
        ),
        state_path=Path(str(data.get("state_path", DEFAULT_STATE_PATH))).expanduser(),
        publish_retain=bool(data.get("publish_retain", True)),
        verbose=bool(data.get("verbose", False)),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _bounded_mqtt_client_id(value: str) -> str:
    if len(value.encode("utf-8")) <= MQTT_CLIENT_ID_MAX_BYTES:
        return value
    digest = sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"ha-mqtt-agent-{digest}"


def _float_at_least(value: object, *, minimum: float, key: str) -> float:
    if isinstance(value, str | bytes):
        parsed = float(value)
    elif isinstance(value, SupportsFloat | SupportsIndex):
        parsed = float(value)
    else:
        raise TypeError(f"{key} must be a number.")
    if parsed < minimum:
        raise ValueError(f"{key} must be at least {minimum:g} seconds.")
    return parsed


def _parse_ping_targets(value: object) -> tuple[PingTarget, ...]:
    if value == DEFAULT_PING_TARGETS:
        return DEFAULT_PING_TARGETS
    if not isinstance(value, list):
        raise TypeError("ping_targets must be a list of hosts or tables.")

    targets = tuple(_parse_ping_target(item) for item in value)
    ids = [target.id for target in targets]
    if len(ids) != len(set(ids)):
        raise ValueError("ping_targets ids must be unique.")
    return targets


def _parse_string_list(value: object, *, key: str) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return value
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list of strings.")

    items = tuple(str(item).strip() for item in value)
    if any(not item for item in items):
        raise ValueError(f"{key} entries must not be empty.")
    return items


def _parse_ipv4_cidrs(value: object) -> tuple[str, ...]:
    cidrs = _parse_string_list(value, key="home_ipv4_cidrs")
    for cidr in cidrs:
        ip_network(cidr, strict=False)
    return cidrs


def _parse_mac_list(value: object, *, key: str) -> tuple[str, ...]:
    items = _parse_string_list(value, key=key)
    normalized = tuple(item.lower() for item in items)
    for item in normalized:
        if not re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", item):
            raise ValueError(f"{key} entries must be colon-separated MAC addresses.")
    return normalized


def _parse_ping_target(value: object) -> PingTarget:
    if isinstance(value, str):
        host = value.strip()
        if not host:
            raise ValueError("ping_targets host entries must not be empty.")
        return PingTarget(id=_ping_target_id_from_host(host), host=host, name=host)

    if isinstance(value, dict):
        host = str(value.get("host", "")).strip()
        if not host:
            raise ValueError("ping_targets entries must include a non-empty host.")
        target_id = str(value.get("id") or _ping_target_id_from_host(host)).strip()
        name = str(value.get("name") or host).strip()
        if not re.fullmatch(r"[a-z0-9_]+", target_id):
            raise ValueError(
                "ping_targets ids must contain only lowercase letters, numbers, and underscores."
            )
        if not name:
            raise ValueError("ping_targets names must not be empty.")
        return PingTarget(id=target_id, host=host, name=name)

    raise TypeError("ping_targets entries must be hosts or tables.")


def _ping_target_id_from_host(host: str) -> str:
    target_id = re.sub(r"[^a-z0-9]+", "_", host.lower()).strip("_")
    if not target_id:
        raise ValueError("ping_targets host entries must produce a non-empty id.")
    if target_id[0].isdigit():
        target_id = f"ip_{target_id}"
    return target_id
