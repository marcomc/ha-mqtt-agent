from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ha_mqtt_agent import cli
from ha_mqtt_agent.capabilities import CapabilitySnapshot, capability_snapshot_from_payload
from ha_mqtt_agent.config import AppConfig, load_config
from ha_mqtt_agent.doctor import (
    MISSING_CONFIG_REASON,
    PLACEHOLDER_MQTT_REASON,
    build_doctor_report,
)
from ha_mqtt_agent.network import NetworkSnapshotCache
from ha_mqtt_agent.providers.base import PayloadPostprocessor


def test_doctor_skips_mqtt_for_missing_placeholder_config(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.toml"
    probe = Mock()

    report, exit_code = build_doctor_report(
        config=AppConfig(),
        config_path=config_path,
        check_mqtt=True,
        provider=_UptimeProvider(),
        mqtt_probe=probe,
        system_name="Linux",
    )

    assert exit_code == 0
    assert report["status"] == "ok"
    assert report["mqtt"] == {"status": "skipped", "reason": MISSING_CONFIG_REASON}
    assert MISSING_CONFIG_REASON in report["warnings"]
    assert PLACEHOLDER_MQTT_REASON in report["warnings"]
    probe.assert_not_called()


def test_doctor_mqtt_uses_connack_probe_without_publishing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('mqtt_host = "mqtt.home.test"\n', encoding="utf-8")
    config = load_config(config_path)
    probe = Mock()

    report, exit_code = build_doctor_report(
        config=config,
        config_path=config_path,
        check_mqtt=True,
        provider=_UptimeProvider(),
        mqtt_probe=probe,
        system_name="Linux",
    )

    assert exit_code == 0
    assert report["mqtt"] == {"status": "ok", "reason": None}
    probe.assert_called_once_with(config)


def test_doctor_cli_can_emit_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('mqtt_host = "mqtt.home.test"\n', encoding="utf-8")
    monkeypatch.setattr(
        "ha_mqtt_agent.doctor.select_telemetry_provider",
        lambda _system_name: _UptimeProvider(),
    )

    result = cli.main(["--config", str(config_path), "doctor", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["config"]["path"] == str(config_path)
    assert payload["capabilities"][0]["id"] == "uptime"


def test_doctor_linux_tool_report_includes_optional_provider_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "ha_mqtt_agent.doctor.shutil.which",
        lambda command: f"/usr/bin/{command}",
    )

    report, exit_code = build_doctor_report(
        config=AppConfig(),
        config_path=tmp_path / "missing.toml",
        provider=_UptimeProvider(),
        system_name="Linux",
    )

    assert exit_code == 0
    assert {item["name"] for item in report["tools"]} == {
        "ip",
        "iw",
        "nmcli",
        "ping",
        "sensors",
        "systemctl",
        "upower",
    }


class _UptimeProvider:
    provider_id = "test"

    def supported_capability_ids(self, config: AppConfig) -> tuple[str, ...]:
        _ = config
        return ("uptime",)

    def sample(
        self,
        config: AppConfig,
        *,
        update_energy: bool = True,
        network_cache: NetworkSnapshotCache | None = None,
        payload_postprocessor: PayloadPostprocessor | None = None,
    ) -> CapabilitySnapshot:
        _ = (update_energy, network_cache)
        payload: dict[str, object] = {"uptime_seconds": 10}
        if payload_postprocessor is not None:
            payload_postprocessor(payload)
        return capability_snapshot_from_payload(
            config=config,
            payload=payload,
            provider=self.provider_id,
            capability_ids=("uptime",),
        )
