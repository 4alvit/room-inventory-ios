# Device build and App Store handoff

The public preview package is an unsigned **Simulator** build. It cannot be
installed on a physical iPhone or uploaded to App Store Connect. Keep device
archives, export directories and any provisioning material outside tracked source.

## Check device compilation without an account

After generating the project, an unsigned generic-device archive can check the
`iphoneos` compilation path and archive contents without signing in or changing
Apple account settings:

```bash
xcodegen_binary="$(python3 scripts/install-xcodegen.py)"
"$xcodegen_binary" generate --spec project.yml
xcodebuild -project RoomInventory.xcodeproj -scheme RoomInventory \
  -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath .build/DeviceRelease \
  -archivePath .build/RoomInventory-unsigned.xcarchive \
  CODE_SIGNING_ALLOWED=NO archive
```

Record the exact commit and `xcodebuild -version`. Inspect the archived app's
bundle identifier, version, `iPhoneOS` platform, arm64 executable, icon and privacy
manifest. Absence of a distribution signature or provisioning profile is expected
for this check. It establishes compilation only; it does not establish device
execution, entitlements, signing validity, upload acceptance or release readiness.

## Authorized owner handoff

1. Supply the enrolled developer team and confirm ownership of
   `com.alvit.roominventory`. An authorized human completes agreements and any
   membership/payment/banking/tax actions.
2. Configure the team/signing in Xcode using the owner's credentials. Do not put
   signing keys or profiles in this repository or public release artifacts.
3. Configure the App Store Connect app and non-consumable
   `com.alvit.roominventory.pro`. Select real availability and pricing; the local
   USD 19.99 StoreKit price is only a test fixture.
4. Reconcile [submission copy](app-store-submission.md), real public privacy/support
   URLs, age rating, export compliance and disclosures with the exact candidate.
5. Build a fresh signed Release archive from that reviewed source, then validate
   and distribute it through the authorized Xcode/App Store Connect workflow.
   Do not reuse the unsigned archive as if it were signed.
6. Run the [device and StoreKit acceptance checks](release-checklist.md) on the
   signed candidate and TestFlight. Retain results for the exact archive/source.
   An unsigned build and local test transactions do not close these gates.

The repository currently has no automatic upload step. Upload, review submission
and storefront publication are separate operations with their own observed results.
