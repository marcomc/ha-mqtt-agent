# Mac MQTT Energy

## Table of Contents

- [Overview](#overview)
- [Telemetry Flow](#telemetry-flow)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Home Assistant Entities](#home-assistant-entities)
- [Command and Control Roadmap](#command-and-control-roadmap)
- [Running as a macOS Service](#running-as-a-macos-service)
- [Project Layout](#project-layout)
- [Development](#development)
- [Release Notes](#release-notes)
- [License](#license)

## Overview

`Mac MQTT Energy` publishes local macOS power and battery telemetry to an MQTT
broker using Home Assistant MQTT discovery.

It reads the local Mac's AppleSmartBattery telemetry, publishes current power in
watts, keeps a persistent total energy counter in kWh, and exposes battery
charge, battery maximum capacity, battery temperature, uptime, cycle count, and
charge status as Home Assistant entities.

The default broker host is `mqtt.example.local:1883`, but every MQTT setting is
configurable so the tool can be reused with any Home Assistant setup that has
MQTT discovery enabled.

The current release is telemetry-only. A future command mode can let Home
Assistant expose buttons and switches for controlled Mac actions without opening
inbound ports on the Mac.

## Telemetry Flow

This diagram shows the runtime path implemented by the CLI, sensor reader,
energy accumulator, and MQTT publisher.

```mermaid
flowchart LR
  accTitle: Telemetry publishing flow
  accDescr: Shows how macOS telemetry becomes Home Assistant MQTT entities.
  ioreg["Read AppleSmartBattery with ioreg"] --> sample["Build telemetry sample"]
  sample --> energy["Update local kWh state"]
  energy --> payload["Build JSON state payload"]
  payload --> mqtt["Publish retained MQTT state"]
  mqtt --> discovery["Publish MQTT discovery configs"]
  discovery --> ha["Home Assistant creates device entities"]
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
- Packaged command-line app exposed as `mac-mqtt-energy`.

## Requirements

For users:

- Python `3.11`
- `uv`
- `make`
- macOS with `ioreg`
- an MQTT broker reachable from the Mac
- Home Assistant MQTT integration with discovery enabled

For maintainers:

- `markdownlint`
- `shellcheck`

## Installation

Clone the repository and install the standalone runtime:

```bash
git clone <repo-url>
cd mac-mqtt-energy
make install
```

`make install`:

- creates a standalone virtual environment in
  `~/.local/share/mac-mqtt-energy/venv`
- installs the packaged CLI into that standalone runtime
- links the command to `~/.local/bin/mac-mqtt-energy`
- installs a config template to `~/.config/mac-mqtt-energy/config.toml` if it
  does not exist yet

If `~/.local/bin` is not on your `PATH`, `make check-deps` prints the shell
snippet to add it.

Install and start the background service:

```bash
make install-agent
```

This installs a per-user macOS LaunchAgent named
`com.marcomc.mac-mqtt-energy`.

This diagram follows the install targets defined in `Makefile` and the
LaunchAgent installer script.

```mermaid
flowchart LR
  accTitle: Installation workflow
  accDescr: Shows how make install-agent installs the runtime and service.
  start["Run make install-agent"] --> deps["Check uv, markdownlint, and shellcheck"]
  deps --> venv["Create or reuse standalone venv"]
  venv --> package["Install mac-mqtt-energy package"]
  package --> link["Link CLI into ~/.local/bin"]
  link --> config["Install config template if missing"]
  config --> agent["Write LaunchAgent plist"]
  agent --> launch["Bootstrap and kickstart service"]
```

### Editable Development Install

```bash
make install-dev
```

This points `~/.local/bin/mac-mqtt-energy` at the project-local `.venv` so source
edits are reflected immediately.

## Configuration

The CLI reads optional config from:

- `~/.config/mac-mqtt-energy/config.toml`
- or the file passed with `--config`

Start from the example file in this repository:

- [config.toml.example](config.toml.example)
- [config.schema.json](config.schema.json)

Example:

```toml
mqtt_host = "mqtt.example.local"
mqtt_port = 1883
device_id = "work_mac"
device_name = "Work Mac"
sample_interval_seconds = 30
state_path = "~/.local/state/mac-mqtt-energy/state.json"
verbose = false
```

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
mac-mqtt-energy info
```

Read one local telemetry sample without publishing:

```bash
mac-mqtt-energy sample
mac-mqtt-energy sample --json
```

Publish Home Assistant discovery and one state update:

```bash
mac-mqtt-energy publish-once
```

Run continuously:

```bash
mac-mqtt-energy run
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

CPU, GPU, memory, SSD, palm-rest, Wi-Fi, and fan sensors are not exposed by the
default LaunchAgent because macOS does not provide those detailed thermal
channels to this app without a privileged sensor source. The default publisher
stays user-scoped and does not require root.

For the complete Home Assistant setup path, including MQTT discovery checks and
Energy dashboard configuration, see
[Home Assistant Setup](docs/home-assistant-setup.md).

## Command and Control Roadmap

This project can grow from a telemetry publisher into a local Mac companion
service. The important design point is that MQTT does not require Home Assistant
to connect directly to the Mac's IP address. The Mac can open one outbound
connection to the MQTT broker, publish sensor state, subscribe to command topics,
and execute approved local actions when Home Assistant publishes a command.

```mermaid
flowchart LR
  accTitle: MQTT command flow
  accDescr: Shows how Home Assistant can command a Mac without inbound Mac ports.
  ha["Home Assistant button"] --> broker["MQTT broker"]
  broker --> mac["Mac agent subscribed to command topics"]
  mac --> action["Run approved local action"]
  action --> state["Publish result or updated state"]
  state --> broker
  broker --> ha
```

The Mac still needs outbound network access to the broker. It does not need SSH,
HTTP, or any other inbound listener for MQTT command handling.

### Home Assistant Entity Model

Useful command entities should be published through MQTT discovery:

- MQTT buttons for momentary actions such as sleep display, lock screen,
  restart app, refresh telemetry, open app, or restart a named service.
- MQTT switches only when there is a real state to report, such as display
  awake or a managed background service running.
- MQTT sensors and binary sensors for command results, last command time, last
  error, active user session, display state, power assertion state, and service
  health.

Commands should use non-retained payloads so an old command is not replayed
after the agent reconnects. Discovery and normal state messages should remain
retained so Home Assistant can rebuild the device after restart.

### Privilege Model

The current LaunchAgent is the right default for user-session actions because
it runs as the logged-in user. It can access user-scoped config, publish local
telemetry, open applications, interact with user LaunchAgents, and run commands
that are allowed for that user.

Some actions need a different privilege boundary:

- User LaunchAgent: open applications, sleep the display, lock the screen,
  publish battery telemetry, restart user services, and run commands that need
  the graphical user session.
- Root LaunchDaemon: manage system daemons, perform privileged sensor reads,
  run `pmset` settings that require administrator rights, or restart protected
  services.
- Split-agent model: keep MQTT and UI actions in the user LaunchAgent, and
  expose a narrow privileged helper only for approved root actions.

Prefer the split-agent model if privileged commands are added. It keeps the
MQTT-facing process low-privilege and limits the privileged surface to explicit,
audited operations.

### Candidate Mac Actions

Reasonable first commands:

- Sleep display.
- Wake display when the Mac is already awake.
- Lock screen.
- Start the screen saver.
- Open an allowlisted application.
- Quit or restart an allowlisted application.
- Restart the `mac-mqtt-energy` LaunchAgent.
- Refresh discovery and publish one immediate telemetry sample.
- Report command status back to Home Assistant.

Actions that need extra care:

- Full system sleep, shutdown, or reboot.
- Restarting system services.
- Running maintenance scripts.
- Changing power settings.
- Reading privileged hardware sensors.
- Any action that can interrupt active user work.

Actions to avoid:

- Executing arbitrary shell commands received from MQTT.
- Accepting command topics with wildcards from untrusted publishers.
- Retaining command payloads.
- Treating Home Assistant as proof that a command succeeded without publishing
  explicit result state from the Mac.

### Wake-on-LAN

Wake-on-LAN is separate from the Mac MQTT agent. If the Mac is asleep deeply
enough that the agent is not connected, MQTT cannot deliver a command to it.
Home Assistant should send the Wake-on-LAN magic packet directly on the local
network, using the Mac's Ethernet MAC address where possible.

Wake-on-LAN is best modeled in Home Assistant as:

- a Wake-on-LAN button to send the magic packet;
- a ping or MQTT availability sensor to show whether the Mac is online;
- optional MQTT buttons for actions that only work after the Mac is awake.

Wake-on-LAN usually depends on local network broadcast behavior, router support,
macOS energy settings, and whether the Mac keeps the relevant network interface
ready during sleep. It is more reliable on wired Ethernet than on Wi-Fi.

### Security Requirements

MQTT commands are a remote-control interface for the Mac. Before adding them,
use these guardrails:

- Use a dedicated MQTT username for this Mac.
- Restrict broker ACLs so Home Assistant can publish only this Mac's command
  topics and the Mac can publish only its state and discovery topics.
- Use TLS when the broker is not fully confined to a trusted local network.
- Keep command topics under a narrow prefix such as
  `mac_mqtt_energy/<device_id>/command/<action>`.
- Implement an allowlist of named actions with fixed arguments or strict
  argument validation.
- Publish command acknowledgements, failures, and last-run timestamps.
- Log every command with action name, payload, result, and timestamp.
- Add per-command config flags so risky actions stay disabled by default.
- Treat privileged actions as a separate helper API, not as direct shell access
  from the MQTT message handler.

### What People Use This For

Home Assistant's MQTT docs explicitly support `command_topic` for buttons and
switches, and the Wake-on-LAN integration supports UI buttons for sending magic
packets. Community Mac companion projects and discussions commonly use this
pattern for volume control, display sleep, sleep/wake workflows, opening apps,
restart-style maintenance actions, and Mac status reporting.

Useful references:

- [Home Assistant MQTT discovery](https://www.home-assistant.io/integrations/mqtt/)
- [Home Assistant MQTT button](https://www.home-assistant.io/integrations/button.mqtt/)
- [Home Assistant Wake-on-LAN](https://www.home-assistant.io/integrations/wake_on_lan/)
- [Mac2mqtt community discussion](https://community.home-assistant.io/t/mac2mqtt-control-volume-on-macos-via-mqtt/298607)
- [Home Assistant macOS display sleep discussion](https://community.home-assistant.io/t/can-the-macos-companion-app-put-my-displays-to-sleep/417502)

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

Use this after editing `~/.config/mac-mqtt-energy/config.toml`; the LaunchAgent
loads config only when the process starts.

Stop and remove it:

```bash
make uninstall-agent
```

The generated plist is written to
`~/Library/LaunchAgents/com.marcomc.mac-mqtt-energy.plist`. Logs are written to
`~/Library/Logs/mac-mqtt-energy/`.

This diagram shows the service controls exposed by the `Makefile` and backed by
the install and uninstall scripts.

```mermaid
flowchart LR
  accTitle: LaunchAgent lifecycle
  accDescr: Shows the supported macOS service operations.
  install["make install-agent"] --> running["LaunchAgent running"]
  running --> status["make agent-status"]
  running --> restart["make restart-agent"]
  restart --> running
  running --> uninstall["make uninstall-agent"]
  uninstall --> removed["Plist removed"]
```

## Project Layout

```text
.
├── AGENTS.md
├── CHANGELOG.md
├── Makefile
├── README.md
├── TODO.md
├── config.toml.example
├── docs/
│   ├── README.md
│   └── home-assistant-setup.md
├── pyproject.toml
├── scripts/
│   ├── install-launch-agent.sh
│   ├── install.sh
│   └── uninstall-launch-agent.sh
├── src/
│   └── mac_mqtt_energy/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── energy.py
│       ├── mqtt.py
│       └── sensors.py
└── tests/
    ├── test_cli.py
    ├── test_energy.py
    ├── test_mqtt.py
    └── test_sensors.py
```

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

## Release Notes

Before tagging a release:

1. update the version in `pyproject.toml`
2. update `src/mac_mqtt_energy/__init__.py`
3. add release notes to `CHANGELOG.md`
4. verify `make check`

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
