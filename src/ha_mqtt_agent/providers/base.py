"""Shared provider interfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ha_mqtt_agent.capabilities import CapabilitySnapshot
from ha_mqtt_agent.config import AppConfig
from ha_mqtt_agent.network import NetworkSnapshotCache

PayloadPostprocessor = Callable[[dict[str, object]], None]


class TelemetryProvider(Protocol):
    provider_id: str

    def sample(
        self,
        config: AppConfig,
        *,
        update_energy: bool = True,
        network_cache: NetworkSnapshotCache | None = None,
        payload_postprocessor: PayloadPostprocessor | None = None,
    ) -> CapabilitySnapshot: ...
