#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

configuration="${1:-Debug}"
case "$configuration" in Debug|Release) ;; *) printf '%s\n' 'Expected Debug or Release' >&2; exit 2 ;; esac
derived_data="${2:-.build/Simulator}"
xcodegen_binary="$(python3 scripts/install-xcodegen.py)"
"$xcodegen_binary" generate --spec project.yml
xcodebuild \
  -project RoomInventory.xcodeproj \
  -scheme RoomInventory \
  -configuration "$configuration" \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$derived_data" \
  CODE_SIGNING_ALLOWED=NO \
  ONLY_ACTIVE_ARCH=NO \
  build
