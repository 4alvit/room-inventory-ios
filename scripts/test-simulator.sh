#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

simulator_id="$(python3 scripts/select-simulator.py)"
derived_data="${1:-.build/SimulatorTests}"
xcodegen_binary="$(python3 scripts/install-xcodegen.py)"
"$xcodegen_binary" generate --spec project.yml
result_bundle=".build/TestResults-$(date -u +%Y%m%dT%H%M%SZ)-$$.xcresult"
xcodebuild \
  -project RoomInventory.xcodeproj \
  -scheme RoomInventory \
  -configuration Debug \
  -destination "platform=iOS Simulator,id=$simulator_id" \
  -derivedDataPath "$derived_data" \
  -resultBundlePath "$result_bundle" \
  -parallel-testing-enabled NO \
  CODE_SIGNING_ALLOWED=NO \
  test
