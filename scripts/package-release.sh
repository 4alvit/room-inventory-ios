#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

release_version="${1:?Expected numeric base version}"
release_channel="${2:?Expected nightly, beta, or rc}"
python3 scripts/package-preview.py prepare "$release_version" "$release_channel"
bash scripts/build-simulator.sh Release .build/ReleaseSimulator
python3 scripts/package-preview.py package "$release_version" "$release_channel"
