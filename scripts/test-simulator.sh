#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

simulator_id="$(python3 scripts/select-simulator.py)"
derived_data="${1:-.build/SimulatorTests}"
xcodegen_binary="$(python3 scripts/install-xcodegen.py)"
"$xcodegen_binary" generate --spec project.yml
result_prefix=".build/TestResults-$(date -u +%Y%m%dT%H%M%SZ)-$$"
test_arguments=(
  -project RoomInventory.xcodeproj
  -scheme RoomInventory
  -configuration Debug
  -destination "platform=iOS Simulator,id=$simulator_id"
  -derivedDataPath "$derived_data"
  -parallel-testing-enabled NO
  CODE_SIGNING_ALLOWED=NO
)

# Fail before starting the longer UI scenarios if an app unit test fails.
# Both invocations keep the scheme's test plan and reuse the same build products.
xcodebuild "${test_arguments[@]}" \
  -only-testing:RoomInventoryTests \
  -resultBundlePath "${result_prefix}-Unit.xcresult" \
  test

# Exclude only the unit target: every other target in the plan still runs,
# including targets added later. A UI failure remains fatal under set -e.
xcodebuild "${test_arguments[@]}" \
  -skip-testing:RoomInventoryTests \
  -resultBundlePath "${result_prefix}-UI.xcresult" \
  test
