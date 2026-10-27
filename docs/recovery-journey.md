# Recovery journey regression

This is a dedicated, opt-in UI data-loss regression. Source preparation and offline
verifier tests do **not** establish that the Swift test compiles or that a device
has completed the journey. Record those results separately after execution.

The test creates its home, room, item and initial fields through the interface,
imports the bundled synthetic receipt through Photos, runs real Vision recognition,
and applies only the model and price suggestions. It preserves the existing serial
number and purchase date. It then saves a ZIP and a restorable backup through the
system Save to Files interface, restores the backup through the picker and explicit
confirmation into a different, empty `UITEST_RUN_ID` namespace, relaunches that same
target, opens the original and saves a second ZIP. The target is a **fresh target**
in an existing app installation, not a fresh install.

All app data is produced through the UI. The only staged input is the PNG in Photos.
No ready-made inventory, repository/service calls, purchase, entitlement override,
StoreKit test session, receipt injection, or restore-purchases operation belongs in
this test. Ordinary app startup still reads StoreKit current entitlements and product
metadata; the test does not disable or replace those production calls. The visible Free UI must be observed at the specified checkpoints; this
is evidence of application behavior, not an independent audit of the App Store.

## Fixture

`UITests/Fixtures/SyntheticRecoveryReceipt.png` is a synthetic receipt: no real
merchant, person, payment or purchase. Its original bytes are 74,736 bytes, SHA-256
`3be0a311997c35182f58e2658f64afe06b437665dfb420f1dc595e23e24ea181`.
The printed OCR fields are model `VISTA-420`, serial `QA-2026-0042`, price
`USD 149.50`, date `2026-10-20`. Vision may return price as exactly `USD149.50` or `USD 149.50`; no other amount or
currency is allowed. Record that actual raw suggestion without editing it and
require storage, CSV and restored UI to preserve it exactly. The initial serial `KEEP-SERIAL` and date `2025-01-01` must survive.
Do not replace this image with text labelled as PNG or re-encode it.

## One bounded execution, after source review

The first run is a compatibility check as well as a regression check. System Photos
and Files accessibility can vary with the installed runtime. Missing or ambiguous
controls must fail with screenshots and accessibility trees, never select an
unrelated file or silently fall back to a service call. A failed first run is useful
evidence; repair and review the cause before separately authorizing another run.

1. Pin the approved source commit containing the reviewed patch, its source tree,
   fixture hash, Xcode/runtime identifiers and controller revision. The preparation
   patch is reviewed before that commit; this procedure does not run an uncommitted
   patch while labelling the result as its unchanged base commit. Use a clean,
   isolated checkout and new, empty result directory. Record the source tree digest.
   Preserve the existing accepted preview ZIP and all historical evidence unchanged.
2. Use one **new dedicated iPhone simulator**, created for this attempt, with a
   known installed runtime and a unique recorded UDID/name. This gives Photos a
   known empty library. Never use `booted`, erase a shared device, or clean a global
   simulator directory. Fail preflight if there is insufficient free storage or
   another native job would violate the host's coordination slot.
3. Generate the Xcode project from `project.yml` with the pinned repository helper.
   Perform one `build-for-testing` with an attempt-owned DerivedData path, unsigned
   Debug simulator settings and only the UI test target selected. Preserve the
   build log, exact command/exit, explicit build options and produced `.xctestrun`.
4. Boot that UDID and import **only** the exact fixture using `simctl addmedia`.
   Record the input hash and command result. Install the freshly built app on this
   dedicated device together with its UI test runner without launching them, then
   pin both data-container identities and record the actual empty export inventory.
   The selected `.xctestrun` uses `UseDestinationArtifacts` with exact app/runner
   bundle IDs and the test-bundle destination-relative path. The generated host,
   target-app and test-bundle source paths are removed as required by
   `xcodebuild.xctestrun(5)`. This prevents a test-command reinstall from relocating
   the pinned containers. A changed identity fails collection. Do not seed any app inventory
   or asset folder. If Photos or app export storage contains prior data, stop the run.
5. Prepare an attempt-local copy of the generated `.xctestrun` beside its original
   so `__TESTROOT__` paths remain valid. Keep only the UI target, set its
   `EnvironmentVariables.RUN_INVENTORY_RECOVERY_JOURNEY` to `1` and
   `EnvironmentVariables.RECOVERY_JOURNEY_RUN_ID`,
   `EnvironmentVariables.RECOVERY_SOURCE_RUN_ID` and
   `EnvironmentVariables.RECOVERY_TARGET_RUN_ID` to three new, distinct UUIDs.
   Retain mandatory generated test environment entries. Record before/after hashes
   and exact edits. The UI test validates and records these namespace identifiers.
   Do not set `UITargetAppEnvironmentVariables` for entitlement or storage overrides.
   No StoreKit configuration or StoreKit transaction replay may be enabled. Inspect
   generated configuration; an unexpected StoreKit setting is a stop condition.
6. Invoke `test-without-building` once with that `.xctestrun`, the recorded UDID,
   only
   `RoomInventoryUITests/InventoryRecoveryJourneyTests/testPhotosOCRExportRestoreIntoFreshNamespace`,
   an attempt-owned result bundle,
   `-parallel-testing-enabled NO`, `-maximum-concurrent-test-simulator-destinations 1`,
   `-test-iterations 1`, `-test-timeouts-enabled YES`, and
   `-maximum-test-execution-time-allowance 420`. Do not pass retry flags. Keep the
   effective xctestrun/selection proving no unit commerce tests were selected.
7. Retain the raw xcresult and logs even on failure. Inventory and hash the original
   **before any xcresult reader**, copy it into the collection directory, and verify
   both the copy and the unchanged original. All reader commands receive only the
   verified copy path. Preserve manifests before/after readers and detect any
   original mutation. On success, require exactly one selected test on the owned
   device to pass with zero skips/failures. Export its keep-always JSON,
   screenshots and accessibility attachments; use the final complete JSON, not an
   earlier partial checkpoint. Preserve attachment IDs and the xcresult digest.
8. After the test has stopped, recheck the pinned app and runner container identities.
   Read-only copy the two exact recorded `tmp/RoomInventoryUITests/<UUID>`
   namespace roots into the attempt evidence. The source namespace remains intact;
   the target namespace is collected **after relaunch**. Do not label these final
   copies as intermediate snapshots.
9. Read-only collect the three named Files copies from this attempt's unique
   `Recovery-<journey UUID>` folder in the simulator's local File Provider Storage,
   outside the app container. Resolve the provider within this UDID only and fail
   on zero or multiple matching folders/files. Collect the app's separately created
   `tmp/InventoryExports/<UUID>/...` backup and two ZIP payloads with original paths,
   inode/file identity, timestamps, byte counts and hashes. Do not infer which ZIP
   is source/recovered solely from content: they may be byte-identical. Preserve
   their distinct creation identities, ordered UI events and directory records.
   Require no prior export directories in the new app container and exactly three
   new exports (two ZIP, one backup). Record the original directory UUIDs, device
   and inode identities and times. A timestamp or content hash alone is insufficient;
   if provenance is ambiguous, report incomplete evidence rather than assign roles.
   Never manufacture a second ZIP by copying the first or regenerating one offline.
10. Build `collection.json` using the verifier's explicit path contract. Evidence
    paths are relative to the immutable evidence root; include source pin, actual
    command exits and collection provenance. Compare saved Files copies with the
    produced payloads. Run the offline verifier against the expected source pin.
    Its PASS means artifact consistency only. Full acceptance also requires the
    passing xcresult, ordered UI evidence, independent screenshot inspection and
    completed owned cleanup. Retain raw evidence if any one condition fails.

### Concrete controller and grant

`scripts/run-recovery-journey.py` is the single-use controller and
`scripts/recovery_collector.py` is its filesystem collector. Source preparation
does not execute either native path. After a reviewed source commit and a separate
coordinator-issued host slot, run exactly:

```sh
python3 scripts/run-recovery-journey.py --execute --grant /absolute/slot.json --grant-sha256 <sha256-of-slot-json>
```

The grant is a JSON object with exactly these fields: `schema_version` (integer 1),
`native_execution_authorized` (true), timezone-qualified `not_before` and
`expires_at`, `source_commit` and `source_tree` (40-character lowercase Git IDs),
`controller_sha256`, `collector_sha256`, `xcodegen_sha256` (64-character lowercase
hashes), absolute `worktree`, `output_root`, `xcodegen_path`, `developer_dir`,
explicit installed `device_type` and `runtime` identifiers, and a new uppercase
canonical `journey_run_id`. The active grant must have at least 1,800 seconds left.
The controller creates two additional distinct namespace UUIDs. The grant is a
reviewed coordination input, not a cryptographic authorization service.

The output must not exist and its parent must already exist outside the checkout.
The committed checkout must be clean; commit, tree, controller, collector, fixture,
XcodeGen and selected test configuration are rechecked before UI execution.
Do not create an executable grant during source-only preparation. Reusing a grant
cannot overwrite an existing attempt directory; retries require fresh review and
a new slot, output directory and journey ID.

The output contains command stdout/stderr and ownership receipts in `logs/` and
`result.json`, `source-pin.json`, generated/selected test configuration copies,
resource samples, retained `DerivedData/`, raw `original.xcresult`, and
`evidence/collection/`. The latter contains bridge snapshots, two final namespace
copies, six separately captured generated/saved export files, original/copy result
manifests, exported attachments, and the verifier's `collection.json` input.

### Live export origin barriers

The test runner publishes six numbered requests in its own
`Documents/RecoveryJourneyBridge/<journey UUID>` directory: before and after each
of `source_zip`, `backup`, `target_zip`. Each request contains all three run IDs,
its role, phase, sequence and a fresh nonce. It waits up to 20 seconds for a strict
matching acknowledgement containing the exact request hash. All requests and
acknowledgements are also kept as XCTest attachments.

The collector checks unchanged containers, the initial empty export state and
every preceding request/acknowledgement. Each before barrier must match the prior
snapshot. Each after barrier must add exactly one generated directory/payload and
exactly the expected named Files copy; all prior exports must remain unchanged.
Only after durable raw snapshots and matching generated/saved bytes are captured
does it publish the acknowledgement. This associates even byte-identical ZIPs with
their actual ordered export operations. Missing, duplicate, stale, ambiguous or
out-of-order evidence fails the attempt. The bridge writes only runner coordination
files and never writes application data or supplies entitlements.

### Storage admission and abort policy

Admission requires **at least 24 GiB free** on both the output and simulator-device
filesystems before creating a device or building. During work, free space below
8 GiB aborts. At most every two seconds the controller checks owned roots using
bounded `lstat` walks without following symlinks. DerivedData has a **4 GiB
allocated disk budget** (`st_blocks * 512`); its logical length is recorded
separately, so sparse cache reservations do not consume that disk budget. The
DerivedData root directory's own allocation is charged before visiting children,
including an empty root; root `lstat` and block validation are deadline checked.
Missing, negative or non-integer block counts fail closed: logical length is not
an upper bound on allocated storage. All other roots still enforce the larger
of logical and allocated bytes. Reaching a sampled cap also aborts: new device 8 GiB,
other attempt output 1 GiB, original xcresult 192 MiB, verified
xcresult copy 192 MiB, exported attachments 128 MiB and logs 64 MiB. Each command
stream is additionally limited to 16 MiB. The collector limits its own writes to
512 MiB and rejects copies that cannot fit its remaining allowance. Every complete
sample and byte-cap crossing identifies its `cap_metric` as `allocated` or
`max_logical_allocated`. No unknown allocation is reported as zero or estimated
from logical size. Hardlinks remain conservatively charged per directory entry;
each entry and every later walk obtain fresh metadata, including later growth.
Entry-count, deadline, exclusions and cleanup bounds are unchanged.

The 24 GiB policy budgets 13 GiB of retained owned output, 3 GiB of transient/shared
growth and the 8 GiB free-space floor. It deliberately includes the new simulator
and DerivedData retained after the first run. Saved measurements informing this
policy include a 4.828 GiB historical device, a 209 MiB DerivedData sample and a
56 MiB UI xcresult sample. They are snapshots of other runs, not a proof that this
run will fit or an empirical peak. The review packet retains exact source receipts
and hashes. Sampled caps can overshoot between checks and do not constrain unrelated
host processes; uncertainty or budget exhaustion remains a failure. No sizing
probe or deletion of unrelated/historical data is part of source preparation.

### Deadline and exit contract

One outer controller owns the complete attempt and every subprocess process group.
Use monotonic absolute deadlines; no phase may renew the outer budget. The total
ceiling is 1,800 seconds, reserving the last 60 seconds for cleanup. Phase caps are
preflight/project generation 120s, build 720s, create/boot/seed 180s, UI execution
480s, evidence collection/verification 240s; each is additionally capped by the
remaining outer budget minus cleanup reserve. These caps are limits, not a promise
that a cold build fits. Do not begin a phase without enough cleanup time left.

An absolute process alarm backs up cooperative deadline checks during filesystem
and collection operations. Every command reserves four seconds of its allowance
for owned-group cleanup. Guard callbacks and live bridge polling share that command
deadline. The outer timer remains active through final receipt writing; final
stdout is nonblocking. A result file is provisional until the external process
exit is known: an interrupted/late final write must never imply success.

The controller must preserve stdout/stderr, start/end/elapsed, PID/PGID, exit status,
phase deadline, timeout status and any signals for each child. On timeout stop the
owned group with TERM, then bounded KILL/reap if necessary. Never use name-wide
`pkill` or signal a process that was not started by this attempt. EPERM, a surviving
group or unreaped leader is a cleanup failure, even if a later check finds it gone.
Maintain the original operational error independently from cleanup errors.

Controller exit contract: `0` only when UI assertions, artifact verification and
owned cleanup complete successfully; independent pixel review remains a separate
acceptance gate after the bounded run;
`1` for assertion/build/artifact failure; `2` for preflight/configuration failure;
`124` for deadline expiry. A cleanup failure forces nonzero exit and is recorded
separately. The test's own deadline is a backstop, not a substitute for the outer
controller. No result from an interrupted attempt may be promoted to PASS.

### Owned cleanup

After evidence collection, terminate only the app/test runner and groups launched
by this attempt, shut down its exact simulator UDID, and confirm shutdown and all
owned group leaders reaped. Preserve the dedicated device and evidence for review;
do not delete the device, DerivedData or its Files folder during this first run.
No changes to existing QA devices, accepted source/candidate/evidence, global
Photos/Files data, signing accounts, remote CI or repositories belong in cleanup.
Record free-space samples as discrete observations, not a claimed global
minimum. A failed initial device-state query must still allow shutdown of the known
owned UUID and a separate final-state query. If cleanup cannot complete inside the reserve, retain evidence, report the
remaining exact owned resources and return nonzero without an automatic retry.

## Offline evidence contract

Run `python3 scripts/verify-recovery-journey.py /absolute/evidence/collection.json
--expected-commit <approved-full-lowercase-SHA>` as one command under the collection
phase deadline. The verifier makes no simulator or network calls. Run its separate
malformed-artifact tests with `python3 -m unittest discover -s scripts/tests -p
"test_recovery_journey.py" -v` during source preparation.

The version-1 collection object has exactly `schema_version`, `source_commit`,
`source_run_id`, `target_run_id`, `ui_evidence`, `ui_attachments`, `artifacts` and
`collection_receipt`. All file references are relative to its directory. The
`artifacts` mapping requires `fixture`, `source_inventory`, `target_inventory`,
`source_original`, `target_original`, `source_zip`, `backup`, `target_zip`,
`source_generated_zip`, `generated_backup` and `target_generated_zip`. Each has its
own collected path. The three short export names refer to the actual saved Files
copies; the three generated names refer to the corresponding app export payloads.
The two inventories and original assets come from the two recorded namespace
roots, copied after the journey has finished.

`ui_evidence` points to the final `recovery-journey-evidence.json` attachment.
`ui_attachments` maps the 34 checkpoint screenshot/accessibility names referenced
by its 17 events to exported files. Keep additional picker/save-dialog and partial
progress attachments in the raw xcresult or a separate capture directory; they
are not entries in this exact checkpoint mapping.

The collector receipt has `schema_version`, all three run IDs, an actually observed
empty `exports_before` array and exactly three `exports_after` entries in UI order.
Each entry records `role`, `directory_id`, `generated_path`, `device_id`, `inode`,
`created_at_ns`, `bytes`, `sha256` and `saved_path`. Numeric fields are JSON integers,
not booleans. IDs must be canonical UUIDs. See `verify_receipt` for exact path and
role spelling. This receipt is an assertion by the trusted host collector; preserve
its raw file listings, command outputs and collection code to make it reviewable.
It is not cryptographic proof that the UI ran.

The verifier checks both complete inventories and the backup independently,
including schema types, names, IDs, all item fields and every attachment field.
Each original must match the pinned image bytes. Both ZIPs must contain the matching
machine CSV, localized companion, original, README and structurally present PDF.
PDF rendering and visible text correctness require separate inspection. Merely
renaming a first ZIP to the second export's name is not an accepted capture method.

## Acceptance boundaries

The new UI test is a rebuilt Debug test artifact. A successful run would validate
that approved source plus test configuration. It would not retroactively turn an
older Release ZIP smoke test into a full recovery run. Historical manual recovery,
current accepted limited preview smoke, new source review, new offline verifier
tests and any future runtime acceptance remain separate records.

A clear single-image, single-item English journey does not cover camera capture,
Files image import, batches, locale matrices, low-storage/interruption recovery,
physical devices or App Store purchases. Those scopes retain their own evidence.
