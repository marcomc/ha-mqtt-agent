"""Installer planning helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Literal

LINUX_SERVICE_NAME = "ha-mqtt-agent"
LINUX_SERVICE_USER = "ha-mqtt-agent"
LINUX_CONFIG_PATH = "/etc/ha-mqtt-agent/config.toml"
LINUX_STATE_PATH = "/var/lib/ha-mqtt-agent/state.json"
LINUX_APP_HOME = "/opt/ha-mqtt-agent"
LINUX_BINARY_PATH = "/usr/local/bin/ha-mqtt-agent"
KNOWN_LINUX_OPTIONAL_PACKAGES = frozenset({"iw", "lm-sensors", "upower"})
RECOMMENDED_LINUX_OPTIONAL_PACKAGES = ("iw", "lm-sensors", "upower")
PackageManager = Literal["apt", "dnf", "pacman"]


@dataclass(frozen=True)
class LinuxInstallPlan:
    service_name: str
    service_user: str
    config_path: str
    state_path: str
    app_home: str
    binary_path: str
    package_manager: PackageManager | None
    optional_packages: tuple[str, ...]


def plan_linux_install(
    *,
    package_manager: PackageManager | None = None,
    enable_optional_sensors: bool = False,
    optional_packages: tuple[str, ...] = (),
) -> LinuxInstallPlan:
    selected_optional = _selected_optional_packages(
        enable_optional_sensors=enable_optional_sensors,
        optional_packages=optional_packages,
    )
    return LinuxInstallPlan(
        service_name=LINUX_SERVICE_NAME,
        service_user=LINUX_SERVICE_USER,
        config_path=LINUX_CONFIG_PATH,
        state_path=LINUX_STATE_PATH,
        app_home=LINUX_APP_HOME,
        binary_path=LINUX_BINARY_PATH,
        package_manager=package_manager or detect_linux_package_manager(),
        optional_packages=selected_optional,
    )


def detect_linux_package_manager() -> PackageManager | None:
    for name in ("apt", "dnf", "pacman"):
        if shutil.which(name) is not None:
            return name
    return None


def optional_package_install_command(
    package_manager: PackageManager,
    packages: tuple[str, ...],
) -> tuple[str, ...]:
    if not packages:
        return ()
    if package_manager == "apt":
        return ("apt-get", "install", "-y", *packages)
    if package_manager == "dnf":
        return ("dnf", "install", "-y", *packages)
    return ("pacman", "-S", "--needed", "--noconfirm", *packages)


def _selected_optional_packages(
    *,
    enable_optional_sensors: bool,
    optional_packages: tuple[str, ...],
) -> tuple[str, ...]:
    unknown = set(optional_packages) - KNOWN_LINUX_OPTIONAL_PACKAGES
    if unknown:
        raise ValueError("unknown optional packages: " + ", ".join(sorted(unknown)))
    if optional_packages:
        return tuple(dict.fromkeys(optional_packages))
    if enable_optional_sensors:
        return RECOMMENDED_LINUX_OPTIONAL_PACKAGES
    return ()
