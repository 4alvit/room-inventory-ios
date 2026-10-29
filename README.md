# Room Inventory

Create a room inventory from photos of belongings, product labels and receipts.
Review text recognized on-device, keep originals connected to each item, and export
a PDF, CSV, original-file package or restorable backup. No account or application
server is required.

**Development preview for iOS 17 and later.** This repository is not an App Store
listing. GitHub preview artifacts contain source and an **unsigned iOS Simulator
app**, not an installable iPhone IPA. Build/test evidence and release status belong
to the exact commit or GitHub release being inspected; source availability alone
does not mean a release passed validation.

## Product scope

- Homes, rooms and items with model, serial number, purchase amount/date and notes.
- Local search across homes by item name, model, serial number, notes and room.
- Camera and selected photo/file import for photos, labels and receipt images.
- On-device OCR suggestions require explicit review before they update item fields.
- Missing-material prompts help identify incomplete item records.
- Local originals, checksum verification, bounded backup and transactional restore.
- PDF/CSV export and ZIP of originals with stable item/file associations.
- StoreKit 2 non-consumable Pro entitlement, purchase restoration and revocation handling.

Free access allows **one room and ten items across the whole inventory**. Pro permits more rooms/items, imports up to ten images per batch into one item,
and customizes PDF reports by room and included detail fields. Existing records, ordinary exports and backup
restore remain available without Pro, including when a restored inventory exceeds
the Free limits. The local StoreKit configuration uses a **USD 19.99 test price**;
it does not collect money. Real product availability, local prices and purchases
require App Store Connect setup. The UI obtains prices from StoreKit.

No 3D scanning, shared family editing, hosted sync, automatic valuation or insurance
approval is promised. Batch import adds images to the current item; it does not
create an item for each photo or apply OCR automatically across the batch. An inventory export is a record of user-supplied information, not an appraisal
or guarantee of coverage or payment.

## Build and test

Use macOS with Xcode supporting Swift 6, an iOS 17+ Simulator runtime, and Python
3.11+. The scripts install **XcodeGen 2.46.0** from its digest-verified official release
into ignored `.build/` storage. No Apple Developer membership is needed for Simulator
builds. Install an iOS runtime from Xcode Settings → Components if none is available.

```bash
python3 -m venv .build/venv
source .build/venv/bin/activate
python3 -m pip install --require-hashes --only-binary=:all: -r .github/requirements-workflow-contracts.txt
bash scripts/ci.sh
```

The full check runs source/release-tooling contracts, Core tests, a generic Simulator
build, and app unit/UI tests on an available iPhone Simulator. Set `SIMULATOR_UDID`
to select a specific available iPhone. It fails if the required runtime is absent.
`bash scripts/ci.sh --static` runs only tooling checks; `--build-only` runs Core
tests and generic compilation, explicitly excluding app tests. Neither is full
release acceptance. Hosted CodeQL for Swift, Python and workflows is a separate
required check in the aggregate **CI gate**.

For a quicker development loop:

```bash
swift test --package-path Core
bash scripts/build-simulator.sh Debug
open RoomInventory.xcodeproj
```

Select the `RoomInventory` scheme and a Simulator in Xcode. The scheme's **Run**
action selects the local StoreKit configuration. The checked-in test plan selects
the hosted and UI test targets; it does not configure a StoreKit environment.
StoreKit tests observe live purchase approval and refund updates without refreshing
entitlements while polling. Use only synthetic sample belongings and documents for
screenshots, fixtures and public bug reports. The first launch starts empty.

For iPad layout coverage, run
`RoomInventoryUITests/testIPadLandscapeAtMaximumDynamicType` on an iPad Simulator.
It selects landscape and the largest accessibility text size, creates and renames
a home and room, edits an item, opens the generated CSV in the system share sheet,
and checks persistence after relaunch. Screenshots and accessibility hierarchies
are retained in the test result. This test is skipped on iPhone and does not perform
a purchase or restore purchases; it is not a VoiceOver or physical-device audit.

**Current StoreKit test limitation:** on Xcode 27.0 / iOS 27.0, the hosted purchase
test failed on a fresh Simulator because StoreKit used the Sandbox environment.
The same tests passed on a previously used Simulator. Those observed passes do not
establish reproducible purchase validation or release acceptance. Do not enter an
Apple Account into a local-test authentication prompt. Keep cold purchase testing
as an unresolved release gate; neither a hand-written test-plan option nor a
verified injected test transaction alone proves where a subsequent purchase routes.

## Language and region

The app follows the first supported language in iOS preferred languages (English
or Russian), including the standard per-app language setting. Unsupported
language lists fall back to English. No account or app-specific selector is needed.
Screens, accessibility labels, errors, camera permission, OCR review and export
captions use the selected language. Russian counts stay grammatical when the
region is set to another country.

Date and price formatting affects display only. ISO purchase dates retain their
stored civil day; explicit currency codes retain their currency. Ambiguous
free-form prices and dates remain as entered. OCR recognizes English and Russian
field labels and proposes changes for confirmation; it never applies them itself.
See [localization implementation and checks](docs/localization.md).

## Storage and exports

Originals remain in the app's local sandbox. Backups and exports are **not encrypted**.
Photo metadata is preserved with originals. Share only with intended recipients;
Files providers and operating-system backups can copy data according to their settings.

Current safety limits are **25 MiB per stored original**, **80 MiB of originals per
inventory**, **128 MiB per JSON backup**, and **4 MiB of inventory text**. CSV rendering stops at **16 MiB of output** with
an error instead of truncating rows; use the restorable backup when a repeated
attachment-table projection exceeds this limit. PDF reports stop at **500 pages**
with an error; no partial PDF or report ZIP is shared. Reduce long notes or select
fewer rooms in a custom report, or use the restorable backup. The capture
UI may apply a smaller image-import limit. These are implementation limits, separate
from Free/Pro quotas. Large JSON exports/restores use additional memory; export jobs
are serialized. A `.roominventory` file restores inventory and originals. A report
ZIP contains `Inventory.pdf`, a stable machine-readable `Inventory.csv`, a
translated `Inventory-localized.csv`, a translated README, and originals at
`originals/<item UUID>/<generated filename>`; the CSV and PDF retain those associations.
The report ZIP is not the restore format.

Use **Custom PDF report · Pro** to select rooms and include or omit serial numbers,
purchase details, notes and attachment names/paths. These choices only affect the
new PDF; they never remove details or images from the saved inventory. Standard
PDF/CSV/ZIP and restorable backup exports remain available without Pro.

The stored original is the image data received by the app: Files imports preserve
the selected file, Photos supplies its current representation (which can reflect
edits or provider conversion), and camera capture creates a JPEG. Photos import
requests the current encoding to avoid transcoding where possible, but does not
promise the untouched camera asset. Copies exported later preserve the bytes the
app actually saved.

Bad checksums, unsafe paths and unsupported schema versions stop an operation. A
failed restore retains the previous inventory. If a regular original filename
collides with different bytes, restore gives the recovered attachment a fresh ID
and filename while preserving the old bytes and home/room/item identities. Unsafe
symlink collisions are rejected. A known-good backup can recover a corrupted
inventory manifest or damaged regular originals in place. Removed/unreferenced originals
are currently retained internally for safety; automatic cleanup is not implemented.
See [storage details](Core/README.md), [privacy](docs/privacy.md) and
[support/recovery](docs/support.md).

The hand icon on the main screen opens **Privacy and support** without Pro.
Its English and Russian explanations are bundled for offline reading, including
deletion/retention limits, unencrypted exports, recovery and public-support guidance.
Optional browser links open only when tapped. The app links to published,
revision-pinned preview documents while final operator/contact details and stable
App Store policy URLs remain release requirements. No private support email is assumed.
`PrivacySupportTests` checks the packaged resources and standalone page dependencies;
`PrivacySupportUITests` checks EN/RU navigation, scrolling, links and large text.
These checks do not disable the device network or replace a physical VoiceOver audit.

## Preview release

The release engine is vendored from
[`venus-os-ci-toolkit` at `755c2e6`](https://github.com/victron-venus/venus-os-ci-toolkit/tree/755c2e66fb1e79fc67d9e4c85ecffcc046b967db).
The reviewed policy is [`.release-policy.json`](.release-policy.json). Follow the
[release strategy](RELEASING.md), [generated runbook](docs/release-workflow.md) and
[application acceptance checklist](docs/release-checklist.md). Device compilation
and the signing handoff are described in [device release](docs/device-release.md);
[App Store copy](docs/app-store-submission.md) remains an unsubmitted draft.

Same-repository pull requests also build an unsigned Simulator candidate on
GitHub-hosted macOS after the iOS tests pass. The existing CI entry point calls
the preview builder with the immutable PR head; the build fails if its tree
differs from the merge commit tested by CI. The run's `pr-simulator-<PR>-<head>-<attempt>`
artifact includes source, the Simulator ZIP, checksums and `preview-provenance.json`
with both commits, their trees, the run identity and payload hashes. This is a
build record, not a signed attestation. Check the complete CI gate and CodeQL
results as well: an uploaded artifact alone does not prove those checks passed.
No GitHub Release, device signing or App Store upload occurs. Running the exact
downloaded ZIP on a Simulator remains a separate acceptance step.

From a clean, committed checkout with an empty `release-dist/`:

```bash
python3 scripts/release.py package --version 0.1.0 --channel beta
```

This builds source and unsigned Simulator ZIPs, a preview notice, toolchain/source
metadata and SHA-256 hashes. It does not publish, sign for devices or contact App
Store Connect. Candidate publication uses the gated default-branch workflow; it
requires repository release configuration and successful checks on that exact SHA.
Stable publication promotes an accepted RC and does not imply App Store acceptance.

Source is MIT licensed. Support and feature requests:
[GitHub issues](https://github.com/4alvit/room-inventory-ios/issues).
