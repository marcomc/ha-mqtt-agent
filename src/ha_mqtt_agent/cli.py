"""Command-line interface for Home Assistant MQTT Agent."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import SupportsFloat, SupportsIndex

from . import __version__
from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config
from .energy import EnergyAccumulator
from .mqtt import (
    MqttMessage,
    availability_message,
    discovery_messages,
    location_attributes_message,
    publish_messages,
    state_message,
)
from .network import NetworkSensorReader, NetworkSnapshotCache
from .sensors import IoregSensorReader

OPEN_PATH = "/usr/bin/open"
MAX_PUBLISH_RETRY_SECONDS = 300.0
MIN_PUBLISH_RETRY_SECONDS = 30.0
LAST_LOCATION_KEY = "last_location"
LAST_GEOCODED_LOCATION_KEY = "last_geocoded_location"
GEOCODED_LOCATION_PAYLOAD_KEYS = {
    "state": "geocoded_location",
    "name": "geocoded_location_name",
    "country": "geocoded_location_country",
    "iso_country_code": "geocoded_location_iso_country_code",
    "time_zone": "geocoded_location_time_zone",
    "administrative_area": "geocoded_location_administrative_area",
    "sub_administrative_area": "geocoded_location_sub_administrative_area",
    "postal_code": "geocoded_location_postal_code",
    "locality": "geocoded_location_locality",
    "sub_locality": "geocoded_location_sub_locality",
    "thoroughfare": "geocoded_location_thoroughfare",
    "sub_thoroughfare": "geocoded_location_sub_thoroughfare",
    "areas_of_interest": "geocoded_location_areas_of_interest",
    "ocean": "geocoded_location_ocean",
    "inland_water": "geocoded_location_inland_water",
    "error": "geocoded_location_error",
}


def format_main_help() -> str:
    return "\n".join(
        [
            "usage: ha-mqtt-agent [--version] [--config PATH] [--verbose] <command>",
            "",
            "Publish local host telemetry to Home Assistant over MQTT discovery.",
            "",
            "Commands:",
            "  info          Show resolved configuration and runtime metadata",
            "  sample        Read local power and battery telemetry once",
            "  authorize-wifi Ask macOS for permission to read the Wi-Fi SSID",
            "  publish-once  Publish discovery and one telemetry sample",
            "  run           Publish telemetry continuously",
            "",
            "Run `ha-mqtt-agent <command> --help` for command-specific help.",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show the installed version and exit.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Optional config file. Defaults to {DEFAULT_CONFIG_PATH}.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose mode for this run.",
    )

    subparsers = parser.add_subparsers(dest="command")

    info_parser = subparsers.add_parser(
        "info",
        help="Show resolved configuration and runtime metadata.",
    )
    info_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )

    sample_parser = subparsers.add_parser(
        "sample",
        help="Read local power and battery telemetry once.",
    )
    sample_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )

    authorize_wifi_parser = subparsers.add_parser(
        "authorize-wifi",
        help="Ask macOS for Location permission so the Wi-Fi SSID can be read.",
    )
    authorize_wifi_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )

    publish_once_parser = subparsers.add_parser(
        "publish-once",
        help="Publish Home Assistant discovery and one telemetry sample.",
    )
    publish_once_parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Publish only state and availability topics.",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Publish Home Assistant discovery and telemetry continuously.",
    )
    run_parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Publish only state and availability topics.",
    )
    run_parser.add_argument(
        "--once",
        action="store_true",
        help="Publish one sample and exit.",
    )

    return parser


def _info_payload(config: AppConfig, config_path: Path) -> dict[str, object]:
    return {
        "project_name": "Home Assistant MQTT Agent",
        "cli_name": "ha-mqtt-agent",
        "package_name": "ha_mqtt_agent",
        "version": __version__,
        "config_path": str(config_path),
        "config_exists": config_path.exists(),
        "mqtt_host": config.mqtt_host,
        "mqtt_port": config.mqtt_port,
        "mqtt_client_id": config.resolved_mqtt_client_id,
        "device_id": config.device_id,
        "device_name": config.device_name,
        "state_topic": config.state_topic,
        "availability_topic": config.availability_topic,
        "state_path": str(config.state_path),
        "sample_interval_seconds": config.sample_interval_seconds,
        "network_interval_seconds": config.network_interval_seconds,
        "ping_timeout_seconds": config.ping_timeout_seconds,
        "wifi_helper_path": str(config.wifi_helper_path),
        "wifi_helper_exists": config.wifi_helper_path.exists(),
        "home_ssids": list(config.home_ssids),
        "home_ipv4_cidrs": list(config.home_ipv4_cidrs),
        "home_gateways": list(config.home_gateways),
        "home_bssids": list(config.home_bssids),
        "home_gateway_macs": list(config.home_gateway_macs),
        "publish_location": config.publish_location,
        "location_timeout_seconds": config.location_timeout_seconds,
        "ping_targets": [
            {"id": target.id, "host": target.host, "name": target.name}
            for target in config.ping_targets
        ],
    }


def _handle_info(config: AppConfig, config_path: Path, as_json: bool) -> int:
    payload = _info_payload(config=config, config_path=config_path)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"project_name: {payload['project_name']}")
    print(f"cli_name: {payload['cli_name']}")
    print(f"package_name: {payload['package_name']}")
    print(f"version: {payload['version']}")
    print(f"config_path: {payload['config_path']}")
    print(f"config_exists: {payload['config_exists']}")
    print(f"mqtt_host: {config.mqtt_host}")
    print(f"mqtt_port: {config.mqtt_port}")
    print(f"mqtt_client_id: {config.resolved_mqtt_client_id}")
    print(f"device_id: {config.device_id}")
    print(f"device_name: {config.device_name}")
    print(f"state_topic: {config.state_topic}")
    print(f"availability_topic: {config.availability_topic}")
    print(f"state_path: {config.state_path}")
    print(f"sample_interval_seconds: {config.sample_interval_seconds}")
    print(f"network_interval_seconds: {config.network_interval_seconds}")
    print(f"ping_timeout_seconds: {config.ping_timeout_seconds}")
    print(f"wifi_helper_path: {config.wifi_helper_path}")
    print(f"wifi_helper_exists: {config.wifi_helper_path.exists()}")
    print(f"home_ssids: {', '.join(config.home_ssids)}")
    print(f"home_ipv4_cidrs: {', '.join(config.home_ipv4_cidrs)}")
    print(f"home_gateways: {', '.join(config.home_gateways)}")
    print(f"home_bssids: {', '.join(config.home_bssids)}")
    print(f"home_gateway_macs: {', '.join(config.home_gateway_macs)}")
    print(f"publish_location: {config.publish_location}")
    print(f"location_timeout_seconds: {config.location_timeout_seconds}")
    print(
        "ping_targets: "
        + ", ".join(f"{target.name} ({target.host})" for target in config.ping_targets)
    )
    print(f"verbose: {config.verbose}")
    return 0


def _handle_authorize_wifi(config: AppConfig, as_json: bool) -> int:
    if not config.wifi_helper_path.exists():
        payload = {
            "ok": False,
            "error": "wifi_helper_missing",
            "wifi_helper_path": str(config.wifi_helper_path),
        }
        if as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 1
        print(f"Wi-Fi helper is missing: {config.wifi_helper_path}", file=sys.stderr)
        print("Run `make install-wifi-helper` from the project checkout.", file=sys.stderr)
        return 1

    try:
        result = _run_wifi_helper_for_cli(config.wifi_helper_path, ["--authorize"], timeout=35)
    except subprocess.TimeoutExpired:
        payload = {
            "ok": False,
            "error": "wifi_authorization_timed_out",
            "wifi_helper_path": str(config.wifi_helper_path),
        }
        if as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("Wi-Fi authorization timed out.", file=sys.stderr)
        return 1
    if as_json:
        print(result.stdout.strip())
    else:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            print(result.stdout.strip())
        else:
            print(f"authorization_status: {payload.get('authorization_status')}")
            print(f"wifi_ssid: {payload.get('ssid')}")
            print(f"wifi_signal_dbm: {payload.get('signal_dbm')}")
            print(f"latitude: {payload.get('latitude')}")
            print(f"longitude: {payload.get('longitude')}")
            print(f"location_accuracy_m: {payload.get('location_accuracy_m')}")
            print(f"location_cached: {payload.get('location_cached')}")
            print(f"location_last_seen: {payload.get('location_last_seen')}")
            print(f"location_error: {payload.get('location_error')}")
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
    return result.returncode


def _run_wifi_helper_for_cli(
    helper_path: Path,
    args: Sequence[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    app_path = _app_bundle_path(helper_path)
    if app_path is None:
        return subprocess.run(
            [str(helper_path), *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )

    with tempfile.TemporaryDirectory(prefix="ha-mqtt-agent-wifi-") as output_dir:
        output_path = Path(output_dir) / "helper.json"
        result = subprocess.run(
            [
                OPEN_PATH,
                "-W",
                "-n",
                str(app_path),
                "--args",
                *args,
                "--output",
                str(output_path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
        stdout = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=stdout or result.stdout,
            stderr=result.stderr,
        )


def _app_bundle_path(path: Path) -> Path | None:
    for parent in (path, *path.parents):
        if parent.suffix == ".app":
            return parent
    return None


def _sample_payload(
    config: AppConfig,
    *,
    update_energy: bool = True,
    network_cache: NetworkSnapshotCache | None = None,
) -> dict[str, object]:
    sample = IoregSensorReader().read()
    accumulator = EnergyAccumulator(
        config.state_path,
        max_gap_seconds=config.max_energy_gap_seconds,
    )
    if update_energy:
        energy_kwh = accumulator.update(timestamp=sample.timestamp, power_w=sample.power_w)
    else:
        energy_kwh = accumulator.energy_kwh
    payload = sample.payload(energy_kwh=energy_kwh)
    network_reader = NetworkSensorReader()
    if network_cache is None:
        payload.update(network_reader.read(config).payload())
    else:
        payload.update(network_cache.read(network_reader, config).payload())
    _apply_location_cache(payload, config, enabled=config.publish_location, persist=update_energy)
    return payload


def _apply_location_cache(
    payload: dict[str, object],
    config: AppConfig,
    *,
    enabled: bool,
    persist: bool,
) -> None:
    payload["location_cached"] = False
    payload["location_last_seen"] = None
    payload["geocoded_location_cached"] = False
    if not enabled:
        return

    latitude = _float_payload_value(payload.get("latitude"))
    longitude = _float_payload_value(payload.get("longitude"))
    accuracy_m = _float_payload_value(payload.get("location_accuracy_m"))
    timestamp = _text_payload_value(payload.get("timestamp"))

    if latitude is not None and longitude is not None:
        payload["location_last_seen"] = timestamp
        if persist:
            _write_last_location(
                config.state_path,
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "accuracy_m": accuracy_m,
                    "timestamp": timestamp,
                },
            )
        _apply_geocoded_location_cache(
            payload,
            config,
            location_is_cached=False,
            persist=bool(persist and timestamp is not None),
            timestamp=timestamp,
        )
        return

    cached = _read_last_location(config.state_path)
    if cached is None:
        return

    payload["latitude"] = cached["latitude"]
    payload["longitude"] = cached["longitude"]
    payload["location_accuracy_m"] = cached["accuracy_m"]
    payload["location_cached"] = True
    payload["location_last_seen"] = cached["timestamp"]
    _apply_geocoded_location_cache(
        payload,
        config,
        location_is_cached=True,
        persist=persist,
        timestamp=_text_payload_value(cached["timestamp"]),
    )


def _apply_geocoded_location_cache(
    payload: dict[str, object],
    config: AppConfig,
    *,
    location_is_cached: bool,
    persist: bool,
    timestamp: str | None,
) -> None:
    current = _current_geocoded_location(payload, timestamp=timestamp)
    if current is not None:
        if persist:
            _write_last_geocoded_location(config.state_path, current)
        return

    if not location_is_cached:
        return

    cached = _read_last_geocoded_location(config.state_path)
    generated = cached or _reverse_geocode_cached_location(config, payload, timestamp=timestamp)
    if generated is None:
        return

    for field, payload_key in GEOCODED_LOCATION_PAYLOAD_KEYS.items():
        if field in generated:
            payload[payload_key] = generated[field]
    payload["geocoded_location_cached"] = True
    if persist and generated is not cached:
        _write_last_geocoded_location(config.state_path, generated)


def _current_geocoded_location(
    payload: dict[str, object],
    *,
    timestamp: str | None,
) -> dict[str, object] | None:
    state = _text_payload_value(payload.get("geocoded_location"))
    if state is None or timestamp is None:
        return None

    geocoded: dict[str, object] = {
        "state": state,
        "timestamp": timestamp,
    }
    for field, payload_key in GEOCODED_LOCATION_PAYLOAD_KEYS.items():
        if field == "state":
            continue
        if field == "areas_of_interest":
            areas_of_interest = _text_list_payload_value(payload.get(payload_key))
            if areas_of_interest:
                geocoded[field] = areas_of_interest
            continue
        value = _text_payload_value(payload.get(payload_key))
        if value is not None:
            geocoded[field] = value
    return geocoded


def _reverse_geocode_cached_location(
    config: AppConfig,
    payload: dict[str, object],
    *,
    timestamp: str | None,
) -> dict[str, object] | None:
    if timestamp is None or not config.wifi_helper_path.exists():
        return None
    latitude = _float_payload_value(payload.get("latitude"))
    longitude = _float_payload_value(payload.get("longitude"))
    if latitude is None or longitude is None:
        return None

    try:
        result = _run_wifi_helper_for_cli(
            config.wifi_helper_path,
            [
                "--reverse-geocode",
                "--latitude",
                str(latitude),
                "--longitude",
                str(longitude),
                "--geocode-timeout",
                f"{config.location_timeout_seconds:g}",
            ],
            timeout=5 + config.location_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return _geocoded_location_from_helper_output(result.stdout, timestamp=timestamp)


def _read_last_location(state_path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    location = data.get(LAST_LOCATION_KEY)
    if not isinstance(location, dict):
        return None

    latitude = _float_payload_value(location.get("latitude"))
    longitude = _float_payload_value(location.get("longitude"))
    timestamp = _text_payload_value(location.get("timestamp"))
    if latitude is None or longitude is None or timestamp is None:
        return None
    return {
        "latitude": latitude,
        "longitude": longitude,
        "accuracy_m": _float_payload_value(location.get("accuracy_m")),
        "timestamp": timestamp,
    }


def _read_last_geocoded_location(state_path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    geocoded = data.get(LAST_GEOCODED_LOCATION_KEY)
    if not isinstance(geocoded, dict):
        return None
    return _geocoded_location_from_mapping(geocoded)


def _geocoded_location_from_helper_output(
    output: str,
    *,
    timestamp: str,
) -> dict[str, object] | None:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    geocoded = data.get("geocoded_location")
    if not isinstance(geocoded, dict):
        return None
    return _geocoded_location_from_mapping(geocoded, timestamp=timestamp)


def _geocoded_location_from_mapping(
    geocoded: dict[object, object],
    *,
    timestamp: str | None = None,
) -> dict[str, object] | None:
    state = _text_payload_value(geocoded.get("state"))
    resolved_timestamp = timestamp or _text_payload_value(geocoded.get("timestamp"))
    if state is None or resolved_timestamp is None:
        return None

    payload: dict[str, object] = {
        "state": state,
        "timestamp": resolved_timestamp,
    }
    for field in GEOCODED_LOCATION_PAYLOAD_KEYS:
        if field == "state":
            continue
        if field == "areas_of_interest":
            areas_of_interest = _text_list_payload_value(geocoded.get(field))
            if areas_of_interest:
                payload[field] = areas_of_interest
            continue
        value = _text_payload_value(geocoded.get(field))
        if value is not None:
            payload[field] = value
    return payload


def _write_last_location(state_path: Path, location: dict[str, object]) -> None:
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[LAST_LOCATION_KEY] = location
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _write_last_geocoded_location(state_path: Path, location: dict[str, object]) -> None:
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[LAST_GEOCODED_LOCATION_KEY] = location
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _float_payload_value(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str | bytes | SupportsFloat | SupportsIndex):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text_payload_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text_list_payload_value(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = _text_payload_value(item)
        if text is not None:
            items.append(text)
    return items


def _handle_sample(config: AppConfig, as_json: bool) -> int:
    payload = _sample_payload(config, update_energy=False)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"host_name: {payload['host_name']}")
    print(f"power_w: {payload['power_w']}")
    print(f"energy_kwh: {payload['energy_kwh']}")
    print(f"uptime_seconds: {payload['uptime_seconds']}")
    print(f"battery_percent: {payload['battery_percent']}")
    print(f"battery_max_capacity_percent: {payload['battery_max_capacity_percent']}")
    print(f"battery_max_capacity_mah: {payload['battery_max_capacity_mah']}")
    print(f"battery_temperature_c: {payload['battery_temperature_c']}")
    print(f"battery_status: {payload['battery_status']}")
    print(f"wifi_ssid: {payload['wifi_ssid']}")
    print(f"wifi_bssid: {payload['wifi_bssid']}")
    print(f"wifi_signal_dbm: {payload['wifi_signal_dbm']}")
    print(f"wifi_signal_percent: {payload['wifi_signal_percent']}")
    print(f"ipv4_addresses: {payload['ipv4_addresses']}")
    print(f"default_gateways: {payload['default_gateways']}")
    print(f"default_gateway_interfaces: {payload['default_gateway_interfaces']}")
    print(f"gateway_macs: {payload['gateway_macs']}")
    print(f"home_network_present: {payload['home_network_present']}")
    print(f"latitude: {payload['latitude']}")
    print(f"longitude: {payload['longitude']}")
    print(f"location_accuracy_m: {payload['location_accuracy_m']}")
    print(f"location_cached: {payload['location_cached']}")
    print(f"location_last_seen: {payload['location_last_seen']}")
    print(f"location_error: {payload['location_error']}")
    print(f"geocoded_location: {payload['geocoded_location']}")
    print(f"geocoded_location_cached: {payload['geocoded_location_cached']}")
    print(f"geocoded_location_error: {payload['geocoded_location_error']}")
    print(f"ethernet_active_count: {payload['ethernet_active_count']}")
    print(f"ethernet_active_interfaces: {payload['ethernet_active_interfaces']}")
    for target in config.ping_targets:
        print(f"ping_{target.id}_ms: {payload[f'ping_{target.id}_ms']}")
    return 0


def _publish_once(
    config: AppConfig,
    *,
    skip_discovery: bool,
    network_cache: NetworkSnapshotCache | None = None,
    client_id_suffix: str = "",
) -> None:
    def messages() -> Iterable[MqttMessage]:
        if not skip_discovery:
            yield from discovery_messages(config)
        yield availability_message(config, "online")
        payload = _sample_payload(config, network_cache=network_cache)
        yield state_message(config, payload)
        location_message = location_attributes_message(config, payload)
        if location_message is not None:
            yield location_message

    publish_messages(config, messages(), client_id_suffix=client_id_suffix)


def _handle_publish_once(config: AppConfig, *, skip_discovery: bool) -> int:
    _publish_once(
        config,
        skip_discovery=skip_discovery,
        client_id_suffix=f"-manual-{os.getpid()}",
    )
    return 0


def _handle_run(config: AppConfig, *, skip_discovery: bool, once: bool) -> int:
    network_cache = NetworkSnapshotCache()
    failure_count = 0
    while True:
        try:
            _publish_once(
                config,
                skip_discovery=skip_discovery,
                network_cache=network_cache,
                client_id_suffix=f"-once-{os.getpid()}" if once else "",
            )
        except Exception as exc:
            if once:
                raise
            failure_count += 1
            print(f"publish failed: {exc}", file=sys.stderr, flush=True)
        else:
            skip_discovery = True
            failure_count = 0
        if once:
            return 0
        time.sleep(_next_publish_delay(config, failure_count))


def _next_publish_delay(config: AppConfig, failure_count: int) -> float:
    if failure_count <= 0:
        return config.sample_interval_seconds
    initial_delay = max(config.sample_interval_seconds, MIN_PUBLISH_RETRY_SECONDS)
    return float(min(initial_delay * (2 ** (failure_count - 1)), MAX_PUBLISH_RETRY_SECONDS))


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list or args_list == ["--help"] or args_list == ["-h"]:
        print(format_main_help())
        return 0

    if args_list == ["--version"]:
        print(__version__)
        return 0

    parser = build_parser()
    args = parser.parse_args(args_list)
    config = load_config(args.config).with_cli_overrides(verbose=args.verbose)

    if args.command == "info":
        as_json = bool(getattr(args, "json", False))
        return _handle_info(config=config, config_path=args.config, as_json=as_json)
    if args.command == "sample":
        as_json = bool(getattr(args, "json", False))
        return _handle_sample(config=config, as_json=as_json)
    if args.command == "authorize-wifi":
        as_json = bool(getattr(args, "json", False))
        return _handle_authorize_wifi(config=config, as_json=as_json)
    if args.command == "publish-once":
        return _handle_publish_once(
            config=config,
            skip_discovery=bool(getattr(args, "skip_discovery", False)),
        )
    if args.command == "run":
        return _handle_run(
            config=config,
            skip_discovery=bool(getattr(args, "skip_discovery", False)),
            once=bool(getattr(args, "once", False)),
        )

    print(format_main_help())
    return 0
