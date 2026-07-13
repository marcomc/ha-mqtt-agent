from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from ha_mqtt_agent.config import AppConfig, PingTarget
from ha_mqtt_agent.network import NetworkSnapshotCache
from ha_mqtt_agent.providers.linux import (
    IP_COMMAND,
    IW_COMMAND,
    NMCLI_COMMAND,
    PING_COMMAND,
    UPOWER_COMMAND,
    VCGENCMD_COMMAND,
    LinuxCommandResult,
    LinuxProvider,
)


class FakeLinuxRunner:
    def __init__(self, results: dict[tuple[str, ...], LinuxCommandResult | None]) -> None:
        self.results = results
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        timeout_seconds: float,
    ) -> LinuxCommandResult | None:
        _ = timeout_seconds
        key = tuple(command)
        self.commands.append(key)
        return self.results.get(key)


def test_linux_provider_reads_uptime_network_wifi_ping_and_cpu_temperature(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "proc/uptime", "12345.67 100.00\n")
    _write(tmp_path / "sys/class/net/wlan0/wireless/.keep", "")
    _write(tmp_path / "sys/class/thermal/thermal_zone0/type", "cpu-thermal\n")
    _write(tmp_path / "sys/class/thermal/thermal_zone0/temp", "45678\n")
    config = AppConfig(
        ping_targets=(PingTarget(id="router", host="192.168.1.1", name="Router"),),
        home_gateways=("192.168.1.1",),
    )
    runner = FakeLinuxRunner(
        {
            (IP_COMMAND, "-j", "addr", "show"): LinuxCommandResult(
                stdout=(
                    '[{"ifname":"eth0","operstate":"UP",'
                    '"addr_info":[{"family":"inet","local":"192.168.1.20"}]},'
                    '{"ifname":"wlan0","operstate":"UP",'
                    '"addr_info":[{"family":"inet","local":"192.168.1.21"}]}]'
                ),
                returncode=0,
            ),
            (IP_COMMAND, "-j", "route", "show", "default"): LinuxCommandResult(
                stdout='[{"gateway":"192.168.1.1","dev":"eth0"}]',
                returncode=0,
            ),
            (IP_COMMAND, "neigh", "show", "192.168.1.1"): LinuxCommandResult(
                stdout="192.168.1.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n",
                returncode=0,
            ),
            (IW_COMMAND, "dev", "wlan0", "link"): LinuxCommandResult(
                stdout=(
                    "Connected to 00:11:22:33:44:55 (on wlan0)\n"
                    "\tSSID: Office WiFi\n"
                    "\tsignal: -58 dBm\n"
                ),
                returncode=0,
            ),
            (PING_COMMAND, "-n", "-c", "1", "-W", "1", "192.168.1.1"): LinuxCommandResult(
                stdout="64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=4.321 ms\n",
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({IP_COMMAND, IW_COMMAND, PING_COMMAND}),
        host_name_provider=lambda: "raspberrypi",
    )

    snapshot = provider.sample(config, update_energy=False)
    payload = snapshot.state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert snapshot.provider == "linux"
    assert payload["host_name"] == "raspberrypi"
    assert payload["uptime_seconds"] == 12345.67
    assert payload["ipv4_addresses"] == "192.168.1.20, 192.168.1.21"
    assert payload["default_gateways"] == "192.168.1.1"
    assert payload["default_gateway_interfaces"] == "eth0"
    assert payload["gateway_macs"] == "aa:bb:cc:dd:ee:ff"
    assert payload["ethernet_active_count"] == 1
    assert payload["ethernet_active_interfaces"] == "eth0"
    assert payload["home_network_present"] is True
    assert payload["wifi_ssid"] == "Office WiFi"
    assert payload["wifi_bssid"] == "00:11:22:33:44:55"
    assert payload["wifi_signal_dbm"] == -58
    assert payload["wifi_signal_percent"] == 84
    assert payload["ping_router_ms"] == 4.321
    assert payload["cpu_temperature_c"] == 45.68
    assert availability["uptime"] == "online"
    assert availability["wifi_signal_dbm"] == "online"
    assert availability["cpu_temperature"] == "online"
    assert "power" not in availability
    assert "energy" not in availability


def test_linux_provider_uses_network_cache_for_network_wifi_and_ping(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "proc/uptime", "12345.67 100.00\n")
    _write(tmp_path / "sys/class/net/wlan0/wireless/.keep", "")
    config = AppConfig(
        network_interval_seconds=60,
        ping_targets=(PingTarget(id="router", host="192.168.1.1", name="Router"),),
    )
    runner = FakeLinuxRunner(
        {
            (IP_COMMAND, "-j", "addr", "show"): LinuxCommandResult(
                stdout=(
                    '[{"ifname":"wlan0","operstate":"UP",'
                    '"addr_info":[{"family":"inet","local":"192.168.1.21"}]}]'
                ),
                returncode=0,
            ),
            (IP_COMMAND, "-j", "route", "show", "default"): LinuxCommandResult(
                stdout='[{"gateway":"192.168.1.1","dev":"wlan0"}]',
                returncode=0,
            ),
            (IP_COMMAND, "neigh", "show", "192.168.1.1"): LinuxCommandResult(
                stdout="192.168.1.1 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n",
                returncode=0,
            ),
            (IW_COMMAND, "dev", "wlan0", "link"): LinuxCommandResult(
                stdout=(
                    "Connected to 00:11:22:33:44:55 (on wlan0)\n"
                    "\tSSID: Office WiFi\n"
                    "\tsignal: -58 dBm\n"
                ),
                returncode=0,
            ),
            (PING_COMMAND, "-n", "-c", "1", "-W", "1", "192.168.1.1"): LinuxCommandResult(
                stdout="64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=4.321 ms\n",
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({IP_COMMAND, IW_COMMAND, PING_COMMAND}),
    )
    network_cache = NetworkSnapshotCache()

    first = provider.sample(config, update_energy=False, network_cache=network_cache)
    second = provider.sample(config, update_energy=False, network_cache=network_cache)

    assert first.state_payload()["wifi_ssid"] == "Office WiFi"
    assert second.state_payload()["ping_router_ms"] == 4.321
    assert runner.commands.count((IP_COMMAND, "-j", "addr", "show")) == 1
    assert runner.commands.count((IP_COMMAND, "-j", "route", "show", "default")) == 1
    assert runner.commands.count((IW_COMMAND, "dev", "wlan0", "link")) == 1
    assert runner.commands.count((PING_COMMAND, "-n", "-c", "1", "-W", "1", "192.168.1.1")) == 1


def test_linux_provider_keeps_supported_wifi_entities_unavailable_when_reads_fail(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "proc/uptime", "1.00 1.00\n")
    _write(tmp_path / "sys/class/net/wlan0/wireless/.keep", "")
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=FakeLinuxRunner({}),
        available_commands=frozenset(),
    )

    snapshot = provider.sample(AppConfig(ping_targets=()), update_energy=False)
    payload = snapshot.state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert "wifi_ssid" in provider.supported_capability_ids(AppConfig(ping_targets=()))
    assert payload["wifi_ssid"] is None
    assert payload["wifi_signal_dbm"] is None
    assert availability["wifi_ssid"] == "offline"
    assert availability["wifi_bssid"] == "offline"
    assert availability["wifi_signal_dbm"] == "offline"


def test_linux_provider_marks_ipv4_unavailable_for_sysfs_only_interfaces(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sys/class/net/eth0/operstate", "up\n")
    _write(
        tmp_path / "proc/net/route",
        (
            "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
            "eth0 00000000 0101A8C0 0003 0 0 0 00000000 0 0 0\n"
        ),
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=FakeLinuxRunner({}),
        available_commands=frozenset(),
    )

    payload = provider.sample(
        AppConfig(home_ipv4_cidrs=("192.168.1.0/24",), ping_targets=()),
        update_energy=False,
    ).state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert payload["ipv4_addresses"] == ""
    assert payload["ethernet_active_count"] == 1
    assert payload["default_gateways"] == "192.168.1.1"
    assert availability["ipv4_addresses"] == "offline"
    assert availability["ethernet_active_count"] == "online"
    assert availability["default_gateways"] == "online"
    assert availability["home_network_present"] == "offline"


def test_linux_provider_does_not_discover_wifi_without_wireless_interface(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "proc/uptime", "1.00 1.00\n")
    runner = FakeLinuxRunner(
        {
            (IW_COMMAND, "dev"): LinuxCommandResult(stdout="", returncode=0),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({IW_COMMAND}),
    )

    supported = provider.supported_capability_ids(AppConfig(ping_targets=()))
    payload = provider.sample(AppConfig(ping_targets=()), update_energy=False).state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert "wifi_ssid" not in supported
    assert "wifi_ssid" not in payload
    assert "wifi_signal_dbm" not in availability


def test_linux_provider_tries_later_wireless_interfaces_when_iw_first_is_disconnected(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sys/class/net/wlan0/wireless/.keep", "")
    _write(tmp_path / "sys/class/net/wlan1/wireless/.keep", "")
    runner = FakeLinuxRunner(
        {
            (IW_COMMAND, "dev"): LinuxCommandResult(
                stdout="phy#0\n\tInterface wlan0\nphy#1\n\tInterface wlan1\n",
                returncode=0,
            ),
            (IW_COMMAND, "dev", "wlan0", "link"): LinuxCommandResult(
                stdout="Not connected.\n",
                returncode=0,
            ),
            (IW_COMMAND, "dev", "wlan1", "link"): LinuxCommandResult(
                stdout=(
                    "Connected to 00:11:22:33:44:66 (on wlan1)\n"
                    "\tSSID: Office WiFi\n"
                    "\tsignal: -61 dBm\n"
                ),
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({IW_COMMAND}),
    )

    payload = provider.sample(AppConfig(ping_targets=()), update_energy=False).state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert payload["wifi_interface"] == "wlan1"
    assert payload["wifi_ssid"] == "Office WiFi"
    assert payload["wifi_bssid"] == "00:11:22:33:44:66"
    assert payload["wifi_signal_dbm"] == -61
    assert availability["wifi_ssid"] == "online"


def test_linux_provider_reads_battery_from_real_sysfs_fields(tmp_path: Path) -> None:
    battery = tmp_path / "sys/class/power_supply/BAT0"
    _write(battery / "type", "Battery\n")
    _write(battery / "capacity", "87\n")
    _write(battery / "charge_full", "4200000\n")
    _write(battery / "charge_full_design", "5000000\n")
    _write(battery / "temp", "315\n")
    _write(battery / "cycle_count", "42\n")
    _write(battery / "status", "Discharging\n")
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=FakeLinuxRunner({}),
        available_commands=frozenset(),
    )

    payload = provider.sample(AppConfig(ping_targets=()), update_energy=False).state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert payload["battery_percent"] == 87
    assert payload["battery_max_capacity_percent"] == 84
    assert payload["battery_max_capacity_mah"] == 4200
    assert payload["battery_design_capacity_mah"] == 5000
    assert payload["battery_temperature_c"] == 31.5
    assert payload["battery_cycle_count"] == 42
    assert payload["battery_status"] == "discharging"
    assert availability["battery"] == "online"
    assert "power" not in availability
    assert "energy" not in availability


def test_linux_provider_discovers_only_real_sysfs_battery_fields(tmp_path: Path) -> None:
    battery = tmp_path / "sys/class/power_supply/BAT0"
    _write(battery / "type", "Battery\n")
    _write(battery / "status", "Charging\n")
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=FakeLinuxRunner({}),
        available_commands=frozenset(),
    )

    payload = provider.sample(AppConfig(ping_targets=()), update_energy=False).state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert "battery" not in provider.supported_capability_ids(AppConfig(ping_targets=()))
    assert "battery_percent" not in payload
    assert payload["battery_status"] == "charging"
    assert "battery" not in availability
    assert availability["battery_status"] == "online"


def test_linux_provider_reads_battery_from_upower_when_sysfs_is_absent(
    tmp_path: Path,
) -> None:
    battery_device = "/org/freedesktop/UPower/devices/battery_BAT0"
    runner = FakeLinuxRunner(
        {
            (UPOWER_COMMAND, "-e"): LinuxCommandResult(
                stdout=f"{battery_device}\n",
                returncode=0,
            ),
            (UPOWER_COMMAND, "-i", battery_device): LinuxCommandResult(
                stdout=(
                    "  native-path:          BAT0\n"
                    "  type:                 battery\n"
                    "  power supply:         yes\n"
                    "  state:                discharging\n"
                    "  percentage:           87%\n"
                    "  capacity:             84%\n"
                    "  temperature:          31.5 degrees C\n"
                    "  charge-cycles:        42\n"
                    "  energy-full:          42.0 Wh\n"
                    "  energy-full-design:   50.0 Wh\n"
                ),
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({UPOWER_COMMAND}),
    )

    payload = provider.sample(AppConfig(ping_targets=()), update_energy=False).state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert payload["battery_percent"] == 87
    assert payload["battery_max_capacity_percent"] == 84
    assert "battery_max_capacity_mah" not in payload
    assert "battery_design_capacity_mah" not in payload
    assert payload["battery_temperature_c"] == 31.5
    assert payload["battery_cycle_count"] == 42
    assert payload["battery_status"] == "discharging"
    assert availability["battery"] == "online"
    assert availability["battery_max_capacity"] == "online"
    assert "battery_max_capacity_mah" not in availability


def test_linux_provider_ignores_upower_peripheral_batteries(
    tmp_path: Path,
) -> None:
    mouse_device = "/org/freedesktop/UPower/devices/battery_hidpp_battery_0"
    runner = FakeLinuxRunner(
        {
            (UPOWER_COMMAND, "-e"): LinuxCommandResult(
                stdout=f"{mouse_device}\n",
                returncode=0,
            ),
            (UPOWER_COMMAND, "-i", mouse_device): LinuxCommandResult(
                stdout=(
                    "  native-path:          hidpp_battery_0\n"
                    "  type:                 battery\n"
                    "  power supply:         no\n"
                    "  state:                discharging\n"
                    "  percentage:           55%\n"
                ),
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({UPOWER_COMMAND}),
    )

    payload = provider.sample(AppConfig(ping_targets=()), update_energy=False).state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert "battery" not in provider.supported_capability_ids(AppConfig(ping_targets=()))
    assert "battery_percent" not in payload
    assert "battery" not in availability


def test_linux_provider_uses_nmcli_for_wifi_on_networkmanager_hosts(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sys/class/net/wlan0/wireless/.keep", "")
    runner = FakeLinuxRunner(
        {
            (
                NMCLI_COMMAND,
                "-t",
                "-f",
                "DEVICE,TYPE,STATE,CONNECTION",
                "dev",
                "status",
            ): LinuxCommandResult(
                stdout="wlan0:wifi:connected:Office WiFi\n",
                returncode=0,
            ),
            (
                NMCLI_COMMAND,
                "-t",
                "-f",
                "ACTIVE,SSID,BSSID,SIGNAL",
                "dev",
                "wifi",
                "list",
                "ifname",
                "wlan0",
            ): LinuxCommandResult(
                stdout="yes:Office WiFi:00\\:11\\:22\\:33\\:44\\:55:72\n",
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({NMCLI_COMMAND}),
    )

    payload = provider.sample(AppConfig(ping_targets=()), update_energy=False).state_payload()

    assert payload["wifi_ssid"] == "Office WiFi"
    assert payload["wifi_bssid"] == "00:11:22:33:44:55"
    assert payload["wifi_signal_dbm"] == -64
    assert payload["wifi_signal_percent"] == 72


def test_linux_provider_decodes_all_raspberry_pi_throttle_flags(tmp_path: Path) -> None:
    _write(tmp_path / "proc/device-tree/model", "Raspberry Pi 3 Model B Plus Rev 1.3\0")
    runner = FakeLinuxRunner(
        {
            (VCGENCMD_COMMAND, "get_throttled"): LinuxCommandResult(
                stdout="throttled=0xf000f\n",
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({VCGENCMD_COMMAND}),
    )

    payload = provider.sample(
        AppConfig(state_path=tmp_path / "state.json", ping_targets=()),
        update_energy=False,
    ).state_payload()

    assert payload["rpi_throttle_flags"] == "0xf000f"
    assert payload["rpi_under_voltage"] is True
    assert payload["rpi_frequency_capped"] is True
    assert payload["rpi_throttled"] is True
    assert payload["rpi_soft_temperature_limit"] is True
    assert payload["rpi_under_voltage_occurred"] is True
    assert payload["rpi_frequency_capped_occurred"] is True
    assert payload["rpi_throttled_occurred"] is True
    assert payload["rpi_soft_temperature_limit_occurred"] is True


def test_linux_provider_reads_pi5_ext5v_supply_voltage(tmp_path: Path) -> None:
    _write(tmp_path / "proc/device-tree/model", "Raspberry Pi 5 Model B Rev 1.0\0")
    pmic_command = (VCGENCMD_COMMAND, "pmic_read_adc", "EXT5V_V")
    runner = FakeLinuxRunner(
        {
            (VCGENCMD_COMMAND, "get_throttled"): LinuxCommandResult(
                stdout="throttled=0x0\n",
                returncode=0,
            ),
            pmic_command: LinuxCommandResult(
                stdout="EXT5V_V volt(24)=5.11746000V\n",
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({VCGENCMD_COMMAND}),
    )
    config = AppConfig(state_path=tmp_path / "state.json", ping_targets=())

    supported = provider.supported_capability_ids(config)
    payload = provider.sample(config, update_energy=False).state_payload()

    assert "rpi_input_voltage" in supported
    assert payload["rpi_input_voltage_v"] == 5.117
    assert pmic_command in runner.commands


def test_linux_provider_keeps_pi5_input_voltage_discovered_when_read_fails(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "proc/device-tree/model", "Raspberry Pi 5 Model B Rev 1.0\0")
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=FakeLinuxRunner(
            {
                (VCGENCMD_COMMAND, "get_throttled"): LinuxCommandResult(
                    stdout="throttled=0x0\n",
                    returncode=0,
                ),
                (VCGENCMD_COMMAND, "pmic_read_adc", "EXT5V_V"): LinuxCommandResult(
                    stdout="error=unsupported\n",
                    returncode=0,
                ),
            }
        ),
        available_commands=frozenset({VCGENCMD_COMMAND}),
    )
    config = AppConfig(state_path=tmp_path / "state.json", ping_targets=())

    supported = provider.supported_capability_ids(config)
    payload = provider.sample(config, update_energy=False).state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert "rpi_input_voltage" in supported
    assert payload["rpi_input_voltage_v"] is None
    assert availability["rpi_input_voltage"] == "offline"


def test_linux_provider_omits_rpi_flags_when_tool_or_hardware_is_missing(tmp_path: Path) -> None:
    config = AppConfig(state_path=tmp_path / "state.json", ping_targets=())
    tool_only_runner = FakeLinuxRunner({})
    tool_only = LinuxProvider(
        root=tmp_path,
        command_runner=tool_only_runner,
        available_commands=frozenset({VCGENCMD_COMMAND}),
    )

    assert "rpi_throttle_flags" not in tool_only.supported_capability_ids(config)
    assert (VCGENCMD_COMMAND, "get_throttled") not in tool_only_runner.commands

    _write(tmp_path / "proc/device-tree/compatible", "raspberrypi,5-model-b\0brcm,bcm2712\0")
    hardware_only = LinuxProvider(
        root=tmp_path,
        command_runner=FakeLinuxRunner({}),
        available_commands=frozenset(),
    )

    assert "rpi_throttle_flags" not in hardware_only.supported_capability_ids(config)
    assert "rpi_input_voltage" not in hardware_only.supported_capability_ids(config)


def test_linux_provider_interprets_0x50000_as_sticky_history_only(tmp_path: Path) -> None:
    _write(tmp_path / "proc/device-tree/model", "Raspberry Pi 4 Model B Rev 1.5\0")
    runner = FakeLinuxRunner(
        {
            (VCGENCMD_COMMAND, "get_throttled"): LinuxCommandResult(
                stdout="throttled=0x50000\n",
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({VCGENCMD_COMMAND}),
    )

    payload = provider.sample(
        AppConfig(state_path=tmp_path / "state.json", ping_targets=()),
        update_energy=False,
    ).state_payload()

    assert payload["rpi_under_voltage"] is False
    assert payload["rpi_throttled"] is False
    assert payload["rpi_under_voltage_occurred"] is True
    assert payload["rpi_throttled_occurred"] is True


def test_linux_provider_omits_unsupported_soft_temperature_entities(tmp_path: Path) -> None:
    _write(tmp_path / "proc/device-tree/model", "Raspberry Pi 4 Model B Rev 1.5\0")
    runner = FakeLinuxRunner(
        {
            (VCGENCMD_COMMAND, "get_throttled"): LinuxCommandResult(
                stdout="throttled=0x80008\n",
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({VCGENCMD_COMMAND}),
    )
    config = AppConfig(state_path=tmp_path / "state.json", ping_targets=())

    supported = provider.supported_capability_ids(config)
    payload = provider.sample(config, update_energy=False).state_payload()

    assert "rpi_throttle_flags" in supported
    assert "rpi_soft_temperature_limit" not in supported
    assert "rpi_soft_temperature_limit_occurred" not in supported
    assert "rpi_input_voltage" not in supported
    assert payload["rpi_throttle_flags"] == "0x80008"
    assert "rpi_soft_temperature_limit" not in payload
    assert (VCGENCMD_COMMAND, "pmic_read_adc", "EXT5V_V") not in runner.commands


def test_linux_provider_omits_unsupported_under_voltage_entities_on_pi_zero(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "proc/device-tree/model", "Raspberry Pi Zero 2 W Rev 1.0\0")
    runner = FakeLinuxRunner(
        {
            (VCGENCMD_COMMAND, "get_throttled"): LinuxCommandResult(
                stdout="throttled=0x40004\n",
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({VCGENCMD_COMMAND}),
    )
    config = AppConfig(state_path=tmp_path / "state.json", ping_targets=())

    supported = provider.supported_capability_ids(config)
    payload = provider.sample(config, update_energy=False).state_payload()

    assert "rpi_throttle_flags" in supported
    assert "rpi_throttled" in supported
    assert "rpi_under_voltage" not in supported
    assert "rpi_under_voltage_occurred" not in supported
    assert payload["rpi_throttled"] is True
    assert "rpi_under_voltage" not in payload


def test_linux_provider_omits_unsupported_under_voltage_entities_on_original_pi(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "proc/device-tree/model", "Raspberry Pi Model B Rev 2.0\0")
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=FakeLinuxRunner(
            {
                (VCGENCMD_COMMAND, "get_throttled"): LinuxCommandResult(
                    stdout="throttled=0x40004\n",
                    returncode=0,
                ),
            }
        ),
        available_commands=frozenset({VCGENCMD_COMMAND}),
    )
    config = AppConfig(state_path=tmp_path / "state.json", ping_targets=())

    supported = provider.supported_capability_ids(config)
    payload = provider.sample(config, update_energy=False).state_payload()

    assert "rpi_throttle_flags" in supported
    assert "rpi_throttled" in supported
    assert "rpi_under_voltage" not in supported
    assert "rpi_under_voltage_occurred" not in supported
    assert payload["rpi_throttled"] is True
    assert "rpi_under_voltage" not in payload


def test_linux_provider_keeps_rpi_entities_discovered_when_firmware_read_fails(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "proc/device-tree/model", "Raspberry Pi 4 Model B Rev 1.5\0")
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=FakeLinuxRunner(
            {
                (VCGENCMD_COMMAND, "get_throttled"): LinuxCommandResult(
                    stdout="vc_gencmd_read_response returned -1\n",
                    returncode=1,
                ),
            }
        ),
        available_commands=frozenset({VCGENCMD_COMMAND}),
    )

    payload = provider.sample(
        AppConfig(state_path=tmp_path / "state.json", ping_targets=()),
        update_energy=True,
    ).state_payload()
    availability = cast(dict[str, str], payload["availability"])

    assert payload["rpi_throttle_flags"] is None
    assert availability["rpi_throttle_flags"] == "offline"
    assert availability["rpi_under_voltage"] == "offline"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
