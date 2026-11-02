#!/usr/bin/env python3
"""Select an iPhone matching the active SDK or explicit runtime/device pins."""
from __future__ import annotations

import json
import os
import re
import subprocess


def select_simulator(inventory: dict, sdk_version: str | None, requested: str | None = None,
                     runtime_version: str | None = None, device_type: str | None = None) -> str:
    """Keep automatic tests on the requested runtime line without silent fallback."""
    if not isinstance(inventory, dict) or not isinstance(inventory.get("devices"), dict):
        raise ValueError("Invalid simctl device inventory")
    if device_type is not None and not re.fullmatch(
            r"com\.apple\.CoreSimulator\.SimDeviceType\.iPhone-[A-Za-z0-9][A-Za-z0-9-]*", device_type):
        raise ValueError("SIMULATOR_DEVICE_TYPE must be a full iPhone device type identifier, "
                         "such as com.apple.CoreSimulator.SimDeviceType.iPhone-16e")
    device_selection = f" and SIMULATOR_DEVICE_TYPE {device_type}" if device_type is not None else ""
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
                    and (device_type is None or device.get("deviceTypeIdentifier") == device_type)
                    and isinstance(udid, str) and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", udid)):
                candidates.append((version, device.get("state") == "Booted", udid))
    if requested and runtime_version is None:
        if not any(device[2] == requested for device in candidates):
            raise ValueError("SIMULATOR_UDID does not identify an available iPhone with iOS 17+" + device_selection)
        return requested
    sdk = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", sdk_version or "")
    if not sdk:
        raise ValueError("Cannot determine the active iOS Simulator SDK version")
    version_line = (int(sdk[1]), int(sdk[2]))
    selection = f"SDK {sdk[1]}.{sdk[2]}"
    if runtime_version is not None:
        pinned = re.fullmatch(r"([1-9]\d*)\.(0|[1-9]\d*)", runtime_version)
        if not pinned or int(pinned[1]) < 17:
            raise ValueError("SIMULATOR_RUNTIME_VERSION must be an iOS 17+ major.minor version, such as 26.2")
        pinned_line = (int(pinned[1]), int(pinned[2]))
        if pinned_line > version_line:
            raise ValueError(f"SIMULATOR_RUNTIME_VERSION {runtime_version} is newer than active {selection}")
        version_line = pinned_line
        selection = f"SIMULATOR_RUNTIME_VERSION {runtime_version}"
    selection += device_selection
    matching = [device for device in candidates if device[0][:2] == version_line]
    if requested:
        if not any(device[2] == requested for device in matching):
            raise ValueError(f"SIMULATOR_UDID does not identify an available iPhone matching {selection}")
        return requested
    if not matching:
        raise ValueError(
            f"No available iOS 17+ iPhone Simulator matches {selection}. "
            "Install the runtime and create a matching iPhone in Xcode, or explicitly change the requested destination"
        )
    # A booted older patch must not outrank a newer patch on the matching line.
    return max(matching)[2]


def main() -> None:
    requested = os.environ.get("SIMULATOR_UDID")
    runtime_version = os.environ.get("SIMULATOR_RUNTIME_VERSION")
    device_type = os.environ.get("SIMULATOR_DEVICE_TYPE")
    try:
        sdk = None if requested and runtime_version is None else subprocess.check_output(
            ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"],
            text=True, stdin=subprocess.DEVNULL, timeout=30,
        ).strip()
        inventory = json.loads(subprocess.check_output(
            ["xcrun", "simctl", "list", "devices", "available", "--json"],
            text=True, stdin=subprocess.DEVNULL, timeout=60,
        ))
        print(select_simulator(inventory, sdk, requested, runtime_version, device_type))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Simulator selection failed: {error}. App tests have NOT run.") from error


if __name__ == "__main__":
    main()
