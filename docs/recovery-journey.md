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

`UITests/Fixtures/SyntheticRecoveryReceipt.data` is a synthetic receipt: no real
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
   known installed runtime and a unique recorded UDID/name. Do not assume its
   Photos library is empty; the bound runner verifies and isolates the fixture. Never use `booted`, erase a shared device, or clean a global
   simulator directory. Fail preflight if there is insufficient free storage or
   another native job would violate the host's coordination slot.
3. Generate the Xcode project from `project.yml` with the pinned repository helper.
   Perform one `build-for-testing` with an attempt-owned DerivedData path, unsigned
   Debug simulator settings and only the UI test target selected. Preserve the
   build log, exact command/exit, explicit build options and produced `.xctestrun`.
4. Boot that UDID and install the freshly built app and UI test runner without
   launching them. Verify the raw fixture in the built test bundle against its
   source hash. The bound runner creates the sole fixture through PhotoKit after
   the installation handshake below. Record the preinstallation container
   identities, empty scenario namespaces/exports, and fixture binding. These are
   installation observations, not the final scenario pins.
   The selected `.xctestrun` keeps the validated generated Simulator host,
   target-app and test-bundle paths beside the original file, with
   `UseDestinationArtifacts` disabled and no destination-relative test-bundle path.
   Xcode rejects that destination-artifacts mode on Simulator because it requires
   a physical iOS device. Xcode may install the same selected products again.
   The first XCTest AUT launch can replace its preinstalled container even after
   runner startup. One installation-only launch uses the distinct journey UUID
   namespace and confirms termination. The startup handshake below then establishes
   final scenario pins once, before source/target launches or data-bearing actions.
   Later container identity or metadata changes fail collection; they never
   trigger rediscovery or repinning.
   Do not seed any app inventory or asset folder. Prior app/export data still
   stops the run. Only the newly created, acknowledged device may have its bounded
   local Photos inventory isolated; shared or surviving user devices are forbidden.
5. Prepare an attempt-local copy of the generated `.xctestrun` beside its original
   so `__TESTROOT__` paths remain valid. Keep only the UI target, set its
   `EnvironmentVariables.RUN_INVENTORY_RECOVERY_JOURNEY` to `1` and
   `EnvironmentVariables.RECOVERY_JOURNEY_RUN_ID`,
   `EnvironmentVariables.RECOVERY_SOURCE_RUN_ID` and
   `EnvironmentVariables.RECOVERY_TARGET_RUN_ID` to three new, distinct UUIDs.
   Bind `EnvironmentVariables.RECOVERY_SIMULATOR_UDID` to the owned destination.
   Set `UserAttachmentLifetime` to `keepAlways` and `SystemAttachmentLifetime`
   to `deleteOnSuccess`. The test explicitly keeps all 17 checkpoint screenshots,
   17 accessibility trees and the final evidence ledger; Xcode may discard its
   redundant automatic diagnostics after success and retains them on failure.
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
   `-test-timeouts-enabled YES`, and `-maximum-test-execution-time-allowance 780`.
   The selected test has an explicit 720-second execution allowance within the
   controller's single 840-second test phase and command cap; launch, finalization
   and accounting still consume that same absolute phase budget.
   Omit repetition and retry flags for this single invocation: Xcode 16.4 rejects
   `-test-iterations 1` before XCTest starts. Keep the
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

### Installation-to-scenario handshake

At test entry, the runner performs exactly one installation-only AUT launch with
`UITEST_RUN_ID` set to the distinct journey UUID, checks foreground state, terminates
it and checks that it is not running. It performs no inventory or Photos action.
Only then does it atomically publish one `installation-request.json` in its own
fresh journey bridge directory. It binds the three run IDs, owned Simulator UDID, expected AUT
and runner bundle IDs, phase and fresh nonce. Its strict request-hash ACK shares
one 60-second monotonic deadline starting before request publication with the
wait and acknowledgement validation. Late observations cannot authorize success;
the XCTest and controller deadlines remain active and are never renewed.

All runner publications (installation, Photos seed/isolation and numbered export
requests) write a complete exclusive temporary file in the same directory, then
publish it with Darwin `renamex_np(RENAME_EXCL)`. An existing destination, including
a symlink, is not replaced; an unsupported or failed rename fails the publication
without a fallback or retry. A failed rename cleans up only its own temporary
file, while an already existing temporary path is left untouched.
This avoids the former hard-link-then-unlink sequence: removing the temporary
link could change the published inode's link count and `ctime` during a strict
collector read, even when its bytes, size and modification time were unchanged.
The collector still rejects every observed identity, content or metadata change
during a read. Request/acknowledgement hashes, ordering and deadlines are unchanged.

The host's existing guarded callback searches only the owned Simulator's
`data/Containers/Data/Application` directory, with at most 2,000 entries and
no-follow metadata reads. Missing old installation metadata is not a scenario
failure before the request. A duplicate, foreign, malformed or ambiguous request
or bundle match fails. A valid request can establish final containers only once:
absent source/target namespaces, empty exports/Files inventory, unchanged fixture
hash and owned-device identity must hold before durable receipts and ACK. The
journey UUID warmup namespace must contain exactly an empty `assets` directory and
a zero-byte regular `.repository.lock`, with no manifest, originals, symlinks or
other entries. Its observed root/entry identities are retained in the installation
receipt and checked again before ACK. This namespace must be absent before the
installation-only launch. Existing
selected build paths, source and `.xctestrun` hashes bind the installed products;
this does not add an independent installed-binary attestation.

The single Photos seed is not repeated or replaced. A fresh Simulator is not
assumed to have an empty Photos library. After the installation ACK and before
launching the data-bearing scenario, the UI-test runner creates and then isolates
the seed using PhotoKit. The controller validates the actual built runner's Photos
usage description and pregrants Photos access only to that runner on its newly
owned device. This command is not proof of the later PhotoKit authorization state:
XCTest may install the runner after the pregrant. After ACK, the runner records
the actual read/write status. Authorized proceeds; only not-determined may request
read/write access through PhotoKit. That asynchronous request returns before UI
interaction. Only one system alert naming the exact runner, declaring the actual
usage message and offering the enabled/hittable Allow Full Access control is
accepted. The callback and final status must both report full authorization.
The English title accepts one optional terminal period, as observed in the
Xcode 26.3 recovery run. This does not broaden runner identity, usage text or
full-access/deny button checks; unrelated, limited and unrecognized localized
prompts still fail closed. The title correction alone is not journey acceptance.
If the request completes authorized without any prompt being observed or tapped,
the full callback and fresh status are accepted with both prompt flags false and
empty prompt fields. This proves authorization without claiming UI interaction.
Denied, restricted, limited, foreign/ambiguous prompts and incomplete callbacks
fail. Before/after raw statuses and the actual prompt association are retained.
The app's privacy permissions and built payload are unchanged.

The canonical fixture is `UITests/Fixtures/SyntheticRecoveryReceipt.data`, an
unchanged PNG payload of 74,736 bytes with SHA-256
`3be0a311997c35182f58e2658f64afe06b437665dfb420f1dc595e23e24ea181`.
Its raw resource extension avoids the PNG processing observed in prior build
logs. Both the controller's built-product check and the runner's bounded bundle
read must match these exact bytes before creation. The PhotoKit original filename
remains `SyntheticRecoveryReceipt.png`; no image decoding or re-encoding occurs.

The seed has one nonrenewable 86-second monotonic window inside the unchanged
720-second native test and 840-second controller test limits. Authorization retains
its own maximum 20 seconds, clipped to the seed window. The runner requires zero
to 63 distinct local asset IDs and no existing resource with the fixture filename.
A fresh inventory check inside the change block must match that initial set. One
`PHAssetCreationRequest` adds one `.photo` resource from the verified data. A timely
successful completion and a valid placeholder ID are mandatory. The new inventory
must equal the original IDs plus exactly that ID, and a network-disabled resource
read must match the canonical bytes. Unknown or late completion fails; it does not
cause a second creation. The seed consumes the existing native allowance rather
than extending any controller or XCTest deadline.

`photos-seed.json` is an atomic, at-most-64-KiB receipt bound to the installation
request, run IDs, device and runner. It includes sorted before/after ID arrays and
their hashes, the created ID, authorization facts, mutation count, raw-bundle and
PhotoKit-original hashes, and elapsed time. The existing isolation receipt binds
the seed receipt hash. The host requires both immutable receipts and independently
checks the ID-set difference and the identity preserved by isolation.

The runner then checks the actual Simulator UUID, runner bundle, usage description
and full read/write authorization. One unchanged 20-second monotonic deadline
covers isolation of at most 64 local assets, at most eight
resources per asset, the unique named 1400×1800 PNG, and two network-disabled
resource reads of at most 74,736 bytes each. Both reads must match the source
fixture's SHA-256. Its initial IDs must equal the seed's final IDs and the fixture
must be the same newly created asset. After a stable inventory re-read, one PhotoKit
change removes only the other asset IDs. The fixture is never deleted, replaced or seeded
again. A per-change system confirmation must carry the exact removal count in
its complete first-line deletion title. For the exact owned
`com.alvit.roominventory.uitests.xctrunner` / `RoomInventoryUITests-Runner` pair,
the title may name that runner or the fixed `com.apple.XCTRunner` carrier observed
on the previously admitted iOS 18.5 Simulator. The Xcode 26.3 / iOS 26.2
qualification must satisfy the same guards; this earlier observation does not
qualify the new runtime. The carrier label alone is not identity proof:
installation ACK, actual Simulator/runner binding, full authorization, unchanged
fixture hash and exact removed asset IDs remain mandatory before the request.
Foreign, duplicate, embedded or count-mismatched titles fail. The one SpringBoard
alert still requires exactly two buttons: Delete and a denial control; only
Delete may be tapped, at most once. A missing control has a distinct diagnostic.
Unknown alerts fail. The native permission/confirmation presentation remains a
runtime compatibility gate, not a source-validation claim.

`photos-isolation.json` is published atomically in the runner bridge, binds the
installation request hash and all run/device identifiers, and records counts,
original hashes, callback/confirmation results and elapsed time. The host retains
failure receipts and requires a successful immutable receipt before acknowledging
the first of the original six export barriers. An overdue/missing callback is a
failure, never success inferred from a submitted request. PhotoKit has no change-
request cancellation API; if a change callback is unresolved, the ordinary owned
process/device cleanup remains mandatory and no scenario acceptance is recorded.
The existing strict picker check for one photo and all OCR/original/export checks
remain. Picker evidence is captured before the cardinality assertion so an
unexpected accessibility representation is retained even when selection stops. After ACK, request/ACK bytes, both final container identities and metadata
remain pinned for every live export check. Installation failure never permits a
second handshake or opportunistic midjourney repin. The original source/target
launches, relaunch, assertions and six export barriers follow ACK unchanged. The
installation-only launch shares the existing XCTest/controller deadlines; it does
not add a host command, retry or additional allowance. Hosted execution must
still prove that later scenario launches preserve the final pinned containers.

Opening the system Photos picker has one 90-second monotonic appearance window,
starting after the single `import.photos` activation. The first live existence
probe runs on the active waiter's first run-loop turn. A negative query schedules
the next probe one second after it returns, so native queries cannot overlap
and accessibility traversal leaves a quiet interval for presentation work.
Waiter teardown disables queued probes and cancels the pending timer. This avoids
`waitForExistence`'s additional query after its timeout; an already active native
query may still return late, and a positive result at or after the deadline is
rejected. This is not a hard wall-clock cancellation of native work.
The selector still requires a `Photo,` Image, followed by
the existing exactly-one-photo, interaction and original-byte checks. There is
no second picker launch or seed attempt, and the XCTest/controller limits do not
increase. In run `41358495304`, PhotoKit had verified the sole fixture, but native
session events show the Photos service appearing about 20 seconds after the
existence wait began, beyond the former ten-second window. The later failure
snapshot contains that exact image; it does not prove the image was available
during the earlier wait.

In run `41663409152`, the former 30-second window began at 16:06:31.516 UTC.
Six queries returned no match; the seventh was interrupted by the waiter's
deadline. The failure screenshot at 16:07:06.503 still showed Loading. A later
accessibility tree at 16:07:39.797 contained the real photo, 68.281 seconds after
the wait began; it does not establish exactly when the photo first became ready.
The 90-second allowance accommodates this observed first-use delay with bounded
headroom, without claiming to repair its underlying cause or guarantee a future
pass. It remains inside the same 720-second native test allowance and existing
controller limits; no negative probe renews the deadline.

Run `41721079406` still reached the 90-second deadline with the picker showing
Loading. Its 80 query activities occupied 81.573 seconds of that window; the
79 gaps totaled 8.423 seconds. These are wall-clock activity spans, not CPU
measurements. The failure screenshot and accessibility attachment retained the
unavailable picker, and session events show the remote picker continuing to
present after the failure. Spacing negative probes by one second reduces the
observer's repeated accessibility work. It does not establish that polling caused
the delayed presentation or guarantee recovery; the exact-source hosted journey
must still pass. The first probe remains immediate, and the same 90-second
deadline rejects late results without another picker launch or a relaxed selector.

In run `41450416826`, two live existence queries completed without a match; the
second took 26.7 seconds. The remote Photos view appeared late in that query.
After the 30-second wait timed out, XCTest made another query and resolved the
image approximately 13.3 seconds later. The deadline guard correctly rejected
it before selection or OCR. Immediate polling removes the initial predicate
delay and the wrapper's final query, but does not establish or repair the cause
of the Photos service/AX latency. The live selector is retained: an earlier
hosted run reached OCR even though `app.snapshot()` omitted the remote photo.


In run `41249372436` the strict Photos selector found one `Photo,` Image, but
`control interactive: observed false, expected true` stopped the tap. The saved
log identified `PXGGridLayout-Info`; it did not preserve enough AX/screenshot
context to identify a legitimate actionable control. Later Xcode system-log
collection crossed the then-current result cap (206,925,824 allocated bytes in the
partial traversal). The smaller standalone Photos observations described in
[hosted retention](recovery-hosted.md) preserve that missing diagnostic context.
Those diagnostic additions did not guess an ancestor, retry selection, relax the
interaction assertion, increase the cap or claim the native journey passed. The
later result-lifecycle policy is described under storage admission below.

### Explicit OCR selection

The journey verifies all four OCR fields start unselected, then activates only
model and price with one left-to-right `XCUICoordinate` drag inside each verified switch. The production
row uses a separate visible localized label and the same bound native Toggle
with `labelsHidden()`. The Toggle retains its original accessibility label;
the visible Text uses `accessibilityHidden(true)`. Raw snapshot Text nodes do not
establish VoiceOver focus behavior, which requires separate validation.

In this fixed English fixture, the native switch must have a narrow 40–80-point
frame. Its entire frame must lie inside the containing OCR Form's visible bounds
with a two-point inset, below its navigation bar, and must not intersect exposed
navigation, tab-bar, keyboard or toolbar-button frames. An alert or
unidentifiable form fails before the gesture. Switch-relative normalized coordinates
`(0.25, 0.5)` and `(0.75, 0.5)` must resolve to the admitted endpoints inside that frame,
within the same readiness window. A changed coordinate fails before the one drag.
The gesture holds for 0.1 seconds, moves at XCTest's `.slow` velocity, then holds
for 0.1 seconds before release. Both endpoints and the intervening straight path
stay inside the verified switch frame. Coordinates
remain dynamic; this check is admission evidence, not an atomic guarantee that
the layout cannot move before event delivery.
The test accepts the exact post-gesture value `1` only within the original ten-second
observation window, with no toggle retry. The later four-field observation, `Apply 2` check and
selective-update artifact checks remain mandatory.

In main run `41915887192`, attempt 1, the synthesized event recorded one 50 ms
center tap at `(339.5, 366)` for the model switch at `(309, 352, 61, 28)`.
Ten subsequent application snapshot queries completed without confirming selection;
the last recorded value was `0`, and pre-activation and failure images were
identical. The legacy event snapshot contains only the
application root, so it does not prove dispatch to the switch's handler. The
record does not support coordinate drift or a slow selection query as the cause.
The single directed drag replaces that short tap; it still requires a fresh
native run to prove selection and the complete recovery journey. No state is
set through a test hook, and no second gesture or longer timeout is allowed.

In run `41800293919`, attempt 2, the native element tap used the AX visible point
`(310, 353)` for the model switch at `(309, 352, 61, 28)`, rather than its center
`(339.5, 366)`. The Session log confirms one touch down/up at that corner. The
post-tap window completed ten snapshot queries without establishing selection;
the final exact switch value was `0`. Pre-tap and failure images were identical,
with all switches off and `Apply 0` disabled. This supports choosing an interior
point explicitly; it does not prove why the corner touch failed or an app state
reset. The next hosted journey must still establish selection and all later
persistence, export and restore outcomes. No timeout or assertion is relaxed.

An isolated iOS 27.0 diagnostic using the production source at `fde75fa` exposed
the original labeled Toggle as a 338×28-point row. Its one native tap at
`(201, 362.3)` left Model unselected; a separate fresh-launch trailing tap at
`(350, 362.3)` selected it. With only the label/control layout changed, the Toggle
frame became 61×28 points. A fresh native tap at `(310, 353)` selected Model in
the first post-tap snapshot, with the other three fields still unselected and
`Apply 1` enabled. This demonstrates a concrete native target ambiguity and a
successful narrow-control interaction. It does not establish the cause of
hosted run `41438176940`, where a delivered trailing tap left the model at `0`,
or replace full Recovery and layout acceptance.

Toolbar obstruction checks use descendant button bounds. A local iOS 27.0 run
on source `753be01` exposed an empty, transparent `Toolbar` spanning the underlying
item screen while the OCR sheet and its model switch were visibly unobscured.
The old whole-container check rejected the switch before tapping it. Navigation
bars, tab bars and keyboards still use their full frames; alerts still block the
action. One immutable application snapshot supplies the form, switch and chrome
geometry, and a bounded `ROOM_OCR_TAP_GEOMETRY` record reports those inputs,
`activation=verified_switch_drag`, both drag endpoints, `checked_region=entire_switch_frame`, and
individual checks before the single activation. Readiness uses that same
snapshot for the unique switch, enabled state and value `0`, followed by one
live hittability check. A single ten-second monotonic window covers readiness
and geometry through admission of the gesture; a late observation cannot authorize
an action. This avoids four independent remote property resolutions consuming
the entire window. The exact post-activation value `1` remains required.

The first readiness probe runs on the main run loop inside an active XCTest
waiter, without the predicate expectation's initial polling delay. An unready
probe schedules one later probe only after returning; probes cannot overlap.
Leaving the waiter disables pending callbacks and invalidates the timer. The
same ten-second window still covers fresh state, live hit testing, geometry and
gesture admission. Keeping the probe inside the waiter preserves
[XCTest's nested query interruption](https://developer.apple.com/documentation/xctest/xctwaiter/result/interrupted);
this is not a promise of termination at exactly 10.000
seconds, because XCTest's watchdog has its own scheduling grace.

In main run `41425796691`, the price switch was positively hittable immediately
before readiness, but the first predicate probe started 1.032 seconds later.
The application-root query then took 7.115 seconds, and the outer waiter
interrupted the subsequent live switch query. Its returned `false` was not a
completed negative hit test. Starting the fresh probe immediately removes the
measured polling delay; it does not identify or eliminate the cause of slow
native queries. Expired observations still fail without a tap or a retry.

After the single gesture returns, a separate ten-second monotonic window starts with
an immediate application snapshot. State is read from exactly one switch with the
expected identifier in that immutable snapshot; absent, wrong-type, wrong-value
or duplicate targets cannot establish selection. Snapshot traversal is bounded
by the same deadline and 10,000-node limit. If selection has not appeared, later
observations share the remaining window. No accepted observation triggers a
second live value query, and neither polling nor an error renews the deadline.

Run `41363140553` selected the model correctly, but its first post-tap predicate
started 1.019 seconds into the ten-second window. Resolving `exists` consumed
9.284 seconds; the selected value arrived 0.313 seconds after the deadline, and
a second live value query was interrupted. The immediate snapshot removes that
initial polling delay and repeated resolution. It does not establish the cause
of slow accessibility queries or guarantee timely completion; observations at
or beyond the deadline still fail, with the original diagnostic evidence retained.

In CI run `40893851357`, attempt 1, the UI log first reported
`OCR selection model: observed 0, expected 1` after the two generic element taps.
Xcode then collected failure diagnostics; a 112,718,394-byte `system.logarchive/dsc`
entry crossed the then-current 192 MiB result budget (209,453,056 allocated bytes
observed). That crossing was real allocation, not a sparse-file accounting error.
The packet could not retain the oversized result, so it does not establish which
part of the labeled switch received the original tap. Targeted single activation
and an immediate state check address the interaction ambiguity; a native run is
still required to establish that selection and the rest of the journey pass.
Those interaction changes did not alter resource caps, result-retention checks
or acceptance requirements.

### Native export menu actions

The English-only recovery journey selects package, backup and restore commands
by their exact visible titles and requires at most one matching button before
activation. On local iOS 27.0, the native menu preserved these titles but omitted
the SwiftUI `export.package` identifier, so scrolling could never find that ID.
The same label semantics are used by the ordinary UI tests. The existing bounded
scrolling, live readiness, one activation and subsequent Files or import-picker
assertions remain required; no export service is invoked directly.

### Autofocused name entry

New `NameEntrySheet` presentations request initial focus for their
`entry.name` field from a noninteractive UIKit appearance observer at the sheet
root. Its `viewDidAppear` callback assigns the field's `FocusState` after the
presentation, while a sheet-owned state flag permits only one request per
presentation, including if SwiftUI recreates the observer. The observer requires
an attached window, rejects dismissal, and clears its callback on dismantle.
It does not schedule delayed requests or repeat focus when an alert returns.
Recovery uses `AutofocusedNameEntry` without a second field tap. One
30-second monotonic setup window covers the exact keyboard introduction and a
unique enabled text field with exactly one software keyboard. Only timely readiness can start the
separate ten-second input window, covering an empty or placeholder value, one
native `typeText`, and the exact typed value afterward. Initial live `nil` values use
the prior empty-value normalization; the typed echo must still be a String
equal to the requested name. After the one input action, immediate serialized
read-only probes allow nil or partial values to settle within the remainder of
the input window. A late exact value or a query error still fails; the wait does
not repeat input or renew its deadline. The existing exact ledger assertion
runs only after a timely match. On failure, `ROOM_NAME_ENTRY_ECHO_V1` records
the stage, timely observation count and last mismatching synthetic name (or
explicit nil), capped at 256 UTF-8 bytes with a truncation flag; the complete
JSON is bounded to 4096 bytes and performs no additional UI or clock queries.

Before starting that input window, the autofocus setup rechecks the exact
introduction owner after the field/keyboard-readiness queries and optional evidence.
An introduction that appeared during those queries uses the same guarded
Continue action immediately when its complete observation is recognized, without
waiting to resolve that owner a second time. A tap still returns control to the
setup loop for a fresh absence and field-readiness check. A duplicate or
unrecognized owner also blocks input. This final check
uses the original setup deadline; a late or throwing check cannot admit input.
It narrows a sequential observation gap rather than making UI queries atomic.

The first focused regression exposed the actual `UIContinuousPathIntroductionView`
with the known sliding-text marker and one Continue button. The helper reuses
Localization's exact recognizer and a per-test Continue allowance shared across
all three sheets. It requires the introduction to disappear and the field to
be ready afterward. Optional before/after screenshots consume the setup window;
they do not renew it. `waitForField` omits the field tap. The helper's explicit
setup/input mode is used for AutofocusedNameEntry; Localization retains its
existing shared ten-second `waitAndTapField` path and field tap. A late query or
input cannot authorize Save; there is no generic Continue action, field-tap
fallback or retyping. Keyboard presence is a setup prerequisite, not proof that
the intended field has focus: native input and its exact echo remain required. Generic item-editor
fields still use their existing tap-based input.

The autofocus adapter resolves the recognized owner and Continue button with
`firstMatch` only after the same owner-count and snapshot-recognition guards.
The snapshot still requires the exact owner identifier, exact marker and exactly
one enabled Continue button; native hittability and the single tap remain gated
by the setup deadline. The adapter inventories exact `entry.name` text fields
from one direct application snapshot, traversing at most 1,024 nodes. It counts
all matching typed fields and uses enabled state and placeholder only from the
sole match in that same snapshot. Each capture clears the prior field proof;
missing, duplicate, oversized, late or throwing captures cannot reuse it. The
autofocus path omits a coordinate hit test because it never taps this field;
native `typeText` requires keyboard focus and a missing-focus error remains a
failure. Localization's tap-based path still requires live hittability. The
initial value, single native input and exact echo use the exact `entry.name`
identifier predicate with unique `element` resolution, so a missing or ambiguous
live field fails instead of selecting its first match. These operations retain
the separate ten-second input deadline. In hosted run `41941238836`, the unused
coordinate hit query exceeded the 30-second setup window after the introduction
was dismissed and the snapshot had established one enabled field; no input was
attempted. Omitting that query does not establish a native performance guarantee.
In hosted run `41952876149`, setup observed no introduction and one enabled
field, but native input failed because neither that field nor a descendant had
keyboard focus. The later failure screenshot and accessibility tree show an
empty name field and no keyboard. Those later observations do not establish
when focus was lost or why the original focus request failed. A subsequent
default-focus region followed Apple's [sheet example](https://developer.apple.com/videos/play/wwdc2023/10162/),
but hosted run `41959681684` stopped before input on the first home sheet:
setup expired after 21 keyboard queries, with the last returned count zero and
no input attempted. That change also added
the software-keyboard prerequisite, so comparison with the earlier passing
Ordinary run does not isolate the cause or establish the field's responder state.
The appearance observer now makes an explicit focus request at UIKit's
[post-presentation callback](https://developer.apple.com/documentation/uikit/displaying-and-managing-views-with-a-view-controller),
instead of relying on a default-focus preference or a pre-presentation task.
SwiftUI manages the observer's containment and layout; it neither accesses
private text-field internals nor changes the field's value.
The setup prerequisite now prevents input while the keyboard is absent; missing,
duplicate, late or throwing keyboard observations cannot start or renew input.
Localization's tap-based path does not require an existing keyboard before its
field tap. The complete hosted scenario must verify the lifecycle change.
The keyboard owner still uses its separate query because an application snapshot
can omit that sibling. These are sequential observations, not an atomic UI
transaction. In attempt 2 of hosted run `41733453608`,
indexed owner resolution took about 17.8 seconds while fetching the resolved
owner snapshot took 0.08 seconds. Continue resolution took another 6.6 seconds;
the setup watchdog cancelled the later tap lookup before event synthesis.
Short-circuit resolution reduces traversal work without increasing either
deadline. Its effect on hosted latency still requires a fresh passing run.

In beta run `41791887890`, the post-Continue field query took 5.144 seconds to
resolve, while fetching its snapshot took 0.012 seconds. Setup expired before
input. A recognized late introduction had also waited one polling interval and
been resolved again before Continue. The direct field snapshot and immediate
guarded action remove those redundant operations without increasing the
30-second setup or ten-second input allowance. They do not guarantee completion
under arbitrary service delays; the complete hosted journey must still pass.

In main run `41772302929`, native input's indexed name-field resolution took
13.340 seconds. The single input completed after its ten-second window, so the
test correctly failed before reading an echo. The failure screenshot shows the
complete requested name and the keyboard introduction; its arrival time is not
recorded. The field locator avoids full indexed resolution, and the final setup
observation prevents an earlier absence from authorizing input after the owner
has become visible. Neither change accepts late input or repeats typing; their
effect on the complete journey requires fresh hosted validation.

In hosted run `41689555867`, the former shared ten-second waiter interrupted
the first exact introduction-owner query before it returned a count. The native
session records the watchdog interruption and cancelled query; the failure
screenshot and accessibility tree show the real introduction and an empty,
focused Home field. No Continue or input action had occurred. The setup/input
split gives cold keyboard initialization its own finite allowance without
loosening exact-value checks. Thirty seconds is a bounded policy allowance,
not a measured guarantee of hosted latency. Neither phase may renew its
deadline, and a failed or late setup cannot start input.

The native `NameEntryAutofocusUITests` regression creates a home, room and item
on successive sheets using this same helper, then relaunches the same isolated
test namespace and verifies all three exact names. This targets the redundant
tap preceding a local empty room-name failure; it does not establish an OS-level
cause for the observed AutoFill menu or discarded input.

### Dismissal observations

`ElementDismissalReadiness` observes the count of the original, typed UI query
inside an active waiter. Its first probe has no initial predicate polling delay;
later probes do not overlap. Only a zero count returned within the original
ten-second monotonic window proves absence. An error or late result cannot
authorize progress, and XCTest issues remain failures. The preceding action
still happens once. The helper is shared by OCR Apply, editor Save/Cancel, name
entry, privacy dismissal and the Files transitions below. Each caller retains
its existing subsequent checks of navigation, saved values or exported bytes.

In run `41550393558`, the OCR navigation controller reported `ViewDidDisappear`
35 ms after the old dismissal waiter began. Its first predicate query started
1.039 seconds into the ten-second allowance and successfully returned no matches
after another 9.129 seconds, past the deadline. The subsequent failure screenshot
showed the applied model and price with the other fields retained. That screenshot
does not prove the complete persistence/export/restore journey. Immediate probing
removes the observed initial scheduling delay; it neither extends the deadline
nor guarantees that a slow accessibility query will finish in time. The cause of
that native query's latency remains unknown.

### Files location titles

The journey recognizes a Files location by its exact, unique, visible title
among a navigation bar's direct children: static text for local storage, or a
button labelled with the folder name followed by `, Actions Menu`. The known
suffix is removed when recording the exact folder name. The title button is
observed, never activated to enter its own folder. The bar itself can expose the identifier
`FullDocumentManagerViewControllerNavigationBar` instead of its displayed folder
name. On local iOS 27.0 the save picker already opened at `On My iPhone`; matching
the bar by that name failed and caused repeated taps on the noninteractive title.
Folder creation, navigation, the exact run-folder name and the saved-file evidence
remain mandatory.

Files can also create a new folder with a focused `DOC.inlineRenameField` text
view in the file grid. The journey requires this editor to be unique and ready,
replaces the selected default name, verifies the exact result and activates the
unique keyboard Done button. A ten-second folder-state observation then requires
exactly one title for the new folder. Each probe uses
`navigationBars.element.snapshot()` for the navigation-bar query with the exact
identifier `FullDocumentManagerViewControllerNavigationBar`. The entire expression
is inside the existing deadline checks, with no separate owner-count query.
XCTest's `element` requires a unique match: a missing or ambiguous owner fails the
test rather than becoming a pending title. Any thrown native error is preserved;
it is not converted to a zero count. The returned root must have the expected type
and identifier. Only direct children are inspected for the
exact typed title predicate; nested button text is not counted twice. The owner
and direct children are bounded to 4,096 nodes. One exact title establishes the
open folder; zero remains pending and duplicate titles fail. The title is not
activated, so this observation does not query its live enabled or hittable state.
Filename input and Save retain their live interaction guards. Every probe captures
afresh; unique resolution, snapshot and child inspection reject late results and preserve
native errors and cancellation within the original deadline. The successful
observation satisfies the existing folder assertions without repeating the title
query or navigation tap. Apple's [unique-element contract](https://developer.apple.com/documentation/xcuiautomation/xcuielementquery/element)
does not guarantee one internal traversal or RPC, nor completion within the
deadline. The creation diagnostic retains its last returned title count when a
later probe fails, without making additional UI queries. Exact saved-file and
restored-content acceptance remains mandatory.

In attempt 2 of run `41829513390`, eleven application-root snapshot requests
followed Done before the last request was interrupted. The failure capture showed
the exact target folder open under this Files navigation-bar identifier. The
snapshot API can omit remote Files nodes; the later debug hierarchy is a separate
observation and cannot establish the earlier counts or timely readiness. Resolving
the known owner before snapshotting follows the same scoped-observation approach
used for the keyboard introduction.

The subsequent run `41846510175` returned one exact title but exhausted the
ten-second window during the live hittable stage after 10.154 seconds. Its failure
capture showed the target folder open and empty. The marker does not record the
returned hittable Boolean, and the later capture cannot prove timely readiness.
The dedicated post-creation observation therefore checks the open-folder state
without requiring the title to be an interaction target. The revised path still
requires hosted validation; this failure is not a passing journey.

In attempt 2 of run `41859790648`, the separate owner-count query began at
316.69 seconds and the subsequent `firstMatch.snapshot()` resolution began at
323.91 seconds. That operation was interrupted by the waiter; creation elapsed
10.272 seconds without a returned title count. The failure capture showed the
created folder open, but no filename or Save action had been reached. Using the
unique resolver directly removes the separately requested count. It does not
establish a speedup or a passing journey; current hosted evidence is still required.

Runs `41814583789` and `41821314272` reached the new folder but exceeded the
ten-second readiness window. In the latter, accessibility-bound title enumeration
occupied about 8.9 seconds before live property checks; the window failed after
10.245 seconds. The later application-snapshot implementation removed that
enumeration, but did not establish title readiness in the attempt described above.
A speedup and successful current runtime still need hosted evidence. A failure
screenshot captured after the window cannot establish
timely readiness. The check does not query the
inline editor after Files removes it. In run `41618087432`, resolving that
disappearing editor exhausted the window even though Files had entered the new
folder. The positive title check passed in PR run `41627999490` and actual-main
run `41635226064`; in the latter it took 8.618 seconds. Interrupted, failed or
late observations cannot establish readiness. The exact folder title and open
state remain required before saving.
The earlier alert-based creation path remains available when that inline
editor is absent; neither path creates directories through a filesystem API.

Before Files opens, Recovery selects the share sheet's exact `Cell` with
identifier `actionGroupCell` and label `Save to Files`. Its nested static text
has the same label, so an all-element label query does not identify only the
action. The existing `FilesNavigationReadiness` selection path, also used by
the standalone RC runner, checks zero/one/multiple matches, enabled state and
native hittability, then performs one direct tap in the same active waiter.
This share transition has one 30-second monotonic allowance, including the tap;
there is no second generic wait or scrolling fallback. In-flight native queries
cannot be preempted by this helper, but late results cannot authorize a tap.

In PR run `41988596028`, the former all-element `firstMatch` query timed out
before any Save to Files tap. The teardown screenshot and typed accessibility
attachment later showed the action visible in `activityCollectionView`, with
the duplicate-label static text beneath it. They do not establish when the
action first became ready or prove that query breadth caused the native delay.
An earlier successful trace also exceeded the nominal ten-second existence
wait before tapping the cell. The combined allowance replaces that wait plus
subsequent unshared checks; it does not claim to cure native service latency.
Current hosted execution must still verify all three exports and their bytes.

After one real Save, return from the external Files service has a separate
30-second monotonic allowance. Each serial probe classifies one immutable app
snapshot. An observed Files action or alert blocks progress. A remaining share
sheet may receive at most one enabled, geometrically valid, natively hittable
Close action, identified under its unique owned header. Success requires unique,
enabled export and run-bound home anchors with positive, contained frames, the
exact home text under that home, and a fresh native hit test of the same home.
Each dashboard home link has the stable ID `inventory.home.<UUID.uuidString>`.
The selected snapshot button must have a canonical UUID ID, with no other button
sharing it. Nonbutton children may inherit the ID without making the button
ambiguous. Both Recovery and RC pass that exact captured ID to
`app.buttons.matching(NSPredicate(format: "identifier == %@", id)).element.isHittable` inside the same
30-second window, without a label-prefix query or `firstMatch` fallback.
Missing or ambiguous native targets cannot establish return; native errors and
late results remain failures. Geometric containment alone does not prove that
an overlay has gone away, so the live hit check remains required. Neither a missing remote
Files node nor closing the share sheet establishes success. The after-export
barrier must still verify the actual saved bytes.

In actual-main run `41635226064`, the first three snapshots returned pending.
The fourth was interrupted while resolving a remote AX element when the former
ten-second allowance expired. Home and Close were never hit-tested. A later
screenshot showed the dashboard, and a post-failure capture found a byte-equal
saved ZIP. These establish neither the exact earlier pending reason nor timely
return. Thirty seconds gives this external transition the same bounded readiness
allowance as initial Files presentation; the ten-second OCR windows and overall
XCTest/controller limits remain unchanged. It does not identify or eliminate the
underlying native latency. Late results and native errors remain failures, and
neither polling nor an error restarts the allowance.

In attempt 2 of run `41883603308`, folder creation completed in 5.193 seconds
and the first export return passed. The later backup return took 11.515 seconds
for the snapshot, then spent 18.862 seconds in the broad home hit query before
the 30-second window rejected the result. Its home-hit value remained null;
that does not distinguish an interrupted query from a Boolean returned too
late to admit. The later screenshot and hierarchy showed the dashboard, but
do not prove timely return. Stable-ID binding removes the second broad label
selection and ties the native check to the observed row. It does not guarantee
one internal RPC, faster completion, or successful end-to-end acceptance.

`ROOM_EXPORT_RETURN_V3` records bounded reasons/counts from those existing
snapshots and the current native stage, without another accessibility query or
private labels or home IDs. It distinguishes an admitted negative observation
from a query with no admitted result, including interruption or a late return.
The complete save/export/restore journey,
including all six byte-verification barriers, remains the acceptance gate.

The first-Files-tap diagnostic keeps selector attributes from one immutable app
snapshot, but Files' remote view may be absent from that snapshot. Its hierarchy
therefore uses the stable app root's later `debugDescription`, which includes the
remote picker. `hierarchy_observation` explicitly distinguishes these observations;
they are diagnostic evidence and do not authorize an action or prove acceptance.

Restore-file selection uses the exact typed hierarchy observed in the picker:
one `Browse View (Picker)`, its run-bound local-storage `DOC.browsingRoot`, one
`File View` collection and one cell whose identifier is the full backup filename
followed by `, roominventory`. Each scope must be unique before querying its
descendants. A single active ten-second window covers those live checks,
enabled/hittable readiness and one direct tap. Missing or noninteractive targets
remain pending; duplicate scopes, errors, late results and repeated selection
fail. The generic scrolling/tap helper is not used for this restore selection.
In run `41704117640`, that helper's repeated existence query ran outside its
waiter after the file had already been found. The scoped path removes that
unbounded query sequence; it does not establish the cause of native query latency.
`ROOM_FILES_SELECTION_V1` records the exact folder/filename, elapsed time, last
returned counts, current stage and tap admissions from existing operations only.
A timely tap still requires the replacement alert and all subsequent restore,
persistence and exported-byte checks; it is not itself proof of restoration.

The replacement alert can expose two nested `restore.confirm` buttons for one
visible Restore backup action. The journey accepts one button or a single nested
pair with the same exact identifier, label and nonempty frame, then selects the
leaf. The existing enabled/hittable wait and one real tap remain required; a
disabled, covered or ambiguous action still fails the test.

### Live export origin barriers

The test runner publishes six numbered requests in its own
`Documents/RecoveryJourneyBridge/<journey UUID>` directory: before and after each
of `source_zip`, `backup`, `target_zip`. Each request contains all three run IDs,
its role, phase, sequence and a fresh nonce. Each barrier has one 60-second
monotonic deadline starting before request publication, including the wait and
validation of a strict matching acknowledgement containing the exact request hash.
A late acknowledgement or interrupted wait fails; neither renews the deadline.
All requests and
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

Files can update a saved backup's metadata when the user opens it in the restore
picker. Raw snapshots retain its change time (`ctime`), but comparisons of saved
Files copies across observations require unchanged path, device/inode identity,
byte count, hash, modification time and birth time instead of unchanged `ctime`.
Generated app exports still require all recorded metadata to match. Every read
also retains its exact before/after stability check, including `ctime`, so a file
changing during collection still fails.

### Storage admission and abort policy

Admission requires **at least 24 GiB free** on both the output and simulator-device
filesystems before creating a device or building. During work, free space below
8 GiB aborts. Periodic full resource walks become due two seconds after the
previous successfully completed full accounting. During work every guard call
still checks the deadline and free-space floors, including calls before another
periodic walk is due. Forced accounting performs a full uncached walk except
inside the explicit sealed offline collection scope described below, which keeps
live output checks and brackets readers with full entry/exit censuses.
A completion timestamp is published only after all root walks, sample persistence
and a final deadline check succeed; failed, interrupted or late accounting does
not advance it. This prevents a long walk from immediately triggering another
periodic walk merely because its start was more than two seconds ago. It caches
no resource values and does not establish that a later install or test will finish
within its unchanged command cap.

The controller uses bounded `lstat` walks without following symlinks. DerivedData has a **4 GiB
allocated disk budget** (`st_blocks * 512`); its logical length is recorded
separately, so sparse cache reservations do not consume that disk budget. The
DerivedData root directory's own allocation is charged before visiting children,
including an empty root; root `lstat` and block validation are deadline checked.
Missing, negative or non-integer block counts fail closed: logical length is not
an upper bound on allocated storage. All other roots still enforce the larger
of logical and allocated bytes. Reaching a sampled cap also aborts: new device 8 GiB,
other attempt output 1 GiB, finalized original xcresult 192 MiB, verified
xcresult copy 192 MiB, exported attachments 128 MiB and logs 64 MiB. While the
exact owned UI-test producer is active, its original xcresult has a separate
512 MiB working allowance within the same 1 GiB output cap. While this exact
producer is active, a child of its original result may disappear between
directory enumeration and `lstat`, or before opening an already queued child
directory. Only these two `ENOENT` boundaries are eligible, in both the total
output and dedicated result scans. The output directory identity is bound at
creation; the result identity is bound on its first ordinary-directory
observation, including first appearance during an output scan. Root loss,
replacement, unrelated output loss, observer/iterator errors and other I/O
errors remain fatal. Attempted entries still consume the work cap, and queued
directories retain their already observed allocation. Deadlines and byte caps
are unchanged. This is a live sample, not an atomic filesystem snapshot.
The child-disappearance policy and working allowance are
revoked before terminal accounting; final original inventory, copying, readers
and retention still require the 192 MiB bound. A failure does not authorize
copying or reading an oversized final bundle. Each command
stream is additionally limited to 16 MiB. The collector limits its own writes to
512 MiB and rejects copies that cannot fit its remaining allowance. Every complete
sample and byte-cap crossing identifies its `cap_metric` as `allocated` or
`max_logical_allocated`. No unknown allocation is reported as zero or estimated
from logical size. Hardlinks remain conservatively charged per directory entry;
each entry and every later walk obtain fresh metadata, including later growth.
Entry-count, deadline, exclusions and cleanup bounds are unchanged.

This is an explicit correction to the earlier policy that applied the 192 MiB
final-artifact bound to Xcode's live staging directory as well. On local Xcode
27.1 / iOS 27.0, the recovery test reached its restored original preview but raw
AUT and session logs reached about 159 MB and 33 MB before result finalization.
A bounded ordinary-test comparison found that the public
`-collect-test-diagnostics never` option did not meaningfully reduce these logs,
so the controller does not use it or private logging controls. With both
attachment lifetimes set to `keepAlways`, that comparison retained complete
logs through finalization; its live bundle was about 39 MB and its final bundle
about 29 MB. These measurements distinguish staging from the final artifact;
they do not prove that a full recovery result will fit either bound.

The recovery configuration now retains user attachments with `keepAlways` and
uses `deleteOnSuccess` for Xcode's automatic system attachments. All 17 explicit
checkpoint PNGs, 17 accessibility trees, bridge receipts and final evidence JSON
remain required and kept on success. Failure system diagnostics remain eligible
for retention under the existing final-bundle and packet limits. No log is
truncated or deleted by the controller to make a result pass. The real UI
actions, assertions, collection provenance checks and offline verifier are
unchanged by this lifecycle policy.

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

Hosted discovery command receipts may include a fixed `discovery_observation`
summary. It records the last entered/completed source operation, tick site and
check substage, Popen-result assignment, returned select/poll counts, a separate
`poll_seen` flag, and per-pipe returned reads/bytes, bytes appended to the in-memory
buffer, EAGAIN count and observed EOF. Retained bytes mean buffer retention, not
durable log publication. EOF is marked only after an empty read. `poll_seen=false`
with a null result is unobserved; a returned null means running at that poll only.
Counters saturate at 2^31−1 and then are lower bounds, with both `saturated` and
`capture_incomplete` set. A primary error during the observed execution marks its
observation incomplete. A cleanup-only failure does not change this pre-cleanup
summary; the flag does not certify overall command or cleanup success.

The summary uses no new clock calls. Its optional `clock_sample` is the last
already-acquired alarm-check/arm, work-comparison or selector-timeout sample, with
explicit provenance and elapsed time rounded to six decimals within 0–86,400
seconds, or null. It is not the timestamp of the last stage, native exit or
snapshot capture. No operation duration or synchronous-versus-alarm origin is
inferred. Entry without completion means no completion was recorded: interruption
can occur after a call returns but before its marker, including EOF, assignment
and counter updates. Even `capture_incomplete` is best effort; its absence does
not prove a complete observation history. No output and an open pipe establish
neither native readiness nor the cause of a delay.

The failure snapshot is captured only after saving the original primary error
and before cleanup; cleanup/receipt checks cannot rewrite that boundary. Ordinary
diagnostic control interruptions still fail the command and run owned cleanup.
Capture after an established primary is best effort and cannot replace it.
The fixed summary has no payload, environment, paths, exception text or history;
its serialization, including the command nesting, is limited to 2 KiB only in
the existing post-cleanup receipt path. A serialization failure follows existing
receipt-failure handling and preserves the first primary and sticky cleanup
errors. A snapshot may remain only in memory if receipt time is exhausted.
Admission failures before the existing command record are still unobserved.
Discovery polls its direct child in every selector iteration, including while
inherited pipes remain open. A failed exit triggers one nonblocking read of each
ready pipe before failure, retaining available diagnostics without waiting for
EOF. The receipt records an observed nonzero exit even if later stream or cleanup
checks fail. A zero exit is recorded only after both EOFs and a final deadline check;
the command also requires
confirmed owned-group cleanup before the command succeeds. The one-pass list,
120-second discovery envelope, 90/86/4-second inventory allowance, other caps
and signal ownership rules remain unchanged. Injected tests compare the existing
non-poll operations and clock boundaries; this does not imply zero scheduling cost.

One outer controller owns the complete attempt and every subprocess process group.
Use monotonic absolute deadlines; no phase may renew the outer budget. The total
ceiling is 1,800 seconds, reserving the last 60 seconds for cleanup. Phase caps are
preflight/project generation 120s, build 720s, nominal create/boot/seed 180s, UI execution
840s, evidence collection/verification 240s; each is additionally capped by the
remaining outer budget minus cleanup reserve. These caps are limits, not a promise
that a cold build fits. The device phase's shared startup deadline is clipped to
660 seconds from controller start, reserving the full 840-second test and
240-second collection phases within the 1,740-second work budget. Do not begin a
phase without enough cleanup time left.

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

Exception receipts may add `exception_origin` beside the unchanged `primary_error`
object, or inside an existing cleanup/finalization error receipt. This optional
metadata records a closed reason, capture site and last reached stage, plus at
most eight source basename/line pairs from at most 32 traceback nodes. Only the
four recovery modules are mapped; external frames have no filename or line.
No exception values, arguments, locals, source text or absolute host paths are
added. Fixed labels, frame counts and line bounds keep each observation below
2 KiB, including its indentation in the existing JSON receipts. Truncated or
unmapped origins are marked explicitly; an unreached innermost frame is unknown.

`last_stage` is a checkpoint, not proof of the instruction that raised: a finally
block may advance it before an outer catch. Compare the source frames and the
earliest command/cleanup observation with the outer observation. A child's zero
exit and successful group cleanup still do not establish successful command
return, device boot or shutdown. These diagnostics do not change deadlines,
signals, commands, cleanup or acceptance. Capture is best effort after an error
is recorded and uses existing receipt writes only; failed/interrupted final
writes may leave the observation only in memory. Retention preserves `run/result.json`
bytes and accepts additive fields without relaxing its existing gates. The hosted
adapter's summary is not a substitute for that retained controller receipt.

`resource_scan` adds one current and one last traversal observation, with a closed
root category and optional start/end/duration in elapsed monotonic seconds.
`started` means completion has not been observed; `returned` means `tree_size`
returned; `failed` means it raised. A missing end or duration remains unknown,
even when return/failure is known. These are wrapper spans, not per-entry timing
or proof of what consumed the command budget. Error capture snapshots this pair
in the command's `process_observation.resource_scan_at_failure` or the controller's
`failure_resource_scan`, so later cleanup scans cannot rewrite the earlier state.

The Recovery controller also retains fixed per-category `resource_scan_cost`
aggregates in the owning command receipt, with a separate aggregate for work
outside a command. These preserve counts and summed/maximum measured wall and
controller user/system CPU time after the current/last spans have been replaced.
Wall durations reuse the existing scan timestamps. Two optional
`getrusage(RUSAGE_SELF)` observations bracket each `resource_size` invocation;
there is no CPU observation per entry, new subprocess or additional receipt write.
Missing, regressing or invalid measurements remain explicitly incomplete.
Returned/failed counts describe the wrapped scan body before the final CPU probe.
A control interruption in that probe can still fail the command after a recorded
return; command errors, exit status and cleanup remain authoritative.

These costs include cooperative pipe servicing and direct log validation nested
inside that scan. Direct `tree_size` calls outside `resource_size` are not separate
measured scans, so the aggregates are not total controller CPU usage. They do not
measure native child CPU, host load, physical I/O or the reason a process waited.
Counts and measurements never determine resource acceptance or scan cadence.
The existing caps, full terminal accounting, ownership checks, deadlines and
cleanup remain authoritative; diagnostic failure cannot replace an existing
operational error.

This instrumentation follows the historical diagnostic-source hosted run
`41467655923`, where the first PhotosPicker presentation remained loading and
its launch request preceded
process creation by 20.740 seconds. Four completed resource-accounting sweeps
overlapped the Photos wait and visited 83,849 metadata entries. That overlap does
not establish contention or explain the delay. That historical packet retained no
per-scan cost history or CPU measurements, so a passing instrumented journey
alone would not prove a repair or qualify the ordinary release source.

Each existing command receipt may add `process_observation`: the last observed
selector state, stdout/stderr EOF only after an existing empty read/unregister,
and the first retained observation of an integer child return code (`first_observed_exit`). Exit source is `poll`, `wait`,
`cleanup_return` or `final_cleanup_return`; the latter two timestamp receipt of the existing cleanup result,
not its internal reap or actual process exit. Empty selector state does not imply
pipe EOF. Missing fields/times mean unobserved or unavailable, never success.
`capture_incomplete` marks an observer error: earlier observations may be missing,
so the first retained exit is then not claimed to be the earliest observed exit.
That flag is itself best effort; its absence does not prove a complete history.
The observation helpers themselves preserve the outer selector/poll short circuit
and add no process calls or receipt writes. The cooperative supervision prototype
below separately adds bounded service and a terminal resource barrier.

The runtime observation helper adds clock reads only at each scan start/end, each
observed pipe EOF and the first captured exit result. Separate child/accounting
boundary samples are described below. Their timestamps use the injected
monotonic clock, round to six
decimal places and accept only finite elapsed values from 0 to 86,400 seconds;
that metadata bound does not extend any execution deadline. Ordinary-path alarm
and interruption exceptions still propagate to the existing failure handlers;
an observer failure cannot replace an already active primary exception.
Post-failure origin/snapshot calls and failed-scan completion observations are
protected at their call sites as well as inside the diagnostic helper. Cleanup
return metadata is similarly optional once an operational or cleanup failure has
been recorded. Ordinary-path control interruptions retain the existing failure
handling. This contains faults in these guarded diagnostic calls; it is not a
claim of immunity to asynchronous interruption at every surrounding instruction.
Closed labels and fixed record shapes bound the current/last pair, one command's
full process observation and the top failure snapshot together below 2 KiB in
the existing indented JSON. There is no per-entry or scan history; one process
record belongs to each already-existing command, with no added command/retry loop.
This diagnostic preparation establishes neither the historical delay's cause
nor native recovery acceptance.

### Cooperative DerivedData supervision prototype

While an owned command is active, only the DerivedData walk uses a cooperative
service checkpoint. Output and log walks, pre-spawn work and cleanup use the plain
deadline tick. At 64 returning checkpoints or 50 ms since the last service, the
checkpoint performs at most one `select(0)`, one read of up to 65,536 bytes from
each of the two known pipes, and one poll of that child. Ready order does not
permit repeated stdout reads to starve stderr or traversal. EOF still requires
an empty read; a zero leader exit does not establish EOF or absence of descendants.
The earlier poll is an intentional ordering change and can reap the leader earlier.

Each service first repeats the existing 8 GiB free-space floor check on the output
parent and simulator device base, with a deadline check after each query. These
are additional filesystem queries. Stream limits remain 16 MiB per pipe. Writes
must report the complete byte count; short/error writes fail. In the cooperative
service, a read or write returning after the deadline, or a partial write, fails
before `buffers.extend`. Bytes already read may be absent from the raw log, and
bytes already written may be absent from the buffer used for its stream digest.
Such a failure leaves incomplete evidence: neither raw byte completeness nor
agreement between the stream digest and its file is guaranteed. After successful
persistence and buffer accounting, a direct log walk with the plain tick enforces
the existing 64 MiB
`max_logical_allocated` bound and 256-entry limit before another service. It keeps
the active DerivedData span intact and attributes a byte crossing to `logs`.
No service invokes guard, collection/bridge callbacks, nested commands or flush.
An identity and reentry check protects the command-local hook; it is cleared
before all cleanup and cannot carry into a later command.

The private completed-child handoff may interrupt only the command loop's outer
guard, which catches and validates that exact per-command signal. Collector
callbacks retain cooperative pipe draining, child polling, ownership checks and
the same deadline, but their guarded resource walks must finish normally. A
callback is never interrupted by this internal handoff or replayed after partial
work. An actual callback error still fails the command. After a handoff, normal
wait, owned-process cleanup and the fresh full accounting barrier remain required.

Child exit never skips or accepts an incomplete walk. For operational commands,
the terminal pipe condition and allowed wait result must still pass a tick under
the original command work deadline (`end - 4`). The hook is disabled before
selector, stream and owned-group cleanup, which retain the original `end` and
sticky cleanup deadline. Every close must return without errors; group absence,
leader reap, an error-free successful report and a cleanup return strictly before
`end` are required. A late success report does not authorize continuation.

Only after that confirmed cleanup, a fresh complete `guard(force=True)` runs
under the armed original `min(phase_end, work_end, outer_end)`, followed by a
deadline tick, before command success or another command. The old command timer
is disarmed after bounded cleanup and before the phase-bound arm; a pending old
alarm still fails closed. No phase is reset and no cleanup reserve is borrowed.
Preflight, pre-Popen and live guards are unchanged. This moves only terminal
accounting out of the child-work allowance; all resource caps, allocation metrics,
free-space floors, entry limits and the full barrier remain. Owned-group absence
does not prove simulator or DerivedData quiescence, so no root is cached or skipped.
Accounting and subsequent device commands share the original nominal startup
allocation of 120 seconds for preflight + 720 for build + 180 for device, but its
1,020-second sum is clipped to 660 seconds from controller start. This reserves
the full 840-second test and 240-second collection allowances within the existing
1,740-second work budget. Preflight and build retain their own phase caps; unused
time remains available for device preparation and its full accounting only before
that fixed 660-second boundary. A build that consumes its entire nominal allowance
cannot then enter device preparation. The 1,800-second outer deadline and
60-second cleanup reserve remain unchanged. Reentering the device phase cannot
renew its absolute startup deadline. Every command remains clipped to this phase
and its own finite cap; all resource walks, identity checks and cleanup requirements
remain mandatory. The single boot-status command allows 300 seconds, including
four seconds for process cleanup (296 seconds for child work and live accounting),
and is clipped to the same absolute startup deadline. This accommodates
[Apple's documented several-minute first launch](https://developer.apple.com/documentation/xcode-release-notes/xcode-27_1-release-notes)
without adding a retry or extending the overall attempt. Successful boot still
requires a fresh complete terminal resource walk and does not replace UI acceptance.
App and runner installation each allow 90 seconds, including the
existing four-second process-cleanup allowance (86 seconds for child work and live
accounting). Both remain single attempts inside the effective 660-second startup pool.
This finite hosted cold-start allowance does not predict installation latency or
turn prior timed-out runs into accepted evidence.

The single `simctl privacy ... grant photos` command for the owned test runner
also allows 90 seconds, including the same four-second cleanup reserve, and is
clipped to that original 660-second startup boundary. In run `41963934642`,
the previous 30-second cap left only 26 seconds for child work and live resource
accounting. The command still had no observed exit after 68 cooperative polls;
the last completed service checkpoint was 0.311 seconds before that work
deadline. The deadline was raised during a DerivedData walk, but these polls
do not support a claim that an already-finished command was hidden by the walk.
The reason for the native command's latency remains unknown. The new allowance
matches installation; it does not add a retry, skip accounting, extend the
startup pool or treat that failed run as accepted. Timely exit, both pipe EOFs,
owned-group cleanup, fresh complete resource accounting and the later PhotoKit
authorization/content checks remain required. No XCTest case ran in that failed
attempt (`test_count == 0`).

The 660-second startup allowance addresses the observed failure before app installation,
where successful boot/bootstatus and full resource accounting consumed nearly all
of the earlier 180-second device phase. It does not guarantee filesystem or
simulator latency, collector completion, XCTest success or simulator shutdown;
any exhausted command, phase or outer deadline still fails the attempt. No
historical failed run becomes accepted.
The runner's single PhotoKit seed replaces `simctl addmedia`, which exhausted its
90-second command cap in both attempts of run `41574541714` before any UI test
executed. The new seed window is 86 seconds, equal to the former command's work
allowance, within the unchanged native/controller limits. It supplies explicit
creation completion and original-byte evidence; it does not establish the cause
of the prior service latency or guarantee success. There is no retry or second
seed. Exact fixture/UDID binding, full terminal accounting, cleanup and later
PhotoKit/UI content checks remain required.
In `cleanup_mode`, the existing guard returns after its deadline tick and remains
time-only, so a resource failure cannot prevent required cleanup. The same call
does not perform a full resource barrier for cleanup commands.
The outer log drain also checks complete write counts.

The command's `elapsed_seconds` remains total elapsed through accounting up to
the existing receipt boundary, rather than child duration alone. Optional
`child_completed_elapsed` samples the post-wait work check; it is not actual OS
exit time. `cleanup_completed_elapsed` reuses the existing post-cleanup clock.
`post_command_accounting` holds fixed `start_elapsed`, `deadline_elapsed`,
`end_elapsed` and `status` fields (`STARTED`, `COMPLETED` or `FAILED`), with a fresh
start sample at the accounting transition. Times are bounded to 0–86,400 seconds,
rounded to six decimals or null; missing/faulted timing is not evidence of success.
Accounting failure uses the closed `command_accounting` stage and preserves its
primary error through best-effort timing/origin capture and later receipt failures.
Barrier completion, receipt success, group cleanup and simulator shutdown remain
separate facts. Failed cleanup skips accounting and leaves its barrier flags false.

This is cooperative service, not a worker or a latency guarantee. A single blocked
stat, select, read, write, disk query or log walk cannot be preempted by the hook;
the original alarm and next returning deadline check remain the bounds. DerivedData
span time now includes pipe service and nested log validation overhead, rather
than measuring pure traversal. Accounting continues to sample a changing tree;
it is not an instantaneous disk quota. Interleaving can change which real failure
is observed first. Fake before/after operation counts establish progress between
returning checkpoints only, without demonstrating native speedup, historical
causation or recovery acceptance.

Operational command receipts may add `derived_service`, a fixed aggregate for
active DerivedData service only. `quanta_started` counts entry into eligible
service work, even if it fails before I/O; `quanta_completed` counts reaching
the existing final checkpoint after service and its deadline tick. Each pipe's
`read_returns` counts successful read returns, including empty EOF returns;
`eof_returns` counts those empty results and `would_block` separately counts
`BlockingIOError`. Other read exceptions are not successful returns.
`read_bytes` counts bytes actually returned before the subsequent deadline or
write check. It does not claim those bytes were persisted, accepted into the
digest buffer, or retained. `polls_returned` counts service poll returns, including
`None`; outer-loop and cleanup polls/reads are excluded.

`first_completed_checkpoint_elapsed` and `last_completed_checkpoint_elapsed`
sample the already obtained completion clock value relative to controller start.
That clock is sampled before the existing final deadline tick; the completion
event is recorded only after the tick returns. It is a sampled checkpoint time,
not the later metadata capture time.
They add no clock queries and are not start times, actual child-exit times or
durations. An unfinished quantum has no completion timestamp. Values are finite,
rounded to six decimals within 0–86,400 seconds; an invalid or backwards sample
is null and marks capture incomplete. A null first sample is not replaced by a
later completion. The incomplete flag stays set after a bad sample; a later valid
last value does not prove a monotonic history. `terminal_barrier.reached` marks reaching the operational call
boundary; `completed` marks return from the applicable guard and following deadline
tick. For sealed offline readers the sample explicitly identifies omitted device
and DerivedData categories; these are covered by the required entry/exit censuses. Neither means command cleanup or the whole run succeeded. Cleanup-mode
commands omit this aggregate: their time-only guard is not a full barrier.

All integer counters saturate at 2,147,483,647. Saturation sets both `saturated`
and `capture_incomplete`; saturated values are lower bounds. Capture is best
effort: an interrupted command or observer error may leave partial fields, and
even the incomplete marker can fail. Missing aggregates or zero counts with
incomplete capture do not prove absence of work. Ordinary control interruptions
still fail the command; the post-primary marker call is protected at its caller
as well as inside the observer. The fixed shape contributes less than 2 KiB to
the existing indented receipt and adds no history, scans, flushes, clock calls,
threads or native work. Aggregates survive the existing terminal guard and cleanup
without being reset, and are saved only by existing receipt writes.

### Sealed offline result collection

After the single UI command succeeds and its owned process group is confirmed
absent with its leader reaped, the collector captures the final live inputs.
It requires all six bridge barriers and three origins, compares the final Files
and generated-export view with the last barrier, and copies both namespaces,
the six export payloads and the exact fixture. Existing generated-file metadata
checks and the narrower saved-file metadata comparison remain unchanged. The
one-use `live-input-seal.json` binds the run, device, roots, source manifests and
captured bytes; a failed or changed seal cannot be repaired by recapturing.

Before native result readers, the controller shuts down only the owned Simulator
UUID, confirms exactly one matching `Shutdown` inventory entry, rechecks the seal,
and completes an uncached device and DerivedData census. Only this explicit
collection scope may omit repeated device/DerivedData traversals during readers.
Its resource samples label those omitted categories and refer to the entry census;
they do not claim fresh device sizes. Root identities, free space, total output,
original and copied xcresult, attachments and logs remain checked. The three
ordered readers accept only the verified copy, never the original or a live
container. Each retains its 40-second cap; collection retains 240 seconds and the
whole run retains 1800 seconds, including shutdown and the final census.

The single normal-path `collection-shutdown` command allows 90 seconds, including
four seconds for owned-process cleanup. Its 86-second work window is still
clipped to the original 240-second collection phase and overall work deadline.
In main run `41979396891`, the UI test passed, but this command had no observed
exit or pipe EOF before its former 21-second work window ended, despite 292
returned device-service polls. That evidence does not establish the cause of the
native delay or show an already-finished command hidden by resource accounting.
The new allowance adds no retry or deadline renewal: successful group cleanup,
exact `Shutdown` state, seal revalidation and full resource accounting remain
required before readers begin. The separate emergency-cleanup shutdown retains
its 25-second cap and the existing 60-second final-cleanup reserve. The failed
run remains unaccepted, including its cleanup errors.

After readers and offline artifact verification, the source/captured content and
original xcresult are checked again and a full uncached resource census is
mandatory. Final checks are attempted even when a reader fails; a secondary
failure cannot replace the primary error. No reader retry or live recapture is
allowed. Failed UI runs still attempt original xcresult preservation and normal
owned cleanup. This phase change addresses repeated live resource traversal
observed during result collection; it does not prove the prior native reader
hung, guarantee hosted latency, or accept any previously failed run.

### Owned cleanup

After evidence collection (or any earlier failure), terminate only the app/test
runner and groups launched by this attempt, shut down its exact simulator UDID
if it is not already shut down, and confirm shutdown and all
owned group leaders reaped. Preserve the dedicated device and evidence for review;
do not delete the device, DerivedData or its Files folder during this first run.
No changes to existing QA devices, accepted source/candidate/evidence, global
Photos/Files data, signing accounts, remote CI or repositories belong in cleanup.
Record free-space samples as discrete observations, not a claimed global
minimum. A failed initial device-state query must still allow shutdown of the known
owned UUID and a separate final-state query. The initial query allows up to 20
seconds of child work plus four seconds for owned-process cleanup (24 total).
Shutdown retains its 25-second cap. The final inventory allows 26 seconds of
child work plus the same four seconds for owned-process cleanup (30 total).
These requested caps sum to 79 seconds; they are not a new cleanup reservation. Every command is
clipped to the original absolute outer deadline. If cleanup begins with only the
60-second reserve and earlier commands consume their full caps, the final query
has at most 11 seconds total (seven for child work), and may fail. Insufficient
admission time prevents a new child; prior failures remain sticky. If cleanup
cannot complete inside the remaining time, retain evidence, report the remaining
exact owned resources and return nonzero without an automatic retry.

In run `41363140553`, shutdown returned zero but the separate final inventory
query exhausted its former 11-second work allowance with no output and no
observed exit. More than 900 seconds remained in the outer budget. Its owned
group cleanup recorded `EPERM`, so neither cleanup success nor final Shutdown
was established. The larger final-query allowance addresses this local timeout
without changing the outer deadline, repeating the query, or clearing that
failure. A future run still has to prove timely exit, valid JSON for the exact
owned device, Shutdown state and successful group cleanup.

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

### Hosted inventory cold-start allowance

The single `xcrun simctl list --json` discovery request has a 90-second maximum:
86 seconds for work and the existing four seconds for owned-group cleanup. This
reallocates up to 30 seconds within the same absolute 120-second discovery window.
It does not establish an OS or product repair and does not retry the command.
The 1,800-second controller, 180-second retention reservation, 2,100-second adapter
envelope, 45-minute job timeout, ownership checks and resource limits are not
changed by that discovery allowance; the result-lifecycle limits are defined above.

The installer still requests 70 seconds, clipped to the original discovery end.
If R seconds remain at inventory entry, its total command deadline is at most
`min(90, R)` seconds away. If that whole allowance is consumed, at most
`max(0, R - 90)` seconds remain for the installer; its work deadline is four
seconds earlier. Every command still needs at least eight seconds remaining to
start. An exhausted discovery window cannot borrow from the full controller plus
retention reservation of 1,980 seconds.

The retained run 40660819848 reached inventory at monotonic 85.627825208,
2.386114708 seconds after the first recorded source command. The adapter's
absolute start is not in that command receipt, so the remaining discovery time
is bounded, not known exactly: `60 <= R <= 117.613885292`. The old full 60-second
request proves the lower bound; host validation before the first command can
reduce the upper bound. Under maximum new inventory consumption, remaining
installer time is therefore at most 27.613885292 seconds, and may be insufficient.
Earlier native deadline and EPERM cleanup failures remain failures even when
final group absence and leader reaping are subsequently observed.
