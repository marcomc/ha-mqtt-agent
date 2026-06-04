# Home Assistant MQTT Agent

## Table of Contents

- [Overview](#overview)
- [Runtime Flow](#runtime-flow)
- [Features](#features)
- [Requirements](#requirements)
- [Linux and Raspberry Pi Support](#linux-and-raspberry-pi-support)
- [Quick Install](#quick-install)
- [Install Modes](#install-modes)
- [Installation](#installation)
- [Configuration](#configuration)
- [Authorizing Wi-Fi SSID Access](#authorizing-wi-fi-ssid-access)
- [Usage](#usage)
- [Home Assistant Entities](#home-assistant-entities)
- [Running as a Service](#running-as-a-service)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Release Notes](#release-notes)
- [License](#license)

## Overview

`Home Assistant MQTT Agent` publishes local host telemetry to an MQTT broker
using Home Assistant MQTT discovery.

The runtime selects a platform provider at startup. macOS reads
AppleSmartBattery and user-space network telemetry, including current power and
a persistent kWh energy counter. Linux and Raspberry Pi OS read real host facts
from readable `/proc`, `/sys`, and common network tools, then publish only the
capabilities present on that host.

The default broker host is `mqtt.example.local:1883`, but every MQTT setting is
configurable so the tool can be reused with any Home Assistant setup that has
MQTT discovery enabled.

The current release is telemetry-only.

## Runtime Flow

This is the runtime path after `make install` installs and starts the platform
service.

```mermaid
flowchart LR
  accTitle: Runtime telemetry flow
  accDescr: Shows how the platform service publishes local telemetry to Home Assistant through MQTT.
  install["make install"] --> service["LaunchAgent or systemd service"]
  service --> run["ha-mqtt-agent run"]
  run --> provider{"Detected platform"}
  provider -->|macOS| macos["Read AppleSmartBattery, network, Wi-Fi helper"]
  provider -->|Linux| linux["Read /proc, /sys, ip, Wi-Fi, ping"]
  macos --> capabilities["Build capability snapshot"]
  linux --> capabilities
  capabilities --> payload["Build MQTT discovery, state, availability"]
  payload --> mqtt["Publish discovery and state to MQTT broker"]
  mqtt --> ha["Home Assistant updates MQTT entities"]
```

## Features

- Platform provider selection for macOS and Linux.
- Home Assistant MQTT discovery for supported local sensors.
- Current power sensor with `device_class: power`, `state_class: measurement`,
  and unit `W` where macOS AppleSmartBattery exposes real power telemetry.
- Total energy sensor with `device_class: energy`,
  `state_class: total_increasing`, and unit `kWh` on macOS.
- Battery charge, maximum capacity, raw maximum capacity, cycle count, and
  status sensors where the active provider has real battery data.
- Battery temperature, battery virtual temperature where available, CPU
  temperature on Linux where readable, and system uptime sensors.
- Wi-Fi SSID, Wi-Fi signal in `dBm`, and Wi-Fi signal as a percentage.
- Wi-Fi BSSID, local IPv4 addresses, default gateway, gateway MAC, and a
  configurable home-network presence binary sensor.
- Optional latitude, longitude, location accuracy, and geocoded location
  sensors.
- Active wired Ethernet interface count and active interface list.
- Configurable external ping latency sensors, with Google and Cloudflare DNS
  targets enabled by default.
- Persistent local energy accumulator on macOS that survives restarts.
- Packaged command-line app exposed as `ha-mqtt-agent`.
- Read-only `doctor` diagnostics and `publish-once --dry-run` message preview.
- Explicit legacy MQTT discovery cleanup for retained `0.1.x` topics.

## Requirements

For users:

- Python `3.11` or newer
- `make`
- an MQTT broker reachable from the host
- Home Assistant MQTT integration with discovery enabled

For macOS source installs:

- Xcode Command Line Tools with `swiftc` and `codesign` for the Wi-Fi SSID
  helper
- macOS with `ioreg`

For Linux system installs:

- `systemd`
- `sudo` for setup when not running the installer as root
- a Debian/Raspberry Pi OS, Fedora, or Arch-style package manager only if you
  opt into optional packages

For maintainers:

- `markdownlint`
- `shellcheck`
- Xcode Command Line Tools with `swiftc`

## Linux and Raspberry Pi Support

Linux and Raspberry Pi OS are supported through the Linux provider and system
`systemd` installer. The provider publishes only real readable host facts:
uptime, network addresses, Wi-Fi, Ethernet, default gateway, gateway MAC,
configured ping latency, CPU temperature where exposed by `/sys`, and battery
facts where Linux power-supply data exists.

It does not estimate power draw or synthesize an energy counter on Linux.
Unsupported capabilities are omitted from MQTT discovery. Supported capabilities
that fail during a sample remain discovered and report unavailable.

For a quick source smoke test without installing a service, use a temporary
developer virtual environment:

```bash
git clone https://github.com/marcomc/ha-mqtt-agent.git
cd ha-mqtt-agent
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install .
ha-mqtt-agent --version
ha-mqtt-agent info
```

Use `ha-mqtt-agent doctor` before installing as a service.

## Quick Install

Clone the repository on the host you want to publish, then run the installer:

```bash
git clone https://github.com/marcomc/ha-mqtt-agent.git
cd ha-mqtt-agent
./scripts/install.sh
```

The script is a user-friendly wrapper around the platform install path. On
macOS it starts the per-user LaunchAgent. On Linux it installs a systemd
service running as the unprivileged `ha-mqtt-agent` user.

This install path does not require activating `.venv`; the Linux installer
creates its own standalone runtime under `/opt/ha-mqtt-agent/venv`.

On first install, the created config file is prefilled with a hostname-derived
`device_id`, `device_name`, explicit `mqtt_client_id`, and any currently
readable SSID, BSSID, IPv4 CIDR, default gateway, and gateway MAC. Existing
config files are not overwritten.

Edit the MQTT and device settings.

macOS:

```bash
$EDITOR ~/.config/ha-mqtt-agent/config.toml
```

Linux/systemd:

```bash
sudoedit /etc/ha-mqtt-agent/config.toml
```

At minimum, set:

```toml
mqtt_host = "mqtt.example.local"
```

Then restart the service:

```bash
make restart-agent
```

## Install Modes

The supported install modes are:

- macOS source install with a per-user LaunchAgent.
- Linux/Raspberry Pi OS source install with a system `systemd` service.

There is not yet a prebuilt, Developer ID signed, notarized macOS installer for
non-developer users.

### macOS Source Install

`./scripts/install.sh` and `make install` expect local build tools:

- Python `3.11` or newer for the packaged CLI runtime. The installer
  auto-detects a compatible `python3.14`, `python3.13`, `python3.12`,
  `python3.11`, or `uv`-managed Python before falling back to `python3`.
- `make` to run the project install targets.
- `swiftc` to compile the Wi-Fi SSID helper app.
- `codesign` to apply the helper's local ad-hoc signature.

The source install builds the helper during installation, then signs it with an
ad-hoc local signature. This is enough for the local Mac to run the helper and
request the macOS Location permission needed to read the current Wi-Fi SSID. It
is not a public distribution signature and does not require an Apple Developer
account.

The installer checks for these tools before installing. On macOS, `make`,
`swiftc`, and `codesign` are normally provided by Xcode Command Line Tools:

```bash
xcode-select --install
```

After installing the command line tools, rerun:

```bash
./scripts/install.sh
```

If more than one Python is installed, you can still force the standalone runtime
interpreter:

```bash
make restart-agent STANDALONE_PYTHON=/path/to/python3.12
```

### Future Prebuilt Install

A non-developer install path is planned but not shipped yet. That path should
provide a prebuilt helper app signed with the maintainer's Developer ID
Application certificate and notarized before release. In that future mode,
users should not need `swiftc`, local helper compilation, or local signing.

The backlog item is tracked as [HMA-009](TODO.md#hma-009-prebuilt-notarized-macos-installer).

### Linux System Install

On Linux, `./scripts/install.sh` and `make install` install:

- a standalone virtual environment in `/opt/ha-mqtt-agent/venv`
- a symlink at `/usr/local/bin/ha-mqtt-agent`
- a config template at `/etc/ha-mqtt-agent/config.toml`
- writable runtime state at `/var/lib/ha-mqtt-agent/state.json`
- a system service named `ha-mqtt-agent`

The service runs as the unprivileged `ha-mqtt-agent` user. Setup uses `sudo`
when the installer is not already running as root.

Optional sensor packages are consent-based:

```bash
./scripts/install.sh --non-interactive
./scripts/install.sh --non-interactive --enable-optional-sensors
./scripts/install.sh --non-interactive --optional-packages iw,lm-sensors,upower
```

Known optional packages are `iw`, `lm-sensors`, and `upower`. Unsupported
package managers print the package recommendations instead of installing them.

## Installation

For the complete platform install, use the Make target directly:

```bash
make install
```

On macOS, `make install`:

- builds the Wi-Fi SSID helper app from `macos/WifiHelper/`
- signs the helper locally with an ad-hoc signature and the Location entitlement
- asks macOS to authorize the helper for Wi-Fi SSID access
- creates a standalone virtual environment in
  `~/.local/share/ha-mqtt-agent/venv`
- installs the packaged CLI into that standalone runtime
- does not require `uv` at runtime
- links the command to `~/.local/bin/ha-mqtt-agent`
- installs a config template to `~/.config/ha-mqtt-agent/config.toml` if it
  does not exist yet, prefilled from local host and network facts where readable
- installs and starts the per-user macOS LaunchAgent

On Linux, `make install`:

- creates the unprivileged `ha-mqtt-agent` service user if needed
- creates a standalone virtual environment in `/opt/ha-mqtt-agent/venv`
- installs the packaged CLI into that standalone runtime
- links the command to `/usr/local/bin/ha-mqtt-agent`
- installs a config template to `/etc/ha-mqtt-agent/config.toml` if missing
  with local host and network defaults where readable
- creates `/var/lib/ha-mqtt-agent` for state owned by the service user
- installs and starts the systemd service

Use `make install-cli` only when you want the user-scoped standalone CLI runtime
without installing config, helper apps, LaunchAgent, or systemd service files.

If `~/.local/bin` is not on your `PATH`, `make check-deps` prints the shell
snippet to add it.

On macOS this installs a per-user LaunchAgent named
`com.marcomc.ha-mqtt-agent`. On Linux this installs a systemd service named
`ha-mqtt-agent`.

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

The repository example stays intentionally inert. `make install` and
`./scripts/install.sh` render a host-aware first config from that example and
leave any existing config untouched.

Example:

```toml
mqtt_host = "mqtt.example.local"
mqtt_port = 1883
device_id = "workstation"
device_name = "Workstation"
sample_interval_seconds = 5
expire_after_seconds = 15
network_interval_seconds = 60
capability_refresh_seconds = 300
ping_timeout_seconds = 1
wifi_helper_path = "~/.local/share/ha-mqtt-agent/HaMqttAgentWifiHelper.app/Contents/MacOS/HaMqttAgentWifiHelper"
state_path = "~/.local/state/ha-mqtt-agent/state.json"
verbose = false
home_ssids = []
home_ipv4_cidrs = []
home_gateways = []
home_bssids = []
home_gateway_macs = []
publish_location = false
location_timeout_seconds = 3

ping_targets = [
  { id = "cloudflare_dns", host = "1.1.1.1", name = "Cloudflare DNS" },
  { id = "cloudflare_dns_secondary", host = "1.0.0.1", name = "Cloudflare DNS secondary" },
  { id = "google_dns", host = "8.8.8.8", name = "Google DNS" },
  { id = "google_dns_secondary", host = "8.8.4.4", name = "Google DNS secondary" }
]
```

`sample_interval_seconds` defaults to `5` and may be set as low as `1`.
`expire_after_seconds` defaults to `15`, so Home Assistant marks sensors
unavailable after about three missed publishes.
`network_interval_seconds` defaults to `60`; Wi-Fi, Ethernet, and ping probes
are cached between those slower network samples while the normal telemetry loop
keeps publishing. `ping_timeout_seconds` defaults to `1`.
`capability_refresh_seconds` defaults to `300`; continuous runs republish
discovery periodically so newly readable capabilities can appear without
restarting the service.
After an MQTT publish failure, the service uses a lightweight broker connection
probe before trying the next full telemetry publish. This keeps local sampling
quiet while the broker is unreachable and lets the service resume promptly
when MQTT connectivity returns.
If `mqtt_client_id` is omitted, the runtime MQTT client ID is derived from
`device_id`; one-shot publish commands add a short process suffix so they do
not disconnect the background service while you are debugging.

Each `ping_targets` entry creates a separate Home Assistant latency sensor named
from its `id`. To configure a longer list quickly, `ping_targets` can also be a
plain host list, for example:

```toml
ping_targets = ["192.168.1.1", "1.1.1.1", "8.8.8.8", "9.9.9.9"]
```

Home-network presence is published as a binary sensor named
`Home network present`. It turns on when any configured home SSID, BSSID, IPv4
CIDR, default gateway, or gateway MAC matches the current local network sample.
Leave lists empty to disable that specific match method.

For example:

```toml
home_ssids = ["Home WiFi", "Home WiFi 5G"]
home_ipv4_cidrs = ["192.168.1.0/24"]
home_gateways = ["192.168.1.1"]
```

`publish_location` defaults to `false`. Set it to `true` only when you want this
Mac to publish latitude, longitude, and horizontal accuracy to Home Assistant.
Location data uses the same macOS Location Services permission as the Wi-Fi
helper. The agent publishes both standalone latitude/longitude sensors and an
MQTT `device_tracker` named `Location` with GPS attributes, so Home Assistant
can place the Mac on map cards. If macOS temporarily reports that the location
is unknown after one valid fix has been seen, the agent keeps publishing the
last known coordinates and marks `Location cached` as on. `Location last seen`
and the `device_tracker` `last_seen` attribute show when the coordinate was last
refreshed. `Location error` shows the current CoreLocation error, if any. The
same setting also enables a `Geocoded location` sensor built from macOS reverse
geocoding, with address-style attributes such as country, locality, postal code,
street, areas of interest, and time zone. When the coordinate is cached because
CoreLocation is temporarily unavailable, the geocoded location is reused only
with that cached coordinate and is marked with `Geocoded location cached`.

On newer macOS versions, SSID access requires the macOS Location permission for
the bundled Wi-Fi helper app. Signal strength is still published from the
fallback user-space probes even before the SSID helper is authorized.

## Authorizing Wi-Fi SSID Access

macOS treats Wi-Fi SSID, BSSID, and geographic coordinates as location-adjacent
data. `make install` installs a small signed helper app at:

```text
~/.local/share/ha-mqtt-agent/HaMqttAgentWifiHelper.app
```

`make install` runs the authorization command automatically after
installing the helper. Approve the Location Services prompt for **Home
Assistant MQTT Agent Wi-Fi Helper** when it appears.

If the prompt does not appear, or if the helper was rebuilt after macOS had
already recorded an older local signature, run:

```bash
ha-mqtt-agent authorize-wifi
```

Then open **System Settings > Privacy & Security > Location Services** and
enable that helper there if needed, then restart the LaunchAgent:

```bash
make restart-agent
```

Without that permission, macOS may return `<redacted>` for the SSID and omit
BSSID or location while still allowing the app to publish Wi-Fi signal strength.

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

Check local readiness without writes or publishes:

```bash
ha-mqtt-agent doctor
ha-mqtt-agent doctor --json
ha-mqtt-agent doctor --verbose
ha-mqtt-agent doctor --mqtt
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

Preview the exact MQTT messages without publishing or writing state:

```bash
ha-mqtt-agent publish-once --dry-run
ha-mqtt-agent publish-once --dry-run --include-cleanup
```

Explicitly remove retained `0.1.x` discovery topics for the current
`device_id`, then publish current capability-based discovery and state:

```bash
ha-mqtt-agent cleanup-discovery --legacy-0-1
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
- Wi-Fi SSID.
- Wi-Fi BSSID.
- Wi-Fi signal in `dBm`.
- Wi-Fi signal percent in `%`.
- IPv4 addresses.
- Default gateways.
- Default gateway interfaces.
- Gateway MACs.
- Home network present.
- Location device tracker for Home Assistant map cards.
- Latitude, longitude, location accuracy, last seen time, cache state, and
  location error when `publish_location` is enabled.
- Geocoded location, geocoded cache state, and geocoded error when
  `publish_location` is enabled.
- Ethernet active count.
- Ethernet active interfaces.
- One ping latency sensor in `ms` for each configured `ping_targets` entry.

The energy entity is the one to add under Home Assistant's Energy dashboard.
Home Assistant long-term statistics are fed by the `total_increasing` kWh
sensor.

Sensors use `expire_after_seconds` in MQTT discovery. The default is `15`, so
Home Assistant marks them unavailable after about three missed publishes.
After MQTT publish failures, the service retries with a lightweight broker
connection probe before doing another full telemetry sample. The recovery probe
keeps running while the broker is unreachable and the retry backoff is capped at
60 seconds.

CPU temperature is exposed on Linux when a readable thermal zone exists. macOS
CPU, GPU, memory, SSD, palm-rest, and fan sensors are not exposed by the
default LaunchAgent because macOS does not provide those detailed thermal
channels to this app without a privileged sensor source. The default macOS
publisher stays user-scoped and does not require root.

For the complete Home Assistant setup path, including MQTT discovery checks and
Energy dashboard configuration, see
[Home Assistant Setup](docs/home-assistant-setup.md).

## Running as a Service

The macOS background mode is a per-user LaunchAgent, not a root LaunchDaemon.
The app reads macOS user-space battery telemetry, stores state in the user's
home directory, and does not need root privileges.

The Linux background mode is a systemd service that runs as the unprivileged
`ha-mqtt-agent` user and stores state in `/var/lib/ha-mqtt-agent/state.json`.

Install and start it:

```bash
make install
```

Check it:

```bash
make agent-status
journalctl -u ha-mqtt-agent
```

Restart it:

```bash
make restart-agent
```

Use this after editing the installed config; the service loads config only when
the process starts.

Stop and remove it:

```bash
make uninstall-agent
```

The generated plist is written to
`~/Library/LaunchAgents/com.marcomc.ha-mqtt-agent.plist`. Logs are written to
`~/Library/Logs/ha-mqtt-agent/`.

The Linux unit is written to `/etc/systemd/system/ha-mqtt-agent.service`. Logs
are available through `journalctl -u ha-mqtt-agent`.

## Troubleshooting

Check the installed configuration:

```bash
ha-mqtt-agent info
ha-mqtt-agent doctor
```

Preview or publish one sample manually:

```bash
ha-mqtt-agent publish-once --dry-run
ha-mqtt-agent publish-once
```

Check the background service:

```bash
make agent-status
tail -n 100 ~/Library/Logs/ha-mqtt-agent/err.log
journalctl -u ha-mqtt-agent
```

Confirm that the host can reach the MQTT broker:

```bash
nc -vz mqtt.example.local 1883
```

If Home Assistant still shows stale values, confirm the discovery payload has
the expected `expire_after` value and restart the service after config
changes.

If Home Assistant shows the device as unavailable and the service is still
running, check whether the log contains MQTT reachability errors such as
`No route to host`, DNS lookup failures, or connection-loss messages. The
service will keep using lightweight recovery probes until the broker is
reachable again.

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
