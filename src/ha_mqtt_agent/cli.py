"""Command-line interface for Home Assistant MQTT Agent."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config
from .energy import EnergyAccumulator
from .mqtt import (
    availability_message,
    discovery_messages,
    publish_messages,
    state_message,
)
from .sensors import IoregSensorReader


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
        "device_id": config.device_id,
        "device_name": config.device_name,
        "state_topic": config.state_topic,
        "availability_topic": config.availability_topic,
        "state_path": str(config.state_path),
        "sample_interval_seconds": config.sample_interval_seconds,
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
    print(f"device_id: {config.device_id}")
    print(f"device_name: {config.device_name}")
    print(f"state_topic: {config.state_topic}")
    print(f"availability_topic: {config.availability_topic}")
    print(f"state_path: {config.state_path}")
    print(f"sample_interval_seconds: {config.sample_interval_seconds}")
    print(f"verbose: {config.verbose}")
    return 0


def _sample_payload(config: AppConfig, *, update_energy: bool = True) -> dict[str, object]:
    sample = IoregSensorReader().read()
    accumulator = EnergyAccumulator(
        config.state_path,
        max_gap_seconds=config.max_energy_gap_seconds,
    )
    if update_energy:
        energy_kwh = accumulator.update(timestamp=sample.timestamp, power_w=sample.power_w)
    else:
        energy_kwh = accumulator.energy_kwh
    return sample.payload(energy_kwh=energy_kwh)


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
    return 0


def _publish_once(config: AppConfig, *, skip_discovery: bool) -> None:
    messages = []
    if not skip_discovery:
        messages.extend(discovery_messages(config))
    messages.append(availability_message(config, "online"))
    messages.append(state_message(config, _sample_payload(config)))
    publish_messages(config, messages)


def _handle_publish_once(config: AppConfig, *, skip_discovery: bool) -> int:
    _publish_once(config, skip_discovery=skip_discovery)
    return 0


def _handle_run(config: AppConfig, *, skip_discovery: bool, once: bool) -> int:
    while True:
        try:
            _publish_once(config, skip_discovery=skip_discovery)
        except Exception as exc:
            if once:
                raise
            print(f"publish failed: {exc}", file=sys.stderr, flush=True)
        else:
            skip_discovery = True
        if once:
            return 0
        time.sleep(config.sample_interval_seconds)


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
