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
   known installed runtime and a unique recorded UDID/name. Do not assume its
   Photos library is empty; the bound runner verifies and isolates the fixture. Never use `booted`, erase a shared device, or clean a global
   simulator directory. Fail preflight if there is insufficient free storage or
   another native job would violate the host's coordination slot.
3. Generate the Xcode project from `project.yml` with the pinned repository helper.
   Perform one `build-for-testing` with an attempt-owned DerivedData path, unsigned
   Debug simulator settings and only the UI test target selected. Preserve the
   build log, exact command/exit, explicit build options and produced `.xctestrun`.
4. Boot that UDID and install the freshly built app and UI test runner without
   launching them. Import **only** the exact fixture once using `simctl addmedia`;
   retain its source hash and command result. Record the preinstallation container
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
   `-test-timeouts-enabled YES`, and `-maximum-test-execution-time-allowance 420`.
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
and runner bundle IDs, phase and fresh nonce. Its strict request-hash ACK uses the
existing 20-second wait inside the unchanged XCTest allowance and controller test
phase; no deadline is renewed.

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
launching the data-bearing scenario, the UI-test runner verifies and isolates the
seed using PhotoKit. The controller validates the actual built runner's Photos
usage description and grants full Photos access only to that runner on its newly
owned device. The app's privacy permissions and built payload are unchanged.

The runner also checks the actual Simulator UUID, runner bundle, usage description
and full read/write authorization. One 20-second monotonic deadline inside the
unchanged XCTest/controller limits covers at most 64 local assets, at most eight
resources per asset, the unique named 1400×1800 PNG, and two network-disabled
resource reads of at most 74,736 bytes each. Both reads must match the source
fixture's SHA-256. After a stable inventory re-read, one PhotoKit change removes
only the other asset IDs. The fixture itself is never deleted, replaced or seeded
again. A per-change system confirmation, when presented, must name this runner and
the exact removal count; only its Delete button may be tapped, at most once.
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
8 GiB aborts. Periodic full resource walks become due two seconds after the
previous successfully completed full accounting. During work every guard call
still checks the deadline and free-space floors, including calls before another
periodic walk is due. Forced accounting always performs a full uncached walk.
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
External-call/clock trace parity in fakes does not imply zero scheduling cost.
Discovery's one-pass list, short-circuit poll, 120-second envelope,
90/86/4-second inventory allowance, other caps, signal and cleanup ordering
remain bounded as described below.

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
Accounting and subsequent device commands share the original startup allocation:
120 seconds for preflight + 720 for build + 180 for device, ending at 1,020 seconds
from controller start. Preflight and build retain their own phase caps; unused
time from those phases remains available for device preparation and its full
accounting. This is redistribution within the existing 1,740-second work budget,
not an extension: device completion is also clipped before the full 480-second
test and 240-second collection allowances. The 1,800-second outer deadline and
60-second cleanup reserve remain unchanged. Reentering the device phase cannot
renew its absolute startup deadline. Every command remains clipped to this phase
and its own finite cap; all resource walks, identity checks and cleanup requirements
remain mandatory. App and runner installation each allow 90 seconds, including the
existing four-second process-cleanup allowance (86 seconds for child work and live
accounting). Both remain single attempts inside the same 1,020-second startup pool.
This finite hosted cold-start allowance does not predict installation latency or
turn prior timed-out runs into accepted evidence.

This finite allowance addresses the observed failure before app installation,
where successful boot/bootstatus and full resource accounting consumed nearly all
of the earlier 180-second device phase. It does not guarantee filesystem or
simulator latency, collector completion, XCTest success or simulator shutdown;
any exhausted command, phase or outer deadline still fails the attempt. No
historical failed run becomes accepted.
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
boundary; `completed` marks return from its full guard and following deadline
tick. Neither means command cleanup or the whole run succeeded. Cleanup-mode
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

### Owned cleanup

After evidence collection, terminate only the app/test runner and groups launched
by this attempt, shut down its exact simulator UDID, and confirm shutdown and all
owned group leaders reaped. Preserve the dedicated device and evidence for review;
do not delete the device, DerivedData or its Files folder during this first run.
No changes to existing QA devices, accepted source/candidate/evidence, global
Photos/Files data, signing accounts, remote CI or repositories belong in cleanup.
Record free-space samples as discrete observations, not a claimed global
minimum. A failed initial device-state query must still allow shutdown of the known
owned UUID and a separate final-state query. The initial query allows up to 20
seconds of child work plus four seconds for owned-process cleanup (24 total).
Shutdown and final inventory retain their 25- and 15-second caps. These requested
caps sum to 64 seconds; they are not a new cleanup reservation. Every command is
clipped to the original absolute outer deadline. If cleanup begins with only the
60-second reserve and earlier commands consume their full caps, the final query
has at most 11 seconds total (seven for child work), and may fail. Insufficient
admission time prevents a new child; prior failures remain sticky. If cleanup
cannot complete inside the remaining time, retain evidence, report the remaining
exact owned resources and return nonzero without an automatic retry.

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
envelope, 45-minute job timeout, ownership checks and all resource limits stay fixed.

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
