from __future__ import annotations

import plistlib
import tomllib
from pathlib import Path
from typing import Any, cast

from ha_mqtt_agent import __version__


def test_release_version_metadata_is_synchronized() -> None:
    expected_version = "0.3.0"
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    helper = cast(
        dict[str, Any],
        plistlib.loads(Path("macos/WifiHelper/Info.plist").read_bytes()),
    )
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert __version__ == expected_version
    assert project["project"]["version"] == expected_version
    assert helper["CFBundleShortVersionString"] == expected_version
    assert helper["CFBundleVersion"] == expected_version
    assert f"## [{expected_version}] - " in changelog
