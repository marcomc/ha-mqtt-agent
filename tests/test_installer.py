from __future__ import annotations

import pytest

from ha_mqtt_agent.installer import (
    LINUX_BINARY_PATH,
    LINUX_CONFIG_PATH,
    LINUX_SERVICE_USER,
    LINUX_STATE_PATH,
    optional_package_install_command,
    plan_linux_install,
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
