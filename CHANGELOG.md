# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.1] - 2026-05-19

### Added in 0.1.1

- Wi-Fi SSID, Wi-Fi signal, wired Ethernet status, and configurable external
  ping latency sensors.
- Bundled macOS Wi-Fi helper app and `authorize-wifi` command for granting
  Location Services access to the current SSID.
- Home-network diagnostics for Wi-Fi BSSID, local IPv4 addresses, default
  gateway, gateway MAC, configurable home-network presence, and optional
  latitude/longitude publishing.
- Location publishing now keeps the last known coordinate when macOS reports a
  temporary CoreLocation failure, with separate cached, last-seen, and error
  sensors for Home Assistant.
- Location publishing also exposes an MQTT `device_tracker` with GPS
  attributes for Home Assistant map cards, without removing the standalone
  latitude and longitude sensors.
- The location `device_tracker` includes a `last_seen` attribute alongside the
  more explicit `location_last_seen` timestamp.
- Location publishing now includes a Companion-style `Geocoded location` sensor
  with macOS reverse-geocoded address attributes and cached fallback state.
- MQTT publish retries now back off after repeated broker failures and defer
  telemetry sampling until after the broker connection succeeds.
- One-shot publish commands now use a process-specific MQTT client ID suffix so
  debugging does not disconnect the background LaunchAgent.
- Optional Wi-Fi and location diagnostic sensors now publish stable text states
  instead of becoming `unknown` when macOS reports no BSSID or no current error.

## [0.1.0] - 2026-05-19

### Added in 0.1.0

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
