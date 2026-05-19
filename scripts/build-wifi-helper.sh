#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
APP_PATH=${1:-"${HOME}/.local/share/ha-mqtt-agent/HaMqttAgentWifiHelper.app"}
EXECUTABLE_NAME="HaMqttAgentWifiHelper"
CONTENTS_DIR="${APP_PATH}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
SOURCE_PATH="${PROJECT_ROOT}/macos/WifiHelper/main.swift"
INFO_PLIST_SOURCE="${PROJECT_ROOT}/macos/WifiHelper/Info.plist"
INFO_PLIST_TARGET="${CONTENTS_DIR}/Info.plist"
ENTITLEMENTS_PATH="${PROJECT_ROOT}/macos/WifiHelper/Entitlements.plist"
SWIFTC=${SWIFTC:-swiftc}

if ! command -v "${SWIFTC}" >/dev/null 2>&1; then
  echo "swiftc not found. Install Xcode Command Line Tools." >&2
  exit 1
fi

if ! command -v codesign >/dev/null 2>&1; then
  echo "codesign not found. Install Xcode Command Line Tools." >&2
  exit 1
fi

rm -rf "${APP_PATH}"
mkdir -p "${MACOS_DIR}"
cp "${INFO_PLIST_SOURCE}" "${INFO_PLIST_TARGET}"

"${SWIFTC}" \
  "${SOURCE_PATH}" \
  -framework CoreLocation \
  -framework CoreWLAN \
  -framework MapKit \
  -o "${MACOS_DIR}/${EXECUTABLE_NAME}"

plutil -lint "${INFO_PLIST_TARGET}" >/dev/null
codesign --force --deep --sign - --entitlements "${ENTITLEMENTS_PATH}" "${APP_PATH}" >/dev/null

echo "Installed Wi-Fi helper app: ${APP_PATH}"
