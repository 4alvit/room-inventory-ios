# Hosted recovery scenario

This is the hosted adapter for the opt-in [recovery journey](recovery-journey.md).
Source review and injected tests do not establish a successful native run. The
first execution needs a separately approved source commit and CI cohort.

## Where the job runs

The existing callable `ci.yml` adds one `recovery` job after `ios`. The job uses
the standard `xcode-27` runner class, read-only repository permissions
and the same pinned checkout, Python and artifact actions. Recovery and Simulator
packaging require an actual `arm64` host and Xcode 27.1 build 27A9275 on
`ImageOS=macos27`. Core, app unit and ordinary UI tests use `macos-26` with
Xcode 26.4.1 build 17E202, iOS 26.2 and iPhone 16e. Swift CodeQL also requires
that exact Xcode 26.4.1 toolchain on macOS 26 for its supported tracing path.
Neither group falls back to another runner or toolchain; the reasons are described
below. Recovery retains its 24 GiB admission floor. The PR preview now
needs both `ios` and `recovery`. A failed recovery job therefore fails the existing
required reusable validation; the generated Quality gate is unchanged.

One push to a branch with an open PR triggers the existing Quality gate through
`pull_request/synchronize`. Its expanded job inventory is:

1. Change scope.
2. CI configuration contracts.
3. Release tooling contracts.
4. Core and iOS tests.
5. Recovery journey, after the Core and iOS tests.
6. PR Simulator candidate, after both iOS and recovery, for a same-repository PR.
7. Swift security analysis.
8. Python tooling security analysis.
9. Actions security analysis.
10. CI gate.

These are ten workflow jobs for a successful same-repository PR cohort, not a
promise about the number of platform-generated check runs. Existing Core/app
tests, CodeQL builds and preview packaging still run; the one-build/one-test limit
applies specifically to the new recovery scenario. No new push trigger or separate
workflow is added. A branch push without an open PR does not trigger these files.

The existing `main` push, schedule and non-stable manual release paths call the
same validation through `release-pipeline.yml`; its release build may run in
parallel with checks, while publication remains behind its existing gates. Manual
stable promotion retains its separate checked-RC path. Release contracts, CodeQL,
action pins and publication permissions are not weakened.

## Toolchain qualification

The 2026-10-31 Core run on Xcode 16.4 reported an expired **StoreKit Testing in
Xcode** certificate (`NSOSStatusErrorDomain -67818`), followed by
`failedToVerifyCertificateChain` during the catalog-failure test's purchase setup.
The app correctly refused an unverified transaction. This is separate from the
catalog-failure and refund assertions, which kept their original expectations.

The subsequent Xcode 26.3 cohort passed Core and iOS tests, but recovery discovery
still timed out while querying the simulator inventory. Xcode 26.4.1 build 17E202
was then selected because [Apple's Xcode 26.4 release notes](https://developer.apple.com/documentation/xcode-release-notes/xcode-26_4-release-notes)
document fixes for `simdiskimaged` hangs under memory pressure (172343027) and
automatic runtime cache creation (170836966). Its iOS 26.4.1 runtime failed native
StoreKit configuration operations with `SKInternalErrorDomain Code=3`, matching
symptoms of FB22237318 acknowledged by Apple DTS in the
[developer forum](https://developer.apple.com/forums/thread/826971). Explicitly
selecting iOS 26.2 restored the native purchase tests. Aligning both jobs to iPhone
16e and completing runtime-cache preparation did not resolve repeated fresh hosted
Recovery boot-readiness failures. These observations do not identify the internal
cause of the hangs or prove that the reported Apple defects caused them.

The next qualification uses GitHub's standard `xcode-27` ARM64 runner, which became
[generally available on October 15, 2026](https://github.blog/changelog/2026-10-15-xcode-27-runner-image-generally-available/).
The repository's older preview badge is stale. The
[versioned image inventory](https://github.com/actions/runner-images/blob/9329c776c4a38d3dcb31fc78b8180005041c07fb/images/macos/xcode-27-arm64-Readme.md)
records image 20261026.0314.1, macOS 27.0.1 and Xcode 27.1 build 27A9275 at
`/Applications/Xcode_27.1.app`. The adapter verifies `ImageOS=macos27`, actual
ARM64 architecture and the exact Xcode version/build, and records the actual image
version. GitHub may update an image behind the runner label; no other Xcode version
is accepted automatically.

Recovery explicitly selects the installed iOS 27.0 runtime line and
`com.apple.CoreSimulator.SimDeviceType.iPhone-17`. This matches the local Xcode
build, runtime line and model that progressed through native Recovery. The
image's iOS 27.1 runtime supports only iPhone Duo, so selecting the SDK's minor
version would not preserve the intended model. Recovery binds its runtime and
device pins in the hashed profile. Missing, unavailable or incompatible pins fail
without substitution. Within the runtime line, the newest installed patch is
selected; SDK and runtime versions are recorded separately.

The ordinary Core, app unit and UI job instead uses the previously passing
Xcode 26.4.1 / iOS 26.2 / iPhone 16e configuration. The
[versioned macOS 26 image inventory](https://github.com/actions/runner-images/blob/102f6553849daabcbd37e321e2e224dbab45c469/images/macos/macos-26-arm64-Readme.md)
includes the required toolchain and runtime. Its job explicitly declares
`SIMULATOR_RUNTIME_VERSION=26.2` and
`SIMULATOR_DEVICE_TYPE=com.apple.CoreSimulator.SimDeviceType.iPhone-16e`.
On the newer runtime, isolating unit-host startup restored local product lookup,
but the real app purchase still opened a Sandbox account prompt. That is not a
qualified local StoreKit purchase. The matrix retains all real purchase, refund,
pending-approval and restore tests on the working older runtime while exercising
full Recovery and building the Simulator candidate with Xcode 27.1.

Every required job still validates the same reviewed source tree. For PR previews,
CI tests the synthetic merge commit and builds the reviewed PR head only when
their trees match exactly; provenance records both commit identities. It does not
require identical compilers or runtimes, and no result is
claimed as proof that StoreKit purchases pass on iOS 27.0. The shared test plan
remains free of StoreKit configuration; Recovery's recursive rejection of such
configuration is unchanged. The app's minimum deployment target remains iOS 17.

[Apple's Xcode 27.1 release notes](https://developer.apple.com/documentation/xcode-release-notes/xcode-27_1-release-notes)
list slow initial Simulator launch as known issue 187708500. Local progress does
not establish hosted boot performance. The single boot-status command allows up
to 300 seconds, including its existing four-second process-cleanup reserve, so
the former 86-second work limit does not preempt a several-minute first boot.
This allowance remains clipped to the effective 660-second startup deadline;
the 1,800-second outer deadline, disk limits and mandatory terminal accounting/cleanup remain unchanged.
The current test and collection reserves are described below.
This is a bounded cold-start allowance, not evidence that a particular silent
boot failure was caused by first-boot initialization. A timeout still fails the
attempt, and successful boot alone cannot qualify Recovery.

The single Photos seed is now created by the actual UI-test runner through
PhotoKit after its owned installation acknowledgement. This replaces the
`simctl addmedia` command that timed out before UI execution in both attempts of
run `41574541714`. The unchanged PNG bytes are packaged as a raw `.data` resource,
verified in the built bundle and again by the runner. One 86-second seed window
retains the former command's work allowance and consumes the existing 720-second
native test budget; no outer, test or cleanup deadline increases. A timely callback,
exactly one newly created asset ID and exact original-byte readback are required.
The subsequent 20-second isolation must leave that same asset as the only photo.
Separate immutable seed/isolation receipts bind both stages. No seed retry, fallback
asset or weaker picker assertion is allowed. PhotoKit still depends on the native
Photos services, so this change does not prove their latency cause or guarantee
completion. See [the seed contract](recovery-journey.md) for the full checks.

Swift CodeQL remains a required check on the tested source using the existing
`macos-26` ARM64 runner and exact Xcode 26.4.1 build 17E202. GitHub's
[CodeQL compatibility guidance](https://github.blog/changelog/2026-10-09-codeql-2-27-2-improves-c-go-rust-and-javascript-analysis/#macos-27-compatibility)
says `manual` and `autobuild` cannot trace compiled-language builds on macOS 27 or
with Xcode 27. The workflow therefore retains the supported analysis toolchain,
its strict identity checks and manual build; it does not skip or weaken security
analysis. Cross-workflow contracts verify both explicit toolchain profiles.

This configuration change does not qualify the matrix by itself.
A fresh exact-source run must pass the existing native purchase, refund, pending
approval, UI, recovery, and packaging checks before qualification is established.
Source-contract tests establish only coherent configuration and guard behavior.
Neither receipt verification nor timing/assertion requirements are relaxed;
changing the clock or trusting an unverified transaction is not a recovery step.

## Source and platform identity

The job checks out `github.sha`, then supplies the exact commit and tree produced
by the preceding `ios` job as `RECOVERY_TESTED_COMMIT` and `RECOVERY_TESTED_TREE`.
The adapter rejects a dirty checkout or a mismatch before native work. On a PR,
this is the actual merge commit; the PR head is recorded separately. GitHub's
[event reference](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
defines this distinction. A prepared, uncommitted patch is never represented as
having run on its unchanged base commit.

For an open PR, the adapter requires the canonical `refs/pull/<number>/merge`
ref, the event repository and base repository to match this repository, and
well-formed base/head SHA and repository fields. A fork head repository may
differ. The checked-out commit must equal both `GITHUB_SHA` and the preceding
iOS job's tested commit; its tree must equal the tested tree.

The event's `merge_commit_sha` is diagnostic metadata: missing, null, and a valid
SHA differing from the run are allowed only while all authoritative source
checks succeed. GitHub describes the event as the original
[webhook payload](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#github-context),
while [mergeability is computed asynchronously](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request).
Those contracts do not promise atomic equality between that payload field and
the run's merge SHA. This does not establish which condition caused an earlier
composite identity failure when its original payload was not retained.

The adapter reads the actual commit object's tree and parent headers using
`git --no-replace-objects cat-file commit`. Unlike history traversal, this works
with the existing depth-one checkout without requiring parent objects or a
network fetch. Raw author, committer, signature and message data are discarded;
only the validated tree and at most two parent SHA values enter evidence.
The actual tree must match the tested tree, and there must be exactly two
parents whose multiset equals the event's base/head SHA values. Parent order is
recorded but not required. Exact event-base equality is our conservative
**snapshot policy**, not a guarantee of GitHub event/ref synchronization. A base
advance can therefore produce a precise, intentional rejection. The adapter
does not replace the original event with a current REST response or retry.

The committed `scripts/recovery-hosted-profile.json` is SHA-256 pinned in the job's
single adapter command. The hosted grant envelope binds the actual checkout,
profile and workflow bytes, adapter/controller/collector/retention code, run ID,
attempt, job and caller-workflow identity. Its embedded controller grant still
passes the existing strict grant validation. The envelope is generated only in
the verified hosted job context and is a traceable execution contract, not a
secret credential or a local execution permission.

Discovery is one bounded pass over the selected Xcode, Simulator SDK and one
installed simulator inventory. The profile's pinned iPhone device type must exist
in that inventory and have evidence of compatibility with the selected runtime.
Its available runtime must match the profile's explicit major/minor
line, which cannot be newer than the selected SDK. Without an explicit line, the
selection helper requires the SDK's major/minor version. Runtime patch differences
and intentional SDK/runtime differences are recorded explicitly. No runtime
download, alternate runner, fallback Xcode or retry of failed commands is allowed. Actual
Xcode version/build, SDK/runtime versions, runner image version and architecture
are recorded; no Intel architecture is assumed. GitHub updates runner images, so
the [exact job image](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners)
and the job's own observations take precedence over a previously seen image.

After selecting the runtime, preflight observes `xcrun simctl runtime list --json`
before building or booting. Runtime availability and a usable dyld cache do not
establish that a runtime image is mounted. The selected image must uniquely match
the inventory's runtime identifier, version, build and bundle path, report `Ready`,
and have an actual mounted `mountPath`. Ordinary volume and cryptex paths are both
accepted; an unknown signature-state label is not treated as an error. Other
runtime images are not changed or required to become usable.

Readiness shares the original 120-second preflight deadline and is additionally
bounded to 30 seconds and eight observations. Each successful but not-ready
response may be followed by a one-second wait and another observation. Each native
command retains its normal stream limits, owned-process cleanup and four-second
cleanup reserve, with a cap of at most 15 seconds or the remaining readiness time.
Failed commands, missing/duplicated images, contradictory identities and an unusable
selected image fail immediately. A late command or mount check cannot establish
readiness. Raw responses and normalized observations are retained; successful
readiness also writes `preflight/runtime-readiness.json`.
The retained packet must bind that receipt to the source, selected runtime and
controller grant, reproduce its normalization from the raw responses, and retain
the bounded command and successful cleanup records. Missing or contradictory
readiness evidence prevents a `COMPLETE` packet. Offline validation checks the
recorded mount observation; it cannot inspect a mount on a torn-down runner.

The receipt stores an absolute monotonic deadline. Retention checks
`start < deadline <= start + 30`, matching the producer's bound without a
tolerance. Subtracting the timestamps can round a valid interval above 30:
the recorded start `234.230182041` and deadline `264.23018204100003` caused
run `41930311878` to reject retention after its UI test and artifact checks
passed. Regression tests cover that receipt, a shorter preflight window and
rejection of a deadline one representable value beyond the bound. The change
does not extend the readiness window or relax command, identity or cleanup checks.

This is a readiness mitigation and additional evidence, not an assertion that a
runtime mount race caused a particular failure. For example, run `41333130962`
built successfully but timed out before UI in silent `bootstatus`; later cleanup
commands also timed out. Its retained packet did not contain runtime-image state
or evidence of an unmount. The upstream
[runtime-mount report](https://github.com/actions/runner-images/issues/14946#issuecomment-6486239367)
describes a different observed trigger involving Metal toolchain installation.
No service is killed, runtime removed, security setting disabled or deadline
extended by this check. Boot completion and the complete Recovery journey remain
separate requirements.

Preflight then runs one non-forced
`xcrun simctl runtime dyld_shared_cache update <selected-runtime>` before the
XcodeGen installer and recovery controller. This follows
[Apple's cache-completion guidance](https://developer.apple.com/documentation/xcode-release-notes/xcode-26_4-release-notes):
runtime scanning and cache generation can delay simulator startup. The
[hosted image already builds these caches](https://github.com/actions/runner-images/blob/102f6553849daabcbd37e321e2e224dbab45c469/images/macos/scripts/build/Install-Xcode.ps1#L33-L44);
this step checks for pending or invalidated cache work, without forcing a rebuild.
Its nominal 60-second cap shares the existing absolute 120-second preflight
window; timeout or command failure stops native work. Cache readiness does not
establish that caching caused the observed silent `bootstatus` timeout, or replace
the controller's boot-readiness check.

## Time and storage

The adapter reserves at most 120 seconds for preflight, 1,800 seconds for the
recovery controller and 180 seconds for retention. The controller keeps
its own final 60-second cleanup reserve. The adapter step is capped at 36 minutes,
upload at 5 minutes and the whole job at 45 minutes, leaving room for checkout and
Python setup. Each boundary fails rather than beginning an unbounded retry.

The single full `xcrun simctl list --json` inventory command has a nominal
90-second cap: at most 86 seconds of work and the existing four seconds reserved
for cleanup. This is a bounded allowance adjustment, not evidence that an earlier
stall has been explained or fixed. Runtime and device compatibility validation
still uses that complete response. No additional query or retry is performed.
All other discovery command caps remain unchanged. In particular, the XcodeGen installer
requests 70 seconds within the same absolute 120-second discovery window.

For each command, its deadline is the earlier of start plus its requested cap
and the absolute discovery deadline; work must finish four seconds before that.
The adapter refuses to start a command with fewer than eight seconds remaining
in its effective cap. Command caps are ceilings, not reserved consecutive slots:
their worst-case sum exceeds 120 seconds. If inventory returns at elapsed 90
seconds, remaining preflight commands share at most 26 seconds of work and four
of cleanup; at elapsed 113 seconds another command cannot start. A successful
command or receipt does not renew the discovery window. Before constructing the
controller the adapter still
requires at least 1,980 seconds remaining in the overall 2,100-second envelope,
preserving the full controller and retention budgets. Slow discovery fails
instead of borrowing either reserve.

Each command receipt adds only five numeric fields from the existing monotonic
clock: start, work deadline, command deadline, requested cap in seconds, and
finish. Finish is sampled after command cleanup and before receipt persistence;
it is not the end of the adapter or retention phase. These clock values are
local to this process and are not wall-clock timestamps. If receipt capture
fails or is interrupted, cleanup has already been attempted and the existing
primary error keeps precedence. Receipt failure cannot turn a command into a
success. A recorded `group_probe` permission error remains a cleanup failure
even if later observations say the group is absent and its leader was reaped.

The controller's 24 GiB free-space admission, 8 GiB free-space abort floor, owned
device/DerivedData/output caps and xcresult subcaps remain in force. Availability
on a particular hosted runner is not guaranteed. Failure to meet admission is a
failed scenario, not evidence that recovery passed. No unrelated SDKs, runtimes,
devices or files are deleted to manufacture admission space.

The original xcresult has a 512 MiB allowance only during its exact owned
`ui-test` producer command, within the unchanged 1 GiB controller-output cap.
That allowance is revoked before terminal accounting: the finalized original
and verified reader copy must each fit 192 MiB. This explicitly changes the
earlier policy that also limited active result staging to 192 MiB. The generated
test configuration uses `SystemAttachmentLifetime=deleteOnSuccess` and
`UserAttachmentLifetime=keepAlways`; all 17 explicit checkpoint screenshots,
17 accessibility trees and the final ledger remain required. System failure
diagnostics remain subject to the final-result and packet limits. See the
[result-lifecycle policy](recovery-journey.md#storage-admission-and-abort-policy)
for the measured rationale and remaining qualification requirements.

The numeric `admission_free_bytes` in the adapter context is the value from the
existing admission disk query, not a second sample. It is retained only after
the same 24 GiB guard has passed; no output directory is created before admission.

The 1 GiB controller-output cap excludes its separately capped 4 GiB DerivedData
and 8 GiB device. Hosted preflight data is separately limited to 16 MiB, compact
build identity to 32 MiB, failure-state copies to 64 MiB, and the upload directory
to 1 GiB including its tar and manifests. These are separate budgets: 1 GiB is
not a claim about the combined live disk footprint. The free-space floor also
applies while retaining evidence. Admission must leave room for the source data
and retained copy to coexist.

When a controller traversal reaches a byte cap, it attempts to add one
`resource_cap_crossing` observation to the existing `result.json` receipt. It
records the category, cap and `cap_metric`, accumulated logical and allocated bytes, entry
count, and the current entry's relative path, type, size and 512-byte block
count. These values come from the traversal and stat result already in memory;
there is no additional walk, stat, disk query or command. The observation is
explicitly a **partial traversal**, not the total tree size or a largest-file
listing. The entry that crosses the threshold is not necessarily the largest
entry or the cause of the resource growth.

The first crossing claims this diagnostic slot even if formatting fails. Path
text uses Python `unicode_escape` notation, bounded to the first 256 source
characters and 1,024 escaped ASCII characters, with an explicit truncation flag.
Numeric fields are bounded to 128 bits and the JSON contribution is limited to
4 KiB. The observation contains no file contents or absolute entry path.
Capture is memory-only: the existing command receipt writes after owned-group
cleanup, and the existing final receipt/retention path carries available data.
Formatting, interruption or receipt failure does not replace the original
`RunFailure` message or bypass cleanup. An unsuccessful final receipt or upload
can still leave this observation unavailable; its existence in memory is not
proof of durable evidence. Complete `resource-samples.json` entries retain their
existing meaning; a failed traversal is not appended as a complete sample.

DerivedData's 4 GiB budget now uses allocated bytes; its potentially large sparse
logical length remains a separate observation. All device, output, xcresult,
attachment and log caps retain `max(logical, allocated)` enforcement, including
logical input/copy limits. Reaching a cap exactly fails. Logical bytes sum
non-directory entry sizes; allocated bytes sum each visited entry's nonnegative
integer `st_blocks` times 512, including directories. Allocated-only DerivedData
accounting additionally validates and charges the root directory's own `lstat`
allocation before scanning children, even when empty. A root-only cap crossing
uses relative path `.` and `entries: 0`; logical bytes remain zero for directories.
The content-policy modes retain their existing traversal accounting. Missing or invalid block
counts fail closed with `ResourceAccountingFailure`, without substituting logical
size or writing an incomplete sample. Valid zero-block sparse files remain zero
allocated bytes. Symlinks contribute only their own metadata without following
targets. Hardlinks are counted per entry without inode deduplication, a deliberate
conservative overcount; a fresh stat at each entry and later sample observes
growth without an inode-size cache. `cap_metric` distinguishes `allocated` from
`max_logical_allocated` in complete samples and partial crossings. Exclusions,
entry/time limits, free-space bounds and numeric caps are unchanged. These sampled
observations can overshoot and are not an instantaneous quota or full-tree atomic
snapshot. A cap failure alone does not establish physical disk exhaustion. For
an earlier failure without a crossing observation, the last complete sample or
last build-log line cannot identify the missing entry, exact size or cause.

## Retention on an ephemeral runner

A hosted runner's live simulator and DerivedData will be unavailable after the
job ends. This differs from the local first-run retention contract. The hosted
adapter records this difference explicitly and uploads only the bounded review
packet from `$RUNNER_TEMP/room-recovery-upload/`; it never uploads the entire
simulator or DerivedData tree. GitHub documents the temporary directory lifecycle
in its [variables reference](https://docs.github.com/en/actions/reference/workflows-and-actions/variables).

The required packet contains the original xcresult, verified reader copy, source
and grant bindings, generated/selected test configurations, command/cleanup logs,
resource observations, raw collector manifests, UI ledger and attachments, both
final namespace inventories and originals, three actual Files copies and their
three independently generated export payloads. A compact build-identity record
contains hashes of the app and test-runner products and the relevant small
Info.plist/configuration files. It does not claim that a full executable build or
live simulator can be recovered after teardown.

The original xcresult is inventoried before readers, never passed to a reader,
and rechecked while packaging. An internal tar and file manifest preserve bytes,
paths and modes; the outer artifact action alone is not treated as preserving
filesystem modes. The upload action runs even after a failure, uses a unique
run/attempt/commit name and requests 14-day retention. Missing upload files or an
upload error fail the job. Artifact publication itself remains a separate outcome
from successful local packet assembly.

If the UI test fails, the adapter preserves available partial data from only its
owned, pinned containers: the two known namespace roots, generated exports and
the unique journey Files folder. Missing data and uncertain origin remain marked
as incomplete. Embedded failure screenshots can remain inside the raw xcresult
when full attachment extraction did not run. No role is assigned from equal ZIP
hashes or timestamps, and no partial capture is promoted to a passing collection.

The Photos selection boundary also publishes two bounded diagnostic observations
(`before` and `after`) from the owned test runner, independently of xcresult.
`run/evidence/collection/photos-selection/` contains their PNG, structured AX and
receipts. Each PNG is at most 2 MiB, AX at most 256 KiB and receipt at most 16 KiB;
the exact six-file source directory is limited to 5 MiB. The existing collection,
packet, time and disk limits remain unchanged. The source commit, tree,
configuration, simulator, three run IDs and pinned container metadata must all
match; symlinks, extra files, mutation and missing/invalid receipts fail capture.
Capture is attempted only after the owned Photos fixture isolation handshake.
No personal library or unrelated device is selected. These files are diagnostics,
never acceptance evidence and never permission to tap a passive Image/ancestor.
A missing capture does not change the existing acceptance rules.

Photos and first-Files-tap diagnostics derive selector matches from one immutable
application snapshot, so a disappearing picker target is not queried again.
Photos also retains the hierarchy from that same snapshot. Its JSON keeps every
node and attribute but omits formatting whitespace so the existing 256 KiB capture
limit is available for evidence. Files' remote picker can be absent from the app
snapshot; its hierarchy instead uses the stable app root's later `debugDescription`.
The `hierarchy_observation` field explicitly distinguishes that later observation
from the selector snapshot. Both remain diagnostic evidence within the same caps.
Snapshot APIs do not expose hit testing: `hittable: null` is
explicitly unknown, not false, and cannot establish a non-hittable failure.
The real tap and readiness assertions still use live UI controls.

If the original result reaches its active 512 MiB allowance or reaches the
192 MiB final-result bound, the small capture can still be retained in a
`PARTIAL` archive. Only after its
bytes are verified in that archive may `failure_precedence` identify the exact
structured `control interactive: observed false, expected true` assertion as the
primary failure and retain the controller's xcresult-cap failure as secondary.
The observed target must still exist and be disabled or non-hittable. Observation
and receipt timestamps must precede the controller's recorded cap event on the
same host wall clock, within five minutes; absent, reversed or distant times
leave ordering unknown and do not change the summary. This is a diagnostic
ordering check, not protection against a hostile or arbitrarily adjusted host
clock. The original controller receipt, failed exit, and all resource limits are
preserved. Raw log keyword matching and screenshots never select a primary error.

If configuration or container pinning never completed, the packet records that
limitation with the available source/configuration/log evidence.
Rejection before the adapter claims its fresh working directory produces only
the workflow log. The existing final JSON summary includes an `identity_audit`
of at most 8 KiB with the validation stage, individual predicate outcomes, and
allowlisted SHA/repository/ref values or field types. Invalid text is represented
only by type and length; the full event, PR text and environment are never logged.
After directory admission the same audit enters `preflight/adapter-result.json`.
No directory is created merely to retain early diagnostics, so the existing disk
and ownership guards remain in force. The missing required upload still fails
explicitly; it does not replace the original adapter failure in the log. An abrupt
runner loss can likewise prevent upload and never counts as retained evidence.

Only data from the current hosted attempt may enter this upload. Private local
paths, earlier admission records, local grants and historical acceptance packets
are not inputs. A completed hosted acceptance requires the exact reviewed source,
successful native scenario and cleanup, a complete retained packet and successful
upload, followed by independent artifact and visual review.

## Native inventory failure diagnostics

If the one `simctl list --json` inventory command fails, the adapter may read
already recorded native logs once. This can expose CoreSimulator service/IPC
errors that Python selector progress cannot explain. It does not retry the
inventory, attach to a PID, sample or suspend a process, reset a simulator,
restart a service, install a runtime, or increase a deadline.

The query is permitted only after the original command reports its owned group
absent and its leader reaped, with no cleanup errors, and at least 14 seconds
remaining in the original 120-second discovery envelope. Cancellation skips
the query. The original inventory keeps its 90-second cap, including its
four-second cleanup reserve. The optional log command gets ten seconds using
the existing command owner (six seconds of work and four for cleanup); parsing
is bounded by the original deadline and a 14-second diagnostic window. That
same non-renewing subdeadline covers preparation and command cleanup; slow
preparation skips the query if its full ten-second cap no longer fits. An
unconfirmed cleanup, exhausted budget, low disk floor, or invalid wall-clock
window makes the diagnostic unavailable. The original inventory failure is
preserved even if the log query succeeds, fails, or is interrupted.

The fixed `/usr/bin/log show` query selects only `simctl`, CoreSimulatorService,
and CoreSimulator subsystem events between the inventory's wall-clock start
and its completed cleanup. The output uses UTC JSON. A fresh empty `HOME`
prevents an inherited `.logrc` from changing the log source. No elevation or
new access is requested. Log access on a hosted image may be unavailable;
empty results do not prove an absence of native errors.

Raw stdout/stderr are bounded in memory and never written to published files.
The existing command receipt records byte counts and cleanup state. The
`inventory_native_log` field in `preflight/adapter-result.json` contains only
fixed source categories, normalized timestamps, allowlisted vocabulary and
error domains, bounded numeric codes, counters and completeness state. It
does not contain raw messages, paths, arbitrary subsystem/category strings,
environment values, or exception text. Input is limited to 4 MiB, depth 16,
4,096 events and 128 retained signals within 64 KiB. Malformed, truncated or
oversized responses remain unavailable.

`OBSERVED` and `NO_MATCHING_SIGNALS` describe a complete bounded query response,
not complete system logging or successful recovery. `native_cause` remains
`UNKNOWN`; returned error vocabulary is evidence for review, not proof of
causation. Native stack sampling is not included: a delayed PID-based sampler
whose cleanup cannot be proved could otherwise inspect a reused PID.

The hosted Recovery journey allows 720 seconds for its single XCTest, with a
780-second native maximum inside the 840-second controller test phase. Device
preparation is clipped to 660 seconds from controller start to reserve the full
test and 240-second collection phases plus the unchanged 60-second cleanup
reserve within 1,800 seconds. Each installation/export acknowledgement has one
60-second monotonic window covering request publication, waiting, evidence and
validation; late reads and non-completed waiters fail without advancing a barrier.
These bounds are calibrated against observed hosted latency, and do not replace
full successful Recovery acceptance.

## Native device-setup failure diagnostics

When the controller returns after a device-phase `simctl` failure before UI
execution, the adapter may make one additional read of recorded native logs.
The `controller_native_log` summary in `preflight/adapter-result.json` uses the
same fixed CoreSimulator predicate, sanitization and byte/event limits described
above. Its window starts at the identified failed command's recorded start and
ends at the earlier of its observed completion and nominal command deadline,
within the controller's recorded duration. Command elapsed time includes child
cleanup, so a cleanup overrun does not by itself invalidate the earlier window.
The exact source interval remains at most 300 seconds. The log command rounds
its timestamps outwards to whole seconds; the sanitizer retains events only
inside the exact, unrounded interval.

Checked wall-clock and monotonic anchors still bind that interval. Ambiguous
timing, clock drift, or an observed command end after controller completion makes
the observation unavailable. A fixed `clock_validation_stage` identifies the
check reached without retaining raw anchors. After relative timing validation,
`command_window` records the actual elapsed time, observed and selected ends,
nominal deadline, and `clipped_to_command_deadline`; clipping never changes the
original command record. A completed clock-validation stage does not mean the
later log query succeeded. Historical records without anchors or this stage
cannot establish which clock check first rejected their diagnostic.

This path requires positive final ledger evidence that every spawned owned
process group is absent and its leader reaped. It does not probe a possibly
reused PID. Historical cleanup errors, including a permission error during a
group probe, remain failures even when a later observation proves the group is
absent. Observing native logs cannot establish that the Simulator shut down or
turn an incomplete run into a successful one.

The optional observation has a single 14-second absolute deadline, including
preparation, its one ten-second `controller-native-log` command, process cleanup
and parsing. It starts only when that whole allowance and the original
180-second retention reserve fit inside the unchanged 2,100-second adapter
envelope. No controller or native-command deadline is increased. A missing
process-group proof, insufficient time, interrupted query or malformed response
leaves an explicit unavailable summary while preserving the original failure.

Raw messages and environment values are not retained. The observation does not
retry the failed command, change permissions, restart a service or operate on a
Simulator. Its `native_cause` remains `UNKNOWN` until the evidence supports a
separate conclusion; a successful later run alone does not explain an earlier
native timeout.
