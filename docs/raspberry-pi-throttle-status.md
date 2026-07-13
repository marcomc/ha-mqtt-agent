# Raspberry Pi Throttle Status Research

## Decision

Add Raspberry Pi firmware health as a capability-gated Linux provider feature.
Publish the raw word plus separate current and history binary sensors through
MQTT discovery. On Raspberry Pi 5-family hardware, also publish the PMIC
`EXT5V_V` ADC measurement. Keep alert policy in Home Assistant.

Do not treat the word as a voltage measurement or promise an exact event count
or timestamp. Those values are not present in the firmware response.

## Firmware Flags

`vcgencmd get_throttled` returns a bit field with four current conditions and
four sticky history conditions. Raspberry Pi documents the following complete
set in the [operating system documentation][rpi-get-throttled] and the
[official utility manual][vcgencmd-manpage].

| Bit | Hex | Meaning |
| ---: | ---: | --- |
| 0 | `0x1` | Under-voltage detected now |
| 1 | `0x2` | Arm frequency capped now |
| 2 | `0x4` | System throttled now |
| 3 | `0x8` | Soft temperature limit active now |
| 16 | `0x10000` | Under-voltage has occurred |
| 17 | `0x20000` | Arm frequency capping has occurred |
| 18 | `0x40000` | Throttling has occurred |
| 19 | `0x80000` | Soft temperature limit has occurred |

`0x50000` sets only bits 16 and 18: under-voltage and throttling occurred
previously, but neither condition is current. The official manual uses this
exact example. A Raspberry Pi engineer confirms that the high bits cover the
period since power-on and reset on reboot [in the official forum][rpi-sticky],
unless a firmware consumer explicitly clears them.

Only bits 0 and 16 directly establish under-voltage. Frequency capping and
throttling can also be thermal, so they must remain separate. Raspberry Pi's
[thermal documentation][rpi-thermal] describes temperature-driven frequency
reduction and throttling.

## Platform Scope

This word belongs to Raspberry Pi VideoCore firmware; it is not a generic Linux
interface. `vcgencmd` is a Raspberry Pi utility that queries that firmware
[and is included in Raspberry Pi OS][rpi-vcgencmd].

The current [utility source][vcgencmd-source] opens `/dev/vcio_gencmd` and
falls back to `/dev/vcio`. Raspberry Pi OS restricts the mailbox interface to
the `video` group, so the systemd unit conditionally gives the service process
that supplementary group when `vcgencmd` is installed.

Official hardware documentation says low-voltage detection circuitry is
present on Raspberry Pi models since the B+ except the Zero range. It reports a
condition below 4.63 V, subject to the documented tolerance
[in the power-supply warnings][rpi-power-warning]. Therefore:

- probe the real interface at runtime;
- omit the capability when the command is missing, and report it unavailable
  when a supported interface fails or returns invalid output;
- do not advertise under-voltage support on original Model A/B boards;
- do not advertise under-voltage support on Zero, Zero W, or Zero 2 W merely
  because `vcgencmd` exists;
- publish the soft-temperature-limit flags only on Pi 3A+/3B+, where the
  [`temp_soft_limit` capability is documented][rpi-config-soft-limit].

Linux `hwmon` standardizes optional voltage values and alarm files, but each
driver decides which channels exist and what they mean
[in the kernel ABI][linux-hwmon]. The Raspberry Pi `raspberrypi-hwmon` driver
exposes only an under-voltage alarm as `in0_lcrit_alarm`; it does not expose the
complete firmware word [in the driver documentation][rpi-hwmon]. A future
generic Linux health feature therefore needs driver-specific adapters, not a
portable interpretation of Raspberry Pi bits.

The [current driver source][rpi-hwmon-source] polls the firmware every two
seconds, requests sticky-bit clearing, logs detected and normalized
transitions, and emits a `hwmon` event. That interface is useful for future
continuous edge capture, but it still cannot distinguish multiple events
inside one polling interval.

## MQTT Entity Model

Home Assistant defines `binary_sensor` device class `problem` as on when a
problem exists and off when the condition is normal
[in its entity documentation][ha-binary-sensor]. All entities below should use
the existing host device identity and be diagnostic entities.

| Priority | Entity | Semantics |
| --- | --- | --- |
| 1 | Raw throttle flag sensor | Lowercase hexadecimal word for diagnosis |
| 1 | Current under-voltage binary sensor | Bit 0, `problem` |
| 1 | Under-voltage history binary sensor | Bit 16 firmware snapshot |
| 1 | Current/history cap binary sensors | Bits 1 and 17, `problem` |
| 1 | Current/history throttle binary sensors | Bits 2 and 18, `problem` |
| 1 | Current/history soft-limit binary sensors | Bits 3 and 19, `problem` |
| 1 | Raspberry Pi 5-family input-voltage sensor | PMIC `EXT5V_V`, volts |
| Deferred | Observed event count | Needs continuous kernel-event capture |
| Deferred | Latest detection timestamp | Needs continuous kernel-event capture |
| Deferred | Stateless under-voltage event | Needs continuous kernel-event capture |

The priority 1 flags come from one `get_throttled` firmware sample. The raw word
makes unexpected combinations diagnosable without collapsing distinct causes;
the Raspberry Pi 5-family voltage is a separate direct PMIC ADC sample.

The deferred set requires explicit semantics:

- the firmware supplies no count or timestamp;
- polling can miss multiple events between samples;
- a newly set history bit proves at least one event, not how many;
- `raspberrypi-hwmon` can clear the history bits before the agent samples them.

The periodic collector therefore publishes only the direct firmware snapshot.
Count, timestamp, and stateless-event entities are deferred until the agent has
a continuous kernel-event source.

If continuous edge capture is later added, Home Assistant supports a
[`total_increasing` sensor][ha-sensor], a timestamp sensor, and a stateless
[MQTT event entity][ha-mqtt-event]. MQTT event messages are a better one-shot
automation source than a synthetic binary pulse, and Home Assistant discards
replayed retained event messages.

## Alerting

Home Assistant should be the alert authority:

1. Trigger an automation when the current under-voltage binary sensor turns on.
2. Optionally use the [Alert integration][ha-alert] on the same
   under-voltage binary sensor for repeated, acknowledgeable notifications
   until voltage normalizes.
3. Deliver the notification to Apple devices through the Home Assistant
   Companion app.

Apple Home should be optional presentation, not the primary alert path. Apple
supports notifications only for certain accessory types
[in its Home documentation][apple-home-notifications]. Home Assistant's
HomeKit Bridge does not map the `problem` device class natively; unsupported
binary sensors default to occupancy, and diagnostic entities are excluded by
default [in the bridge documentation][ha-homekit]. Mapping under-voltage to
occupancy, smoke, or leak would be misleading.

## Supply Voltage

`get_throttled` contains status flags only. The documented `measure_volts`
targets are internal core and SDRAM rails, not the input 5 V rail
[in the utility documentation][rpi-measure-volts].

The broader statement that every Pi needs an external ADC for input voltage is
not universal. Current Raspberry Pi documentation says supported PMIC ADCs can
report `EXT5V_V` through `vcgencmd pmic_read_adc`
[in the power-supply documentation][rpi-pmic-adc]. The implemented Raspberry Pi
5-family collector, including Raspberry Pi 500 device-tree identifiers, runs
`vcgencmd pmic_read_adc EXT5V_V`, accepts a response such as
`EXT5V_V volt(24)=5.11746000V`, and publishes the value in volts with millivolt
precision. Invalid reads report unavailable. Devices without that PMIC
exposure still require external measurement hardware for actual rail voltage.

The ADC measures supply voltage. It does not provide the current or total power
consumed by USB devices or other hardware connected directly to the 5 V rail.

## Sources

- [Raspberry Pi OS: `vcgencmd` and `get_throttled`][rpi-get-throttled]
- [Official `vcgencmd` manual][vcgencmd-manpage]
- [Raspberry Pi hardware power-supply warnings][rpi-power-warning]
- [Linux `hwmon` sysfs interface][linux-hwmon]
- [Raspberry Pi `hwmon` driver][rpi-hwmon]
- [Home Assistant MQTT and entity documentation][ha-mqtt-event]
- [Home Assistant Alert integration][ha-alert]
- [Home Assistant HomeKit Bridge][ha-homekit]
- [Apple Home accessory notifications][apple-home-notifications]

[apple-home-notifications]: https://support.apple.com/105042
[ha-alert]: https://www.home-assistant.io/integrations/alert/
[ha-binary-sensor]: https://developers.home-assistant.io/docs/core/entity/binary-sensor/#available-device-classes
[ha-homekit]: https://www.home-assistant.io/integrations/homekit/#supported-integrations
[ha-mqtt-event]: https://www.home-assistant.io/integrations/event.mqtt/
[ha-sensor]: https://developers.home-assistant.io/docs/core/entity/sensor/#long-term-statistics
[linux-hwmon]: https://docs.kernel.org/hwmon/sysfs-interface.html
[rpi-get-throttled]: https://www.raspberrypi.com/documentation/computers/os.html#get-throttled
[rpi-hwmon]: https://docs.kernel.org/hwmon/raspberrypi-hwmon.html
[rpi-hwmon-source]: https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/hwmon/raspberrypi-hwmon.c#L27-L112
[rpi-measure-volts]: https://www.raspberrypi.com/documentation/computers/os.html#measure-volts
[rpi-pmic-adc]: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supplies-and-raspberry-pi-os
[rpi-power-warning]: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply-warnings
[rpi-config-soft-limit]: https://www.raspberrypi.com/documentation/computers/config_txt.html#overclocking-options
[rpi-sticky]: https://forums.raspberrypi.com/viewtopic.php?t=377392#p2269309
[rpi-thermal]: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#frequency-management-and-thermal-control
[rpi-vcgencmd]: https://www.raspberrypi.com/documentation/computers/os.html#vcgencmd
[vcgencmd-manpage]: https://github.com/raspberrypi/utils/blob/master/vcgencmd/vcgencmd.1#L53-L90
[vcgencmd-source]: https://github.com/raspberrypi/utils/blob/master/vcgencmd/vcgencmd.c
