# Hosted recovery scenario

This is the hosted adapter for the opt-in [recovery journey](recovery-journey.md).
Source review and injected tests do not establish a successful native run. The
first execution needs a separately approved source commit and CI cohort.

## Where the job runs

The existing callable `ci.yml` adds one `recovery` job after `ios`. The job uses
the standard `macos-15` runner class, read-only repository permissions
and the same pinned checkout, Python and artifact actions. All four existing Mac
jobs require an actual `arm64` host and Xcode 16.4 build 16F6; they do not fall
back to another runner or toolchain. Recovery retains its 24 GiB admission floor. The PR preview now
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
installed simulator inventory. The chosen iPhone device type must exist in that
inventory, and its available runtime must match the selected SDK's major/minor
version. A differing runtime patch version is recorded explicitly. No runtime
download, alternate runner, fallback Xcode or probe/retry loop is allowed. Actual
Xcode version/build, SDK/runtime versions, runner image version and architecture
are recorded; no Intel architecture is assumed. GitHub updates runner images, so
the [exact job image](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners)
and the job's own observations take precedence over a previously seen image.

## Time and storage

The adapter reserves at most 120 seconds for discovery, 1,800 seconds for the
unchanged recovery controller and 180 seconds for retention. The controller keeps
its own final 60-second cleanup reserve. The adapter step is capped at 36 minutes,
upload at 5 minutes and the whole job at 45 minutes, leaving room for checkout and
Python setup. Each boundary fails rather than beginning an unbounded retry.

The single full `xcrun simctl list --json` inventory command has a nominal
60-second cap: at most 56 seconds of work and the existing four seconds reserved
for cleanup. This is a bounded allowance adjustment, not evidence that an earlier
stall has been explained or fixed. Runtime and device compatibility validation
still uses that complete response. No additional query or retry is performed.
All other command caps remain unchanged. In particular, the XcodeGen installer
requests 70 seconds within the same absolute 120-second discovery window.

For each command, its deadline is the earlier of start plus its requested cap
and the absolute discovery deadline; work must finish four seconds before that.
The adapter refuses to start a command with fewer than eight seconds remaining
in its effective cap. Command caps are ceilings, not reserved consecutive slots:
their worst-case sum exceeds 120 seconds. If inventory returns at elapsed 90
seconds, the installer has at most 26 seconds of work and four of cleanup; at
elapsed 113 seconds it cannot start. A successful command or receipt does not
renew the discovery window. Before constructing the controller the adapter still
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
