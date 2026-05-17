# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - Unreleased

### Added

- Home Assistant MQTT discovery publisher for macOS host telemetry.
- Power, energy, battery charge, battery health, battery capacity, battery
  temperature, cycle count, charge status, and uptime sensors.
- Persistent kWh energy accumulator for Home Assistant Energy dashboard use.
- Configurable MQTT broker, discovery prefix, device identity, publish interval,
  sensor expiry, retained state, and local state path.
- Standalone packaged CLI exposed as `ha-mqtt-agent`.
- Per-user macOS LaunchAgent install, restart, status, and uninstall workflow.
- End-user setup documentation for Home Assistant MQTT discovery and Energy
  dashboard integration.
