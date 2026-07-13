from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from ha_mqtt_agent.config import load_config
from ha_mqtt_agent.installer import (
    LINUX_BINARY_PATH,
    LINUX_CONFIG_PATH,
    LINUX_SERVICE_USER,
    LINUX_STATE_PATH,
    InstallConfigFacts,
    InstallNetworkFacts,
    detect_install_config_facts,
    optional_package_install_command,
    plan_linux_install,
    render_install_config,
    write_install_config,
)
from ha_mqtt_agent.network import (
    ARP_PATH,
    IFCONFIG_PATH,
    NETWORKSETUP_PATH,
    ROUTE_PATH,
    SYSTEM_PROFILER_PATH,
    CommandResult,
)
from ha_mqtt_agent.providers.linux import (
    IP_COMMAND,
    NMCLI_COMMAND,
    LinuxCommandResult,
    LinuxProvider,
)


class FakeRunner:
    def __init__(self, results: dict[tuple[str, ...], CommandResult | None]) -> None:
        self.results = results
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        timeout_seconds: float,
    ) -> CommandResult | None:
        _ = timeout_seconds
        key = tuple(command)
        self.commands.append(key)
        return self.results.get(key)


class FakeLinuxRunner:
    def __init__(self, results: dict[tuple[str, ...], LinuxCommandResult | None]) -> None:
        self.results = results
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        timeout_seconds: float,
    ) -> LinuxCommandResult | None:
        _ = timeout_seconds
        key = tuple(command)
        self.commands.append(key)
        return self.results.get(key)


def test_systemd_installer_help_exposes_deferred_start_mode() -> None:
    result = subprocess.run(
        ["sh", "scripts/install-systemd-service.sh", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--no-start" in result.stdout


def test_systemd_installer_deferred_start_guards_service_activation() -> None:
    script = Path("scripts/install-systemd-service.sh").read_text(encoding="utf-8")

    assert "--no-start)\n      START_SERVICE=0" in script
    activation_guard = script.index('if [ "${START_SERVICE}" -eq 1 ]; then')
    enable_service = script.index('systemctl enable "${SERVICE_NAME}"')
    restart_service = script.index('systemctl restart "${SERVICE_NAME}"')
    no_start_result = script.index(
        'echo "Installed ${SERVICE_NAME} without enabling or restarting it"'
    )

    assert activation_guard < enable_service < restart_service < no_start_result


def test_systemd_installer_interactive_prompt_is_not_captured_as_package() -> None:
    script = Path("scripts/install-systemd-service.sh").read_text(encoding="utf-8")

    assert (
        "printf 'Install optional sensor packages (%s)? [y/N] ' "
        '"${RECOMMENDED_OPTIONAL_PACKAGES}" >&2'
    ) in script


def test_systemd_installer_renders_host_aware_config_template() -> None:
    script = Path("scripts/install-systemd-service.sh").read_text(encoding="utf-8")

    assert '"${APP_PYTHON}" -m ha_mqtt_agent.installer render-config' in script
    assert '--state-path "${STATE_PATH}"' in script


def test_systemd_installer_grants_vcgencmd_device_access_when_available() -> None:
    script = Path("scripts/install-systemd-service.sh").read_text(encoding="utf-8")

    assert "command -v vcgencmd >/dev/null 2>&1" in script
    assert "getent group video >/dev/null 2>&1" in script
    assert 'SUPPLEMENTARY_GROUPS_DIRECTIVE="SupplementaryGroups=video"' in script
    assert "${SUPPLEMENTARY_GROUPS_DIRECTIVE}" in script
    assert "usermod --append" not in script


def test_systemd_installer_restarts_service_after_unit_update() -> None:
    script = Path("scripts/install-systemd-service.sh").read_text(encoding="utf-8")

    daemon_reload = "run_root systemctl daemon-reload"
    enable = 'run_root systemctl enable "${SERVICE_NAME}"'
    restart = 'run_root systemctl restart "${SERVICE_NAME}"'

    assert "systemctl enable --now" not in script
    assert script.index(daemon_reload) < script.index(enable) < script.index(restart)


def test_makefile_install_config_uses_renderer_without_overwriting_existing_config() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "ha_mqtt_agent.installer render-config" in makefile
    assert 'if [ ! -f "$(CONFIG_PATH)" ]; then' in makefile


def test_makefile_macos_install_runs_install_steps_sequentially() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "install-macos: check-install-deps ## Install the full user LaunchAgent" in makefile
    assert "$(MAKE) install-cli" in makefile
    assert "$(MAKE) install-config" in makefile
    assert "$(MAKE) install-wifi-helper" in makefile


def test_makefile_linux_restart_agent_works_without_sudo_when_root() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert re.search(
        r'Linux\) if \[ "\$\$\(id -u\)" -eq 0 \]; '
        r"then systemctl restart ha-mqtt-agent; "
        r"else sudo systemctl restart ha-mqtt-agent; fi ;;",
        makefile,
    )


def test_linux_install_plan_uses_systemd_service_paths_without_optional_packages() -> None:
    plan = plan_linux_install(package_manager="apt")

    assert plan.service_user == LINUX_SERVICE_USER
    assert plan.config_path == LINUX_CONFIG_PATH
    assert plan.state_path == LINUX_STATE_PATH
    assert plan.binary_path == LINUX_BINARY_PATH
    assert plan.package_manager == "apt"
    assert plan.optional_packages == ()


def test_linux_install_plan_selects_recommended_optional_packages_when_enabled() -> None:
    plan = plan_linux_install(package_manager="dnf", enable_optional_sensors=True)

    assert plan.optional_packages == ("iw", "lm-sensors", "upower")


def test_linux_install_plan_accepts_explicit_optional_package_list() -> None:
    plan = plan_linux_install(package_manager="pacman", optional_packages=("iw", "upower"))

    assert plan.optional_packages == ("iw", "upower")


def test_linux_install_plan_rejects_unknown_optional_packages() -> None:
    with pytest.raises(ValueError, match="unknown optional packages: htop"):
        plan_linux_install(package_manager="apt", optional_packages=("htop",))


def test_optional_package_install_commands_are_package_manager_specific() -> None:
    assert optional_package_install_command("apt", ("iw",)) == ("apt-get", "install", "-y", "iw")
    assert optional_package_install_command("dnf", ("iw",)) == ("dnf", "install", "-y", "iw")
    assert optional_package_install_command("pacman", ("iw",)) == (
        "pacman",
        "-S",
        "--needed",
        "--noconfirm",
        "iw",
    )


def test_render_install_config_prefills_identity_network_and_state_path(tmp_path: Path) -> None:
    facts = InstallConfigFacts(
        hostname="rpi",
        device_id="rpi",
        device_name="rpi",
        mqtt_client_id="ha-mqtt-agent-rpi",
        network=InstallNetworkFacts(
            home_ssids=("Home WiFi",),
            home_ipv4_cidrs=("192.0.2.0/24",),
            home_gateways=("192.0.2.1",),
            home_bssids=("02:00:00:00:00:40",),
            home_gateway_macs=("02:00:00:00:00:01",),
        ),
    )
    rendered = render_install_config(
        Path("config.toml.example").read_text(encoding="utf-8"),
        facts=facts,
        state_path="/var/lib/ha-mqtt-agent/state.json",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(rendered, encoding="utf-8")

    config = load_config(config_path)

    assert config.device_id == "rpi"
    assert config.device_name == "rpi"
    assert config.mqtt_client_id == "ha-mqtt-agent-rpi"
    assert config.resolved_mqtt_client_id == "ha-mqtt-agent-rpi"
    assert config.home_ssids == ("Home WiFi",)
    assert config.home_ipv4_cidrs == ("192.0.2.0/24",)
    assert config.home_gateways == ("192.0.2.1",)
    assert config.home_bssids == ("02:00:00:00:00:40",)
    assert config.home_gateway_macs == ("02:00:00:00:00:01",)
    assert config.state_path == Path("/var/lib/ha-mqtt-agent/state.json")


def test_write_install_config_uses_private_file_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template_path = tmp_path / "template.toml"
    output_path = tmp_path / "config.toml"
    template_path.write_text(
        Path("config.toml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ha_mqtt_agent.installer.detect_install_config_facts",
        lambda: InstallConfigFacts(
            hostname="rpi",
            device_id="rpi",
            device_name="rpi",
            mqtt_client_id="ha-mqtt-agent-rpi",
        ),
    )

    write_install_config(template_path=template_path, output_path=output_path)

    assert output_path.stat().st_mode & 0o777 == 0o600


def test_detect_install_config_facts_reads_linux_host_network(tmp_path: Path) -> None:
    runner = FakeLinuxRunner(
        {
            (IP_COMMAND, "-j", "addr", "show"): LinuxCommandResult(
                stdout=(
                    '[{"ifname":"lo","operstate":"UNKNOWN",'
                    '"addr_info":[{"family":"inet","local":"127.0.0.1","prefixlen":8}]},'
                    '{"ifname":"wlan0","operstate":"UP",'
                    '"addr_info":[{"family":"inet","local":"192.0.2.63","prefixlen":24}]}]'
                ),
                returncode=0,
            ),
            (IP_COMMAND, "-j", "route", "show", "default"): LinuxCommandResult(
                stdout='[{"gateway":"192.0.2.1","dev":"wlan0"}]',
                returncode=0,
            ),
            (IP_COMMAND, "neigh", "show", "192.0.2.1"): LinuxCommandResult(
                stdout="192.0.2.1 dev wlan0 lladdr 02:00:00:00:00:01 REACHABLE\n",
                returncode=0,
            ),
            (
                NMCLI_COMMAND,
                "-t",
                "-f",
                "DEVICE,TYPE,STATE,CONNECTION",
                "dev",
                "status",
            ): LinuxCommandResult(stdout="wlan0:wifi:connected:Home WiFi\n", returncode=0),
            (
                NMCLI_COMMAND,
                "-t",
                "-f",
                "ACTIVE,SSID,BSSID,SIGNAL",
                "dev",
                "wifi",
                "list",
                "ifname",
                "wlan0",
            ): LinuxCommandResult(
                stdout="yes:Home WiFi:02\\:00\\:00\\:00\\:00\\:40:84\n",
                returncode=0,
            ),
        }
    )
    provider = LinuxProvider(
        root=tmp_path,
        command_runner=runner,
        available_commands=frozenset({IP_COMMAND, NMCLI_COMMAND}),
    )

    facts = detect_install_config_facts(
        system_name="Linux",
        hostname="rpi.local",
        linux_provider=provider,
    )

    assert facts.device_id == "rpi"
    assert facts.device_name == "rpi"
    assert facts.mqtt_client_id == "ha-mqtt-agent-rpi"
    assert facts.network.home_ssids == ("Home WiFi",)
    assert facts.network.home_bssids == ("02:00:00:00:00:40",)
    assert facts.network.home_gateways == ("192.0.2.1",)
    assert facts.network.home_gateway_macs == ("02:00:00:00:00:01",)
    assert facts.network.home_ipv4_cidrs == ("192.0.2.0/24",)


def test_detect_install_config_facts_reads_macos_host_network() -> None:
    runner = FakeRunner(
        {
            (NETWORKSETUP_PATH, "-listallhardwareports"): CommandResult(
                stdout="""
                Hardware Port: Wi-Fi
                Device: en0
                Ethernet Address: aa:bb:cc:dd:ee:ff
                """,
                returncode=0,
            ),
            (NETWORKSETUP_PATH, "-getairportnetwork", "en0"): CommandResult(
                stdout="Current Wi-Fi Network: Office WiFi\n",
                returncode=0,
            ),
            (SYSTEM_PROFILER_PATH, "SPAirPortDataType", "-json"): CommandResult(
                stdout="""
                {
                  "SPAirPortDataType": [
                    {
                      "spairport_airport_interfaces": [
                        {
                          "_name": "en0",
                          "spairport_current_network_information": {
                            "_name": "Office WiFi",
                            "spairport_bssid": "00:11:22:33:44:55",
                            "spairport_signal_noise": "-55 dBm / -91 dBm"
                          }
                        }
                      ]
                    }
                  ]
                }
                """,
                returncode=0,
            ),
            (IFCONFIG_PATH, "en0"): CommandResult(
                stdout="""
                en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
                    inet 10.0.0.23 netmask 0xffffff00 broadcast 10.0.0.255
                    status: active
                """,
                returncode=0,
            ),
            (ROUTE_PATH, "-n", "get", "default"): CommandResult(
                stdout="""
                   route to: default
                destination: default
                       mask: default
                    gateway: 10.0.0.1
                  interface: en0
                """,
                returncode=0,
            ),
            (ARP_PATH, "-n", "10.0.0.1"): CommandResult(
                stdout="? (10.0.0.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]\n",
                returncode=0,
            ),
        }
    )

    facts = detect_install_config_facts(
        system_name="Darwin",
        hostname="Work-Mac.local",
        command_runner=runner,
    )

    assert facts.device_id == "work-mac"
    assert facts.device_name == "Work-Mac"
    assert facts.mqtt_client_id == "ha-mqtt-agent-work-mac"
    assert facts.network.home_ssids == ("Office WiFi",)
    assert facts.network.home_bssids == ("00:11:22:33:44:55",)
    assert facts.network.home_gateways == ("10.0.0.1",)
    assert facts.network.home_gateway_macs == ("aa:bb:cc:dd:ee:ff",)
    assert facts.network.home_ipv4_cidrs == ("10.0.0.0/24",)
