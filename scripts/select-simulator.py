#!/usr/bin/env python3
"""Select an available iPhone Simulator running iOS 17+, without creating devices."""
from __future__ import annotations

import json
import os
import re
import subprocess


def main() -> None:
    inventory = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devices", "available", "--json"], text=True))
    candidates = []
    for runtime, devices in inventory.get("devices", {}).items():
        match = re.search(r"\.iOS-(\d+)(?:-(\d+))?", runtime)
        if not match or int(match[1]) < 17:
            continue
        for device in devices:
            if device.get("isAvailable") and device.get("name", "").startswith("iPhone"):
                candidates.append((device.get("state") == "Booted", int(match[1]), int(match[2] or 0), device["udid"]))
    requested = os.environ.get("SIMULATOR_UDID")
    if requested:
        if not any(device[3] == requested for device in candidates):
            raise SystemExit("SIMULATOR_UDID does not identify an available iPhone with iOS 17+")
        print(requested)
    elif candidates:
        print(sorted(candidates, reverse=True)[0][3])
    else:
        raise SystemExit("No iOS 17+ iPhone Simulator is installed. Install an iOS runtime in Xcode Settings > Components. App tests have NOT run.")


if __name__ == "__main__":
    main()
