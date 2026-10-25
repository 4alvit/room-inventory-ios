#!/usr/bin/env python3
"""Check source metadata and public release boundaries without invoking Xcode."""
from __future__ import annotations

import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    version = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
        raise SystemExit("VERSION must be a numeric X.Y.Z base version")
    project = yaml.safe_load((ROOT / "project.yml").read_text())
    if project["settings"]["base"]["MARKETING_VERSION"] != version:
        raise SystemExit("project.yml MARKETING_VERSION and VERSION differ")
    policy = json.loads((ROOT / ".release-policy.json").read_text())
    if policy["repository"] != "4alvit/room-inventory-ios" or policy["version_file"] != "VERSION":
        raise SystemExit("Unexpected release repository or version source")
    for path in ROOT.joinpath("App").rglob("*.plist"):
        with path.open("rb") as stream:
            plistlib.load(stream)
    for path in ROOT.joinpath("App").rglob("*.xcprivacy"):
        with path.open("rb") as stream:
            plistlib.load(stream)
    store = json.loads((ROOT / "App/RoomInventory.storekit").read_text())
    if not any(product.get("type") == "NonConsumable" for product in store["products"]):
        raise SystemExit("StoreKit fixture must contain a non-consumable product")
    plans = project["schemes"]["RoomInventory"]["test"].get("testPlans", [])
    if not any(plan.get("path") == "RoomInventory.xctestplan" and plan.get("defaultPlan") for plan in plans):
        raise SystemExit("Hosted tests require the checked-in test plan")
    plan = json.loads((ROOT / "RoomInventory.xctestplan").read_text())
    if {target["target"]["name"] for target in plan["testTargets"]} != {"RoomInventoryTests", "RoomInventoryUITests"}:
        raise SystemExit("The test plan must include both hosted unit and UI tests")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    forbidden = (".p12", ".p8", ".mobileprovision", ".tfstate", ".roominventory", ".ipa")
    for name in tracked:
        if name.endswith(forbidden) or any(part in {"DerivedData", "release-dist", "xcuserdata"} for part in Path(name).parts):
            raise SystemExit(f"Private/generated file must not be tracked: {name}")
    subprocess.run([sys.executable, str(ROOT / "scripts/verify-localizations.py"), "--root", str(ROOT)], check=True)
    print("Source metadata and tracked-file boundaries passed")


if __name__ == "__main__":
    main()
