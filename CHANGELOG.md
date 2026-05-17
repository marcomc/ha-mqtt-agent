# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - Unreleased

### Added

- Home Assistant MQTT discovery publisher for macOS telemetry.
- Power, energy, battery charge, battery health, battery capacity, battery
  temperature, cycle count, charge status, and uptime sensors.
- Persistent kWh energy accumulator for Home Assistant Energy dashboard use.
- macOS-only telemetry provider based on AppleSmartBattery data. Linux and
  Raspberry Pi hosts are not supported yet.
- Configurable MQTT broker, discovery prefix, device identity, publish interval,
  sensor expiry, retained state, and local state path.
- Standalone packaged CLI exposed as `ha-mqtt-agent`.
- User-friendly `scripts/install.sh` wrapper for installing the standalone
  runtime and starting the LaunchAgent on a new Mac.
- Per-user macOS LaunchAgent install, restart, status, and uninstall workflow.
- End-user setup documentation for Home Assistant MQTT discovery and Energy
  dashboard integration.
