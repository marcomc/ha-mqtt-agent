"""Capability definitions and normalized runtime results."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from .config import AppConfig

CapabilityGroup = Literal[
    "agent_diagnostics",
    "uptime",
    "battery",
    "power",
    "energy",
    "network",
    "wifi",
    "temperature",
    "ping",
    "location",
]
DiscoveryComponent = Literal["sensor", "binary_sensor", "device_tracker"]


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    group: CapabilityGroup
    name: str
    payload_key: str
    value_template: str
    component: DiscoveryComponent = "sensor"
    device_class: str | None = None
    state_class: str | None = None
    unit: str | None = None
    attributes_template: str | None = None
    entity_category: str | None = None
    null_value_available: bool = False
    required_payload_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityResult:
    id: str
    available: bool
    value: object
    source: str
    error: str | None = None


@dataclass(frozen=True)
class CapabilitySnapshot:
    provider: str
    payload: Mapping[str, object]
    results: tuple[CapabilityResult, ...]

    def state_payload(self) -> dict[str, object]:
        payload = dict(self.payload)
        payload["availability"] = {
            result.id: "online" if result.available else "offline" for result in self.results
        }
        return payload

    def result(self, capability_id: str) -> CapabilityResult | None:
        for result in self.results:
            if result.id == capability_id:
                return result
        return None


def capability_snapshot_from_payload(
    *,
    config: AppConfig,
    payload: Mapping[str, object],
    provider: str,
    capability_ids: Iterable[str] | None = None,
    unavailable_ids: Iterable[str] = (),
    errors: Mapping[str, str] | None = None,
) -> CapabilitySnapshot:
    unavailable = set(unavailable_ids)
    resolved_errors = errors or {}
    results = tuple(
        _capability_result(
            definition,
            payload=payload,
            provider=provider,
            force_unavailable=definition.id in unavailable,
            error=resolved_errors.get(definition.id),
        )
        for definition in capability_definitions(config, capability_ids=capability_ids)
    )
    return CapabilitySnapshot(provider=provider, payload=payload, results=results)


def capability_definitions(
    config: AppConfig,
    *,
    capability_ids: Iterable[str] | None = None,
) -> tuple[CapabilityDefinition, ...]:
    definitions = sensor_registry(config)
    if capability_ids is None:
        return definitions

    supported = set(capability_ids)
    return tuple(definition for definition in definitions if definition.id in supported)


def sensor_registry(config: AppConfig) -> tuple[CapabilityDefinition, ...]:
    definitions = [
        CapabilityDefinition(
            id="power",
            group="power",
            name="Power",
            payload_key="power_w",
            device_class="power",
            state_class="measurement",
            unit="W",
            value_template="{{ value_json.power_w }}",
        ),
        CapabilityDefinition(
            id="energy",
            group="energy",
            name="Energy",
            payload_key="energy_kwh",
            device_class="energy",
            state_class="total_increasing",
            unit="kWh",
            value_template="{{ value_json.energy_kwh }}",
        ),
        CapabilityDefinition(
            id="battery",
            group="battery",
            name="Battery",
            payload_key="battery_percent",
            device_class="battery",
            state_class="measurement",
            unit="%",
            value_template="{{ value_json.battery_percent }}",
        ),
        CapabilityDefinition(
            id="battery_max_capacity",
            group="battery",
            name="Battery maximum capacity",
            payload_key="battery_max_capacity_percent",
            device_class="battery",
            state_class="measurement",
            unit="%",
            value_template="{{ value_json.battery_max_capacity_percent }}",
        ),
        CapabilityDefinition(
            id="battery_max_capacity_mah",
            group="battery",
            name="Battery maximum capacity mAh",
            payload_key="battery_max_capacity_mah",
            state_class="measurement",
            unit="mAh",
            value_template="{{ value_json.battery_max_capacity_mah }}",
        ),
        CapabilityDefinition(
            id="battery_design_capacity",
            group="battery",
            name="Battery design capacity",
            payload_key="battery_design_capacity_mah",
            state_class="measurement",
            unit="mAh",
            value_template="{{ value_json.battery_design_capacity_mah }}",
        ),
        CapabilityDefinition(
            id="battery_temperature",
            group="temperature",
            name="Battery temperature",
            payload_key="battery_temperature_c",
            device_class="temperature",
            state_class="measurement",
            unit="°C",
            value_template="{{ value_json.battery_temperature_c }}",
        ),
        CapabilityDefinition(
            id="battery_virtual_temperature",
            group="temperature",
            name="Battery virtual temperature",
            payload_key="battery_virtual_temperature_c",
            device_class="temperature",
            state_class="measurement",
            unit="°C",
            value_template="{{ value_json.battery_virtual_temperature_c }}",
        ),
        CapabilityDefinition(
            id="cpu_temperature",
            group="temperature",
            name="CPU temperature",
            payload_key="cpu_temperature_c",
            device_class="temperature",
            state_class="measurement",
            unit="°C",
            value_template="{{ value_json.cpu_temperature_c }}",
        ),
        CapabilityDefinition(
            id="battery_cycle_count",
            group="battery",
            name="Battery cycle count",
            payload_key="battery_cycle_count",
            state_class="total_increasing",
            value_template="{{ value_json.battery_cycle_count }}",
        ),
        CapabilityDefinition(
            id="battery_status",
            group="battery",
            name="Battery status",
            payload_key="battery_status",
            value_template="{{ value_json.battery_status }}",
        ),
        CapabilityDefinition(
            id="uptime",
            group="uptime",
            name="Uptime",
            payload_key="uptime_seconds",
            device_class="duration",
            state_class="measurement",
            unit="s",
            value_template="{{ value_json.uptime_seconds }}",
        ),
        CapabilityDefinition(
            id="wifi_ssid",
            group="wifi",
            name="Wi-Fi SSID",
            payload_key="wifi_ssid",
            value_template="{{ value_json.wifi_ssid }}",
        ),
        CapabilityDefinition(
            id="wifi_bssid",
            group="wifi",
            name="Wi-Fi BSSID",
            payload_key="wifi_bssid",
            value_template=(
                "{{ value_json.wifi_bssid if value_json.wifi_bssid is not none "
                "else 'not_available' }}"
            ),
            null_value_available=True,
        ),
        CapabilityDefinition(
            id="wifi_signal_dbm",
            group="wifi",
            name="Wi-Fi signal",
            payload_key="wifi_signal_dbm",
            device_class="signal_strength",
            state_class="measurement",
            unit="dBm",
            value_template="{{ value_json.wifi_signal_dbm }}",
        ),
        CapabilityDefinition(
            id="wifi_signal_percent",
            group="wifi",
            name="Wi-Fi signal percent",
            payload_key="wifi_signal_percent",
            state_class="measurement",
            unit="%",
            value_template="{{ value_json.wifi_signal_percent }}",
        ),
        CapabilityDefinition(
            id="ipv4_addresses",
            group="network",
            name="IPv4 addresses",
            payload_key="ipv4_addresses",
            value_template="{{ value_json.ipv4_addresses }}",
        ),
        CapabilityDefinition(
            id="default_gateways",
            group="network",
            name="Default gateways",
            payload_key="default_gateways",
            value_template="{{ value_json.default_gateways }}",
        ),
        CapabilityDefinition(
            id="default_gateway_interfaces",
            group="network",
            name="Default gateway interfaces",
            payload_key="default_gateway_interfaces",
            value_template="{{ value_json.default_gateway_interfaces }}",
        ),
        CapabilityDefinition(
            id="gateway_macs",
            group="network",
            name="Gateway MACs",
            payload_key="gateway_macs",
            value_template="{{ value_json.gateway_macs }}",
        ),
        CapabilityDefinition(
            id="ethernet_active_count",
            group="network",
            name="Ethernet active count",
            payload_key="ethernet_active_count",
            state_class="measurement",
            value_template="{{ value_json.ethernet_active_count }}",
        ),
        CapabilityDefinition(
            id="ethernet_active_interfaces",
            group="network",
            name="Ethernet active interfaces",
            payload_key="ethernet_active_interfaces",
            value_template="{{ value_json.ethernet_active_interfaces }}",
        ),
        CapabilityDefinition(
            id="home_network_present",
            group="network",
            component="binary_sensor",
            name="Home network present",
            payload_key="home_network_present",
            device_class="presence",
            value_template="{{ value_json.home_network_present | tojson }}",
        ),
    ]
    if config.publish_location:
        definitions.extend(_location_definitions())
    definitions.extend(_ping_definitions(config))
    return tuple(definitions)


def _location_definitions() -> list[CapabilityDefinition]:
    return [
        CapabilityDefinition(
            id="latitude",
            group="location",
            name="Latitude",
            payload_key="latitude",
            state_class="measurement",
            unit="°",
            value_template="{{ value_json.latitude }}",
        ),
        CapabilityDefinition(
            id="longitude",
            group="location",
            name="Longitude",
            payload_key="longitude",
            state_class="measurement",
            unit="°",
            value_template="{{ value_json.longitude }}",
        ),
        CapabilityDefinition(
            id="location_accuracy",
            group="location",
            name="Location accuracy",
            payload_key="location_accuracy_m",
            device_class="distance",
            state_class="measurement",
            unit="m",
            value_template="{{ value_json.location_accuracy_m }}",
        ),
        CapabilityDefinition(
            id="location_last_seen",
            group="location",
            name="Location last seen",
            payload_key="location_last_seen",
            device_class="timestamp",
            value_template="{{ value_json.location_last_seen }}",
        ),
        CapabilityDefinition(
            id="location_error",
            group="location",
            name="Location error",
            payload_key="location_error",
            value_template=(
                "{{ value_json.location_error if value_json.location_error is not none "
                "else 'none' }}"
            ),
            null_value_available=True,
        ),
        CapabilityDefinition(
            id="geocoded_location",
            group="location",
            name="Geocoded location",
            payload_key="geocoded_location",
            value_template="{{ value_json.geocoded_location }}",
            attributes_template=(
                "{{ {"
                "'Location': [value_json.latitude, value_json.longitude], "
                "'Name': value_json.geocoded_location_name, "
                "'Country': value_json.geocoded_location_country, "
                "'ISOCountryCode': value_json.geocoded_location_iso_country_code, "
                "'TimeZone': value_json.geocoded_location_time_zone, "
                "'AdministrativeArea': value_json.geocoded_location_administrative_area, "
                "'SubAdministrativeArea': "
                "value_json.geocoded_location_sub_administrative_area, "
                "'PostalCode': value_json.geocoded_location_postal_code, "
                "'Locality': value_json.geocoded_location_locality, "
                "'SubLocality': value_json.geocoded_location_sub_locality, "
                "'Thoroughfare': value_json.geocoded_location_thoroughfare, "
                "'SubThoroughfare': value_json.geocoded_location_sub_thoroughfare, "
                "'AreasOfInterest': value_json.geocoded_location_areas_of_interest, "
                "'Ocean': value_json.geocoded_location_ocean, "
                "'InlandWater': value_json.geocoded_location_inland_water, "
                "'Error': value_json.geocoded_location_error, "
                "'Cached': value_json.geocoded_location_cached, "
                "'LastSeen': value_json.location_last_seen"
                "} | tojson }}"
            ),
        ),
        CapabilityDefinition(
            id="geocoded_location_error",
            group="location",
            name="Geocoded location error",
            payload_key="geocoded_location_error",
            value_template=(
                "{{ value_json.geocoded_location_error if "
                "value_json.geocoded_location_error is not none else 'none' }}"
            ),
            null_value_available=True,
        ),
        CapabilityDefinition(
            id="location",
            group="location",
            component="device_tracker",
            name="Location",
            payload_key="latitude",
            value_template="",
            required_payload_keys=("latitude", "longitude"),
        ),
        CapabilityDefinition(
            id="location_cached",
            group="location",
            component="binary_sensor",
            name="Location cached",
            payload_key="location_cached",
            value_template="{{ value_json.location_cached | tojson }}",
        ),
        CapabilityDefinition(
            id="geocoded_location_cached",
            group="location",
            component="binary_sensor",
            name="Geocoded location cached",
            payload_key="geocoded_location_cached",
            value_template="{{ value_json.geocoded_location_cached | tojson }}",
        ),
    ]


def _ping_definitions(config: AppConfig) -> list[CapabilityDefinition]:
    return [
        CapabilityDefinition(
            id=f"ping_{target.id}",
            group="ping",
            name=f"Ping {target.name}",
            payload_key=f"ping_{target.id}_ms",
            device_class="duration",
            state_class="measurement",
            unit="ms",
            value_template=f"{{{{ value_json.ping_{target.id}_ms }}}}",
        )
        for target in config.ping_targets
    ]


def _capability_result(
    definition: CapabilityDefinition,
    *,
    payload: Mapping[str, object],
    provider: str,
    force_unavailable: bool = False,
    error: str | None = None,
) -> CapabilityResult:
    value = payload.get(definition.payload_key)
    required_keys = definition.required_payload_keys or (definition.payload_key,)
    available = all(payload.get(key) is not None for key in required_keys)
    if definition.null_value_available and len(required_keys) == 1:
        available = True
    if force_unavailable:
        available = False
    resolved_error = None if available else error or f"{definition.payload_key} unavailable"
    return CapabilityResult(
        id=definition.id,
        available=available,
        value=value,
        source=provider,
        error=resolved_error,
    )
