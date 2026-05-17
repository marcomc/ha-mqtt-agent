# Roadmap

## Overview

The first public release is macOS telemetry-only. Future work should preserve
the current model: the Mac opens an outbound MQTT connection, publishes state,
and does not require Home Assistant to connect directly to the Mac.

Backlog tickets are tracked in [TODO.md](../TODO.md).

## HMA-001 Persistent MQTT Command Loop

Add a command loop to `ha-mqtt-agent run`.

- Keep telemetry publishing active on the same outbound broker connection.
- Subscribe only to `ha_mqtt_agent/<device_id>/command/+`.
- Ignore retained command messages.
- Publish command acknowledgements, failures, and last-run timestamps.

Backlog: [HMA-001](../TODO.md#hma-001-persistent-mqtt-command-loop)

## HMA-002 Home Assistant Command Entities

Expose safe Home Assistant command entities through MQTT discovery.

- Start with buttons for refresh telemetry, sleep display, lock screen, and
  opening an allowlisted application.
- Use switches only for commands with reliable state feedback.
- Keep command payloads non-retained.

Backlog: [HMA-002](../TODO.md#hma-002-home-assistant-command-entities)

## HMA-003 Command Safety Controls

Add guardrails before any remote command support ships.

- Require explicit config flags for every command group.
- Use allowlists for application names, service names, and maintenance tasks.
- Reject arbitrary shell commands from MQTT payloads.
- Add structured command logs.

Backlog: [HMA-003](../TODO.md#hma-003-command-safety-controls)

## HMA-004 Wake-on-LAN Documentation

Document Wake-on-LAN as a Home Assistant-side action.

- Do not model Wake-on-LAN as a host MQTT command.
- Pair Wake-on-LAN with ping or MQTT availability state.
- Call out wired Ethernet as the preferred target for reliable wake.

Backlog: [HMA-004](../TODO.md#hma-004-wake-on-lan-documentation)

## HMA-005 Privileged Action Boundary

Define which actions belong in each macOS execution context.

- Keep user-session actions in the LaunchAgent.
- Add a narrow privileged helper only if root-only actions are required.
- Document LaunchAgent, LaunchDaemon, and helper responsibilities.

Backlog: [HMA-005](../TODO.md#hma-005-privileged-action-boundary)

## HMA-006 MQTT TLS Settings

Add optional TLS configuration for hardened brokers.

- Support CA, client certificate, and client key paths.
- Keep plain local-network MQTT simple by default.
- Document broker-side expectations.

Backlog: [HMA-006](../TODO.md#hma-006-mqtt-tls-settings)

## HMA-007 Linux and Raspberry Pi Providers

Add non-macOS telemetry providers.

- Keep macOS AppleSmartBattery support as the first provider.
- Add Linux power-source detection behind provider selection.
- Document unsupported sensors clearly on Raspberry Pi.

Backlog: [HMA-007](../TODO.md#hma-007-linux-and-raspberry-pi-providers)

## HMA-008 Release Automation

Add release automation only when the project is ready to publish packages or
binaries.

- Keep version updates consistent across package metadata and code.
- Run `make check` before tagging.
- Avoid hosted release workflows until distribution requirements are clear.

Backlog: [HMA-008](../TODO.md#hma-008-release-automation)
