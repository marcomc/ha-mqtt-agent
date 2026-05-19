"""Network telemetry collection for macOS hosts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any, SupportsFloat, SupportsIndex

from .config import AppConfig, PingTarget

AIRPORT_PATH = (
    "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
)
NETWORKSETUP_PATH = "/usr/sbin/networksetup"
PING_PATH = "/sbin/ping"
SYSTEM_PROFILER_PATH = "/usr/sbin/system_profiler"
IFCONFIG_PATH = "/sbin/ifconfig"
ROUTE_PATH = "/sbin/route"
ARP_PATH = "/usr/sbin/arp"
OPEN_PATH = "/usr/bin/open"
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
    bssid: str | None = None


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
class DefaultGateway:
    address: str
    interface: str | None
    mac_address: str | None


@dataclass(frozen=True)
class LocationStatus:
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class GeocodedLocation:
    state: str | None = None
    name: str | None = None
    country: str | None = None
    iso_country_code: str | None = None
    time_zone: str | None = None
    administrative_area: str | None = None
    sub_administrative_area: str | None = None
    postal_code: str | None = None
    locality: str | None = None
    sub_locality: str | None = None
    thoroughfare: str | None = None
    sub_thoroughfare: str | None = None
    areas_of_interest: tuple[str, ...] = ()
    ocean: str | None = None
    inland_water: str | None = None
    error: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "geocoded_location": self.state,
            "geocoded_location_name": self.name,
            "geocoded_location_country": self.country,
            "geocoded_location_iso_country_code": self.iso_country_code,
            "geocoded_location_time_zone": self.time_zone,
            "geocoded_location_administrative_area": self.administrative_area,
            "geocoded_location_sub_administrative_area": self.sub_administrative_area,
            "geocoded_location_postal_code": self.postal_code,
            "geocoded_location_locality": self.locality,
            "geocoded_location_sub_locality": self.sub_locality,
            "geocoded_location_thoroughfare": self.thoroughfare,
            "geocoded_location_sub_thoroughfare": self.sub_thoroughfare,
            "geocoded_location_areas_of_interest": list(self.areas_of_interest),
            "geocoded_location_ocean": self.ocean,
            "geocoded_location_inland_water": self.inland_water,
            "geocoded_location_error": self.error,
        }


@dataclass(frozen=True)
class NetworkSample:
    wifi: WifiStatus
    ethernet: tuple[EthernetStatus, ...]
    pings: tuple[PingResult, ...]
    wifi_ipv4_addresses: tuple[str, ...] = ()
    default_gateways: tuple[DefaultGateway, ...] = ()
    location: LocationStatus = LocationStatus()
    geocoded_location: GeocodedLocation = GeocodedLocation()
    home_network_present: bool = False

    def payload(self) -> dict[str, object]:
        active_ethernet = [item for item in self.ethernet if item.active]
        ethernet_ipv4_addresses = tuple(
            address for item in active_ethernet for address in item.ipv4_addresses
        )
        ipv4_addresses = tuple(dict.fromkeys(ethernet_ipv4_addresses + self.wifi_ipv4_addresses))
        payload: dict[str, object] = {
            "wifi_interface": self.wifi.interface,
            "wifi_ssid": self.wifi.ssid,
            "wifi_bssid": self.wifi.bssid,
            "wifi_signal_dbm": self.wifi.signal_dbm,
            "wifi_signal_percent": self.wifi.signal_percent,
            "ipv4_addresses": ", ".join(ipv4_addresses),
            "default_gateways": ", ".join(item.address for item in self.default_gateways),
            "default_gateway_interfaces": ", ".join(
                item.interface or "" for item in self.default_gateways
            ),
            "gateway_macs": ", ".join(
                item.mac_address for item in self.default_gateways if item.mac_address is not None
            ),
            "home_network_present": self.home_network_present,
            "latitude": self.location.latitude,
            "longitude": self.location.longitude,
            "location_accuracy_m": self.location.accuracy_m,
            "location_error": self.location.error,
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
        payload.update(self.geocoded_location.payload())
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
        wifi_helper_result = (
            self._wifi_helper_json(config) if config.wifi_helper_path.exists() else None
        )
        wifi = self._wifi_status(
            wifi_interface,
            config=config,
            wifi_helper_result=wifi_helper_result,
        )
        ethernet = self._ethernet_statuses(hardware_ports, wifi_interface)
        wifi_ipv4_addresses = self._interface_ipv4_addresses(wifi_interface)
        default_gateways = self._default_gateways()
        pings = tuple(
            self._ping(target, config.ping_timeout_seconds) for target in config.ping_targets
        )
        home_network_present = _home_network_present(
            config=config,
            wifi=wifi,
            ethernet=ethernet,
            wifi_ipv4_addresses=wifi_ipv4_addresses,
            default_gateways=default_gateways,
        )
        return NetworkSample(
            wifi=wifi,
            ethernet=ethernet,
            pings=pings,
            wifi_ipv4_addresses=wifi_ipv4_addresses,
            default_gateways=default_gateways,
            location=self._location_status(config, wifi_helper_result),
            geocoded_location=self._geocoded_location(wifi_helper_result),
            home_network_present=home_network_present,
        )

    def _wifi_status(
        self,
        wifi_interface: str | None,
        *,
        config: AppConfig,
        wifi_helper_result: CommandResult | None,
    ) -> WifiStatus:
        helper = self._wifi_helper_status(config, wifi_helper_result)
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
                    bssid=airport.bssid,
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
                    bssid=profiler.bssid,
                )
            return profiler

        return WifiStatus(
            interface=wifi_interface,
            ssid=networksetup_ssid,
            signal_dbm=None,
            signal_percent=None,
        )

    def _wifi_helper_status(
        self,
        config: AppConfig,
        result: CommandResult | None,
    ) -> WifiStatus:
        if not config.wifi_helper_path.exists():
            return WifiStatus(
                interface=None,
                ssid=None,
                signal_dbm=None,
                signal_percent=None,
            )
        if result is None or result.returncode != 0:
            return WifiStatus(
                interface=None,
                ssid=None,
                signal_dbm=None,
                signal_percent=None,
            )
        return _parse_wifi_helper_status(result.stdout)

    def _wifi_helper_json(self, config: AppConfig) -> CommandResult | None:
        args = ["--json"]
        timeout_seconds = NETWORK_COMMAND_TIMEOUT_SECONDS
        if config.publish_location:
            args.extend(["--location-timeout", f"{config.location_timeout_seconds:g}"])
            args.extend(["--geocode-timeout", f"{config.location_timeout_seconds:g}"])
            timeout_seconds += config.location_timeout_seconds * 2

        app_path = _app_bundle_path(config.wifi_helper_path)
        if app_path is None:
            return self._run(
                [str(config.wifi_helper_path), *args],
                timeout_seconds,
            )

        with tempfile.TemporaryDirectory(prefix="ha-mqtt-agent-wifi-") as output_dir:
            output_path = Path(output_dir) / "helper.json"
            result = self._run(
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
                timeout_seconds,
            )
            if result is None:
                return None
            stdout = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
            return CommandResult(stdout=stdout or result.stdout, returncode=result.returncode)

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
            bssid=_normalize_mac(fields.get("BSSID")),
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

    def _interface_ipv4_addresses(self, interface: str | None) -> tuple[str, ...]:
        if interface is None:
            return ()
        result = self._run([IFCONFIG_PATH, interface], NETWORK_COMMAND_TIMEOUT_SECONDS)
        if result is None or result.returncode != 0:
            return ()
        if not _interface_is_active(result.stdout):
            return ()
        return _ipv4_addresses(result.stdout)

    def _default_gateways(self) -> tuple[DefaultGateway, ...]:
        result = self._run([ROUTE_PATH, "-n", "get", "default"], NETWORK_COMMAND_TIMEOUT_SECONDS)
        if result is None or result.returncode != 0:
            return ()
        fields = _parse_colon_fields(result.stdout)
        gateway = fields.get("gateway")
        if gateway is None:
            return ()
        return (
            DefaultGateway(
                address=gateway,
                interface=fields.get("interface"),
                mac_address=self._gateway_mac(gateway),
            ),
        )

    def _gateway_mac(self, gateway: str) -> str | None:
        result = self._run([ARP_PATH, "-n", gateway], NETWORK_COMMAND_TIMEOUT_SECONDS)
        if result is None or result.returncode != 0:
            return None
        match = re.search(
            r"\bat\s+([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5})\b",
            result.stdout,
            flags=re.IGNORECASE,
        )
        if match is None:
            return None
        return _normalize_mac(match.group(1))

    def _location_status(
        self,
        config: AppConfig,
        wifi_helper_result: CommandResult | None,
    ) -> LocationStatus:
        if not config.publish_location or not config.wifi_helper_path.exists():
            return LocationStatus()
        result = wifi_helper_result
        if result is None or result.returncode != 0:
            return LocationStatus()
        return _parse_location_status(result.stdout)

    def _geocoded_location(self, wifi_helper_result: CommandResult | None) -> GeocodedLocation:
        result = wifi_helper_result
        if result is None or result.returncode != 0:
            return GeocodedLocation()
        return _parse_geocoded_location(result.stdout)

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


def _app_bundle_path(executable_path: object) -> Path | None:
    path = Path(str(executable_path))
    for parent in (path, *path.parents):
        if parent.suffix == ".app":
            return parent
    return None


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
            bssid=_normalize_mac(_optional_text(current.get("spairport_bssid"))),
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
        bssid=_normalize_mac(_optional_text(data.get("bssid"))),
    )


def _parse_location_status(output: str) -> LocationStatus:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return LocationStatus()
    return LocationStatus(
        latitude=_float_value(data.get("latitude")),
        longitude=_float_value(data.get("longitude")),
        accuracy_m=_float_value(data.get("location_accuracy_m")),
        error=_optional_text(data.get("location_error")),
    )


def _parse_geocoded_location(output: str) -> GeocodedLocation:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return GeocodedLocation()
    raw_location = data.get("geocoded_location")
    if not isinstance(raw_location, dict):
        return GeocodedLocation()
    return GeocodedLocation(
        state=_optional_text(raw_location.get("state")),
        name=_optional_text(raw_location.get("name")),
        country=_optional_text(raw_location.get("country")),
        iso_country_code=_optional_text(raw_location.get("iso_country_code")),
        time_zone=_optional_text(raw_location.get("time_zone")),
        administrative_area=_optional_text(raw_location.get("administrative_area")),
        sub_administrative_area=_optional_text(raw_location.get("sub_administrative_area")),
        postal_code=_optional_text(raw_location.get("postal_code")),
        locality=_optional_text(raw_location.get("locality")),
        sub_locality=_optional_text(raw_location.get("sub_locality")),
        thoroughfare=_optional_text(raw_location.get("thoroughfare")),
        sub_thoroughfare=_optional_text(raw_location.get("sub_thoroughfare")),
        areas_of_interest=_parse_text_tuple(raw_location.get("areas_of_interest")),
        ocean=_optional_text(raw_location.get("ocean")),
        inland_water=_optional_text(raw_location.get("inland_water")),
        error=_optional_text(raw_location.get("error")),
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


def _home_network_present(
    *,
    config: AppConfig,
    wifi: WifiStatus,
    ethernet: Sequence[EthernetStatus],
    wifi_ipv4_addresses: Sequence[str],
    default_gateways: Sequence[DefaultGateway],
) -> bool:
    if wifi.ssid is not None and wifi.ssid in config.home_ssids:
        return True
    if wifi.bssid is not None and wifi.bssid in config.home_bssids:
        return True
    if any(gateway.address in config.home_gateways for gateway in default_gateways):
        return True
    if any(
        gateway.mac_address is not None and gateway.mac_address in config.home_gateway_macs
        for gateway in default_gateways
    ):
        return True

    addresses = tuple(
        address for item in ethernet if item.active for address in item.ipv4_addresses
    ) + tuple(wifi_ipv4_addresses)
    return any(
        _ip_in_cidr(address, cidr) for address in addresses for cidr in config.home_ipv4_cidrs
    )


def _ip_in_cidr(address: str, cidr: str) -> bool:
    return ip_address(address) in ip_network(cidr, strict=False)


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


def _float_value(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str | bytes | SupportsFloat | SupportsIndex):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items = []
    for item in value:
        text = _optional_text(item)
        if text is not None:
            items.append(text)
    return tuple(items)


def _is_redacted_text(value: str | None) -> bool:
    return value is not None and value.casefold() == "<redacted>"


def _normalize_mac(value: str | None) -> str | None:
    if value is None:
        return None
    parts = value.strip().lower().split(":")
    if len(parts) != 6 or any(not re.fullmatch(r"[0-9a-f]{1,2}", part) for part in parts):
        return None
    return ":".join(part.zfill(2) for part in parts)


def _wifi_signal_percent(signal_dbm: int | None) -> int | None:
    if signal_dbm is None:
        return None
    return max(0, min(100, 2 * (signal_dbm + 100)))


def _round_optional(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)
