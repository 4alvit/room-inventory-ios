#!/usr/bin/env python3
"""Select an iPhone matching the active SDK, or an explicit iOS 17+ override."""
from __future__ import annotations

import json
import os
import re
import subprocess


def select_simulator(inventory: dict, sdk_version: str | None, requested: str | None = None) -> str:
    """Keep automatic tests on the SDK's runtime line, never an unrelated booted OS."""
    if not isinstance(inventory, dict) or not isinstance(inventory.get("devices"), dict):
        raise ValueError("Invalid simctl device inventory")
    candidates = []
    for runtime, devices in inventory["devices"].items():
        match = re.fullmatch(r"com\.apple\.CoreSimulator\.SimRuntime\.iOS-(\d+)-(\d+)(?:-(\d+))?", runtime)
        if not match or int(match[1]) < 17 or not isinstance(devices, list):
            continue
        version = (int(match[1]), int(match[2]), int(match[3] or 0))
        for device in devices:
            if not isinstance(device, dict):
                continue
            name, udid = device.get("name"), device.get("udid")
            if (device.get("isAvailable") is True and isinstance(name, str) and name.startswith("iPhone")
                    and isinstance(udid, str) and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", udid)):
                candidates.append((version, device.get("state") == "Booted", udid))
    if requested:
        if not any(device[2] == requested for device in candidates):
            raise ValueError("SIMULATOR_UDID does not identify an available iPhone with iOS 17+")
        return requested
    sdk = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", sdk_version or "")
    if not sdk:
        raise ValueError("Cannot determine the active iOS Simulator SDK version")
    version_line = (int(sdk[1]), int(sdk[2]))
    matching = [device for device in candidates if device[0][:2] == version_line]
    if not matching:
        raise ValueError(
            f"No available iOS 17+ iPhone Simulator matches SDK {sdk[1]}.{sdk[2]}. "
            "Install a matching runtime in Xcode Settings > Components, or set SIMULATOR_UDID for a deliberate override"
        )
    # A booted older patch must not outrank a newer patch on the matching line.
    return max(matching)[2]


def main() -> None:
    requested = os.environ.get("SIMULATOR_UDID")
    try:
        sdk = None if requested else subprocess.check_output(
            ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"],
            text=True, stdin=subprocess.DEVNULL, timeout=30,
        ).strip()
        inventory = json.loads(subprocess.check_output(
            ["xcrun", "simctl", "list", "devices", "available", "--json"],
            text=True, stdin=subprocess.DEVNULL, timeout=60,
        ))
        print(select_simulator(inventory, sdk, requested))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Simulator selection failed: {error}. App tests have NOT run.") from error


if __name__ == "__main__":
    main()
