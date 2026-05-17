from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ha_mqtt_agent import __version__, cli
from ha_mqtt_agent.config import AppConfig, load_config


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


def test_config_defaults_to_five_second_publish_and_fifteen_second_expiry(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    config = load_config(config_path)

    assert config.sample_interval_seconds == 5
    assert config.expire_after_seconds == 15


def test_publish_once_sends_discovery_availability_and_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AppConfig(state_path=tmp_path / "state.json")
    publish_mock = Mock()
    monkeypatch.setattr(cli, "publish_messages", publish_mock)
    monkeypatch.setattr(
        cli,
        "_sample_payload",
        lambda _config: {
            "timestamp": "2026-05-17T10:00:00+00:00",
            "power_w": 12.3,
            "energy_kwh": 0.001,
        },
    )

    result = cli._handle_publish_once(config, skip_discovery=False)

    assert result == 0
    messages = list(publish_mock.call_args.args[1])
    topics = [message.topic for message in messages]
    assert "homeassistant/sensor/host_power/config" in topics
    assert "ha_mqtt_agent/host/availability" in topics
    assert "ha_mqtt_agent/host/state" in topics


def test_run_keeps_running_after_publish_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = AppConfig(state_path=tmp_path / "state.json", sample_interval_seconds=0)
    attempts = {"count": 0}

    def publish_once(_config: AppConfig, *, skip_discovery: bool) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OSError("temporary network failure")
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_publish_once", publish_once)

    with pytest.raises(KeyboardInterrupt):
        cli._handle_run(config, skip_discovery=False, once=False)

    captured = capsys.readouterr()
    assert "temporary network failure" in captured.err
    assert attempts["count"] == 2
