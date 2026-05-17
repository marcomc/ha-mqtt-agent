#!/usr/bin/env sh
set -eu

LABEL="com.marcomc.mac-mqtt-energy"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/mac-mqtt-energy"
PROGRAM="${HOME}/.local/bin/mac-mqtt-energy"
GUI_DOMAIN="gui/$(id -u)"

if [ ! -x "${PROGRAM}" ]; then
  echo "Missing executable at ${PROGRAM}" >&2
  echo "Run 'make install' first." >&2
  exit 1
fi

mkdir -p "${PLIST_DIR}" "${LOG_DIR}"

if launchctl print "${GUI_DOMAIN}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "${GUI_DOMAIN}/${LABEL}"
fi

cat >"${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PROGRAM}</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/err.log</string>
  <key>WorkingDirectory</key>
  <string>${HOME}</string>
</dict>
</plist>
EOF

plutil -lint "${PLIST_PATH}" >/dev/null
launchctl bootstrap "${GUI_DOMAIN}" "${PLIST_PATH}"
launchctl kickstart -k "${GUI_DOMAIN}/${LABEL}"

echo "Installed and started ${LABEL}"
echo "Plist: ${PLIST_PATH}"
echo "Logs: ${LOG_DIR}"
