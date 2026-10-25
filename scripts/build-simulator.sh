#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

configuration="${1:-Debug}"
case "$configuration" in Debug|Release) ;; *) printf '%s\n' 'Expected Debug or Release' >&2; exit 2 ;; esac
derived_data="${2:-.build/Simulator}"
build_settings=(CODE_SIGNING_ALLOWED=NO ONLY_ACTIVE_ARCH=NO)
if [[ "$configuration" == Release ]]; then
  # Preview binaries must not retain coverage data or local build paths.
  build_settings+=(ENABLE_CODE_COVERAGE=NO DEPLOYMENT_POSTPROCESSING=YES STRIP_INSTALLED_PRODUCT=YES)
fi
xcodegen_binary="$(python3 scripts/install-xcodegen.py)"
"$xcodegen_binary" generate --spec project.yml
xcodebuild \
  -project RoomInventory.xcodeproj \
  -scheme RoomInventory \
  -configuration "$configuration" \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$derived_data" \
  "${build_settings[@]}" \
  build
