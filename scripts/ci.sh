#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1:-full}"
case "$mode" in full|--static|--build-only) ;; *) printf '%s\n' 'Usage: scripts/ci.sh [--static|--build-only]' >&2; exit 2 ;; esac
python3 scripts/verify-source.py
python3 scripts/workflow_contracts.py
python3 -m unittest discover -s .github/workflow-tests -p 'test_*.py'
python3 -m unittest discover -s .github/release-tests -p 'test_*.py'
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
if [[ "$mode" == '--static' ]]; then
  printf '%s\n' 'Static tooling checks passed. Swift builds, app tests and CodeQL were not run.'
  exit 0
fi
swift test --package-path Core
bash scripts/build-simulator.sh Debug
if [[ "$mode" == '--build-only' ]]; then
  printf '%s\n' 'Core tests and generic Simulator build passed. App tests and CodeQL were not run.'
  exit 0
fi
bash scripts/test-simulator.sh
printf '%s\n' 'Core tests, generic Simulator build and app tests passed. Hosted CodeQL remains a separate required check.'
