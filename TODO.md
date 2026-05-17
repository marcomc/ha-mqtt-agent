# TODO

## Next Steps

- Implement a persistent MQTT command loop for `mac-mqtt-energy run`.
  - Keep telemetry publishing active on the same outbound broker connection.
  - Subscribe only to `mac_mqtt_energy/<device_id>/command/+`.
  - Ignore retained command messages.
  - Publish command acknowledgements, failures, and last-run timestamps.
- Add MQTT discovery for safe Home Assistant command entities.
  - Start with buttons for refresh telemetry, sleep display, lock screen, and
    open an allowlisted application.
  - Use switches only for commands with reliable state feedback.
  - Keep command payloads non-retained.
- Add command safety controls.
  - Require explicit config flags for every command group.
  - Use allowlists for application names, service names, and maintenance tasks.
  - Reject arbitrary shell commands from MQTT payloads.
  - Add structured command logs.
- Add Home Assistant Wake-on-LAN documentation.
  - Document the Wake-on-LAN button as a Home Assistant-side action, not a Mac
    MQTT command.
  - Document pairing it with ping or MQTT availability state.
  - Call out wired Ethernet as the preferred target for reliable wake.
- Design the privileged action boundary.
  - Keep user-session actions in the LaunchAgent.
  - Add a separate narrow privileged helper only if root-only actions are
    required.
  - Document which actions belong in the LaunchAgent, LaunchDaemon, or helper.
- Add optional TLS settings for hardened MQTT brokers.
- Add Linux power-source plugins for non-macOS systems.
- Add release automation if the project will publish packages or binaries.
