"""Platform telemetry providers."""

from __future__ import annotations

import platform
import socket
from dataclasses import dataclass
from datetime import UTC, datetime

from ha_mqtt_agent.capabilities import CapabilitySnapshot, capability_snapshot_from_payload
from ha_mqtt_agent.config import AppConfig
from ha_mqtt_agent.network import NetworkSnapshotCache
from ha_mqtt_agent.providers.base import PayloadPostprocessor, TelemetryProvider
from ha_mqtt_agent.providers.linux import LinuxProvider
from ha_mqtt_agent.providers.macos import MacOSProvider

__all__ = ["UnsupportedProvider", "select_telemetry_provider"]


@dataclass
class UnsupportedProvider:
    provider_id: str = "unsupported"

    def supported_capability_ids(self, config: AppConfig) -> tuple[str, ...]:
        _ = config
        return ()

    def sample(
        self,
        config: AppConfig,
        *,
        update_energy: bool = True,
        network_cache: NetworkSnapshotCache | None = None,
        payload_postprocessor: PayloadPostprocessor | None = None,
    ) -> CapabilitySnapshot:
        _ = (update_energy, network_cache)
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "host_name": socket.gethostname(),
        }
        if payload_postprocessor is not None:
            payload_postprocessor(payload)
        return capability_snapshot_from_payload(
            config=config,
            payload=payload,
            provider=self.provider_id,
            capability_ids=(),
        )


def select_telemetry_provider(system_name: str | None = None) -> TelemetryProvider:
    detected = system_name or platform.system()
    if detected == "Darwin":
        return MacOSProvider()
    if detected == "Linux":
        return LinuxProvider()
    return UnsupportedProvider()
