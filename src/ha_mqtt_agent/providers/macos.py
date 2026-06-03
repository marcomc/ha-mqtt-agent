"""macOS provider wrapping the existing telemetry readers."""

from __future__ import annotations

from dataclasses import dataclass, field

from ha_mqtt_agent.capabilities import (
    CapabilitySnapshot,
    capability_snapshot_from_payload,
    sensor_registry,
)
from ha_mqtt_agent.config import AppConfig
from ha_mqtt_agent.energy import EnergyAccumulator
from ha_mqtt_agent.network import NetworkSensorReader, NetworkSnapshotCache
from ha_mqtt_agent.providers.base import PayloadPostprocessor
from ha_mqtt_agent.sensors import IoregSensorReader


@dataclass
class MacOSProvider:
    sensor_reader: IoregSensorReader = field(default_factory=IoregSensorReader)
    network_reader: NetworkSensorReader = field(default_factory=NetworkSensorReader)
    provider_id: str = "macos"

    def supported_capability_ids(self, config: AppConfig) -> tuple[str, ...]:
        return tuple(definition.id for definition in sensor_registry(config))

    def sample(
        self,
        config: AppConfig,
        *,
        update_energy: bool = True,
        network_cache: NetworkSnapshotCache | None = None,
        payload_postprocessor: PayloadPostprocessor | None = None,
    ) -> CapabilitySnapshot:
        payload = self._payload(
            config,
            update_energy=update_energy,
            network_cache=network_cache,
        )
        if payload_postprocessor is not None:
            payload_postprocessor(payload)
        return capability_snapshot_from_payload(
            config=config,
            payload=payload,
            provider=self.provider_id,
            capability_ids=self.supported_capability_ids(config),
        )

    def _payload(
        self,
        config: AppConfig,
        *,
        update_energy: bool,
        network_cache: NetworkSnapshotCache | None,
    ) -> dict[str, object]:
        sample = self.sensor_reader.read()
        accumulator = EnergyAccumulator(
            config.state_path,
            max_gap_seconds=config.max_energy_gap_seconds,
        )
        if update_energy:
            energy_kwh = accumulator.update(timestamp=sample.timestamp, power_w=sample.power_w)
        else:
            energy_kwh = accumulator.energy_kwh

        payload = sample.payload(energy_kwh=energy_kwh)
        if network_cache is None:
            payload.update(self.network_reader.read(config).payload())
        else:
            payload.update(network_cache.read(self.network_reader, config).payload())
        return payload
