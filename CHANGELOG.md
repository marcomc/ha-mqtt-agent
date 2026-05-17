# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Initial Home Assistant MQTT publisher for macOS power, energy, and battery
  telemetry.
- Persistent kWh energy accumulator for Energy dashboard compatibility.
- MQTT discovery payloads for power, energy, battery charge, battery maximum
  capacity, battery raw capacity, cycle count, and battery status.
- macOS LaunchAgent install, restart, status, and uninstall targets.
- Generic MQTT broker placeholders in public config and documentation.
- Battery temperature, battery virtual temperature, battery design capacity,
  and system uptime sensors.
- Battery maximum capacity percentage now reports capacity health from maximum
  charge capacity over design capacity.
- README roadmap for Home Assistant MQTT commands, Wake-on-LAN, macOS privilege
  boundaries, and command safety guardrails.
