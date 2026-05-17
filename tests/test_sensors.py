from __future__ import annotations

from ha_mqtt_agent.sensors import parse_ioreg_sample


def test_parse_ioreg_sample_reads_power_and_battery_fields() -> None:
    sample = parse_ioreg_sample(
        """
        +-o AppleSmartBattery
          {
            "CurrentCapacity" = 74
            "ExternalConnected" = Yes
            "FullyCharged" = No
            "IsCharging" = Yes
            "MaxCapacity" = 100
            "AppleRawMaxCapacity" = 4644
            "DesignCapacity" = 6075
            "CycleCount" = 219
            "Temperature" = 3058
            "VirtualTemperature" = 3259
            "PowerTelemetryData" = {"SystemPowerIn"=83526}
          }
        """,
        host_name="macbook",
        uptime_seconds=123.456,
    )

    assert sample.host_name == "macbook"
    assert sample.uptime_seconds == 123.456
    assert sample.power_w == 83.526
    assert sample.battery_percent == 74
    assert round(sample.battery_max_capacity_percent or 0, 2) == 76.44
    assert sample.battery_max_capacity_mah == 4644
    assert sample.battery_design_capacity_mah == 6075
    assert sample.battery_reported_max_capacity_percent == 100
    assert round(sample.battery_temperature_c or 0, 2) == 32.65
    assert round(sample.battery_virtual_temperature_c or 0, 2) == 52.75
    assert sample.battery_cycle_count == 219
    assert sample.battery_status == "charging"
    assert sample.external_power is True


def test_parse_ioreg_sample_falls_back_to_battery_power_estimate() -> None:
    sample = parse_ioreg_sample(
        """
        {
          "InstantAmperage" = -1200
          "Voltage" = 12500
          "ExternalConnected" = No
          "IsCharging" = No
        }
        """,
    )

    assert sample.power_w == 15
    assert sample.battery_status == "discharging"


def test_parse_ioreg_sample_prefers_battery_power_when_discharging() -> None:
    sample = parse_ioreg_sample(
        """
        {
          "ExternalConnected" = No
          "BatteryPower" = 31894
          "SystemPowerIn" = 251
        }
        """,
    )

    assert sample.power_w == 31.894
