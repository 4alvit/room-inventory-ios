# Changelog

## Unreleased

- Type once into Recovery's already-autofocused name sheets without retapping the field, handling only the identified keyboard introduction and waiting for the exact typed echo within the same ten-second window; retain the last mismatching echo on failure and cover successive home, room and item creation through relaunch.
- Publish runner bridge messages with atomic exclusive rename, avoiding a temporary-link cleanup race while retaining overwrite refusal and strict collector metadata checks.
- Seed the exact recovery receipt through PhotoKit in the owned test runner, with a byte-preserving resource, one bounded creation and linked seed/isolation evidence before opening the system Photos picker.
- Filter native diagnostic queries to recognized signal candidates before serialization, preserving the existing sanitizer, byte limits and cleanup requirements.
- Bound passive StoreKit approval/refund observation to one ten-second monotonic window after a hosted approval arrived beyond the former five-second allowance; reject late matches and propagate cancellation without refreshing entitlements.
- Update related CI action pins together and group future Dependabot action updates.
- Collect bounded, redacted native diagnostics when Recovery device setup fails before UI execution, preserving the original failure and cleanup evidence.
- Keep the bounded diagnostic window when device-command cleanup overruns its deadline, recording the actual duration, clipping and clock-validation stage without changing command limits or failure status.
- Start OCR readiness observation on the first waiter run-loop turn, preserving its ten-second allowance and nested-query cancellation.
- Keep OCR selection controls separate from their visible labels, and use one native switch tap after checking the full control frame without changing selection deadlines.
- Allow up to 90 seconds for the first system Photos presentation after an observed delayed load, with immediate serialized probes, no renewed deadline and late-result rejection inside the existing overall test limits.
- Record bounded Recovery resource-scan wall and controller CPU costs without changing resource checks, command deadlines or cleanup.
- Handle the identified iOS keyboard introduction before querying the covered name field, retaining one real Continue action and the shared ten-second check for a unique, interactive field.
- Observe Files inline-folder rename and Save dismissal through live queries, retaining the ten-second deadline, exact destination-folder checks and exported-byte verification.
- Share immediate, bounded dismissal queries across OCR, item editors, name entry, privacy and Files tests, preserving the original ten-second limit and rejecting late or failed observations.

## [0.1.0] - development preview

### Added

- Build same-repository PR Simulator candidates on GitHub-hosted macOS, with verified tested-tree identity and payload provenance, without publishing a release.
- Add an offline English and Russian privacy/support page from the main screen, available without Pro. It explains local data, deletion, sharing, backups and public support, with optional links to published preview documents.
- English and Russian UI, accessibility text, errors, permission text and report captions selected automatically from iOS language preferences.
- Russian receipt/label OCR suggestions, regional display formatting and separate translated CSV output while machine CSV and backups retain their stable formats.

- Native iOS room/item inventory with photo import, receipt/label attachments and explicit OCR review.
- Local manifests and originals with checksums, atomic saves and validated backup restore.
- PDF, CSV and original-file report packages; Free users retain viewing, basic export and restore.
- StoreKit 2 non-consumable Pro flow and a local USD 19.99 test configuration.
- Core regression tests, Simulator/app validation, CodeQL and gated unsigned preview packaging.
- Pro batch image import with per-file outcomes and retry of failed files only.
- Pro custom PDFs with room selection and optional serial numbers, purchase details, notes and attachment paths.

This entry describes development scope, not a completed App Store publication.
Production StoreKit configuration, device signing, Apple agreements, real-device
acceptance and App Review remain separate requirements.

### Fixed

- Give the final owned Simulator state query a bounded 26-second work allowance while retaining the outer deadline and mandatory cleanup proof.
- Observe Recovery OCR selection immediately from one bounded snapshot after a single tap, avoiding delayed and repeated accessibility queries.
- Bound backup-file reads before restoration, reject non-regular inputs, and keep cancelling the file picker silent.
- Align automatic Simulator selection with the active SDK and support explicit runtime pins.
- Stop before UI tests when app unit tests fail, preserving separate result bundles for both required phases.
- Reduce CSV share-sheet accessibility queries within the existing deadline and retain Files tap diagnostics when readiness fails.
- Capture Photos and Files diagnostics from one immutable application snapshot so a dismissed picker cannot fail the test during diagnostic reads.
- Check actual toolbar buttons during Recovery OCR selection instead of treating transparent full-screen toolbar containers as obstructions.
- Select Recovery export actions by unique visible titles when native menus omit accessibility identifiers, and keep full snapshot diagnostics within their byte budget using compact JSON.
- Recognize Files locations by their exact visible navigation titles and retain remote-picker diagnostics when application snapshots omit them.
- Support Files' inline new-folder editor while preserving exact folder-name and save checks.
- Recognize Files folder titles exposed as action-menu buttons without activating the title menu.
- Select the actual Restore backup button when the system alert exposes a duplicate accessibility wrapper.
- Scope Recovery field and purpose lookups to their native control types and stop querying a failed purpose selection after its wait has expired.
- Calibrate Recovery test and acknowledgement budgets within the existing 30-minute attempt, preserving resource checks, late-result rejection and cleanup reserves.
- Avoid starting app-level inventory and purchase stores inside hosted unit tests.
- Accept Files metadata-only change times after opening a saved backup while preserving content, identity and collection-stability checks.
- Give the active Recovery test's xcresult staging a 512 MiB allowance within the existing 1 GiB output cap, while retaining 192 MiB final-result limits; keep all explicit checkpoint evidence and let Xcode discard automatic system diagnostics only after success.
- Poll discovery subprocesses while their streams remain open and retain buffered failure diagnostics within the existing deadlines.
- Complete the selected Simulator runtime's cache preparation within the existing hosted preflight deadline before starting Recovery.
- Allow a several-minute first Simulator boot within the existing Recovery startup budget, preserving one attempt, complete resource accounting and required cleanup.
- Give the single Recovery photo import bounded headroom inside the existing startup deadline, preserving exact fixture binding and full terminal accounting without retrying the seed.
- Keep Recovery collector callbacks intact when the native child finishes during resource accounting, while preserving child supervision and the final complete resource check.
- Account for disappearing children only inside the active, identity-bound XCTest result; keep unrelated output and finalized results strict.
- Reuse one OCR state and geometry snapshot before the single switch activation, preserving the ten-second readiness deadline and explicit hittability check.
- Allow the system Photos picker to finish its first presentation within one 30-second appearance window, rejecting late results without relaunching the picker or relaxing fixture checks.
- Keep real StoreKit and ordinary UI tests on Xcode 26.4.1 / iOS 26.2 / iPhone 16e, while requiring Recovery on Xcode 27.1 / iOS 27.0 / iPhone 17 and building previews with Xcode 27.1; retain supported Swift CodeQL analysis on Xcode 26.4.1.
- Unsigned Release previews omit build-machine paths and code-coverage data; packaging rejects app payloads that retain them.
- PDF fonts preserve exact Cyrillic text for copying and searching, including the letter к.

- Singular inventory counts and word-aware PDF line wrapping.
- Removed unsupported Open In document-editor registration; restore remains available through the in-app Files picker.
- Preview/OCR errors no longer promise that a missing or damaged original can be exported.
- Entitlement refresh ordering prevents an older scan from replacing a newer result.

### Upgrade

This is the initial development preview. Preserve a `.roominventory` backup before
changing builds or uninstalling. Storage currently permits 80 MiB of originals per
inventory. When a regular original filename has conflicting bytes, restoration
preserves the old file and remaps only the recovered attachment. Home, room and
item identities remain unchanged. Unreferenced originals are not automatically deleted.

### Security

Backups and report packages are not encrypted and can contain original photo
metadata. Share them only with intended recipients. The repository checks paths,
sizes and SHA-256 integrity and rejects symlink originals. No device-signing keys,
personal inventories or real purchase records belong in public fixtures or releases.
