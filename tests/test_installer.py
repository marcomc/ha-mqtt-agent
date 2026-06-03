from __future__ import annotations

import re
from pathlib import Path

import pytest

from ha_mqtt_agent.installer import (
    LINUX_BINARY_PATH,
    LINUX_CONFIG_PATH,
    LINUX_SERVICE_USER,
    LINUX_STATE_PATH,
    optional_package_install_command,
    plan_linux_install,
)


def test_systemd_installer_interactive_prompt_is_not_captured_as_package() -> None:
    script = Path("scripts/install-systemd-service.sh").read_text(encoding="utf-8")

    assert (
        "printf 'Install optional sensor packages (%s)? [y/N] ' "
        '"${RECOMMENDED_OPTIONAL_PACKAGES}" >&2'
    ) in script


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
