"""Network telemetry collection for macOS hosts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .config import AppConfig, PingTarget

AIRPORT_PATH = (
    "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
)
NETWORKSETUP_PATH = "/usr/sbin/networksetup"
PING_PATH = "/sbin/ping"
SYSTEM_PROFILER_PATH = "/usr/sbin/system_profiler"
IFCONFIG_PATH = "/sbin/ifconfig"
NETWORK_COMMAND_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    returncode: int


CommandRunner = Callable[[Sequence[str], float], CommandResult | None]


@dataclass(frozen=True)
class HardwarePort:
    name: str
    device: str
    ethernet_address: str | None = None


@dataclass(frozen=True)
class WifiStatus:
    interface: str | None
    ssid: str | None
    signal_dbm: int | None
    signal_percent: int | None


@dataclass(frozen=True)
class EthernetStatus:
    name: str
    device: str
    active: bool
    ipv4_addresses: tuple[str, ...]


@dataclass(frozen=True)
class PingResult:
    target: PingTarget
    latency_ms: float | None


@dataclass(frozen=True)
class NetworkSample:
    wifi: WifiStatus
    ethernet: tuple[EthernetStatus, ...]
    pings: tuple[PingResult, ...]

    def payload(self) -> dict[str, object]:
        active_ethernet = [item for item in self.ethernet if item.active]
        payload: dict[str, object] = {
            "wifi_interface": self.wifi.interface,
            "wifi_ssid": self.wifi.ssid,
            "wifi_signal_dbm": self.wifi.signal_dbm,
            "wifi_signal_percent": self.wifi.signal_percent,
            "ethernet_active_count": len(active_ethernet),
            "ethernet_active_interfaces": ", ".join(item.device for item in active_ethernet),
            "ethernet_interfaces": [
                {
                    "name": item.name,
                    "device": item.device,
                    "active": item.active,
                    "ipv4_addresses": list(item.ipv4_addresses),
                }
                for item in self.ethernet
            ],
        }
        for ping in self.pings:
            payload[f"ping_{ping.target.id}_ms"] = _round_optional(ping.latency_ms, 3)
        return payload


class NetworkSnapshotCache:
    """Cache slower network probes while the main telemetry loop keeps publishing."""

    def __init__(self) -> None:
        self._last_refresh_monotonic: float | None = None
        self._sample: NetworkSample | None = None

    def read(self, reader: "NetworkSensorReader", config: AppConfig) -> NetworkSample:
        now = time.monotonic()
        if (
            self._sample is None
            or self._last_refresh_monotonic is None
            or now - self._last_refresh_monotonic >= config.network_interval_seconds
        ):
            self._sample = reader.read(config)
            self._last_refresh_monotonic = now
        return self._sample


class NetworkSensorReader:
    """Read Wi-Fi, wired interface, and configured ping telemetry."""

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self._run = command_runner or _run_command

    def read(self, config: AppConfig) -> NetworkSample:
        hardware_ports = _parse_hardware_ports(
            self._run(
                [NETWORKSETUP_PATH, "-listallhardwareports"],
                NETWORK_COMMAND_TIMEOUT_SECONDS,
            ),
        )
        wifi_interface = _wifi_interface(hardware_ports)
        wifi = self._wifi_status(wifi_interface, config=config)
        ethernet = self._ethernet_statuses(hardware_ports, wifi_interface)
        pings = tuple(
            self._ping(target, config.ping_timeout_seconds) for target in config.ping_targets
        )
        return NetworkSample(wifi=wifi, ethernet=ethernet, pings=pings)

    def _wifi_status(self, wifi_interface: str | None, *, config: AppConfig) -> WifiStatus:
        helper = self._wifi_helper_status(config)
        if helper.ssid is not None and not _is_redacted_text(helper.ssid):
            return helper

        networksetup_ssid = self._networksetup_wifi_ssid(wifi_interface)

        airport = self._airport_wifi_status(wifi_interface)
        if airport.ssid is not None or airport.signal_dbm is not None:
            if _is_redacted_text(airport.ssid) and networksetup_ssid is not None:
                return WifiStatus(
                    interface=airport.interface,
                    ssid=networksetup_ssid,
                    signal_dbm=airport.signal_dbm,
                    signal_percent=airport.signal_percent,
                )
            return airport

        profiler = self._system_profiler_wifi_status(wifi_interface)
        if profiler.ssid is not None or profiler.signal_dbm is not None:
            if _is_redacted_text(profiler.ssid) and networksetup_ssid is not None:
                return WifiStatus(
                    interface=profiler.interface,
                    ssid=networksetup_ssid,
                    signal_dbm=profiler.signal_dbm,
                    signal_percent=profiler.signal_percent,
                )
            return profiler

        return WifiStatus(
            interface=wifi_interface,
            ssid=networksetup_ssid,
            signal_dbm=None,
            signal_percent=None,
        )

    def _wifi_helper_status(self, config: AppConfig) -> WifiStatus:
        if not config.wifi_helper_path.exists():
            return WifiStatus(
                interface=None,
                ssid=None,
                signal_dbm=None,
                signal_percent=None,
            )
        result = self._run(
            [str(config.wifi_helper_path), "--json"],
            NETWORK_COMMAND_TIMEOUT_SECONDS,
        )
        if result is None or result.returncode != 0:
            return WifiStatus(
                interface=None,
                ssid=None,
                signal_dbm=None,
                signal_percent=None,
            )
        return _parse_wifi_helper_status(result.stdout)

    def _airport_wifi_status(self, wifi_interface: str | None) -> WifiStatus:
        airport_command = _airport_command()
        if airport_command is None:
            return WifiStatus(
                interface=wifi_interface,
                ssid=None,
                signal_dbm=None,
                signal_percent=None,
            )
        result = self._run([airport_command, "-I"], NETWORK_COMMAND_TIMEOUT_SECONDS)
        if result is None or result.returncode != 0:
            return WifiStatus(
                interface=wifi_interface,
                ssid=None,
                signal_dbm=None,
                signal_percent=None,
            )
        fields = _parse_colon_fields(result.stdout)
        signal_dbm = _int_value(fields.get("agrCtlRSSI"))
        return WifiStatus(
            interface=wifi_interface,
            ssid=fields.get("SSID"),
            signal_dbm=signal_dbm,
            signal_percent=_wifi_signal_percent(signal_dbm),
        )

    def _system_profiler_wifi_status(self, wifi_interface: str | None) -> WifiStatus:
        result = self._run(
            [SYSTEM_PROFILER_PATH, "SPAirPortDataType", "-json"],
            NETWORK_COMMAND_TIMEOUT_SECONDS,
        )
        if result is None or result.returncode != 0:
            return WifiStatus(
                interface=wifi_interface,
                ssid=None,
                signal_dbm=None,
                signal_percent=None,
            )
        return _parse_system_profiler_wifi(result.stdout, wifi_interface=wifi_interface)

    def _networksetup_wifi_ssid(self, wifi_interface: str | None) -> str | None:
        if wifi_interface is None:
            return None
        result = self._run(
            [NETWORKSETUP_PATH, "-getairportnetwork", wifi_interface],
            NETWORK_COMMAND_TIMEOUT_SECONDS,
        )
        if result is None or result.returncode != 0:
            return None
        match = re.search(r"Current Wi-Fi Network:\s*(.+)", result.stdout)
        if match is None:
            return None
        return match.group(1).strip() or None

    def _ethernet_statuses(
        self,
        hardware_ports: Sequence[HardwarePort],
        wifi_interface: str | None,
    ) -> tuple[EthernetStatus, ...]:
        statuses = []
        for port in hardware_ports:
            if not _is_wired_port(port, wifi_interface=wifi_interface):
                continue
            result = self._run([IFCONFIG_PATH, port.device], NETWORK_COMMAND_TIMEOUT_SECONDS)
            status_text = "" if result is None else result.stdout
            statuses.append(
                EthernetStatus(
                    name=port.name,
                    device=port.device,
                    active=_interface_is_active(status_text),
                    ipv4_addresses=_ipv4_addresses(status_text),
                )
            )
        return tuple(statuses)

    def _ping(self, target: PingTarget, timeout_seconds: float) -> PingResult:
        timeout_ms = max(1, int(timeout_seconds * 1000))
        result = self._run(
            [PING_PATH, "-n", "-c", "1", "-W", str(timeout_ms), target.host],
            timeout_seconds + 1,
        )
        if result is None:
            return PingResult(target=target, latency_ms=None)
        return PingResult(target=target, latency_ms=_parse_ping_latency_ms(result.stdout))


def _run_command(command: Sequence[str], timeout_seconds: float) -> CommandResult | None:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    return CommandResult(stdout=result.stdout, returncode=result.returncode)


def _parse_hardware_ports(result: CommandResult | None) -> tuple[HardwarePort, ...]:
    if result is None or result.returncode != 0:
        return ()

    ports = []
    current: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                port = _hardware_port_from_fields(current)
                if port is not None:
                    ports.append(port)
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.strip()] = value.strip()

    if current:
        port = _hardware_port_from_fields(current)
        if port is not None:
            ports.append(port)

    return tuple(ports)


def _hardware_port_from_fields(fields: dict[str, str]) -> HardwarePort | None:
    name = fields.get("Hardware Port")
    device = fields.get("Device")
    if not name or not device:
        return None
    return HardwarePort(
        name=name,
        device=device,
        ethernet_address=fields.get("Ethernet Address"),
    )


def _wifi_interface(hardware_ports: Sequence[HardwarePort]) -> str | None:
    for port in hardware_ports:
        if port.name.casefold() in {"wi-fi", "wifi", "airport"}:
            return port.device
    return None


def _airport_command() -> str | None:
    return shutil.which(AIRPORT_PATH) or shutil.which("airport")


def _parse_colon_fields(output: str) -> dict[str, str]:
    fields = {}
    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _parse_system_profiler_wifi(output: str, *, wifi_interface: str | None) -> WifiStatus:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return WifiStatus(
            interface=wifi_interface,
            ssid=None,
            signal_dbm=None,
            signal_percent=None,
        )

    for interface in _system_profiler_interfaces(data):
        if wifi_interface is not None and interface.get("_name") != wifi_interface:
            continue
        current = interface.get("spairport_current_network_information")
        if not isinstance(current, dict):
            continue
        ssid = _optional_text(current.get("_name"))
        signal_dbm = _signal_noise_dbm(_optional_text(current.get("spairport_signal_noise")))
        return WifiStatus(
            interface=_optional_text(interface.get("_name")) or wifi_interface,
            ssid=ssid,
            signal_dbm=signal_dbm,
            signal_percent=_wifi_signal_percent(signal_dbm),
        )

    return WifiStatus(
        interface=wifi_interface,
        ssid=None,
        signal_dbm=None,
        signal_percent=None,
    )


def _parse_wifi_helper_status(output: str) -> WifiStatus:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return WifiStatus(
            interface=None,
            ssid=None,
            signal_dbm=None,
            signal_percent=None,
        )
    signal_dbm = _int_value(_optional_text(data.get("signal_dbm")))
    return WifiStatus(
        interface=_optional_text(data.get("interface")),
        ssid=_optional_text(data.get("ssid")),
        signal_dbm=signal_dbm,
        signal_percent=_wifi_signal_percent(signal_dbm),
    )


def _system_profiler_interfaces(data: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(data, dict):
        return ()
    items = data.get("SPAirPortDataType")
    if not isinstance(items, list):
        return ()
    interfaces: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        nested = item.get("spairport_airport_interfaces")
        if isinstance(nested, list):
            interfaces.extend(interface for interface in nested if isinstance(interface, dict))
    return tuple(interfaces)


def _signal_noise_dbm(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"(-?\d+)\s*dBm", value)
    if match is None:
        return None
    return int(match.group(1))


def _is_wired_port(port: HardwarePort, *, wifi_interface: str | None) -> bool:
    if port.device == wifi_interface:
        return False

    name = port.name.casefold()
    if any(excluded in name for excluded in ("wi-fi", "wifi", "airport", "bluetooth")):
        return False
    if any(included in name for included in ("ethernet", "lan", "10/100", "gigabit", "10gbe")):
        return True
    return port.device.startswith("en") and "thunderbolt" not in name


def _interface_is_active(output: str) -> bool:
    match = re.search(r"^\s*status:\s*(\S+)", output, flags=re.MULTILINE)
    return match is not None and match.group(1).casefold() == "active"


def _ipv4_addresses(output: str) -> tuple[str, ...]:
    return tuple(re.findall(r"^\s*inet\s+(\d+\.\d+\.\d+\.\d+)\b", output, flags=re.MULTILINE))


def _parse_ping_latency_ms(output: str) -> float | None:
    match = re.search(r"time[=<]\s*([0-9.]+)\s*ms", output)
    if match is None:
        return None
    return float(match.group(1))


def _int_value(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_redacted_text(value: str | None) -> bool:
    return value is not None and value.casefold() == "<redacted>"


def _wifi_signal_percent(signal_dbm: int | None) -> int | None:
    if signal_dbm is None:
        return None
    return max(0, min(100, 2 * (signal_dbm + 100)))


def _round_optional(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)
