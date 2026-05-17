#!/usr/bin/env sh
set -eu

LABEL="com.marcomc.mac-mqtt-energy"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
GUI_DOMAIN="gui/$(id -u)"

if launchctl print "${GUI_DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${GUI_DOMAIN}/${LABEL}"
fi

rm -f "${PLIST_PATH}"

echo "Stopped and removed ${LABEL}"
