"""Installer planning and config rendering helpers."""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import socket
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from ipaddress import ip_network
from pathlib import Path
from typing import Literal

from ha_mqtt_agent.config import AppConfig
from ha_mqtt_agent.network import (
    IFCONFIG_PATH,
    NETWORK_COMMAND_TIMEOUT_SECONDS,
    CommandResult,
    NetworkSensorReader,
)
from ha_mqtt_agent.providers.linux import (
    IP_COMMAND,
    LINUX_COMMAND_TIMEOUT_SECONDS,
    LinuxCommandResult,
    LinuxProvider,
)

LINUX_SERVICE_NAME = "ha-mqtt-agent"
LINUX_SERVICE_USER = "ha-mqtt-agent"
LINUX_CONFIG_PATH = "/etc/ha-mqtt-agent/config.toml"
LINUX_STATE_PATH = "/var/lib/ha-mqtt-agent/state.json"
LINUX_APP_HOME = "/opt/ha-mqtt-agent"
LINUX_BINARY_PATH = "/usr/local/bin/ha-mqtt-agent"
KNOWN_LINUX_OPTIONAL_PACKAGES = frozenset({"iw", "lm-sensors", "upower"})
RECOMMENDED_LINUX_OPTIONAL_PACKAGES = ("iw", "lm-sensors", "upower")
PackageManager = Literal["apt", "dnf", "pacman"]
InstallerCommandRunner = Callable[[Sequence[str], float], CommandResult | None]


@dataclass(frozen=True)
class LinuxInstallPlan:
    service_name: str
    service_user: str
    config_path: str
    state_path: str
    app_home: str
    binary_path: str
    package_manager: PackageManager | None
    optional_packages: tuple[str, ...]


@dataclass(frozen=True)
class InstallNetworkFacts:
    home_ssids: tuple[str, ...] = ()
    home_ipv4_cidrs: tuple[str, ...] = ()
    home_gateways: tuple[str, ...] = ()
    home_bssids: tuple[str, ...] = ()
    home_gateway_macs: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstallConfigFacts:
    hostname: str
    device_id: str
    device_name: str
    mqtt_client_id: str
    network: InstallNetworkFacts = InstallNetworkFacts()


def plan_linux_install(
    *,
    package_manager: PackageManager | None = None,
    enable_optional_sensors: bool = False,
    optional_packages: tuple[str, ...] = (),
) -> LinuxInstallPlan:
    selected_optional = _selected_optional_packages(
        enable_optional_sensors=enable_optional_sensors,
        optional_packages=optional_packages,
    )
    return LinuxInstallPlan(
        service_name=LINUX_SERVICE_NAME,
        service_user=LINUX_SERVICE_USER,
        config_path=LINUX_CONFIG_PATH,
        state_path=LINUX_STATE_PATH,
        app_home=LINUX_APP_HOME,
        binary_path=LINUX_BINARY_PATH,
        package_manager=package_manager or detect_linux_package_manager(),
        optional_packages=selected_optional,
    )


def detect_linux_package_manager() -> PackageManager | None:
    for name in ("apt", "dnf", "pacman"):
        if shutil.which(name) is not None:
            return name
    return None


def optional_package_install_command(
    package_manager: PackageManager,
    packages: tuple[str, ...],
) -> tuple[str, ...]:
    if not packages:
        return ()
    if package_manager == "apt":
        return ("apt-get", "install", "-y", *packages)
    if package_manager == "dnf":
        return ("dnf", "install", "-y", *packages)
    return ("pacman", "-S", "--needed", "--noconfirm", *packages)


def _selected_optional_packages(
    *,
    enable_optional_sensors: bool,
    optional_packages: tuple[str, ...],
) -> tuple[str, ...]:
    unknown = set(optional_packages) - KNOWN_LINUX_OPTIONAL_PACKAGES
    if unknown:
        raise ValueError("unknown optional packages: " + ", ".join(sorted(unknown)))
    if optional_packages:
        return tuple(dict.fromkeys(optional_packages))
    if enable_optional_sensors:
        return RECOMMENDED_LINUX_OPTIONAL_PACKAGES
    return ()


def detect_install_config_facts(
    *,
    system_name: str | None = None,
    hostname: str | None = None,
    command_runner: InstallerCommandRunner | None = None,
    linux_provider: LinuxProvider | None = None,
) -> InstallConfigFacts:
    resolved_hostname = _short_hostname(hostname or _local_hostname())
    device_id = _device_id_from_hostname(resolved_hostname)
    config = AppConfig(device_id=device_id, ping_targets=())
    return InstallConfigFacts(
        hostname=resolved_hostname,
        device_id=device_id,
        device_name=resolved_hostname or "Host",
        mqtt_client_id=config.resolved_mqtt_client_id,
        network=_detect_install_network_facts(
            system_name=system_name,
            config=config,
            command_runner=command_runner,
            linux_provider=linux_provider,
        ),
    )


def render_install_config(
    template: str,
    *,
    facts: InstallConfigFacts,
    state_path: str | None = None,
) -> str:
    replacements = {
        "mqtt_client_id": _toml_string(facts.mqtt_client_id),
        "device_id": _toml_string(facts.device_id),
        "device_name": _toml_string(facts.device_name),
        "home_ssids": _toml_array(facts.network.home_ssids),
        "home_ipv4_cidrs": _toml_array(facts.network.home_ipv4_cidrs),
        "home_gateways": _toml_array(facts.network.home_gateways),
        "home_bssids": _toml_array(facts.network.home_bssids),
        "home_gateway_macs": _toml_array(facts.network.home_gateway_macs),
    }
    if state_path is not None:
        replacements["state_path"] = _toml_string(state_path)

    rendered = template
    for key, value in replacements.items():
        rendered = _replace_toml_assignment(rendered, key=key, value=value)
    return rendered


def write_install_config(
    *,
    template_path: Path,
    output_path: Path,
    state_path: str | None = None,
) -> None:
    facts = detect_install_config_facts()
    rendered = render_install_config(
        template_path.read_text(encoding="utf-8"),
        facts=facts,
        state_path=state_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ha_mqtt_agent.installer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    render_parser = subparsers.add_parser(
        "render-config",
        help="Render an install config with local host and network defaults.",
    )
    render_parser.add_argument("--template", type=Path, required=True)
    render_parser.add_argument("--output", type=Path, required=True)
    render_parser.add_argument("--state-path")

    args = parser.parse_args(argv)
    if args.command == "render-config":
        write_install_config(
            template_path=args.template,
            output_path=args.output,
            state_path=args.state_path,
        )
        return 0
    return 2


def _detect_install_network_facts(
    *,
    system_name: str | None,
    config: AppConfig,
    command_runner: InstallerCommandRunner | None,
    linux_provider: LinuxProvider | None,
) -> InstallNetworkFacts:
    detected = system_name or platform.system()
    if detected == "Darwin":
        return _detect_macos_network_facts(config=config, command_runner=command_runner)
    if detected == "Linux":
        return _detect_linux_network_facts(
            config=config,
            command_runner=command_runner,
            linux_provider=linux_provider,
        )
    return InstallNetworkFacts()


def _detect_macos_network_facts(
    *,
    config: AppConfig,
    command_runner: InstallerCommandRunner | None,
) -> InstallNetworkFacts:
    runner = command_runner or _run_command
    sample = NetworkSensorReader(command_runner=runner).read(config)
    gateway_interfaces = tuple(
        gateway.interface for gateway in sample.default_gateways if gateway.interface is not None
    )
    preferred_interfaces = tuple(
        dict.fromkeys(
            interface
            for interface in (
                *gateway_interfaces,
                sample.wifi.interface,
                *(item.device for item in sample.ethernet if item.active),
            )
            if interface is not None
        )
    )
    return InstallNetworkFacts(
        home_ssids=_single_value_tuple(sample.wifi.ssid),
        home_ipv4_cidrs=_macos_ipv4_cidrs(runner, preferred_interfaces),
        home_gateways=tuple(dict.fromkeys(gateway.address for gateway in sample.default_gateways)),
        home_bssids=_single_value_tuple(sample.wifi.bssid),
        home_gateway_macs=tuple(
            dict.fromkeys(
                gateway.mac_address
                for gateway in sample.default_gateways
                if gateway.mac_address is not None
            )
        ),
    )


def _detect_linux_network_facts(
    *,
    config: AppConfig,
    command_runner: InstallerCommandRunner | None,
    linux_provider: LinuxProvider | None,
) -> InstallNetworkFacts:
    _ = config
    provider = linux_provider or LinuxProvider(command_runner=_linux_command_runner(command_runner))
    wifi = provider._read_wifi_status()
    gateways = provider._default_gateways() or ()
    gateway_interfaces = tuple(
        gateway.interface for gateway in gateways if gateway.interface is not None
    )
    return InstallNetworkFacts(
        home_ssids=_single_value_tuple(wifi.ssid),
        home_ipv4_cidrs=_linux_ipv4_cidrs(provider, gateway_interfaces),
        home_gateways=tuple(dict.fromkeys(gateway.address for gateway in gateways)),
        home_bssids=_single_value_tuple(wifi.bssid),
        home_gateway_macs=tuple(
            dict.fromkeys(gateway.mac_address for gateway in gateways if gateway.mac_address)
        ),
    )


def _linux_command_runner(
    runner: InstallerCommandRunner | None,
) -> Callable[[Sequence[str], float], LinuxCommandResult | None] | None:
    if runner is None:
        return None

    def wrapped(command: Sequence[str], timeout_seconds: float) -> LinuxCommandResult | None:
        result = runner(command, timeout_seconds)
        if result is None:
            return None
        return LinuxCommandResult(stdout=result.stdout, returncode=result.returncode)

    return wrapped


def _linux_ipv4_cidrs(
    provider: LinuxProvider,
    preferred_interfaces: Sequence[str],
) -> tuple[str, ...]:
    if not provider._command_available(IP_COMMAND):
        return ()
    result = provider._run(
        [IP_COMMAND, "-j", "addr", "show"],
        LINUX_COMMAND_TIMEOUT_SECONDS,
    )
    if result is None or result.returncode != 0:
        return ()
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ()
    if not isinstance(data, list):
        return ()

    preferred = set(preferred_interfaces)
    all_cidrs: list[str] = []
    preferred_cidrs: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        interface = _optional_text(item.get("ifname"))
        if interface is None or interface == "lo":
            continue
        cidrs = _ipv4_cidrs_from_linux_addr_item(item)
        all_cidrs.extend(cidrs)
        if interface in preferred:
            preferred_cidrs.extend(cidrs)
    return tuple(dict.fromkeys(preferred_cidrs or all_cidrs))


def _ipv4_cidrs_from_linux_addr_item(item: dict[str, object]) -> tuple[str, ...]:
    addr_info = item.get("addr_info")
    if not isinstance(addr_info, list):
        return ()
    cidrs = []
    for address in addr_info:
        if not isinstance(address, dict) or address.get("family") != "inet":
            continue
        local = _optional_text(address.get("local"))
        prefixlen = address.get("prefixlen")
        if local is None or not isinstance(prefixlen, int):
            continue
        cidr = _ipv4_cidr(local, prefixlen)
        if cidr is not None:
            cidrs.append(cidr)
    return tuple(cidrs)


def _macos_ipv4_cidrs(
    runner: InstallerCommandRunner,
    interfaces: Sequence[str],
) -> tuple[str, ...]:
    cidrs: list[str] = []
    for interface in interfaces:
        result = runner([IFCONFIG_PATH, interface], NETWORK_COMMAND_TIMEOUT_SECONDS)
        if result is None or result.returncode != 0:
            continue
        cidrs.extend(_ipv4_cidrs_from_ifconfig(result.stdout))
    return tuple(dict.fromkeys(cidrs))


def _ipv4_cidrs_from_ifconfig(output: str) -> tuple[str, ...]:
    cidrs = []
    for match in re.finditer(
        r"^\s*inet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+(0x[0-9a-fA-F]+)\b",
        output,
        flags=re.MULTILINE,
    ):
        prefixlen = _prefixlen_from_hex_netmask(match.group(2))
        if prefixlen is None:
            continue
        cidr = _ipv4_cidr(match.group(1), prefixlen)
        if cidr is not None:
            cidrs.append(cidr)
    return tuple(cidrs)


def _ipv4_cidr(address: str, prefixlen: int) -> str | None:
    try:
        network = ip_network(f"{address}/{prefixlen}", strict=False)
    except ValueError:
        return None
    if network.version != 4:
        return None
    return str(network)


def _prefixlen_from_hex_netmask(value: str) -> int | None:
    try:
        mask = int(value, 16)
    except ValueError:
        return None
    binary = f"{mask:032b}"
    if "01" in binary:
        return None
    return binary.count("1")


def _replace_toml_assignment(text: str, *, key: str, value: str) -> str:
    pattern = re.compile(rf"^(#\s*)?{re.escape(key)}\s*=.*$", flags=re.MULTILINE)
    replacement = f"{key} = {value}"
    rendered, count = pattern.subn(replacement, text, count=1)
    if count:
        return rendered
    suffix = "" if text.endswith("\n") else "\n"
    return f"{text}{suffix}{replacement}\n"


def _toml_array(values: Sequence[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _local_hostname() -> str:
    return socket.gethostname() or platform.node() or "host"


def _short_hostname(hostname: str) -> str:
    return hostname.strip().split(".", maxsplit=1)[0] or "host"


def _device_id_from_hostname(hostname: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", hostname.lower()).strip("-_")
    return normalized or "host"


def _single_value_tuple(value: str | None) -> tuple[str, ...]:
    return () if value is None else (value,)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _run_command(command: Sequence[str], timeout_seconds: float) -> CommandResult | None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return CommandResult(stdout=result.stdout, returncode=result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
