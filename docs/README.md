# Documentation

## User Guides

- [Cross-Platform Architecture](cross-platform-architecture.md): capability
  model, current implementation status, Linux and macOS install behavior, MQTT
  discovery, and legacy cleanup.
- [Home Assistant Setup](home-assistant-setup.md): configure MQTT discovery,
  confirm the host device, and add supported entities to dashboards.
- [Raspberry Pi Throttle Status Research](raspberry-pi-throttle-status.md):
  firmware flag semantics, platform limits, entity design, and alerting.
- [Roadmap](roadmap.md): future command, security, provider, and release work
  linked to numbered backlog tickets in [TODO.md](../TODO.md).

## Installer Shape

`make install` is the user-facing entrypoint for a new host. It delegates to
the macOS LaunchAgent installer on Darwin and the Linux systemd installer on
Linux. `scripts/install.sh` remains a wrapper for Linux-specific installer
flags.

The `Makefile` remains the durable automation API for install, restart, status,
uninstall, development checks, and tests. macOS keeps the per-user LaunchAgent
flow. Linux installs a system service with `/etc/ha-mqtt-agent/config.toml`,
`/var/lib/ha-mqtt-agent/state.json`, and the unprivileged `ha-mqtt-agent`
runtime user.

First installs render config files from the inert example plus local readable
facts: hostname-derived identity, MQTT client ID, and current SSID, BSSID, IPv4
CIDR, gateway, and gateway MAC where available. Existing configs are preserved.

## Included Defaults

- `uv` for development environment and package management
- auto-detected Python 3.11+ plus `pip` for the installed standalone runtime
- `src/` package layout
- `argparse` for a small CLI surface
- TOML config loading via `tomllib`
- platform provider selection for macOS and Linux
- `doctor`, `publish-once --dry-run`, and explicit device-scoped discovery cleanup
- `make check` for tests, typing, formatting, Markdown, and shell linting

## Intended Workflow

1. Keep sensor collection, energy accumulation, and MQTT publishing in separate
   modules.
2. Keep `README.md`, `CHANGELOG.md`, and `TODO.md` current as the project
   evolves.
3. Preserve `make install` as the durable service installation path unless
   you have a reason to redesign distribution.
