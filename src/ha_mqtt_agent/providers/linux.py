"""Linux and Raspberry Pi telemetry provider."""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import SupportsFloat, SupportsIndex

from ha_mqtt_agent.capabilities import CapabilitySnapshot, capability_snapshot_from_payload
from ha_mqtt_agent.config import AppConfig, PingTarget
from ha_mqtt_agent.network import NetworkSnapshotCache, _wifi_signal_percent
from ha_mqtt_agent.providers.base import PayloadPostprocessor

LINUX_COMMAND_TIMEOUT_SECONDS = 5.0
IP_COMMAND = "ip"
IW_COMMAND = "iw"
NMCLI_COMMAND = "nmcli"
PING_COMMAND = "ping"
UPOWER_COMMAND = "upower"

LinuxCommandRunner = Callable[[Sequence[str], float], "LinuxCommandResult | None"]


@dataclass(frozen=True)
class LinuxCommandResult:
    stdout: str
    returncode: int


@dataclass(frozen=True)
class LinuxInterface:
    name: str
    operstate: str | None
    ipv4_addresses: tuple[str, ...] | None


@dataclass(frozen=True)
class LinuxGateway:
    address: str
    interface: str | None
    mac_address: str | None


@dataclass(frozen=True)
class LinuxWifiStatus:
    interface: str | None
    ssid: str | None
    signal_dbm: int | None
    bssid: str | None

    @property
    def signal_percent(self) -> int | None:
        return _wifi_signal_percent(self.signal_dbm)


@dataclass(frozen=True)
class LinuxBatteryStatus:
    capacity_percent: int | None
    max_capacity_percent: float | None
    max_capacity_mah: int | None
    design_capacity_mah: int | None
    temperature_c: float | None
    cycle_count: int | None
    status: str | None


@dataclass(frozen=True)
class LinuxNetworkSample:
    payload: dict[str, object]
    errors: dict[str, str]


@dataclass
class LinuxProvider:
    root: Path = Path("/")
    command_runner: LinuxCommandRunner | None = None
    available_commands: frozenset[str] | None = None
    host_name_provider: Callable[[], str] = socket.gethostname
    provider_id: str = "linux"

    def supported_capability_ids(self, config: AppConfig) -> tuple[str, ...]:
        supported: list[str] = []
        if self._path("proc/uptime").exists():
            supported.append("uptime")

        if self._network_supported():
            supported.extend(
                [
                    "ipv4_addresses",
                    "default_gateways",
                    "default_gateway_interfaces",
                    "gateway_macs",
                    "ethernet_active_count",
                    "ethernet_active_interfaces",
                    "home_network_present",
                ]
            )

        if self._wifi_supported():
            supported.extend(
                [
                    "wifi_ssid",
                    "wifi_bssid",
                    "wifi_signal_dbm",
                    "wifi_signal_percent",
                ]
            )

        if self._command_available(PING_COMMAND):
            supported.extend(f"ping_{target.id}" for target in config.ping_targets)

        battery_capabilities = self._battery_capability_ids()
        supported.extend(battery_capabilities)

        if self._cpu_temperature_source() is not None:
            supported.append("cpu_temperature")

        return tuple(dict.fromkeys(supported))

    def sample(
        self,
        config: AppConfig,
        *,
        update_energy: bool = True,
        network_cache: NetworkSnapshotCache | None = None,
        payload_postprocessor: PayloadPostprocessor | None = None,
    ) -> CapabilitySnapshot:
        _ = update_energy
        supported = self.supported_capability_ids(config)
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "host_name": self.host_name_provider(),
        }
        errors: dict[str, str] = {}

        if "uptime" in supported:
            uptime = self._read_uptime_seconds()
            payload["uptime_seconds"] = _round_optional(uptime, 3)
            if uptime is None:
                errors["uptime"] = "/proc/uptime unavailable"

        if any(_is_linux_network_sample_capability(capability_id) for capability_id in supported):
            network_sample = self._read_network_sample(
                config=config,
                capability_ids=supported,
                network_cache=network_cache,
            )
            payload.update(network_sample.payload)
            errors.update(network_sample.errors)

        if any(capability_id.startswith("battery") for capability_id in supported):
            payload.update(self._battery_payload(supported=supported, errors=errors))

        if "cpu_temperature" in supported:
            cpu_temperature = self._read_cpu_temperature_c()
            payload["cpu_temperature_c"] = _round_optional(cpu_temperature, 2)
            if cpu_temperature is None:
                errors["cpu_temperature"] = "CPU temperature unavailable"

        if payload_postprocessor is not None:
            payload_postprocessor(payload)

        return capability_snapshot_from_payload(
            config=config,
            payload=payload,
            provider=self.provider_id,
            capability_ids=supported,
            unavailable_ids=tuple(errors),
            errors=errors,
        )

    def _read_network_sample(
        self,
        *,
        config: AppConfig,
        capability_ids: tuple[str, ...],
        network_cache: NetworkSnapshotCache | None,
    ) -> LinuxNetworkSample:
        reader = _LinuxNetworkReader(provider=self, capability_ids=capability_ids)
        if network_cache is None:
            return reader.read(config)
        return network_cache.read(reader, config)

    def _network_sample(
        self,
        *,
        config: AppConfig,
        capability_ids: tuple[str, ...],
    ) -> LinuxNetworkSample:
        payload: dict[str, object] = {}
        errors: dict[str, str] = {}
        wifi = (
            self._read_wifi_status()
            if any(
                _is_network_capability(capability_id) or capability_id.startswith("wifi_")
                for capability_id in capability_ids
            )
            else None
        )
        if any(_is_network_capability(capability_id) for capability_id in capability_ids):
            payload.update(self._network_payload(config=config, errors=errors, wifi=wifi))
        if any(capability_id.startswith("wifi_") for capability_id in capability_ids):
            payload.update(self._wifi_payload(errors=errors, wifi=wifi))
        if any(capability_id.startswith("ping_") for capability_id in capability_ids):
            for target in config.ping_targets:
                capability_id = f"ping_{target.id}"
                if capability_id not in capability_ids:
                    continue
                latency_ms = self._ping(target, config.ping_timeout_seconds)
                payload[f"ping_{target.id}_ms"] = _round_optional(latency_ms, 3)
                if latency_ms is None:
                    errors[capability_id] = f"ping {target.host} unavailable"
        return LinuxNetworkSample(payload=payload, errors=errors)

    def _network_payload(
        self,
        *,
        config: AppConfig,
        errors: dict[str, str],
        wifi: LinuxWifiStatus | None,
    ) -> dict[str, object]:
        interfaces = self._interfaces()
        gateways = self._default_gateways()
        ipv4_available = False
        if interfaces is None:
            for capability_id in (
                "ipv4_addresses",
                "ethernet_active_count",
                "ethernet_active_interfaces",
                "home_network_present",
            ):
                errors[capability_id] = "network interfaces unavailable"
            active_ethernet: tuple[LinuxInterface, ...] = ()
            ipv4_addresses: tuple[str, ...] = ()
        else:
            ipv4_available = any(interface.ipv4_addresses is not None for interface in interfaces)
            active_ethernet = tuple(
                interface
                for interface in interfaces
                if _is_linux_ethernet_interface(interface.name, self._wireless_interfaces())
                and _interface_is_active(interface)
            )
            ipv4_addresses = tuple(
                dict.fromkeys(
                    address
                    for interface in interfaces
                    for address in (interface.ipv4_addresses or ())
                )
            )
            if not ipv4_available:
                errors["ipv4_addresses"] = "IPv4 addresses unavailable"

        if gateways is None:
            for capability_id in ("default_gateways", "default_gateway_interfaces", "gateway_macs"):
                errors[capability_id] = "default gateway unavailable"
            gateways = ()

        wifi = wifi or LinuxWifiStatus(interface=None, ssid=None, signal_dbm=None, bssid=None)
        home_network_present = _linux_home_network_present(
            config=config,
            wifi=wifi,
            ethernet=active_ethernet,
            wifi_ipv4_addresses=tuple(
                address
                for interface in interfaces or ()
                if interface.name == wifi.interface
                for address in (interface.ipv4_addresses or ())
            ),
            default_gateways=gateways,
        )
        if config.home_ipv4_cidrs and not ipv4_available and not home_network_present:
            errors["home_network_present"] = "IPv4 addresses unavailable"
        return {
            "ipv4_addresses": ", ".join(ipv4_addresses),
            "default_gateways": ", ".join(gateway.address for gateway in gateways),
            "default_gateway_interfaces": ", ".join(
                gateway.interface or "" for gateway in gateways
            ),
            "gateway_macs": ", ".join(
                gateway.mac_address for gateway in gateways if gateway.mac_address is not None
            ),
            "ethernet_active_count": len(active_ethernet),
            "ethernet_active_interfaces": ", ".join(
                interface.name for interface in active_ethernet
            ),
            "home_network_present": home_network_present,
        }

    def _wifi_payload(
        self,
        *,
        errors: dict[str, str],
        wifi: LinuxWifiStatus | None = None,
    ) -> dict[str, object]:
        wifi = wifi or self._read_wifi_status()
        payload: dict[str, object] = {
            "wifi_interface": wifi.interface,
            "wifi_ssid": wifi.ssid,
            "wifi_bssid": wifi.bssid,
            "wifi_signal_dbm": wifi.signal_dbm,
            "wifi_signal_percent": wifi.signal_percent,
        }
        if wifi.ssid is None:
            errors["wifi_ssid"] = "Wi-Fi SSID unavailable"
        if wifi.bssid is None:
            errors["wifi_bssid"] = "Wi-Fi BSSID unavailable"
        if wifi.signal_dbm is None:
            errors["wifi_signal_dbm"] = "Wi-Fi signal unavailable"
            errors["wifi_signal_percent"] = "Wi-Fi signal unavailable"
        return payload

    def _battery_payload(
        self,
        *,
        supported: Iterable[str],
        errors: dict[str, str],
    ) -> dict[str, object]:
        supported_set = set(supported)
        battery = self._read_battery_status()
        mapping: dict[str, tuple[str, object]] = {
            "battery": ("battery_percent", None if battery is None else battery.capacity_percent),
            "battery_max_capacity": (
                "battery_max_capacity_percent",
                None if battery is None else _round_optional(battery.max_capacity_percent, 2),
            ),
            "battery_max_capacity_mah": (
                "battery_max_capacity_mah",
                None if battery is None else battery.max_capacity_mah,
            ),
            "battery_design_capacity": (
                "battery_design_capacity_mah",
                None if battery is None else battery.design_capacity_mah,
            ),
            "battery_temperature": (
                "battery_temperature_c",
                None if battery is None else _round_optional(battery.temperature_c, 2),
            ),
            "battery_cycle_count": (
                "battery_cycle_count",
                None if battery is None else battery.cycle_count,
            ),
            "battery_status": ("battery_status", None if battery is None else battery.status),
        }
        payload: dict[str, object] = {}
        for capability_id, (payload_key, value) in mapping.items():
            if capability_id not in supported_set:
                continue
            payload[payload_key] = value
            if value is None:
                errors[capability_id] = f"{payload_key} unavailable"
        return payload

    def _read_uptime_seconds(self) -> float | None:
        text = self._read_text("proc/uptime")
        if text is None:
            return None
        first = text.split(maxsplit=1)[0] if text.split() else ""
        return _float_value(first)

    def _interfaces(self) -> tuple[LinuxInterface, ...] | None:
        from_ip = self._interfaces_from_ip()
        if from_ip is not None:
            return from_ip
        return self._interfaces_from_sysfs()

    def _interfaces_from_ip(self) -> tuple[LinuxInterface, ...] | None:
        if not self._command_available(IP_COMMAND):
            return None
        result = self._run(
            [IP_COMMAND, "-j", "addr", "show"],
            LINUX_COMMAND_TIMEOUT_SECONDS,
        )
        if result is None or result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, list):
            return None
        interfaces: list[LinuxInterface] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = _optional_text(item.get("ifname"))
            if name is None:
                continue
            addr_info = item.get("addr_info")
            ipv4_addresses = []
            if isinstance(addr_info, list):
                for address in addr_info:
                    if not isinstance(address, dict) or address.get("family") != "inet":
                        continue
                    local = _optional_text(address.get("local"))
                    if local is not None:
                        ipv4_addresses.append(local)
            interfaces.append(
                LinuxInterface(
                    name=name,
                    operstate=_optional_text(item.get("operstate")),
                    ipv4_addresses=tuple(ipv4_addresses),
                )
            )
        return tuple(interfaces)

    def _interfaces_from_sysfs(self) -> tuple[LinuxInterface, ...] | None:
        net_path = self._path("sys/class/net")
        if not net_path.exists():
            return None
        interfaces = []
        for interface_path in sorted(net_path.iterdir()):
            if not interface_path.is_dir():
                continue
            name = interface_path.name
            interfaces.append(
                LinuxInterface(
                    name=name,
                    operstate=self._read_text(f"sys/class/net/{name}/operstate"),
                    ipv4_addresses=None,
                )
            )
        return tuple(interfaces)

    def _default_gateways(self) -> tuple[LinuxGateway, ...] | None:
        from_ip = self._default_gateways_from_ip()
        if from_ip is not None:
            return from_ip
        return self._default_gateways_from_proc_route()

    def _default_gateways_from_ip(self) -> tuple[LinuxGateway, ...] | None:
        if not self._command_available(IP_COMMAND):
            return None
        result = self._run(
            [IP_COMMAND, "-j", "route", "show", "default"],
            LINUX_COMMAND_TIMEOUT_SECONDS,
        )
        if result is None or result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, list):
            return None
        gateways = []
        for item in data:
            if not isinstance(item, dict):
                continue
            gateway = _optional_text(item.get("gateway"))
            if gateway is None:
                continue
            interface = _optional_text(item.get("dev"))
            gateways.append(
                LinuxGateway(
                    address=gateway,
                    interface=interface,
                    mac_address=self._gateway_mac(gateway),
                )
            )
        return tuple(gateways)

    def _default_gateways_from_proc_route(self) -> tuple[LinuxGateway, ...] | None:
        text = self._read_text("proc/net/route")
        if text is None:
            return None
        gateways = []
        for raw_line in text.splitlines()[1:]:
            fields = raw_line.split()
            if len(fields) < 3 or fields[1] != "00000000":
                continue
            address = _little_endian_hex_ipv4(fields[2])
            if address is None:
                continue
            gateways.append(
                LinuxGateway(
                    address=address,
                    interface=fields[0],
                    mac_address=self._gateway_mac(address),
                )
            )
        return tuple(gateways)

    def _gateway_mac(self, gateway: str) -> str | None:
        if self._command_available(IP_COMMAND):
            result = self._run(
                [IP_COMMAND, "neigh", "show", gateway],
                LINUX_COMMAND_TIMEOUT_SECONDS,
            )
            if result is not None and result.returncode == 0:
                match = re.search(
                    r"\blladdr\s+([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5})\b",
                    result.stdout,
                    flags=re.IGNORECASE,
                )
                if match is not None:
                    return _normalize_mac(match.group(1))

        arp_text = self._read_text("proc/net/arp")
        if arp_text is None:
            return None
        for raw_line in arp_text.splitlines()[1:]:
            fields = raw_line.split()
            if len(fields) >= 4 and fields[0] == gateway:
                return _normalize_mac(fields[3])
        return None

    def _read_wifi_status(self) -> LinuxWifiStatus:
        interface = self._preferred_wireless_interface()
        for reader in (
            self._wifi_status_from_iw,
            self._wifi_status_from_nmcli,
            self._wifi_status_from_proc_wireless,
        ):
            status = reader(interface)
            if _wifi_status_has_reading(status):
                return status
        return LinuxWifiStatus(interface=interface, ssid=None, signal_dbm=None, bssid=None)

    def _wifi_status_from_iw(self, interface: str | None) -> LinuxWifiStatus:
        if not self._command_available(IW_COMMAND):
            return LinuxWifiStatus(interface=interface, ssid=None, signal_dbm=None, bssid=None)
        resolved_interface = interface or self._wireless_interface_from_iw()
        if resolved_interface is None:
            return LinuxWifiStatus(interface=None, ssid=None, signal_dbm=None, bssid=None)
        result = self._run(
            [IW_COMMAND, "dev", resolved_interface, "link"],
            LINUX_COMMAND_TIMEOUT_SECONDS,
        )
        if result is None or result.returncode != 0:
            return LinuxWifiStatus(
                interface=resolved_interface,
                ssid=None,
                signal_dbm=None,
                bssid=None,
            )
        return _parse_iw_link(result.stdout, interface=resolved_interface)

    def _wireless_interface_from_iw(self) -> str | None:
        result = self._run([IW_COMMAND, "dev"], LINUX_COMMAND_TIMEOUT_SECONDS)
        if result is None or result.returncode != 0:
            return None
        match = re.search(r"^\s*Interface\s+(\S+)", result.stdout, flags=re.MULTILINE)
        if match is None:
            return None
        return match.group(1)

    def _wifi_status_from_nmcli(self, interface: str | None) -> LinuxWifiStatus:
        if not self._command_available(NMCLI_COMMAND):
            return LinuxWifiStatus(interface=interface, ssid=None, signal_dbm=None, bssid=None)

        resolved_interface = interface
        status_result = self._run(
            [NMCLI_COMMAND, "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"],
            LINUX_COMMAND_TIMEOUT_SECONDS,
        )
        if status_result is not None and status_result.returncode == 0:
            for raw_line in status_result.stdout.splitlines():
                fields = _split_nmcli(raw_line)
                if len(fields) >= 4 and fields[1] == "wifi" and fields[2] == "connected":
                    resolved_interface = fields[0] or resolved_interface
                    ssid = fields[3] or None
                    ap_status = self._nmcli_active_ap(resolved_interface)
                    return LinuxWifiStatus(
                        interface=resolved_interface,
                        ssid=ap_status.ssid or ssid,
                        signal_dbm=ap_status.signal_dbm,
                        bssid=ap_status.bssid,
                    )

        if resolved_interface is None:
            return LinuxWifiStatus(interface=None, ssid=None, signal_dbm=None, bssid=None)
        return self._nmcli_active_ap(resolved_interface)

    def _nmcli_active_ap(self, interface: str | None) -> LinuxWifiStatus:
        if interface is None:
            return LinuxWifiStatus(interface=None, ssid=None, signal_dbm=None, bssid=None)
        result = self._run(
            [
                NMCLI_COMMAND,
                "-t",
                "-f",
                "ACTIVE,SSID,BSSID,SIGNAL",
                "dev",
                "wifi",
                "list",
                "ifname",
                interface,
            ],
            LINUX_COMMAND_TIMEOUT_SECONDS,
        )
        if result is None or result.returncode != 0:
            return LinuxWifiStatus(interface=interface, ssid=None, signal_dbm=None, bssid=None)
        for raw_line in result.stdout.splitlines():
            fields = _split_nmcli(raw_line)
            if len(fields) < 4 or fields[0] != "yes":
                continue
            signal_percent = _int_value(fields[3])
            return LinuxWifiStatus(
                interface=interface,
                ssid=fields[1] or None,
                signal_dbm=_nmcli_signal_percent_to_dbm(signal_percent),
                bssid=_normalize_mac(fields[2]),
            )
        return LinuxWifiStatus(interface=interface, ssid=None, signal_dbm=None, bssid=None)

    def _wifi_status_from_proc_wireless(self, interface: str | None) -> LinuxWifiStatus:
        text = self._read_text("proc/net/wireless")
        if text is None:
            return LinuxWifiStatus(interface=interface, ssid=None, signal_dbm=None, bssid=None)
        readings = _parse_proc_net_wireless(text)
        if not readings:
            return LinuxWifiStatus(interface=interface, ssid=None, signal_dbm=None, bssid=None)
        resolved_interface = interface or next(iter(readings))
        return LinuxWifiStatus(
            interface=resolved_interface,
            ssid=None,
            signal_dbm=readings.get(resolved_interface),
            bssid=None,
        )

    def _preferred_wireless_interface(self) -> str | None:
        interfaces = self._wireless_interfaces()
        if interfaces:
            return interfaces[0]
        return self._wireless_interface_from_iw() if self._command_available(IW_COMMAND) else None

    def _wireless_interfaces(self) -> tuple[str, ...]:
        interfaces = []
        net_path = self._path("sys/class/net")
        if net_path.exists():
            for interface_path in sorted(net_path.iterdir()):
                if (interface_path / "wireless").exists():
                    interfaces.append(interface_path.name)
        proc_wireless = self._read_text("proc/net/wireless")
        if proc_wireless is not None:
            interfaces.extend(_parse_proc_net_wireless(proc_wireless).keys())
        return tuple(dict.fromkeys(interfaces))

    def _read_battery_status(self) -> LinuxBatteryStatus | None:
        battery_path = self._battery_path()
        if battery_path is None:
            return self._read_upower_battery_status()
        charge_full = _int_file(battery_path / "charge_full")
        charge_design = _int_file(battery_path / "charge_full_design")
        energy_full = _int_file(battery_path / "energy_full")
        energy_design = _int_file(battery_path / "energy_full_design")
        full = charge_full if charge_full is not None else energy_full
        design = charge_design if charge_design is not None else energy_design
        return LinuxBatteryStatus(
            capacity_percent=_int_file(battery_path / "capacity"),
            max_capacity_percent=_capacity_percent(full=full, design=design),
            max_capacity_mah=None if charge_full is None else round(charge_full / 1000),
            design_capacity_mah=None if charge_design is None else round(charge_design / 1000),
            temperature_c=_battery_temperature_c(_int_file(battery_path / "temp")),
            cycle_count=_int_file(battery_path / "cycle_count"),
            status=_linux_battery_status(self._read_text_from_path(battery_path / "status")),
        )

    def _battery_capability_ids(self) -> tuple[str, ...]:
        battery_path = self._battery_path()
        if battery_path is None:
            return self._upower_battery_capability_ids()
        capabilities = []
        if (battery_path / "capacity").exists():
            capabilities.append("battery")
        if (battery_path / "status").exists():
            capabilities.append("battery_status")
        if _has_any_file(battery_path, ("charge_full", "energy_full")) and _has_any_file(
            battery_path,
            ("charge_full_design", "energy_full_design"),
        ):
            capabilities.append("battery_max_capacity")
        if (battery_path / "charge_full").exists():
            capabilities.append("battery_max_capacity_mah")
        if (battery_path / "charge_full_design").exists():
            capabilities.append("battery_design_capacity")
        if (battery_path / "temp").exists():
            capabilities.append("battery_temperature")
        if (battery_path / "cycle_count").exists():
            capabilities.append("battery_cycle_count")
        return tuple(capabilities)

    def _read_upower_battery_status(self) -> LinuxBatteryStatus | None:
        fields = self._upower_battery_fields()
        if fields is None:
            return None
        energy_full = _upower_float(fields.get("energy-full"))
        energy_design = _upower_float(fields.get("energy-full-design"))
        return LinuxBatteryStatus(
            capacity_percent=_upower_int_percent(fields.get("percentage")),
            max_capacity_percent=_upower_percent(fields.get("capacity"))
            or _capacity_percent(full=energy_full, design=energy_design),
            max_capacity_mah=None,
            design_capacity_mah=None,
            temperature_c=_upower_float(fields.get("temperature")),
            cycle_count=_upower_int(fields.get("charge-cycles")),
            status=_linux_battery_status(fields.get("state")),
        )

    def _upower_battery_capability_ids(self) -> tuple[str, ...]:
        fields = self._upower_battery_fields()
        if fields is None:
            return ()
        capabilities = []
        if _upower_int_percent(fields.get("percentage")) is not None:
            capabilities.append("battery")
        if _upower_percent(fields.get("capacity")) is not None or (
            _upower_float(fields.get("energy-full")) is not None
            and _upower_float(fields.get("energy-full-design")) is not None
        ):
            capabilities.append("battery_max_capacity")
        if _upower_float(fields.get("temperature")) is not None:
            capabilities.append("battery_temperature")
        if _upower_int(fields.get("charge-cycles")) is not None:
            capabilities.append("battery_cycle_count")
        if _linux_battery_status(fields.get("state")) is not None:
            capabilities.append("battery_status")
        return tuple(capabilities)

    def _upower_battery_fields(self) -> dict[str, str] | None:
        if not self._command_available(UPOWER_COMMAND):
            return None
        result = self._run([UPOWER_COMMAND, "-e"], LINUX_COMMAND_TIMEOUT_SECONDS)
        if result is None or result.returncode != 0:
            return None
        for raw_line in result.stdout.splitlines():
            device = raw_line.strip()
            if "battery" not in device.casefold():
                continue
            fields = self._upower_device_fields(device)
            if fields is not None and _upower_is_system_battery(fields):
                return fields
        return None

    def _upower_device_fields(self, device: str) -> dict[str, str] | None:
        result = self._run([UPOWER_COMMAND, "-i", device], LINUX_COMMAND_TIMEOUT_SECONDS)
        if result is None or result.returncode != 0:
            return None
        return _parse_upower_fields(result.stdout)

    def _battery_path(self) -> Path | None:
        power_path = self._path("sys/class/power_supply")
        if not power_path.exists():
            return None
        for item in sorted(power_path.iterdir()):
            if not item.is_dir():
                continue
            if (self._read_text_from_path(item / "type") or "").casefold() == "battery":
                return item
        return None

    def _read_cpu_temperature_c(self) -> float | None:
        source = self._cpu_temperature_source()
        if source is None:
            return None
        return _thermal_temperature_c(_int_file(source))

    def _cpu_temperature_source(self) -> Path | None:
        thermal_path = self._path("sys/class/thermal")
        if not thermal_path.exists():
            return None
        candidates = [
            item
            for item in sorted(thermal_path.glob("thermal_zone*/temp"))
            if item.is_file() or item.exists()
        ]
        if not candidates:
            return None
        preferred = []
        fallback = []
        for temp_path in candidates:
            thermal_type = (self._read_text_from_path(temp_path.parent / "type") or "").casefold()
            if any(
                token in thermal_type
                for token in ("cpu", "x86_pkg", "soc", "bcm", "k10temp", "coretemp")
            ):
                preferred.append(temp_path)
            else:
                fallback.append(temp_path)
        for temp_path in (*preferred, *fallback):
            if _thermal_temperature_c(_int_file(temp_path)) is not None:
                return temp_path
        return None

    def _ping(self, target: PingTarget, timeout_seconds: float) -> float | None:
        timeout = str(max(1, int(round(timeout_seconds))))
        result = self._run(
            [PING_COMMAND, "-n", "-c", "1", "-W", timeout, target.host],
            timeout_seconds + 1,
        )
        if result is None:
            return None
        return _parse_ping_latency_ms(result.stdout)

    def _network_supported(self) -> bool:
        return self._command_available(IP_COMMAND) or self._path("sys/class/net").exists()

    def _wifi_supported(self) -> bool:
        return bool(self._wireless_interfaces()) or (
            self._command_available(IW_COMMAND) and self._wireless_interface_from_iw() is not None
        )

    def _command_available(self, command: str) -> bool:
        if self.available_commands is not None:
            return command in self.available_commands
        if self.command_runner is not None:
            return True
        return shutil.which(command) is not None

    def _run(
        self,
        command: Sequence[str],
        timeout_seconds: float,
    ) -> LinuxCommandResult | None:
        if self.command_runner is not None:
            return self.command_runner(command, timeout_seconds)
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
        return LinuxCommandResult(stdout=result.stdout, returncode=result.returncode)

    def _path(self, relative_path: str) -> Path:
        return self.root / relative_path

    def _read_text(self, relative_path: str) -> str | None:
        return self._read_text_from_path(self._path(relative_path))

    def _read_text_from_path(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return None


@dataclass(frozen=True)
class _LinuxNetworkReader:
    provider: LinuxProvider
    capability_ids: tuple[str, ...]

    def read(self, config: AppConfig) -> LinuxNetworkSample:
        return self.provider._network_sample(
            config=config,
            capability_ids=self.capability_ids,
        )


def _is_linux_network_sample_capability(capability_id: str) -> bool:
    return (
        _is_network_capability(capability_id)
        or capability_id.startswith("wifi_")
        or capability_id.startswith("ping_")
    )


def _is_network_capability(capability_id: str) -> bool:
    return capability_id in {
        "ipv4_addresses",
        "default_gateways",
        "default_gateway_interfaces",
        "gateway_macs",
        "ethernet_active_count",
        "ethernet_active_interfaces",
        "home_network_present",
    }


def _interface_is_active(interface: LinuxInterface) -> bool:
    return (interface.operstate or "").casefold() in {"up", "unknown"}


def _linux_home_network_present(
    *,
    config: AppConfig,
    wifi: LinuxWifiStatus,
    ethernet: Sequence[LinuxInterface],
    wifi_ipv4_addresses: Sequence[str],
    default_gateways: Sequence[LinuxGateway],
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
        address for interface in ethernet for address in (interface.ipv4_addresses or ())
    ) + tuple(wifi_ipv4_addresses)
    return any(
        _ip_in_cidr(address, cidr) for address in addresses for cidr in config.home_ipv4_cidrs
    )


def _ip_in_cidr(address: str, cidr: str) -> bool:
    from ipaddress import ip_address, ip_network

    return ip_address(address) in ip_network(cidr, strict=False)


def _is_linux_ethernet_interface(name: str, wireless_interfaces: Sequence[str]) -> bool:
    if name in wireless_interfaces or name == "lo":
        return False
    excluded_prefixes = ("br-", "docker", "veth", "tun", "tap", "wg")
    if name.startswith(excluded_prefixes):
        return False
    return name.startswith(("eth", "en", "eno", "ens", "enp", "enx", "usb"))


def _parse_iw_link(output: str, *, interface: str) -> LinuxWifiStatus:
    ssid = None
    signal_dbm = None
    bssid = None
    connected = re.search(
        r"^\s*Connected to\s+([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5})\b",
        output,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if connected is not None:
        bssid = _normalize_mac(connected.group(1))
    ssid_match = re.search(r"^\s*SSID:\s*(.+)$", output, flags=re.MULTILINE)
    if ssid_match is not None:
        ssid = ssid_match.group(1).strip() or None
    signal_match = re.search(r"^\s*signal:\s*(-?\d+)\s*dBm\b", output, flags=re.MULTILINE)
    if signal_match is not None:
        signal_dbm = int(signal_match.group(1))
    return LinuxWifiStatus(interface=interface, ssid=ssid, signal_dbm=signal_dbm, bssid=bssid)


def _parse_proc_net_wireless(output: str) -> dict[str, int]:
    readings: dict[str, int] = {}
    for raw_line in output.splitlines()[2:]:
        if ":" not in raw_line:
            continue
        interface, values = raw_line.split(":", 1)
        fields = values.split()
        if len(fields) < 3:
            continue
        signal_dbm = _wireless_level_to_dbm(fields[2].rstrip("."))
        if signal_dbm is not None:
            readings[interface.strip()] = signal_dbm
    return readings


def _wireless_level_to_dbm(value: str) -> int | None:
    level = _float_value(value)
    if level is None:
        return None
    if level > 100:
        level -= 256
    return int(round(level))


def _wifi_status_has_reading(status: LinuxWifiStatus) -> bool:
    return status.ssid is not None or status.signal_dbm is not None or status.bssid is not None


def _split_nmcli(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == ":":
            fields.append("".join(current))
            current = []
            continue
        current.append(char)
    fields.append("".join(current))
    return fields


def _nmcli_signal_percent_to_dbm(value: int | None) -> int | None:
    if value is None:
        return None
    percent = max(0, min(100, value))
    return round(percent / 2 - 100)


def _linux_battery_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized == "charging":
        return "charging"
    if normalized == "discharging":
        return "discharging"
    if normalized in {"full", "fully-charged"}:
        return "charged"
    if normalized in {"not charging", "unknown"}:
        return "plugged_in"
    return normalized or None


def _parse_upower_fields(output: str) -> dict[str, str]:
    fields = {}
    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        normalized_key = key.strip().casefold()
        if normalized_key:
            fields[normalized_key] = value.strip()
    return fields


def _upower_is_system_battery(fields: dict[str, str]) -> bool:
    return (
        fields.get("type", "").casefold() == "battery"
        and _upower_bool(fields.get("power supply")) is True
    )


def _upower_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized in {"yes", "true", "1"}:
        return True
    if normalized in {"no", "false", "0"}:
        return False
    return None


def _upower_percent(value: str | None) -> float | None:
    return _upower_float(value)


def _upower_int_percent(value: str | None) -> int | None:
    percent = _upower_percent(value)
    if percent is None:
        return None
    return round(percent)


def _upower_int(value: str | None) -> int | None:
    parsed = _upower_float(value)
    if parsed is None:
        return None
    return round(parsed)


def _upower_float(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if match is None:
        return None
    return float(match.group(0))


def _battery_temperature_c(value: int | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 200:
        return value / 10
    return float(value)


def _thermal_temperature_c(value: int | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1000:
        return value / 1000
    if abs(value) > 200:
        return value / 10
    return float(value)


def _capacity_percent(*, full: int | float | None, design: int | float | None) -> float | None:
    if full is None or design is None or design <= 0:
        return None
    return full / design * 100


def _parse_ping_latency_ms(output: str) -> float | None:
    match = re.search(r"time[=<]\s*([0-9.]+)\s*ms", output)
    if match is None:
        return None
    return float(match.group(1))


def _little_endian_hex_ipv4(value: str) -> str | None:
    if not re.fullmatch(r"[0-9A-Fa-f]{8}", value):
        return None
    parts = [str(int(value[index : index + 2], 16)) for index in range(6, -1, -2)]
    return ".".join(parts)


def _has_any_file(path: Path, names: Sequence[str]) -> bool:
    return any((path / name).exists() for name in names)


def _int_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _int_value(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
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


def _normalize_mac(value: str | None) -> str | None:
    if value is None:
        return None
    parts = value.strip().lower().split(":")
    if len(parts) != 6 or any(not re.fullmatch(r"[0-9a-f]{1,2}", part) for part in parts):
        return None
    return ":".join(part.zfill(2) for part in parts)


def _round_optional(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)
