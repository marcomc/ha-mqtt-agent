from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from ha_mqtt_agent.config import AppConfig, PingTarget
from ha_mqtt_agent.network import (
    AIRPORT_PATH,
    IFCONFIG_PATH,
    NETWORKSETUP_PATH,
    OPEN_PATH,
    PING_PATH,
    ROUTE_PATH,
    SYSTEM_PROFILER_PATH,
    CommandResult,
    NetworkSensorReader,
)


class FakeRunner:
    def __init__(self, results: dict[tuple[str, ...], CommandResult | None]) -> None:
        self.results = results
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        timeout_seconds: float,
    ) -> CommandResult | None:
        _ = timeout_seconds
        key = tuple(command)
        self.commands.append(key)
        return self.results.get(key)


def test_network_reader_reports_wifi_ethernet_and_ping_payload() -> None:
    config = AppConfig(
        ping_targets=(PingTarget(id="cloudflare_dns", host="1.1.1.1", name="Cloudflare DNS"),),
    )
    runner = FakeRunner(
        {
            (NETWORKSETUP_PATH, "-listallhardwareports"): CommandResult(
                stdout="""
                Hardware Port: USB 10/100/1000 LAN
                Device: en4
                Ethernet Address: 00:e0:4c:68:1f:37

                Hardware Port: Wi-Fi
                Device: en0
                Ethernet Address: aa:bb:cc:dd:ee:ff
                """,
                returncode=0,
            ),
            (SYSTEM_PROFILER_PATH, "SPAirPortDataType", "-json"): CommandResult(
                stdout="""
                {
                  "SPAirPortDataType": [
                    {
                      "spairport_airport_interfaces": [
                        {
                          "_name": "en0",
                          "spairport_current_network_information": {
                            "_name": "Office WiFi",
                            "spairport_signal_noise": "-55 dBm / -91 dBm"
                          }
                        }
                      ]
                    }
                  ]
                }
                """,
                returncode=0,
            ),
            (NETWORKSETUP_PATH, "-getairportnetwork", "en0"): CommandResult(
                stdout="Current Wi-Fi Network: Office WiFi\n",
                returncode=0,
            ),
            (IFCONFIG_PATH, "en4"): CommandResult(
                stdout="""
                en4: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
                    inet 192.168.1.113 netmask 0xffffff00 broadcast 192.168.1.255
                    media: autoselect (1000baseT <full-duplex>)
                    status: active
                """,
                returncode=0,
            ),
            (PING_PATH, "-n", "-c", "1", "-W", "1000", "1.1.1.1"): CommandResult(
                stdout="64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=12.345 ms\n",
                returncode=0,
            ),
        }
    )

    payload = NetworkSensorReader(command_runner=runner).read(config).payload()

    assert payload["wifi_interface"] == "en0"
    assert payload["wifi_ssid"] == "Office WiFi"
    assert payload["wifi_signal_dbm"] == -55
    assert payload["wifi_signal_percent"] == 90
    assert payload["ethernet_active_count"] == 1
    assert payload["ethernet_active_interfaces"] == "en4"
    assert payload["ping_cloudflare_dns_ms"] == 12.345


def test_network_reader_reports_home_network_diagnostics(tmp_path: Path) -> None:
    helper_path = tmp_path / "HaMqttAgentWifiHelper"
    helper_path.write_text("", encoding="utf-8")
    config = AppConfig(
        ping_targets=(),
        wifi_helper_path=helper_path,
        home_ssids=("Office WiFi", "Office Guest"),
        home_ipv4_cidrs=("192.168.1.0/24",),
        home_gateways=("192.168.1.1",),
        home_bssids=("00:11:22:33:44:55",),
        home_gateway_macs=("aa:bb:cc:dd:ee:ff",),
        publish_location=True,
    )
    runner = FakeRunner(
        {
            (NETWORKSETUP_PATH, "-listallhardwareports"): CommandResult(
                stdout="""
                Hardware Port: USB 10/100/1000 LAN
                Device: en4
                Ethernet Address: 00:e0:4c:68:1f:37

                Hardware Port: Wi-Fi
                Device: en0
                Ethernet Address: aa:bb:cc:dd:ee:ff
                """,
                returncode=0,
            ),
            (
                str(helper_path),
                "--json",
                "--location-timeout",
                "3",
                "--geocode-timeout",
                "3",
            ): CommandResult(
                stdout=(
                    '{"authorized":true,"authorization_status":"authorized_when_in_use",'
                    '"interface":"en0","ssid":"Office WiFi","bssid":"00:11:22:33:44:55",'
                    '"signal_dbm":-53,"noise_dbm":-92,'
                    '"latitude":45.4642,"longitude":9.19,"location_accuracy_m":65.5,'
                    '"geocoded_location":{"state":"Piazza del Duomo, Milano, Italia",'
                    '"name":"Duomo di Milano","country":"Italia","iso_country_code":"IT",'
                    '"time_zone":"Europe/Rome","administrative_area":"Lombardia",'
                    '"sub_administrative_area":"Milano","postal_code":"20122",'
                    '"locality":"Milano","sub_locality":"Centro Storico",'
                    '"thoroughfare":"Piazza del Duomo","sub_thoroughfare":"1",'
                    '"areas_of_interest":["Duomo di Milano"],'
                    '"ocean":null,"inland_water":null,"error":null},'
                    '"error":null}'
                ),
                returncode=0,
            ),
            (IFCONFIG_PATH, "en4"): CommandResult(
                stdout="""
                en4: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
                    inet 192.168.1.113 netmask 0xffffff00 broadcast 192.168.1.255
                    status: active
                """,
                returncode=0,
            ),
            (IFCONFIG_PATH, "en0"): CommandResult(
                stdout="""
                en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
                    inet 192.168.1.114 netmask 0xffffff00 broadcast 192.168.1.255
                    status: active
                """,
                returncode=0,
            ),
            (ROUTE_PATH, "-n", "get", "default"): CommandResult(
                stdout="""
                   route to: default
                destination: default
                       mask: default
                    gateway: 192.168.1.1
                  interface: en4
                """,
                returncode=0,
            ),
            ("/usr/sbin/arp", "-n", "192.168.1.1"): CommandResult(
                stdout="? (192.168.1.1) at a:bb:cc:dd:ee:ff on en4 ifscope [ethernet]\n",
                returncode=0,
            ),
        }
    )

    payload = NetworkSensorReader(command_runner=runner).read(config).payload()

    assert payload["wifi_bssid"] == "00:11:22:33:44:55"
    assert payload["ipv4_addresses"] == "192.168.1.113, 192.168.1.114"
    assert payload["default_gateways"] == "192.168.1.1"
    assert payload["default_gateway_interfaces"] == "en4"
    assert payload["gateway_macs"] == "0a:bb:cc:dd:ee:ff"
    assert payload["home_network_present"] is True
    assert payload["latitude"] == 45.4642
    assert payload["longitude"] == 9.19
    assert payload["location_accuracy_m"] == 65.5
    assert payload["geocoded_location"] == "Piazza del Duomo, Milano, Italia"
    assert payload["geocoded_location_name"] == "Duomo di Milano"
    assert payload["geocoded_location_country"] == "Italia"
    assert payload["geocoded_location_iso_country_code"] == "IT"
    assert payload["geocoded_location_time_zone"] == "Europe/Rome"
    assert payload["geocoded_location_administrative_area"] == "Lombardia"
    assert payload["geocoded_location_sub_administrative_area"] == "Milano"
    assert payload["geocoded_location_postal_code"] == "20122"
    assert payload["geocoded_location_locality"] == "Milano"
    assert payload["geocoded_location_sub_locality"] == "Centro Storico"
    assert payload["geocoded_location_thoroughfare"] == "Piazza del Duomo"
    assert payload["geocoded_location_sub_thoroughfare"] == "1"
    assert payload["geocoded_location_areas_of_interest"] == ["Duomo di Milano"]


def test_network_reader_keeps_ping_sensor_null_when_target_is_unreachable() -> None:
    config = AppConfig(
        ping_targets=(PingTarget(id="router", host="192.0.2.1", name="Router"),),
        ping_timeout_seconds=0.5,
    )
    runner = FakeRunner(
        {
            (NETWORKSETUP_PATH, "-listallhardwareports"): CommandResult(stdout="", returncode=0),
            (SYSTEM_PROFILER_PATH, "SPAirPortDataType", "-json"): CommandResult(
                stdout="{}",
                returncode=0,
            ),
            (PING_PATH, "-n", "-c", "1", "-W", "500", "192.0.2.1"): CommandResult(
                stdout="--- 192.0.2.1 ping statistics ---\n100.0% packet loss\n",
                returncode=2,
            ),
        }
    )

    payload = NetworkSensorReader(command_runner=runner).read(config).payload()

    assert payload["ping_router_ms"] is None
    assert payload["ethernet_active_count"] == 0


def test_network_reader_uses_networksetup_ssid_when_profiler_redacts_name() -> None:
    config = AppConfig(ping_targets=())
    runner = FakeRunner(
        {
            (NETWORKSETUP_PATH, "-listallhardwareports"): CommandResult(
                stdout="""
                Hardware Port: Wi-Fi
                Device: en0
                Ethernet Address: aa:bb:cc:dd:ee:ff
                """,
                returncode=0,
            ),
            (NETWORKSETUP_PATH, "-getairportnetwork", "en0"): CommandResult(
                stdout="Current Wi-Fi Network: Office WiFi\n",
                returncode=0,
            ),
            (SYSTEM_PROFILER_PATH, "SPAirPortDataType", "-json"): CommandResult(
                stdout="""
                {
                  "SPAirPortDataType": [
                    {
                      "spairport_airport_interfaces": [
                        {
                          "_name": "en0",
                          "spairport_current_network_information": {
                            "_name": "<redacted>",
                            "spairport_signal_noise": "-61 dBm / -92 dBm"
                          }
                        }
                      ]
                    }
                  ]
                }
                """,
                returncode=0,
            ),
        }
    )

    payload = NetworkSensorReader(command_runner=runner).read(config).payload()

    assert payload["wifi_ssid"] == "Office WiFi"
    assert payload["wifi_signal_dbm"] == -61


def test_network_reader_uses_airport_command_from_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_which(command: str) -> str | None:
        if command == "airport":
            return "/usr/local/bin/airport"
        return None

    monkeypatch.setattr("ha_mqtt_agent.network.shutil.which", fake_which)
    config = AppConfig(ping_targets=(), wifi_helper_path=tmp_path / "missing-helper")
    runner = FakeRunner(
        {
            (NETWORKSETUP_PATH, "-listallhardwareports"): CommandResult(
                stdout="""
                Hardware Port: Wi-Fi
                Device: en0
                Ethernet Address: aa:bb:cc:dd:ee:ff
                """,
                returncode=0,
            ),
            (NETWORKSETUP_PATH, "-getairportnetwork", "en0"): CommandResult(
                stdout="You are not associated with an AirPort network.\n",
                returncode=1,
            ),
            ("/usr/local/bin/airport", "-I"): CommandResult(
                stdout="""
                agrCtlRSSI: -48
                SSID: Office WiFi
                """,
                returncode=0,
            ),
        }
    )

    payload = NetworkSensorReader(command_runner=runner).read(config).payload()

    assert payload["wifi_ssid"] == "Office WiFi"
    assert payload["wifi_signal_dbm"] == -48
    assert (AIRPORT_PATH, "-I") not in runner.commands
    assert ("/usr/local/bin/airport", "-I") in runner.commands


def test_network_reader_prefers_authorized_wifi_helper_ssid(tmp_path: Path) -> None:
    helper_path = tmp_path / "HaMqttAgentWifiHelper"
    helper_path.write_text("", encoding="utf-8")
    config = AppConfig(ping_targets=(), wifi_helper_path=helper_path)
    runner = FakeRunner(
        {
            (NETWORKSETUP_PATH, "-listallhardwareports"): CommandResult(
                stdout="""
                Hardware Port: Wi-Fi
                Device: en0
                Ethernet Address: aa:bb:cc:dd:ee:ff
                """,
                returncode=0,
            ),
            (str(helper_path), "--json"): CommandResult(
                stdout=(
                    '{"authorized":true,"authorization_status":"authorized_when_in_use",'
                    '"interface":"en0","ssid":"Office WiFi","bssid":"00:11:22:33:44:55",'
                    '"signal_dbm":-53,"noise_dbm":-92,"error":null}'
                ),
                returncode=0,
            ),
        }
    )

    payload = NetworkSensorReader(command_runner=runner).read(config).payload()

    assert payload["wifi_ssid"] == "Office WiFi"
    assert payload["wifi_signal_dbm"] == -53
    assert payload["wifi_signal_percent"] == 94
    assert (str(helper_path), "--authorize") not in runner.commands


def test_network_reader_runs_app_bundle_helper_through_launch_services(tmp_path: Path) -> None:
    app_path = tmp_path / "HaMqttAgentWifiHelper.app"
    helper_path = app_path / "Contents" / "MacOS" / "HaMqttAgentWifiHelper"
    helper_path.parent.mkdir(parents=True)
    helper_path.write_text("", encoding="utf-8")
    config = AppConfig(ping_targets=(), wifi_helper_path=helper_path, publish_location=True)

    class LaunchServicesRunner(FakeRunner):
        def __call__(
            self,
            command: Sequence[str],
            timeout_seconds: float,
        ) -> CommandResult | None:
            self.commands.append(tuple(command))
            if command[0] == OPEN_PATH:
                output_path = Path(command[command.index("--output") + 1])
                output_path.write_text(
                    (
                        '{"authorized":true,"authorization_status":"authorized_always",'
                        '"interface":"en0","ssid":"Office WiFi",'
                        '"bssid":"00:11:22:33:44:55","signal_dbm":-53,'
                        '"latitude":45.4642,"longitude":9.19,'
                        '"location_accuracy_m":35}'
                    ),
                    encoding="utf-8",
                )
                return CommandResult(stdout="", returncode=0)
            return super().__call__(command, timeout_seconds)

    runner = LaunchServicesRunner(
        {
            (NETWORKSETUP_PATH, "-listallhardwareports"): CommandResult(
                stdout="""
                Hardware Port: Wi-Fi
                Device: en0
                Ethernet Address: aa:bb:cc:dd:ee:ff
                """,
                returncode=0,
            ),
            (IFCONFIG_PATH, "en0"): CommandResult(
                stdout="""
                en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
                    inet 192.168.1.114 netmask 0xffffff00 broadcast 192.168.1.255
                    status: active
                """,
                returncode=0,
            ),
            (ROUTE_PATH, "-n", "get", "default"): CommandResult(stdout="", returncode=1),
        }
    )

    payload = NetworkSensorReader(command_runner=runner).read(config).payload()

    assert payload["wifi_ssid"] == "Office WiFi"
    assert payload["wifi_bssid"] == "00:11:22:33:44:55"
    assert payload["latitude"] == 45.4642
    assert payload["longitude"] == 9.19
    assert any(command[0] == OPEN_PATH for command in runner.commands)
    assert (
        str(helper_path),
        "--json",
        "--location-timeout",
        "3",
        "--geocode-timeout",
        "3",
    ) not in runner.commands


def test_network_reader_reports_location_error_when_location_is_unknown(
    tmp_path: Path,
) -> None:
    helper_path = tmp_path / "HaMqttAgentWifiHelper"
    helper_path.write_text("", encoding="utf-8")
    config = AppConfig(ping_targets=(), wifi_helper_path=helper_path, publish_location=True)
    runner = FakeRunner(
        {
            (NETWORKSETUP_PATH, "-listallhardwareports"): CommandResult(
                stdout="""
                Hardware Port: Wi-Fi
                Device: en0
                Ethernet Address: aa:bb:cc:dd:ee:ff
                """,
                returncode=0,
            ),
            (
                str(helper_path),
                "--json",
                "--location-timeout",
                "3",
                "--geocode-timeout",
                "3",
            ): CommandResult(
                stdout=(
                    '{"authorized":true,"authorization_status":"authorized_always",'
                    '"interface":"en0","ssid":"Office WiFi",'
                    '"location_error":"The operation could not be completed."}'
                ),
                returncode=0,
            ),
        }
    )

    payload = NetworkSensorReader(command_runner=runner).read(config).payload()

    assert payload["latitude"] is None
    assert payload["longitude"] is None
    assert payload["location_accuracy_m"] is None
    assert payload["location_error"] == "The operation could not be completed."
