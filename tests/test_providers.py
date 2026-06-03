from __future__ import annotations

from ha_mqtt_agent.providers import UnsupportedProvider, select_telemetry_provider
from ha_mqtt_agent.providers.linux import LinuxProvider
from ha_mqtt_agent.providers.macos import MacOSProvider


def test_provider_selection_uses_platform_specific_provider() -> None:
    assert isinstance(select_telemetry_provider("Darwin"), MacOSProvider)
    assert isinstance(select_telemetry_provider("Linux"), LinuxProvider)
    assert isinstance(select_telemetry_provider("FreeBSD"), UnsupportedProvider)
