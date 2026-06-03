# Cross-Platform Architecture

## Table of Contents

- [Purpose](#purpose)
- [Goals](#goals)
- [Supported Platforms](#supported-platforms)
- [Detection Model](#detection-model)
- [Capability Model](#capability-model)
- [Doctor Command](#doctor-command)
- [Installer Behavior](#installer-behavior)
- [Runtime Behavior](#runtime-behavior)
- [MQTT Discovery](#mqtt-discovery)
- [Home Assistant Naming](#home-assistant-naming)
- [Legacy Migration](#legacy-migration)
- [Configuration](#configuration)
- [Implementation Shape](#implementation-shape)
- [Test Plan](#test-plan)

## Purpose

`ha-mqtt-agent` should install and run on macOS and normal Linux hosts, including Raspberry Pi OS. It should detect the platform, service manager, tools, permissions, and readable sensors on the machine where it is running, then publish only real values that can actually be collected from that machine.

This document is the implementation target for the breaking `0.2.0` cross-platform rewrite.

## Goals

- Keep the project installable as a packaged Python CLI.
- Keep `ha-mqtt-agent` and `python -m ha_mqtt_agent` working.
- Support macOS and Linux from one capability-driven runtime.
- Use install-time detection for service setup and optional dependency prompts.
- Use runtime detection as the source of truth for telemetry capabilities.
- Publish Home Assistant MQTT discovery only for supported or previously known entities.
- Never invent estimated power or energy values.
- Keep missing or failing sensors visible as unavailable unless the user explicitly cleans them up.
- Provide a read-only `doctor` command that uses the same detection engine as runtime and install.

## Supported Platforms

The first cross-platform release targets:

- macOS with the existing per-user LaunchAgent model.
- Raspberry Pi OS and Debian-style Linux systems.
- Generic Linux systems with `systemd`.

Out of scope for the first release:

- Windows.
- OpenWrt.
- BSD.
- Containers as first-class installs.
- NAS appliance installs unless they behave like normal Linux.

## Detection Model

Detection is layered:

```text
doctor
  -> read-only readiness and capability report

install
  -> runs the same read-only detection
  -> offers optional packages and permission fixes after consent
  -> installs the platform service

run startup
  -> full platform and capability scan
  -> publishes capability-based discovery

run loop
  -> samples values at normal intervals
  -> marks failing entities unavailable
  -> refreshes capabilities periodically
```

Runtime detection is the source of truth. Install-time detection may help set up the machine, but the agent must not assume a capability still exists because it was present during installation.

## Capability Model

The rewrite should use platform providers plus normalized capability definitions.

Platform providers:

- `macos`
- `linux`

Core capability groups:

- `agent_diagnostics`
- `uptime`
- `battery`
- `power`
- `energy`
- `network`
- `wifi`
- `temperature`
- `ping`
- `location`

Sensor IDs should be stable internal IDs. Display names can improve without changing MQTT unique IDs.

Examples:

```text
uptime
battery_percent
battery_temperature
power
energy
wifi_ssid
wifi_signal_dbm
default_gateway
agent_status
agent_capabilities
agent_errors
```

Providers return normalized facts, not Home Assistant-specific payloads:

```text
CapabilityResult:
  id: wifi_signal_dbm
  available: true
  value: -58
  source: linux_iw
  error: null
```

Multiple sources for the same sensor should be tried in priority order. For example, Linux Wi-Fi signal can try:

1. `iw`
2. `nmcli`
3. `iwconfig`
4. `/proc/net/wireless`

If a weaker source works but a better optional source is installable, `doctor` and the installer should report that as an improvement, not a requirement.

## Doctor Command

`ha-mqtt-agent doctor` is the standard read-only assessment command.

Default behavior:

- Inspect platform, service manager, tools, permissions, and local sensor capabilities.
- Use the default config path if it exists.
- Stay useful when config is missing.
- Never write config, install packages, change permissions, publish MQTT, create services, or update state.

Commands:

```bash
ha-mqtt-agent doctor
ha-mqtt-agent doctor --json
ha-mqtt-agent doctor --verbose
ha-mqtt-agent doctor --mqtt
```

`doctor --mqtt` uses the configured MQTT settings from the default config path, or from the global `--config` override. If the config is missing or still uses placeholder MQTT values, it should skip broker checks and explain that a full MQTT-scoped doctor requires a real config.

`doctor --mqtt` may connect and wait for MQTT CONNACK. It must not publish discovery, state, or availability messages.

## Installer Behavior

Installers should run the shared detection engine before installing.

Linux default install:

- Use a system `systemd` service.
- Create or update a dedicated unprivileged service user, such as `ha-mqtt-agent`.
- Use `/etc/ha-mqtt-agent/config.toml`.
- Use `/var/lib/ha-mqtt-agent/state.json`.
- Log through `journalctl -u ha-mqtt-agent`.

macOS default install:

- Keep the existing per-user LaunchAgent model.
- Use `~/.config/ha-mqtt-agent/config.toml`.
- Use `~/.local/state/ha-mqtt-agent/state.json`.
- Keep the Wi-Fi helper permission flow user-scoped.

The installer is interactive by default. It may install optional packages only after explicit confirmation.

Non-interactive install should be supported:

```bash
./scripts/install.sh --non-interactive
./scripts/install.sh --non-interactive --enable-optional-sensors
./scripts/install.sh --non-interactive --optional-packages iw,lm-sensors,nut-client
```

Rules:

- `--non-interactive` installs required pieces only.
- `--enable-optional-sensors` installs safe recommended optional packages for the detected platform.
- `--optional-packages` installs exactly the listed known optional packages.
- Unknown package names fail fast.
- Unsupported package managers print recommendations and do not try to install automatically.
- Permission-changing steps require explicit consent or explicit flags.

Package manager support for the first release:

- `apt` for Debian, Ubuntu, and Raspberry Pi OS.
- `dnf` for Fedora.
- `pacman` for Arch.
- `brew` for macOS only if optional tools become relevant.

## Runtime Behavior

At startup, the agent performs a full capability scan.

During normal operation:

- Sample actual values on the configured sample intervals.
- Publish `null` for supported sensors that are currently unreadable.
- Publish per-entity availability status.
- Keep the device online if the agent and MQTT connection are healthy.
- Set `agent_status` to `degraded` when one or more supported sensors fail.
- Refresh capabilities periodically using one global interval.

Recommended default:

```toml
capability_refresh_seconds = 300
```

When a new capability appears at runtime:

```text
capability becomes available
  -> publish discovery for the new entity
  -> publish real state on the next sample
```

When a previously available capability disappears:

```text
capability disappears
  -> keep discovery
  -> publish null value
  -> mark the entity unavailable
  -> publish a concise diagnostic reason
```

The agent must not automatically delete missing runtime capabilities. Explicit cleanup preserves evidence when hardware, permissions, or drivers fail.

## MQTT Discovery

MQTT discovery should be generated from capability definitions, not from hardcoded always-on sensor lists.

Each sensor definition should include:

- stable sensor ID
- display name
- unit
- device class
- state class
- payload key
- availability key
- required capability
- entity category when diagnostic

State payloads should keep keys present and use `null` for unreadable values:

```json
{
  "uptime_seconds": 123456,
  "wifi_signal_dbm": null,
  "availability": {
    "uptime": "online",
    "wifi_signal_dbm": "offline"
  }
}
```

The whole device and individual entities must have separate availability concepts:

```text
agent offline
  -> whole Home Assistant device unavailable

one sensor unreadable
  -> only that entity unavailable
  -> device remains online
  -> diagnostics report degraded status
```

`publish-once --dry-run` should sample real local sensors and build the exact discovery and state payloads without MQTT publish or persistent state writes.

## Home Assistant Naming

The `0.2.0` rewrite may recreate Home Assistant entities.

New entity naming should follow Home Assistant conventions:

- Device name comes from `device_name`.
- Entity name is only the data point.
- Object IDs and unique IDs are stable and generated from `device_id` plus sensor ID.

Example:

```text
Device: Raspberry Pi Gateway
Entity: Uptime
Entity: Wi-Fi signal
Entity: Agent status
Entity: CPU temperature
```

Avoid names that duplicate the device name or the word `sensor`.

## Legacy Migration

`0.2.0` is a breaking release for MQTT discovery.

The agent should provide an explicit cleanup path for known `0.1.x` retained
discovery topics for the current `device_id`. Cleanup should run only when the
operator requests the migration cleanup, or when a future install/upgrade flow
adds a documented opt-in migration step. Normal runtime publishes must not
delete retained discovery topics as a steady-state side effect.

Migration flow:

```text
operator requests legacy cleanup
  -> connect MQTT
  -> remove known 0.1.x discovery topics for current device_id
  -> publish 0.2.x capability-based discovery
  -> publish state
  -> record legacy cleanup done in local state
```

If the session fails before cleanup is recorded, the agent may retry the next
time the operator requests cleanup.

Legacy cleanup must not scan broad broker topic trees or remove discovery topics for other devices.

Manual commands should also exist:

```bash
ha-mqtt-agent cleanup-discovery --legacy-0-1
ha-mqtt-agent publish-once --dry-run --include-cleanup
```

Normal runtime missing sensors are not automatically cleaned up. The legacy
cleanup is a one-time, operator-controlled migration from the old hardcoded
discovery model.

## Configuration

Capability controls should support automatic detection plus user opt-out.

Example target shape:

```toml
capability_refresh_seconds = 300

[capabilities]
battery = "auto"
power = "auto"
network = "auto"
wifi = "auto"
temperature = "auto"
ping = "auto"
location = "off"
```

Initial meanings:

- `auto`: publish if real and readable.
- `off`: never publish.

Do not add forced `on` in the first release. A future `required` mode can be added if operators want startup failure when a sensor is missing.

Default config paths:

```text
macOS user install:
  ~/.config/ha-mqtt-agent/config.toml

Linux system service:
  /etc/ha-mqtt-agent/config.toml

Linux manual or user run:
  ~/.config/ha-mqtt-agent/config.toml
```

The global `--config` option always overrides platform defaults.

## Implementation Shape

The rewrite should replace the hardcoded macOS-only runtime with a shared capability engine.

Recommended modules:

```text
src/ha_mqtt_agent/capabilities.py
src/ha_mqtt_agent/providers/base.py
src/ha_mqtt_agent/providers/macos.py
src/ha_mqtt_agent/providers/linux.py
src/ha_mqtt_agent/discovery.py
src/ha_mqtt_agent/doctor.py
src/ha_mqtt_agent/installer.py
```

The exact filenames can change to match the final implementation, but the ownership boundaries should remain:

- Providers read platform-specific facts.
- Capability engine normalizes support, values, source, and errors.
- MQTT discovery consumes normalized capabilities.
- CLI renders `doctor`, `info`, `sample`, `publish-once`, `run`, and cleanup commands.
- Install scripts call the same detection engine where practical.

## Test Plan

Local automated tests:

- Config loading and schema validation for new capability keys.
- Doctor JSON output for macOS and Linux fixture inputs.
- Linux provider parsing for `/proc`, `/sys`, `ip`, `iw`, `nmcli`, and fallback sources.
- macOS provider wrapping existing AppleSmartBattery and network helper behavior.
- MQTT discovery generated only for available or previously known capabilities.
- Per-entity availability payloads with `null` values.
- `doctor --mqtt` connects and waits for CONNACK without publishing.
- `publish-once --dry-run` samples and renders messages without publishing or writing state.
- One-time legacy `0.1.x` cleanup topics for current `device_id` only.
- Linux installer planning for interactive and non-interactive optional packages.

Manual validation:

- Run `make check` locally on macOS.
- Install and run on the current Mac with the LaunchAgent path.
- Run `ha-mqtt-agent doctor`, `sample`, `publish-once --dry-run`, and `run`.
- Validate MQTT discovery in Home Assistant after `0.2.0` legacy cleanup.
- Install and test on a Raspberry Pi OS host.
- On Raspberry Pi, verify systemd service, `/etc/ha-mqtt-agent/config.toml`, `/var/lib/ha-mqtt-agent/state.json`, local sensors, optional package prompts, and per-entity unavailable behavior.
