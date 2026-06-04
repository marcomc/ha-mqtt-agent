"""Read-only host readiness checks."""

from __future__ import annotations

import platform
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ha_mqtt_agent.config import AppConfig
from ha_mqtt_agent.providers import select_telemetry_provider
from ha_mqtt_agent.providers.base import TelemetryProvider

MISSING_CONFIG_REASON = "config_missing"
PLACEHOLDER_MQTT_REASON = "mqtt_placeholder"

MqttProbe = Callable[[AppConfig], None]


def build_doctor_report(
    *,
    config: AppConfig,
    config_path: Path,
    check_mqtt: bool = False,
    provider: TelemetryProvider | None = None,
    mqtt_probe: MqttProbe | None = None,
    system_name: str | None = None,
) -> tuple[dict[str, Any], int]:
    detected_system = system_name or platform.system()
    telemetry_provider = provider or select_telemetry_provider(detected_system)
    warnings: list[str] = []
    errors: list[str] = []

    if not config_path.exists():
        warnings.append(MISSING_CONFIG_REASON)
    if _mqtt_settings_are_placeholder(config):
        warnings.append(PLACEHOLDER_MQTT_REASON)

    capability_items: list[dict[str, object]] = []
    try:
        supported = telemetry_provider.supported_capability_ids(config)
        snapshot = telemetry_provider.sample(config, update_energy=False)
    except Exception as exc:  # noqa: BLE001 - doctor reports provider failures.
        supported = ()
        errors.append(f"provider_sample_failed: {exc}")
    else:
        results = {result.id: result for result in snapshot.results}
        for capability_id in supported:
            result = results.get(capability_id)
            capability_items.append(
                {
                    "id": capability_id,
                    "available": None if result is None else result.available,
                    "source": None if result is None else result.source,
                    "error": None if result is None else result.error,
                }
            )

    mqtt_report = _mqtt_report(
        config=config,
        config_path=config_path,
        check_mqtt=check_mqtt,
        mqtt_probe=mqtt_probe,
        warnings=warnings,
        errors=errors,
    )
    report: dict[str, Any] = {
        "status": "error" if errors else "ok",
        "platform": {
            "system": detected_system,
            "provider": telemetry_provider.provider_id,
            "service_manager": _service_manager(detected_system),
        },
        "config": {
            "path": str(config_path),
            "exists": config_path.exists(),
            "device_id": config.device_id,
            "device_name": config.device_name,
            "state_path": str(config.state_path),
            "mqtt_host": config.mqtt_host,
            "mqtt_port": config.mqtt_port,
            "mqtt_client_id": config.resolved_mqtt_client_id,
        },
        "tools": _tool_report(detected_system),
        "capabilities": capability_items,
        "mqtt": mqtt_report,
        "warnings": warnings,
        "errors": errors,
    }
    return report, 1 if errors else 0


def render_doctor_text(report: dict[str, Any], *, verbose: bool = False) -> str:
    platform_info = _mapping(report["platform"])
    config = _mapping(report["config"])
    mqtt = _mapping(report["mqtt"])
    capabilities = _list(report["capabilities"])
    available = sum(1 for item in capabilities if _mapping(item).get("available") is True)
    unavailable = sum(1 for item in capabilities if _mapping(item).get("available") is False)
    lines = [
        f"status: {report['status']}",
        f"platform: {platform_info['system']}",
        f"provider: {platform_info['provider']}",
        f"service_manager: {platform_info['service_manager']}",
        f"config_path: {config['path']}",
        f"config_exists: {config['exists']}",
        f"device_id: {config['device_id']}",
        f"mqtt: {mqtt['status']}",
        (
            f"capabilities: {available} online, {unavailable} unavailable, "
            f"{len(capabilities)} supported"
        ),
    ]
    if report["warnings"]:
        lines.append("warnings: " + ", ".join(str(item) for item in _list(report["warnings"])))
    if report["errors"]:
        lines.append("errors: " + ", ".join(str(item) for item in _list(report["errors"])))

    if verbose:
        lines.append("tools:")
        for tool in _list(report["tools"]):
            item = _mapping(tool)
            lines.append(f"  {item['name']}: {item['available']}")
        lines.append("capability_details:")
        for capability in capabilities:
            item = _mapping(capability)
            status = "online" if item["available"] is True else "offline"
            lines.append(f"  {item['id']}: {status}")
            if item.get("error"):
                lines.append(f"    error: {item['error']}")
    return "\n".join(lines)


def _mqtt_report(
    *,
    config: AppConfig,
    config_path: Path,
    check_mqtt: bool,
    mqtt_probe: MqttProbe | None,
    warnings: list[str],
    errors: list[str],
) -> dict[str, object]:
    if not check_mqtt:
        return {"status": "not_checked", "reason": None}
    if not config_path.exists():
        return {"status": "skipped", "reason": MISSING_CONFIG_REASON}
    if _mqtt_settings_are_placeholder(config):
        return {"status": "skipped", "reason": PLACEHOLDER_MQTT_REASON}
    if mqtt_probe is None:
        return {"status": "not_checked", "reason": "mqtt_probe_missing"}
    try:
        mqtt_probe(config)
    except Exception as exc:  # noqa: BLE001 - user-facing readiness report.
        errors.append(f"mqtt_connect_failed: {exc}")
        return {"status": "error", "reason": str(exc)}
    return {"status": "ok", "reason": None}


def _mqtt_settings_are_placeholder(config: AppConfig) -> bool:
    host = config.mqtt_host.casefold()
    return host in {"mqtt.example.local", "mqtt.example.test"} or host.endswith(".example.local")


def _service_manager(system_name: str) -> str | None:
    if system_name == "Darwin":
        return "launchd"
    if system_name == "Linux" and shutil.which("systemctl") is not None:
        return "systemd"
    return None


def _tool_report(system_name: str) -> list[dict[str, object]]:
    tools = {
        "Darwin": ("ioreg", "networksetup", "launchctl", "swiftc", "codesign"),
        "Linux": ("ip", "iw", "nmcli", "ping", "sensors", "systemctl", "upower"),
    }.get(system_name, ())
    return [{"name": tool, "available": shutil.which(tool) is not None} for tool in tools]


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("expected mapping")
    return value


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError("expected list")
    return value
