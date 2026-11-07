# Exercise a published unsigned RC on hosted Simulators

This additional manual workflow exercises the **downloaded published RC**, rather than rebuilding the app under test. It does not publish, promote, modify a tag, or replace the existing ordinary/Recovery/security requirements. It produces `PASS_HOSTED_RC_EXERCISE_REVIEW_PENDING`, not a final release approval.

## Pre-merge harness compilation

The existing required `ci.yml` workflow includes a PR-only `harness-build` job. It runs the pure-Python provenance and failure fixtures, then compiles the standalone runner on the same ARM Xcode runner and validates the generated test specification and absence of any AUT build product. It runs for every pull request that reaches the required iOS workflow, including harness and fixture changes. It has read-only contents permission, no RC token or inputs, and does not create, boot or install into a Simulator, or run a native test. Its result is `PASS_RC_HARNESS_BUILD_NOT_EXERCISED`; this is necessary pre-merge compile evidence, not RC exercise. The existing protected Quality gate includes this job through its unchanged reusable-workflow call; the gate definition and release policy are unchanged. The separate `rc-acceptance.yml` workflow accepts only manual dispatch for actual RC exercise. Review the additional required job before merging harness changes.

## Scope and inputs

Run `Exercise published unsigned RC` from reviewed `main`. Supply the actual RC tag, release ID, source commit/tree, candidate-producing release run/attempt, SHA256 of `release-manifest.json`, and the reviewed current main harness SHA. Never substitute a prospective merge or infer an attempt from an older run. The controller verifies the live tag, release, asset inventory, immutable evidence, source policy, validation run and exact downloaded bytes; it repeats the release snapshot check after exercise. Read requests cannot invoke publication methods.

The fixed matrix is iPhone 17 and iPad Pro 13-inch M4 (16 GB), on iOS 27.0, using the existing `xcode-27` ARM runner and Xcode 27.1 build 27A9275. The installed runtime's build is recorded. An unavailable device/runtime fails; there is no automatic substitute. This is not an Intel, all-iOS-version, physical-device, TestFlight or production-StoreKit claim. Both matrix rows must pass and be reviewed for this stated scope. Broader supported-version coverage remains a separately declared release criterion.

Each row owns one newly created Simulator UUID. Work is bounded to 1,800 seconds plus one 90-second cleanup reserve, within a 35-minute job. Individual build, boot, test, metadata, reader and output bounds also apply. Test repetition and automatic retry are absent. Any incomplete action, invalid metadata, mismatched installed file, failed command or unproved shutdown fails the row and preserves its available evidence.

The verified RC app is explicitly installed once within a 300-second allowance, clipped to the original 1,800-second work deadline and retaining the four-second command cleanup reserve. A failed or late return prevents the test. The standalone runner is installed by Xcode during `test-without-building`, within the existing 720-second test allowance; it is not manually installed first. The shared boot allowance remains 180 seconds, and metadata commands retain their 30-second caps. This removes a redundant installation, not the underlying Simulator responsiveness or network failures. Hosted run `42330878489` spent 116.265 seconds installing the RC and another 144.857 seconds manually installing the runner before a subsequent container-query timeout; its iPad row failed earlier during a policy read, and artifact upload then reported `ENOTFOUND`. Neither row exercised the corrected descriptor. Fresh CI and both complete installed-device rows remain required, including authoritative installed-byte and final-shutdown checks; unresolved failures remain tracked in [issue 34](https://github.com/4alvit/room-inventory-ios/issues/34).

Before boot, the controller validates the fresh device against the before/after censuses and writes an exclusive `owned-device.json` receipt binding its UUID, name, runtime and device type. Cleanup uses that receipt within the existing single 90-second reserve: an initial census failure still permits one targeted shutdown request, followed by an independent final census. A returned census with conflicting ownership blocks shutdown. Missing or changed ownership never permits a device action. The original operation error and all cleanup errors remain failures even if the final device state is `Shutdown`. `device_cleanup.shutdown_requested` records a helper request; the command receipt establishes whether a child was actually admitted. No foreign device, reset, deletion or retry is introduced. This improves cleanup after a failed census; it does not guarantee that an unresponsive Simulator service will shut down. See [issue 33](https://github.com/4alvit/room-inventory-ios/issues/33).

Each RC command passes its existing absolute parent deadline to process cleanup: the original 1,800-second work deadline, or the fixed 90-second device-cleanup deadline. Cleanup receives at most one four-second window from entry, clipped to that parent. A command that returns control after its own work cap therefore does not automatically lose all cleanup admission while its parent still has time. The work allowance, parent deadlines and failure result are unchanged. An expired parent admits no cleanup signals; an unproved process or device state, or an observation error such as `EPERM`, remains a failure. These are cooperative deadlines, not hard preemption of a stalled system call or a descheduled host. Other callers of the process helper retain their existing combined work-plus-cleanup deadline.

## Why this uses a separate test project

`Acceptance/RC/project.yml` has one UI-test target and **no application target or application dependency**. It reuses the existing keyboard, Files and export-return readiness helpers without changing their time windows. The RC scenario is outside `UITests` and the normal app test plan; shared helper regressions remain in the ordinary suite.

The controller builds the runner in Release configuration, requires that it is the only `.app` build product, and manually installs only the verified RC. Xcode stages the runner from its generated `TestHostPath` during testing. The generated test-run specification must retain `UseUITargetAppProvidedByTests=true`, the exact runner/test-bundle paths and only those two build dependencies. It must not name an AUT path or AUT build dependency. `UseDestinationArtifacts=true` is device-only: Xcode rejects that mode for an iOS Simulator before any test executes. The controller therefore preserves Xcode's normal Simulator runner paths and testing environment, selecting just the acceptance method and its journey ID.

The executable `RC-Installed.xctestrun` stays beside the generated descriptor in `DerivedData/Build/Products`, so `__TESTROOT__` still resolves to the original build products. The top-level `configured.xctestrun` is an evidence copy, not the file passed to Xcode. `test-without-building` stages the standalone runner; that work consumes the existing 720-second test command and 1,800-second parent budget. It does not rebuild the app or provide another app for installation. The verified RC is extracted outside Build Products, and the standalone project has no matching app target, dependency or product. The test uses `XCUIApplication(bundleIdentifier:)` to launch the already installed RC; the only app launch arguments select English/en_US. There is no `--ui-testing`, data-reset namespace, store mutation, Pro injection or production-code hook. Before and after the test, every installed app file and executable bit must equal the extracted RC inventory.

Apple documents Simulator `test-without-building`, the bundle paths in `.xctestrun`, and the build-product search order for `XCUIApplication(bundleIdentifier:)`. When no matching app exists in the test dependencies, scheme build targets or root Build Products directory, that API launches the existing installed app. The isolated project and runner-only checks enforce those prerequisites:

- The bundled `xcodebuild.xctestrun(5)` manual: `TestHostPath` identifies the UI-test runner, and `UseDestinationArtifacts` is the exceptional mode that suppresses Xcode installation of test artifacts. The normal Simulator descriptor uses its build-product paths.
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

Uploaded evidence contains the explicit inputs, provenance/assets, source hashes, generated and configured test-run specifications, installed inventories, exact native summary, raw result bundle, command logs/closure receipts, step journal, screenshots/AX, real exports and final restored inventory. No authentication/config or build-cache directory is uploaded. A failed native test attaches its available screenshots/AX and the capped 64 KiB `failure-journey` JSON directly to `Acceptance.xcresult` while the runner is alive. Custom attachments must be selected by their exact names; Xcode's `--only-failures` export can omit attachments not marked as associated with a failure. Cleanup does not query the runner container after shutdown, which rejects that lookup. Successful exercise still copies and verifies the complete runner evidence directory before cleanup. Missing captures never change the failure result or establish acceptance.

If execution fails, the controller also prints one `ROOM_RC_FAILURE_V1` JSON line after cleanup. It contains only a fixed phase label, a failed operation index when available, finite numeric timing/exit values, a fixed work/cleanup exit-code source, and timeout/process-closure/cleanup-failure booleans. It excludes commands, paths, exception text and captured streams. A controller failure between commands has no failed operation index. This limited summary survives a later artifact-upload failure; it does not replace detailed receipts or prove runtime acceptance. Diagnostic-output errors never replace the original failure, and no command is retried.

After a failure involving an owned Simulator, the controller attempts one small
host diagnostic collection **after device cleanup**. Its combined 20-second
window comes from the remaining original 1,800-second work deadline; it never
extends that deadline or consumes the separate 90-second device-cleanup reserve.
With no remaining admission time it records a skip. Three fixed, bounded reads
capture selected process counters (`ps`, without arguments or environment),
memory page statistics (`vm_stat`), and the last ten minutes of narrowly filtered
CoreSimulator/Simulator/installer unified logs. Each child has the existing
bounded process cleanup; an unproved diagnostic child stops further collection.
The process filter recognizes the service's truncated accounting names as well
as its full name. The ten-minute log interval includes installation before a slow
metadata query and cleanup without increasing the time or output caps.
These are cooperative deadlines, not hard preemption of a stalled host.

The files and command receipts stay in the failed row's `failure-diagnostics/`
artifact directory, explicitly included in the upload paths even for partial
collection. Only an allowlisted collection status is added to the public
failure summary; raw service messages never go into that summary. An empty log
or matching PID does not prove the cause, service health, or process identity.
Collection failure cannot replace the original error, turn the row green, or
erase an unproved process/device closure. No `simctl diagnose`, repeated metadata
query, service restart, or extra test is performed. Both rows of run `42334033801`
stalled at the authoritative app-container query before XCTest, even after the
redundant runner installation was removed; this evidence collection diagnoses
that unresolved boundary and does not claim to repair it.

For a native-test failure, the runner first writes one journey-ID-bound marker
before its screenshot/AX calls and before terminating the app. Only that marker
can trigger a live AUT sample; a passing test performs no extra process lookup
or sampling. The controller identifies exactly one process whose executable
path is the verified installed app inside the owned Simulator, then compares
PID, process start time and executable path before and after sampling. Ambiguous,
missing or changed identity leaves the diagnostic incomplete. These observations
are not an atomic process-identity guarantee, and PID equality alone is insufficient.

The fixed `sample` command observes one second at ten-millisecond intervals,
with a two-MiB captured-stream cap. Its two process reads and sample share at most
ten seconds, including owned-child cleanup, clipped to the original 720-second
test command and 1,800-second work deadline. They never consume or extend the
90-second device-cleanup reserve. The existing upload retains partial receipts
and stack output under `failure-diagnostics/live-aut/`; other process paths and
command arguments are not retained by the identity reads. No private XCTest
setting, debugger, service restart, app relaunch or retry is used.

Apple's `sample(1)` describes transiently suspending threads while collecting
their stacks. This measurement can affect timing, so a marked or sampled attempt
remains failed even if Xcode later returns zero. Diagnostic failure never replaces
the original test error. A collected stack describes the sampled interval after
failure; it does not prove the state at the earlier tap or resolve the historical
idle-notification failure by itself. Long-running `xcodebuild` sysdiagnoses remain
disabled.

Review both rows, screenshots/AX and both PDFs, verify that their RC/manifest/asset identities agree, and record the exact run/attempt and reviewer evidence before checking release-checklist.md's RC item. The protected stable environment remains unchanged; do not approve promotion while evidence is missing or a release criterion remains open. This workflow cannot supply that approval.

## Descriptor validation and remaining runtime acceptance

Hosted run `42325874162`, attempt 1, installed the RC and runner, but Xcode rejected the former destination-artifacts mode with exit 70 before UI execution. The regression fixture is the actual generated standalone descriptor from that run. Tests cover both supported descriptor formats, exact runner-only dependencies, rejection of device-only mode or AUT build paths, and the original Products-directory binding even when the output path contains spaces. Fixture and standalone compile checks establish the descriptor contract; they do not prove the installed-RC journey. Both complete device rows, all installed-byte checks, visual/export review and final shutdown remain required before [issue 34](https://github.com/4alvit/room-inventory-ios/issues/34) or release acceptance can be completed. No timeout or retry policy changes accompany this correction.

### Exact backup selection in Files

Files can reopen the run folder while its internal browsing-root identifier still
names the provider entry location (for example, `On My iPhone`). The RC harness
uses the shared immutable-picker classifier to verify the current navigation-bar
title, LocalStorage owner, unique File View and exact run-specific backup. It then
resolves one live file within that observed owner and keeps its bound identity for
enabled, hittable and tap checks. Every new probe clears the previous identity.
The existing 30-second selection window and one-tap limit are unchanged.

The host fixture `scripts/tests/fixtures/rc-backup-selection.swift` exercises the
actual `selectBackup` method alongside the unchanged shared classifier and waiter.
The host validation substitutes only the XCUI transport types and inserts that
method at `RC_SELECT_BACKUP_BODY`; it covers the retained stale-title shape, wrong
folder/file/provider, ambiguity, cross-owner matches, refreshed identities and
late observations. It does not launch the app or replace installed-RC acceptance.

On macOS with Xcode selected (or `DEVELOPER_DIR` set), run:

```sh
python3 scripts/test-rc-backup-selection.py --output "$TMPDIR/rc-backup-selection"
```

The output directory must be new. The existing required PR harness-build job runs
this command before compiling the standalone runner and retains its exact-case
result, process-closure receipt and bounded logs. The host command allows 180
seconds plus four seconds for owned-process cleanup; it removes its temporary
package only after closure is proved. Python-only fixtures remain usable on Linux.
