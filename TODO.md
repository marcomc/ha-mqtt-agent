# TODO

## Backlog

### HMA-001 Persistent MQTT Command Loop

- Roadmap: [HMA-001](docs/roadmap.md#hma-001-persistent-mqtt-command-loop)
- Implement a persistent MQTT command loop for `ha-mqtt-agent run`.

### HMA-002 Home Assistant Command Entities

- Roadmap: [HMA-002](docs/roadmap.md#hma-002-home-assistant-command-entities)
- Add MQTT discovery for safe Home Assistant command entities.

### HMA-003 Command Safety Controls

- Roadmap: [HMA-003](docs/roadmap.md#hma-003-command-safety-controls)
- Add command safety controls and structured command logs.

### HMA-004 Wake-on-LAN Documentation

- Roadmap: [HMA-004](docs/roadmap.md#hma-004-wake-on-lan-documentation)
- Document Home Assistant Wake-on-LAN setup.

### HMA-005 Privileged Action Boundary

- Roadmap: [HMA-005](docs/roadmap.md#hma-005-privileged-action-boundary)
- Design the privileged action boundary.

### HMA-006 MQTT TLS Settings

- Roadmap: [HMA-006](docs/roadmap.md#hma-006-mqtt-tls-settings)
- Add optional TLS settings for hardened MQTT brokers.

### HMA-007 Linux and Raspberry Pi Providers

- Roadmap: [HMA-007](docs/roadmap.md#hma-007-linux-and-raspberry-pi-providers)
- Add Linux and Raspberry Pi telemetry providers.

### HMA-008 Release Automation

- Roadmap: [HMA-008](docs/roadmap.md#hma-008-release-automation)
- Add release automation when publishing packages or binaries.

### HMA-009 Prebuilt Notarized macOS Installer

- Roadmap: [HMA-009](docs/roadmap.md#hma-009-prebuilt-notarized-macos-installer)
- Add a non-developer install path with a prebuilt Developer ID signed and
  notarized Wi-Fi helper app.
- Package the Python runtime, LaunchAgent, config template, and helper into a
  release artifact that does not require local `swiftc` or local signing.
- Keep the current source install path for development and advanced users.
