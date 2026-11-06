# Exercise a published unsigned RC on hosted Simulators

This additional manual workflow exercises the **downloaded published RC**, rather than rebuilding the app under test. It does not publish, promote, modify a tag, or replace the existing ordinary/Recovery/security requirements. It produces `PASS_HOSTED_RC_EXERCISE_REVIEW_PENDING`, not a final release approval.

## Pre-merge harness compilation

The existing required `ci.yml` workflow includes a PR-only `harness-build` job. It runs the pure-Python provenance and failure fixtures, then compiles the standalone runner on the same ARM Xcode runner and validates the generated test specification and absence of any AUT build product. It runs for every pull request that reaches the required iOS workflow, including harness and fixture changes. It has read-only contents permission, no RC token or inputs, and does not create, boot or install into a Simulator, or run a native test. Its result is `PASS_RC_HARNESS_BUILD_NOT_EXERCISED`; this is necessary pre-merge compile evidence, not RC exercise. The existing protected Quality gate includes this job through its unchanged reusable-workflow call; the gate definition and release policy are unchanged. The separate `rc-acceptance.yml` workflow accepts only manual dispatch for actual RC exercise. Review the additional required job before merging harness changes.

## Scope and inputs

Run `Exercise published unsigned RC` from reviewed `main`. Supply the actual RC tag, release ID, source commit/tree, candidate-producing release run/attempt, SHA256 of `release-manifest.json`, and the reviewed current main harness SHA. Never substitute a prospective merge or infer an attempt from an older run. The controller verifies the live tag, release, asset inventory, immutable evidence, source policy, validation run and exact downloaded bytes; it repeats the release snapshot check after exercise. Read requests cannot invoke publication methods.

The fixed matrix is iPhone 17 and iPad Pro 13-inch M4 (16 GB), on iOS 27.0, using the existing `xcode-27` ARM runner and Xcode 27.1 build 27A9275. The installed runtime's build is recorded. An unavailable device/runtime fails; there is no automatic substitute. This is not an Intel, all-iOS-version, physical-device, TestFlight or production-StoreKit claim. Both matrix rows must pass and be reviewed for this stated scope. Broader supported-version coverage remains a separately declared release criterion.

Each row owns one newly created Simulator UUID. Work is bounded to 1,800 seconds plus one 90-second cleanup reserve, within a 35-minute job. Individual build, boot, test, metadata, reader and output bounds also apply. Test repetition and automatic retry are absent. Any incomplete action, invalid metadata, mismatched installed file, failed command or unproved shutdown fails the row and preserves its available evidence.

## Why this uses a separate test project

`Acceptance/RC/project.yml` has one UI-test target and **no application target or application dependency**. It reuses the existing keyboard, Files and export-return readiness helpers without changing their time windows. The RC scenario is outside `UITests` and the normal app test plan; shared helper regressions remain in the ordinary suite.

The controller builds the runner in Release configuration, requires that it is the only `.app` build product, and manually installs the verified RC and that runner. It changes only the generated test-run specification: `UseDestinationArtifacts=true`, the known installed runner/bundle identifiers and its test plug-in path. Host-side AUT/install paths are removed. The test uses `XCUIApplication(bundleIdentifier:)`; the only app launch arguments select English/en_US. There is no `--ui-testing`, data-reset namespace, store mutation, Pro injection or production-code hook. Before and after the test, every installed app file and executable bit must equal the extracted RC inventory.

Apple documents `test-without-building` and that an `.xctestrun` specifies its test bundles. Apple's installed `xcodebuild.xctestrun(5)` describes `UseDestinationArtifacts` as using installed artifacts without installing replacements. Apple also documents the build-product search order for `XCUIApplication(bundleIdentifier:)`, which is why the standalone project must not contain another matching app:

- [Building from the command line](https://developer.apple.com/library/archive/technotes/tn2339/_index.html)
- [Application proxy for a bundle identifier](https://developer.apple.com/documentation/xcuiautomation/xcuiapplication/init(bundleidentifier:))
- [XcodeGen project specification](https://github.com/yonaskolb/XcodeGen/blob/master/Docs/ProjectSpec.md)

## Actual exercise and evidence

One test creates a home, room and item through the public UI, edits model/serial/price/date/notes, and checks them after relaunch. It saves standalone CSV and PDF, the inventory ZIP and a restorable backup through the real share/Files UI. It selects that backup and cancels the confirmation, exports another backup, changes the notes and verifies that mutation after a cold relaunch, selects the original backup again, confirms restore once, then checks restored values after another relaunch.

Files navigation reuses Recovery's bound-picker observer. Each serial probe resolves the exact picker identifier once with `allElementsBoundByAccessibilityElement`, requires zero or one match, and snapshots that same accessibility-bound element. Zero matches remain pending; duplicates and native errors fail. The shared bounded classifier binds folder titles to their exact local owner and requires unique navigation candidates within the picker, instead of separate live title/count/hit probes. Its enabled-state observation is not a claim of native hittability: the existing navigation actions still use their live interaction guards. Presentation and later navigation use the same fixed 30-second `FilesNavigationReadiness.systemProviderAllowance`, and at most five navigation actions are permitted. `ROOM_RC_FILES_NAVIGATION_V1` records schema-2 query and snapshot counts, durations, remaining allowances and the last classification stage, capped at 4,096 bytes without an additional AX read. Query and snapshot remain separate native operations; this does not guarantee atomicity, latency or success on either RC device. Folder creation, filename input, Save and restore retain their existing checks and require actual installed-RC validation.

After creating the export folder, both inline and alert routes use the same fixed 30-second Files folder-state observation as Recovery. Each probe calls `navigationBars.element.snapshot()` on the navigation-bar query with the exact identifier `FullDocumentManagerViewControllerNavigationBar`, with the whole expression inside the deadline checks and no separate owner-count query. XCTest's [unique `element` resolution](https://developer.apple.com/documentation/xcuiautomation/xcuielementquery/element) fails for a missing or ambiguous owner; native errors are preserved rather than converted to a pending count. A valid owner's missing title remains pending; duplicate titles fail. The snapshot root must have that identifier and navigation-bar type. Only its direct children are inspected for the exact static title or Actions Menu button, with a 4,096-node limit including the owner. Nested title text is not counted twice. One exact title establishes the open folder; the title is not activated and does not require live enabled or hittable queries. Filename input and Save retain their live interaction guards. Unique resolution, snapshot and child inspection retain deadline admission/return checks, cancellation and native errors, without another navigation tap. The creation diagnostic records native snapshot, native return, local validation and completed-capture stages, plus the last returned title count, without extra queries or clock samples. A returned snapshot can still fail the deadline check. The API does not guarantee one internal traversal or RPC, timely completion, or successful RC execution; exact exported-byte acceptance remains required below.

The exact backup-file selection also uses the named 30-second Files allowance, including its fresh readiness checks and single tap. General RC `ready()`/`tap()` defaults, form detection, filename input and all case/controller limits are unchanged. The allowance does not renew on a pending result or error and does not guarantee provider latency.

After each Save, the shared return helper keeps one 30-second window for a positive dashboard observation and a live hit check of its run-bound home. The home button must have the stable `inventory.home.<UUID.uuidString>` ID, an exact descendant home label, and no duplicate button with that ID. The native check uses that captured ID in an exact `identifier == %@` predicate over buttons with unique `.element` resolution, without a label-prefix search, other identifying-property match or `firstMatch` fallback. IDs inherited by nonbutton children do not count as duplicate buttons. Snapshot geometry is not proof of interactivity behind an omitted remote overlay; Files/share rejection and the live hit check remain required. Missing or ambiguous native targets, errors and late results cannot establish return. Share Close remains limited to one guarded action, followed by a fresh dashboard observation. This binding does not guarantee native query timing or prove that the exported bytes are correct.

The controller verifies that the two backups have identical complete contents after cancellation, the final inventory equals the original exported backup, the CSV contains the exact synthetic record, the packaged/localized CSV matches its standalone export, and all five saved files match the generated export byte multiset in the app container. The standalone and packaged PDFs are preserved independently: renderer metadata can differ, so byte equality between separately rendered PDFs is not assumed. Their page contents still require reviewer inspection.

This is a text-record scenario; no image original is added. Existing full Recovery and other source tests remain required and do not become exact-RC evidence. Acceptance of original/photo/OCR behavior on the RC would need explicit additional scope, not reinterpretation of this result.

Uploaded evidence contains the explicit inputs, provenance/assets, source hashes, generated and configured test-run specifications, installed inventories, exact native summary, raw result bundle, command logs/closure receipts, step journal, screenshots/AX, real exports and final restored inventory. No authentication/config or build-cache directory is uploaded. Failed tests retain the raw result bundle and any available runner-side failure captures.

Review both rows, screenshots/AX and both PDFs, verify that their RC/manifest/asset identities agree, and record the exact run/attempt and reviewer evidence before checking release-checklist.md's RC item. The protected stable environment remains unchanged; do not approve promotion while evidence is missing or a release criterion remains open. This workflow cannot supply that approval.

## Validation status of the initial proposal

The isolated proposal is validated by pure Python fixtures only. No local Xcode/Swift/Simulator command was executed. The first authorized hosted run must still establish that the selected XcodeGen/Xcode combination emits the supported standalone UI-runner shape, that destination-artifacts mode starts it with the installed RC, and that the pinned runtime exposes the exact public Files/editing selectors. Those are fail-closed validation assumptions, not native PASS claims or reasons to loosen the guards.

## Branch-only install responsiveness diagnostic

The exact `diagnostic/rc-install-responsiveness` branch can dispatch the existing
workflow's separate `install-diagnostic` job. The normal main-only exercise job
and Python entry point retain their guards. The diagnostic takes the same eight
inputs, with its reviewed branch commit as `harness_sha` and the separately pinned
accepted RC source as `source_sha`. It downloads and verifies the same published
RC, builds the same standalone runner, creates one new iPhone 17 on iOS 27.0,
and stops after one AUT installation and cleanup. It never installs the runner,
executes XCTest, publishes, promotes, or satisfies either installed acceptance row.

The 1,800-second work budget, shared 180-second boot window, 60-second install,
90-second cleanup reserve and 35-minute job are unchanged. No sleeps are used to
settle Simulator state; no retry, reset, runtime removal, remount or signing change
is performed. The existing list-first cleanup remains observable, including its
inability to reach shutdown if the first list fails. Issue33's proposed fallback
is not included. Failed or unknown process/device closure remains a failure.

After runner build, one separately owned heartbeat-only child records clock,
load and free-space samples at one-second measurement intervals for at most
480 seconds, clipped to the existing parent deadline. Its final join is also
clipped to any existing cleanup deadline. It launches no subprocesses. Coverage
is best effort and never renewed: device operations plus overhead can outlast it. The parent owns bounded
process snapshots, two runtime-registry/mount snapshots and one scoped native-log
query. These bypass normal raw-stream file persistence; only sanitized fixed
categories, UUID/build/mount-device correlations and numeric fields are retained.
Runtime and process observations retain the real runner environment; only the
log query uses an empty home to exclude `.logrc`. Failed or capped queries retain
only prefix byte counts/digests and fixed sanitized correlations, marked incomplete.
Environment evidence contains only presence of fixed Simulator/DYLD names and
allowlisted toolchain identity, never values or a complete environment dump.

Optional process phase hooks preserve the command owner and its default-off
behavior. Command events have a 2,048-row cap with independent terminal summaries;
the largest gap's two bounding events survive saturation. Diagnostic output has
an 8 MiB ceiling and omission reasons. Checks inspect only
the owned output tree (12 GiB ceiling, 100,000 entries, ten seconds) and enforce a
16 GiB free-space floor. Observational children require their own closure; no
new device action is admitted after an unproved observational child. The fixed
cleanup path is still attempted after ordinary, closed observational failures.

These are cooperative deadlines, not a hard scheduling guarantee. Continuing
independent heartbeats can help distinguish a main-process pause from a wider
host pause. Neither gaps nor native log vocabulary alone establishes causation;
missing, capped or unavailable observations remain explicit. A passing command
or diagnostic job does not replace the required two-row installed-RC acceptance.
