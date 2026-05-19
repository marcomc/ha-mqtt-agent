from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from ha_mqtt_agent.config import AppConfig, PingTarget
from ha_mqtt_agent.network import (
    AIRPORT_PATH,
    IFCONFIG_PATH,
    NETWORKSETUP_PATH,
    PING_PATH,
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
