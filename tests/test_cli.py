from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from ha_mqtt_agent import __version__, cli
from ha_mqtt_agent.config import AppConfig, load_config
from ha_mqtt_agent.network import GeocodedLocation, LocationStatus, NetworkSample, WifiStatus
from ha_mqtt_agent.sensors import SensorSample


def test_main_without_args_prints_focused_help(capsys: pytest.CaptureFixture[str]) -> None:
    expected_usage = "usage: ha-mqtt-agent [--version] [--config PATH] [--verbose] <command>"
    result = cli.main([])

    captured = capsys.readouterr()

    assert result == 0
    assert expected_usage in captured.out
    assert "Commands:" in captured.out
    assert "info" in captured.out
    assert "run" in captured.out


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main(["--version"])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out.strip() == __version__


def test_info_command_reads_config_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'mqtt_host = "mqtt.example.test"\ndevice_name = "Workstation"\nverbose = false\n',
        encoding="utf-8",
    )

    result = cli.main(["--config", str(config_path), "info"])

    captured = capsys.readouterr()

    assert result == 0
    assert "mqtt_host: mqtt.example.test" in captured.out
    assert "device_name: Workstation" in captured.out
    assert f"config_path: {config_path}" in captured.out


def test_info_command_can_emit_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('mqtt_host = "mqtt.example.test"\n', encoding="utf-8")

    result = cli.main(["--config", str(config_path), "info", "--json"])

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload["project_name"] == "Home Assistant MQTT Agent"
    assert payload["cli_name"] == "ha-mqtt-agent"
    assert payload["mqtt_host"] == "mqtt.example.test"
    assert payload["mqtt_client_id"] == "ha-mqtt-agent-host"


def test_config_derives_default_mqtt_client_id_from_device_id(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('device_id = "workstation"\n', encoding="utf-8")

    config = load_config(config_path)

    assert config.resolved_mqtt_client_id == "ha-mqtt-agent-workstation"


def test_config_keeps_explicit_mqtt_client_id(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'device_id = "workstation"\nmqtt_client_id = "custom-agent"\n',
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.resolved_mqtt_client_id == "custom-agent"


def test_example_config_uses_inert_home_network_defaults() -> None:
    config = load_config(Path("config.toml.example"))

    assert config.resolved_mqtt_client_id == "ha-mqtt-agent-host"
    assert config.home_ssids == ()
    assert config.home_ipv4_cidrs == ()
    assert config.home_gateways == ()
    assert config.home_bssids == ()
    assert config.home_gateway_macs == ()


def test_config_rejects_sample_interval_below_supported_minimum(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("sample_interval_seconds = 0.5\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sample_interval_seconds must be at least 1 second"):
        load_config(config_path)


def test_config_reads_expire_after_seconds(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("expire_after_seconds = 5\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.expire_after_seconds == 5


def test_config_reads_custom_ping_targets(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    helper_path = tmp_path / "WifiHelper"
    config_path.write_text(
        f"""
        ping_targets = [
          {{ id = "router", host = "192.168.1.1", name = "Router" }},
          {{ id = "quad9_dns", host = "9.9.9.9", name = "Quad9 DNS" }}
        ]
        network_interval_seconds = 30
        ping_timeout_seconds = 0.5
        wifi_helper_path = "{helper_path}"
        """,
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert [target.id for target in config.ping_targets] == ["router", "quad9_dns"]
    assert [target.host for target in config.ping_targets] == ["192.168.1.1", "9.9.9.9"]
    assert config.network_interval_seconds == 30
    assert config.ping_timeout_seconds == 0.5
    assert config.wifi_helper_path == helper_path


def test_config_reads_home_network_and_location_options(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        home_ssids = ["HoStello", "HoStello IoT"]
        home_ipv4_cidrs = ["192.168.1.0/24"]
        home_gateways = ["192.168.1.1"]
        home_bssids = ["AA:BB:CC:DD:EE:FF"]
        home_gateway_macs = ["11:22:33:44:55:66"]
        publish_location = true
        location_timeout_seconds = 2
        """,
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.home_ssids == ("HoStello", "HoStello IoT")
    assert config.home_ipv4_cidrs == ("192.168.1.0/24",)
    assert config.home_gateways == ("192.168.1.1",)
    assert config.home_bssids == ("aa:bb:cc:dd:ee:ff",)
    assert config.home_gateway_macs == ("11:22:33:44:55:66",)
    assert config.publish_location is True
    assert config.location_timeout_seconds == 2


def test_config_accepts_ping_targets_as_host_list(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('ping_targets = ["1.1.1.1", "8.8.8.8"]\n', encoding="utf-8")

    config = load_config(config_path)

    assert [target.id for target in config.ping_targets] == ["ip_1_1_1_1", "ip_8_8_8_8"]


def test_config_rejects_duplicate_ping_target_ids(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        ping_targets = [
          { id = "router", host = "192.168.1.1", name = "Router" },
          { id = "router", host = "192.168.1.2", name = "Backup router" }
        ]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ping_targets ids must be unique"):
        load_config(config_path)


def test_config_rejects_max_energy_gap_below_supported_minimum(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("max_energy_gap_seconds = 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="max_energy_gap_seconds must be at least 1 second"):
        load_config(config_path)


def test_config_defaults_to_five_second_publish_and_fifteen_second_expiry(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    config = load_config(config_path)

    assert config.sample_interval_seconds == 5
    assert config.expire_after_seconds == 15


def test_sample_command_does_not_write_energy_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = AppConfig(state_path=tmp_path / "state.json")
    sample = SensorSample(
        timestamp=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
        host_name="macbook",
        uptime_seconds=123,
        power_w=12.5,
        battery_percent=80,
        battery_max_capacity_percent=90,
        battery_max_capacity_mah=4500,
        battery_design_capacity_mah=5000,
        battery_reported_max_capacity_percent=100,
        battery_temperature_c=32.5,
        battery_virtual_temperature_c=33.5,
        battery_cycle_count=20,
        battery_status="charging",
        external_power=True,
    )
    reader = Mock()
    reader.read.return_value = sample
    network_reader = Mock()
    network_reader.read.return_value = NetworkSample(
        wifi=WifiStatus(
            interface="en0",
            ssid="Office",
            signal_dbm=-55,
            signal_percent=90,
        ),
        ethernet=(),
        pings=(),
    )
    monkeypatch.setattr(cli, "IoregSensorReader", Mock(return_value=reader))
    monkeypatch.setattr(cli, "NetworkSensorReader", Mock(return_value=network_reader))

    result = cli._handle_sample(config, as_json=True)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["energy_kwh"] == 0
    assert payload["wifi_ssid"] == "Office"
    assert not config.state_path.exists()


def test_sample_payload_reuses_last_known_location_when_current_location_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "energy_kwh": 0,
                "last_location": {
                    "latitude": 45.4642,
                    "longitude": 9.19,
                    "accuracy_m": 35.0,
                    "timestamp": "2026-05-17T10:00:00+00:00",
                },
                "last_geocoded_location": {
                    "state": "Piazza del Duomo, Milano, Italia",
                    "name": "Duomo di Milano",
                    "country": "Italia",
                    "iso_country_code": "IT",
                    "time_zone": "Europe/Rome",
                    "administrative_area": "Lombardia",
                    "sub_administrative_area": "Milano",
                    "postal_code": "20122",
                    "locality": "Milano",
                    "sub_locality": "Centro Storico",
                    "thoroughfare": "Piazza del Duomo",
                    "sub_thoroughfare": "1",
                    "areas_of_interest": ["Duomo di Milano"],
                    "timestamp": "2026-05-17T10:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig(state_path=state_path, publish_location=True)
    reader = Mock()
    reader.read.return_value = SensorSample(
        timestamp=datetime(2026, 5, 17, 10, 1, tzinfo=UTC),
        host_name="macbook",
        uptime_seconds=123,
        power_w=12.5,
        battery_percent=80,
        battery_max_capacity_percent=90,
        battery_max_capacity_mah=4500,
        battery_design_capacity_mah=5000,
        battery_reported_max_capacity_percent=100,
        battery_temperature_c=32.5,
        battery_virtual_temperature_c=33.5,
        battery_cycle_count=20,
        battery_status="charging",
        external_power=True,
    )
    network_reader = Mock()
    network_reader.read.return_value = NetworkSample(
        wifi=WifiStatus(
            interface="en0",
            ssid="Office",
            signal_dbm=-55,
            signal_percent=90,
        ),
        ethernet=(),
        pings=(),
        location=LocationStatus(error="The operation could not be completed."),
    )
    monkeypatch.setattr(cli, "IoregSensorReader", Mock(return_value=reader))
    monkeypatch.setattr(cli, "NetworkSensorReader", Mock(return_value=network_reader))

    payload = cli._sample_payload(config)

    assert payload["latitude"] == 45.4642
    assert payload["longitude"] == 9.19
    assert payload["location_accuracy_m"] == 35.0
    assert payload["location_cached"] is True
    assert payload["location_last_seen"] == "2026-05-17T10:00:00+00:00"
    assert payload["location_error"] == "The operation could not be completed."
    assert payload["geocoded_location"] == "Piazza del Duomo, Milano, Italia"
    assert payload["geocoded_location_name"] == "Duomo di Milano"
    assert payload["geocoded_location_country"] == "Italia"
    assert payload["geocoded_location_cached"] is True


def test_sample_payload_reverse_geocodes_cached_location_when_address_cache_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper_path = tmp_path / "HaMqttAgentWifiHelper"
    helper_path.write_text("", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "energy_kwh": 0,
                "last_location": {
                    "latitude": 45.4642,
                    "longitude": 9.19,
                    "accuracy_m": 35.0,
                    "timestamp": "2026-05-17T10:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig(
        state_path=state_path,
        publish_location=True,
        wifi_helper_path=helper_path,
    )
    reader = Mock()
    reader.read.return_value = SensorSample(
        timestamp=datetime(2026, 5, 17, 10, 1, tzinfo=UTC),
        host_name="macbook",
        uptime_seconds=123,
        power_w=12.5,
        battery_percent=80,
        battery_max_capacity_percent=90,
        battery_max_capacity_mah=4500,
        battery_design_capacity_mah=5000,
        battery_reported_max_capacity_percent=100,
        battery_temperature_c=32.5,
        battery_virtual_temperature_c=33.5,
        battery_cycle_count=20,
        battery_status="charging",
        external_power=True,
    )
    network_reader = Mock()
    network_reader.read.return_value = NetworkSample(
        wifi=WifiStatus(
            interface="en0",
            ssid="Office",
            signal_dbm=-55,
            signal_percent=90,
        ),
        ethernet=(),
        pings=(),
        location=LocationStatus(error="The operation could not be completed."),
    )
    helper_result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            '{"geocoded_location":{"state":"Piazza del Duomo, Milano, Italia",'
            '"name":"Duomo di Milano","country":"Italia","locality":"Milano",'
            '"areas_of_interest":["Duomo di Milano"],"error":null}}'
        ),
        stderr="",
    )
    run_helper = Mock(return_value=helper_result)
    monkeypatch.setattr(cli, "IoregSensorReader", Mock(return_value=reader))
    monkeypatch.setattr(cli, "NetworkSensorReader", Mock(return_value=network_reader))
    monkeypatch.setattr(cli, "_run_wifi_helper_for_cli", run_helper)

    payload = cli._sample_payload(config)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["geocoded_location"] == "Piazza del Duomo, Milano, Italia"
    assert payload["geocoded_location_name"] == "Duomo di Milano"
    assert payload["geocoded_location_cached"] is True
    assert state["last_geocoded_location"]["state"] == "Piazza del Duomo, Milano, Italia"
    assert state["last_geocoded_location"]["timestamp"] == "2026-05-17T10:00:00+00:00"
    run_helper.assert_called_once()
    assert run_helper.call_args.args[1][:5] == [
        "--reverse-geocode",
        "--latitude",
        "45.4642",
        "--longitude",
        "9.19",
    ]


def test_sample_payload_does_not_reverse_geocode_cached_location_in_read_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper_path = tmp_path / "HaMqttAgentWifiHelper"
    helper_path.write_text("", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "energy_kwh": 0,
                "last_location": {
                    "latitude": 45.4642,
                    "longitude": 9.19,
                    "accuracy_m": 35.0,
                    "timestamp": "2026-05-17T10:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig(
        state_path=state_path,
        publish_location=True,
        wifi_helper_path=helper_path,
    )
    reader = Mock()
    reader.read.return_value = SensorSample(
        timestamp=datetime(2026, 5, 17, 10, 1, tzinfo=UTC),
        host_name="macbook",
        uptime_seconds=123,
        power_w=12.5,
        battery_percent=80,
        battery_max_capacity_percent=90,
        battery_max_capacity_mah=4500,
        battery_design_capacity_mah=5000,
        battery_reported_max_capacity_percent=100,
        battery_temperature_c=32.5,
        battery_virtual_temperature_c=33.5,
        battery_cycle_count=20,
        battery_status="charging",
        external_power=True,
    )
    network_reader = Mock()
    network_reader.read.return_value = NetworkSample(
        wifi=WifiStatus(
            interface="en0",
            ssid="Office",
            signal_dbm=-55,
            signal_percent=90,
        ),
        ethernet=(),
        pings=(),
        location=LocationStatus(error="The operation could not be completed."),
    )
    run_helper = Mock()
    monkeypatch.setattr(cli, "IoregSensorReader", Mock(return_value=reader))
    monkeypatch.setattr(cli, "NetworkSensorReader", Mock(return_value=network_reader))
    monkeypatch.setattr(cli, "_run_wifi_helper_for_cli", run_helper)

    payload = cli._sample_payload(config, update_energy=False)

    assert payload["latitude"] == 45.4642
    assert payload["longitude"] == 9.19
    assert payload["location_cached"] is True
    assert payload["geocoded_location"] is None
    assert payload["geocoded_location_cached"] is False
    run_helper.assert_not_called()


def test_sample_payload_persists_fresh_location_for_later_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AppConfig(state_path=tmp_path / "state.json", publish_location=True)
    reader = Mock()
    reader.read.return_value = SensorSample(
        timestamp=datetime(2026, 5, 17, 10, 1, tzinfo=UTC),
        host_name="macbook",
        uptime_seconds=123,
        power_w=12.5,
        battery_percent=80,
        battery_max_capacity_percent=90,
        battery_max_capacity_mah=4500,
        battery_design_capacity_mah=5000,
        battery_reported_max_capacity_percent=100,
        battery_temperature_c=32.5,
        battery_virtual_temperature_c=33.5,
        battery_cycle_count=20,
        battery_status="charging",
        external_power=True,
    )
    network_reader = Mock()
    network_reader.read.return_value = NetworkSample(
        wifi=WifiStatus(
            interface="en0",
            ssid="Office",
            signal_dbm=-55,
            signal_percent=90,
        ),
        ethernet=(),
        pings=(),
        location=LocationStatus(latitude=45.4642, longitude=9.19, accuracy_m=35.0),
        geocoded_location=GeocodedLocation(
            state="Piazza del Duomo, Milano, Italia",
            name="Duomo di Milano",
            country="Italia",
            iso_country_code="IT",
            time_zone="Europe/Rome",
            administrative_area="Lombardia",
            sub_administrative_area="Milano",
            postal_code="20122",
            locality="Milano",
            sub_locality="Centro Storico",
            thoroughfare="Piazza del Duomo",
            sub_thoroughfare="1",
            areas_of_interest=("Duomo di Milano",),
        ),
    )
    monkeypatch.setattr(cli, "IoregSensorReader", Mock(return_value=reader))
    monkeypatch.setattr(cli, "NetworkSensorReader", Mock(return_value=network_reader))

    payload = cli._sample_payload(config)

    state = json.loads(config.state_path.read_text(encoding="utf-8"))
    assert payload["location_cached"] is False
    assert payload["location_last_seen"] == "2026-05-17T10:01:00+00:00"
    assert state["last_location"] == {
        "latitude": 45.4642,
        "longitude": 9.19,
        "accuracy_m": 35.0,
        "timestamp": "2026-05-17T10:01:00+00:00",
    }
    assert state["last_geocoded_location"] == {
        "administrative_area": "Lombardia",
        "areas_of_interest": ["Duomo di Milano"],
        "country": "Italia",
        "iso_country_code": "IT",
        "locality": "Milano",
        "name": "Duomo di Milano",
        "postal_code": "20122",
        "state": "Piazza del Duomo, Milano, Italia",
        "sub_administrative_area": "Milano",
        "sub_locality": "Centro Storico",
        "sub_thoroughfare": "1",
        "thoroughfare": "Piazza del Duomo",
        "time_zone": "Europe/Rome",
        "timestamp": "2026-05-17T10:01:00+00:00",
    }


def test_publish_once_sends_discovery_availability_and_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AppConfig(state_path=tmp_path / "state.json", publish_location=True)
    publish_mock = Mock()
    monkeypatch.setattr(cli, "publish_messages", publish_mock)
    monkeypatch.setattr(
        cli,
        "_sample_payload",
        lambda _config, **_kwargs: {
            "timestamp": "2026-05-17T10:00:00+00:00",
            "power_w": 12.3,
            "energy_kwh": 0.001,
            "latitude": 45.4642,
            "longitude": 9.19,
            "location_accuracy_m": 35.0,
        },
    )

    result = cli._handle_publish_once(config, skip_discovery=False)

    assert result == 0
    messages = list(publish_mock.call_args.args[1])
    topics = [message.topic for message in messages]
    assert "homeassistant/sensor/host_power/config" in topics
    assert "homeassistant/device_tracker/host_location/config" in topics
    assert "ha_mqtt_agent/host/availability" in topics
    assert "ha_mqtt_agent/host/state" in topics
    assert "ha_mqtt_agent/host/location/attributes" in topics


def test_publish_once_skips_location_attributes_when_location_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AppConfig(state_path=tmp_path / "state.json", publish_location=False)
    publish_mock = Mock()
    monkeypatch.setattr(cli, "publish_messages", publish_mock)
    monkeypatch.setattr(
        cli,
        "_sample_payload",
        lambda _config, **_kwargs: {
            "timestamp": "2026-05-17T10:00:00+00:00",
            "power_w": 12.3,
            "energy_kwh": 0.001,
            "latitude": 45.4642,
            "longitude": 9.19,
            "location_accuracy_m": 35.0,
        },
    )

    result = cli._handle_publish_once(config, skip_discovery=False)

    assert result == 0
    topics = [message.topic for message in publish_mock.call_args.args[1]]
    assert "homeassistant/device_tracker/host_location/config" not in topics
    assert "ha_mqtt_agent/host/location/attributes" not in topics


def test_publish_once_defers_sampling_until_after_mqtt_connect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AppConfig(state_path=tmp_path / "state.json")

    def fail_before_iterating(
        _config: AppConfig,
        messages: object,
        *,
        client_id_suffix: str = "",
    ) -> None:
        _ = (messages, client_id_suffix)
        raise OSError("No route to host")

    monkeypatch.setattr(cli, "publish_messages", fail_before_iterating)
    sample_mock = Mock(side_effect=AssertionError("sample should not run before connect"))
    monkeypatch.setattr(cli, "_sample_payload", sample_mock)

    with pytest.raises(OSError, match="No route to host"):
        cli._publish_once(config, skip_discovery=False)

    sample_mock.assert_not_called()


def test_authorize_wifi_runs_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    helper_path = tmp_path / "HaMqttAgentWifiHelper"
    helper_path.write_text("", encoding="utf-8")
    config = AppConfig(wifi_helper_path=helper_path)
    result_mock = Mock()
    result_mock.returncode = 0
    result_mock.stdout = (
        '{"authorization_status":"authorized_when_in_use","ssid":"Office WiFi","signal_dbm":-53}'
    )
    result_mock.stderr = ""
    run_mock = Mock(return_value=result_mock)
    monkeypatch.setattr("ha_mqtt_agent.cli.subprocess.run", run_mock)

    result = cli._handle_authorize_wifi(config, as_json=False)

    captured = capsys.readouterr()
    assert result == 0
    assert "authorization_status: authorized_when_in_use" in captured.out
    assert "wifi_ssid: Office WiFi" in captured.out
    assert run_mock.call_args.args[0] == [str(helper_path), "--authorize"]


def test_run_keeps_running_after_publish_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = AppConfig(state_path=tmp_path / "state.json", sample_interval_seconds=0)
    attempts = {"count": 0}

    def publish_once(
        _config: AppConfig,
        *,
        skip_discovery: bool,
        network_cache: object | None = None,
        client_id_suffix: str = "",
    ) -> None:
        _ = (skip_discovery, network_cache, client_id_suffix)
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OSError("temporary network failure")
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_publish_once", publish_once)
    sleep_mock = Mock()
    monkeypatch.setattr("ha_mqtt_agent.cli.time.sleep", sleep_mock)

    with pytest.raises(KeyboardInterrupt):
        cli._handle_run(config, skip_discovery=False, once=False)

    captured = capsys.readouterr()
    assert "temporary network failure" in captured.err
    assert attempts["count"] == 2
    sleep_mock.assert_called_once_with(30.0)
