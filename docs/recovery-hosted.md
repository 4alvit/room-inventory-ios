# Hosted recovery scenario

This is the hosted adapter for the opt-in [recovery journey](recovery-journey.md).
Source review and injected tests do not establish a successful native run. The
first execution needs a separately approved source commit and CI cohort.

## Where the job runs

The existing callable `ci.yml` adds one `recovery` job after `ios`. The job uses
the existing standard `macos-15` runner class, read-only repository permissions
and the same pinned checkout, Python and artifact actions. The PR preview now
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

The controller's 24 GiB free-space admission, 8 GiB free-space abort floor, owned
device/DerivedData/output caps and xcresult subcaps remain in force. Availability
on a particular hosted runner is not guaranteed. Failure to meet admission is a
failed scenario, not evidence that recovery passed. No unrelated SDKs, runtimes,
devices or files are deleted to manufacture admission space.

The 1 GiB controller-output cap excludes its separately capped 4 GiB DerivedData
and 8 GiB device. Hosted preflight data is separately limited to 16 MiB, compact
build identity to 32 MiB, failure-state copies to 64 MiB, and the upload directory
to 1 GiB including its tar and manifests. These are separate budgets: 1 GiB is
not a claim about the combined live disk footprint. The free-space floor also
applies while retaining evidence. Admission must leave room for the source data
and retained copy to coexist.

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
the workflow log; the missing required upload then fails explicitly. An abrupt
runner loss can likewise prevent upload and never counts as retained evidence.

Only data from the current hosted attempt may enter this upload. Private local
paths, earlier admission records, local grants and historical acceptance packets
are not inputs. A completed hosted acceptance requires the exact reviewed source,
successful native scenario and cleanup, a complete retained packet and successful
upload, followed by independent artifact and visual review.
