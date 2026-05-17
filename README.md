# Home Assistant MQTT Agent

## Table of Contents

- [Overview](#overview)
- [Runtime Flow](#runtime-flow)
- [Features](#features)
- [Requirements](#requirements)
- [Quick Install](#quick-install)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Home Assistant Entities](#home-assistant-entities)
- [Running as a macOS Service](#running-as-a-macos-service)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Release Notes](#release-notes)
- [License](#license)

## Overview

`Home Assistant MQTT Agent` publishes local Mac telemetry to an MQTT broker
using Home Assistant MQTT discovery.

The current provider reads macOS AppleSmartBattery telemetry, publishes current
power in watts, keeps a persistent total energy counter in kWh, and exposes
battery charge, battery maximum capacity, battery temperature, uptime, cycle
count, and charge status as Home Assistant entities.

The default broker host is `mqtt.example.local:1883`, but every MQTT setting is
configurable so the tool can be reused with any Home Assistant setup that has
MQTT discovery enabled.

The current release is telemetry-only.

## Runtime Flow

This is the runtime path after `make install-agent` installs and starts the
per-user LaunchAgent.

```mermaid
flowchart LR
  accTitle: Runtime telemetry flow
  accDescr: Shows how the LaunchAgent publishes Mac telemetry to Home Assistant through MQTT.
  install["make install-agent"] --> plist["Write LaunchAgent plist"]
  plist --> launchd["macOS launchd starts ha-mqtt-agent run"]
  launchd --> reader["Read AppleSmartBattery telemetry"]
  reader --> energy["Update local kWh state"]
  energy --> payload["Build MQTT state payload"]
  payload --> mqtt["Publish discovery and state to MQTT broker"]
  mqtt --> ha["Home Assistant updates MQTT entities"]
```

## Features

- Home Assistant MQTT discovery for all sensors.
- Current power sensor with `device_class: power`, `state_class: measurement`,
  and unit `W`.
- Total energy sensor with `device_class: energy`,
  `state_class: total_increasing`, and unit `kWh`.
- Battery charge, maximum capacity, raw maximum capacity, cycle count, and
  status sensors.
- Battery temperature, battery virtual temperature, and system uptime sensors.
- Persistent local energy accumulator that survives restarts.
- Packaged command-line app exposed as `ha-mqtt-agent`.

Only macOS is supported in this release. Linux and Raspberry Pi hosts
need a future provider that does not depend on AppleSmartBattery telemetry.

## Requirements

For users:

- Python `3.11` or newer
- `make`
- macOS with `ioreg` for the current telemetry provider
- an MQTT broker reachable from the Mac
- Home Assistant MQTT integration with discovery enabled

For maintainers:

- `markdownlint`
- `shellcheck`

## Quick Install

Clone the repository on the Mac you want to publish, then run the installer:

```bash
git clone <repo-url>
cd ha-mqtt-agent
./scripts/install.sh
```

The script is a user-friendly wrapper around `make install-agent`. It checks the
local prerequisites, installs the standalone runtime, creates the config
template if needed, and starts the per-user LaunchAgent.

Edit the MQTT and device settings:

```bash
$EDITOR ~/.config/ha-mqtt-agent/config.toml
```

At minimum, set:

```toml
mqtt_host = "mqtt.example.local"
device_id = "workstation"
device_name = "Workstation"
```

Then restart the service:

```bash
make restart-agent
```

## Installation

For scripted installs, use the Make target directly:

```bash
make install-agent
```

`make install-agent`:

- creates a standalone virtual environment in
  `~/.local/share/ha-mqtt-agent/venv`
- installs the packaged CLI into that standalone runtime
- does not require `uv` at runtime
- links the command to `~/.local/bin/ha-mqtt-agent`
- installs a config template to `~/.config/ha-mqtt-agent/config.toml` if it
  does not exist yet
- installs and starts the per-user macOS LaunchAgent

If `~/.local/bin` is not on your `PATH`, `make check-deps` prints the shell
snippet to add it.

This installs a per-user macOS LaunchAgent named
`com.marcomc.ha-mqtt-agent`.

### Editable Development Install

```bash
make install-dev
```

This points `~/.local/bin/ha-mqtt-agent` at the project-local `.venv` so source
edits are reflected immediately.

## Configuration

The CLI reads optional config from:

- `~/.config/ha-mqtt-agent/config.toml`
- or the file passed with `--config`

Start from the example file in this repository:

- [config.toml.example](config.toml.example)
- [config.schema.json](config.schema.json)

Example:

```toml
mqtt_host = "mqtt.example.local"
mqtt_port = 1883
device_id = "workstation"
device_name = "Workstation"
sample_interval_seconds = 5
expire_after_seconds = 15
state_path = "~/.local/state/ha-mqtt-agent/state.json"
verbose = false
```

`sample_interval_seconds` defaults to `5` and may be set as low as `1`.
`expire_after_seconds` defaults to `15`, so Home Assistant marks sensors
unavailable after about three missed publishes.

For brokers with authentication, set:

```toml
mqtt_username = "homeassistant"
mqtt_password = "change-me"
```

Restart the LaunchAgent after changing the installed config:

```bash
make restart-agent
```

Changing `device_id` changes MQTT topics and Home Assistant unique IDs, so Home
Assistant will discover a new device. Remove the old MQTT device from Home
Assistant if you no longer need it.

## Usage

Inspect the resolved configuration:

```bash
ha-mqtt-agent info
```

Read one local telemetry sample without publishing:

```bash
ha-mqtt-agent sample
ha-mqtt-agent sample --json
```

Publish Home Assistant discovery and one state update:

```bash
ha-mqtt-agent publish-once
```

Run continuously:

```bash
ha-mqtt-agent run
```

## Home Assistant Entities

The discovery payloads create one Home Assistant device named by `device_name`
with these entities:

- Power: current power in `W`.
- Energy: accumulated energy in `kWh`, suitable for the Energy dashboard.
- Battery: current battery charge in `%`.
- Battery maximum capacity: reported maximum battery capacity in `%`.
- Battery maximum capacity mAh: raw maximum charge capacity in `mAh`.
- Battery design capacity: design charge capacity in `mAh`.
- Battery temperature: battery temperature in `°C`.
- Battery virtual temperature: Apple battery virtual temperature in `°C`.
- Battery cycle count.
- Battery status: `charging`, `charged`, `plugged_in`, or `discharging`.
- Uptime: system uptime in seconds.

The energy entity is the one to add under Home Assistant's Energy dashboard.
Home Assistant long-term statistics are fed by the `total_increasing` kWh
sensor.

Sensors use `expire_after_seconds` in MQTT discovery. The default is `15`, so
Home Assistant marks them unavailable after about three missed publishes.

CPU, GPU, memory, SSD, palm-rest, Wi-Fi, and fan sensors are not exposed by the
default LaunchAgent because macOS does not provide those detailed thermal
channels to this app without a privileged sensor source. The default publisher
stays user-scoped and does not require root.

For the complete Home Assistant setup path, including MQTT discovery checks and
Energy dashboard configuration, see
[Home Assistant Setup](docs/home-assistant-setup.md).

## Running as a macOS Service

The supported background mode is a per-user LaunchAgent, not a root
LaunchDaemon. The app reads macOS user-space battery telemetry, stores state in
the user's home directory, and does not need root privileges.

Install and start it:

```bash
make install-agent
```

Check it:

```bash
make agent-status
```

Restart it:

```bash
make restart-agent
```

Use this after editing `~/.config/ha-mqtt-agent/config.toml`; the LaunchAgent
loads config only when the process starts.

Stop and remove it:

```bash
make uninstall-agent
```

The generated plist is written to
`~/Library/LaunchAgents/com.marcomc.ha-mqtt-agent.plist`. Logs are written to
`~/Library/Logs/ha-mqtt-agent/`.

## Troubleshooting

Check the installed configuration:

```bash
ha-mqtt-agent info
```

Publish one sample manually:

```bash
ha-mqtt-agent publish-once
```

Check the background service:

```bash
make agent-status
tail -n 100 ~/Library/Logs/ha-mqtt-agent/err.log
```

Confirm that the Mac can reach the MQTT broker:

```bash
nc -vz mqtt.example.local 1883
```

If Home Assistant still shows stale values, confirm the discovery payload has
the expected `expire_after` value and restart the LaunchAgent after config
changes.

## Development

Sync the environment and run the default quality gate:

```bash
make check
```

Common commands:

```bash
make sync
make test
make lint
make run
```

Future work is tracked in [TODO.md](TODO.md) and expanded in
[Roadmap](docs/roadmap.md).

## Release Notes

Before tagging a release:

1. update the version in `pyproject.toml`
2. update `src/ha_mqtt_agent/__init__.py`
3. add release notes to `CHANGELOG.md`
4. verify `make check`

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
