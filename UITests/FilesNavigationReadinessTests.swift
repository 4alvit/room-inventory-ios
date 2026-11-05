import XCTest

final class FilesNavigationReadinessTests: XCTestCase {
    private struct TitleNode {
        let kind: FilesNavigationReadiness.TitleKind
        let label: String
        let identifier: String
        let children: [TitleNode]

        init(_ kind: FilesNavigationReadiness.TitleKind, _ label: String = "",
             identifier: String = "", children: [TitleNode] = []) {
            self.kind = kind
            self.label = label
            self.identifier = identifier
            self.children = children
        }

        static func owner(children: [TitleNode] = []) -> TitleNode {
            TitleNode(.navigationBar, identifier: "FullDocumentManagerViewControllerNavigationBar",
                      children: children)
        }

        var item: FilesNavigationReadiness.TitleItem {
            .init(kind: kind, label: label, identifier: identifier)
        }
    }

    @MainActor
    private func titleCount(_ root: TitleNode, window: FilesNavigationReadiness) throws -> Int {
        try window.captureTargetFolderTitleCount(title: "Run folder", uniqueSnapshot: { root },
            children: { $0.children }, attributes: { $0.item })
    }

    @MainActor
    private func saveBar(title: TitleNode? = nil, actions: [TitleNode]? = nil) -> TitleNode {
        .owner(children: [title ?? TitleNode(.button, "Run folder, Actions Menu")] +
            (actions ?? [TitleNode(.button, "Save", identifier: "DOCPicker.actionButton")]))
    }

    @MainActor
    private func saveOwner(_ children: [TitleNode], title: String = "On My iPhone") -> TitleNode {
        TitleNode(.other, identifier: FilesNavigationReadiness.localStorageRootPrefix + title, children: children)
    }

    @MainActor
    private func savePicker(_ children: [TitleNode]) -> TitleNode {
        TitleNode(.other, identifier: FilesNavigationReadiness.pickerIdentifier, children: children)
    }

    @MainActor
    private func captureSave(_ root: TitleNode, window: FilesNavigationReadiness) throws
        -> FilesNavigationReadiness.SelectionObservation? {
        try window.captureSelection(folder: "Run folder", uniqueSnapshot: { root },
                                     children: { $0.children }, attributes: { $0.item })
    }

    @MainActor
    func testFilenameEchoAcceptsImmediateExactValueAndStopsReading() throws {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        let expected = "source-E1836DD1-50AE-4CE6-9473-89348E24DB97"
        var reads = 0
        XCTAssertEqual(try window.waitForFilenameEcho(expected: expected, readValue: {
            XCTAssertTrue(Thread.isMainThread)
            reads += 1
            return expected
        }), expected)
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(reads, 1)
    }

    @MainActor
    func testFilenameEchoMissingOrPrefixThenFullUsesOriginalDeadline() throws {
        let expected = "source-E1836DD1-50AE-4CE6-9473-89348E24DB97"
        let initialValues: [String?] = [nil, "source-E1836DD1-50AE-4CE6-9473-89"]
        for initial in initialValues {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            var reads = 0
            XCTAssertEqual(try window.waitForFilenameEcho(expected: expected, readValue: {
                reads += 1
                if reads == 1 { now = 9.5; return initial }
                return expected
            }), expected)
            XCTAssertEqual(reads, 2)
            XCTAssertEqual(try window.remaining(), 0.5)
            now = 10
            XCTAssertThrowsError(try window.waitForFilenameEcho(expected: expected, readValue: {
                reads += 1; return expected
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            XCTAssertEqual(reads, 2)
        }
    }

    @MainActor
    func testFilenameEchoStableMissingPartialOrWrongValueExpiresWithoutAdmission() {
        let expected = "source-E1836DD1-50AE-4CE6-9473-89348E24DB97"
        let values: [String?] = [nil, "", "source-E1836DD1-50AE-4CE6-9473-89", "wrong",
                                 expected + ".zip", expected.lowercased()]
        for value in values {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            var reads = 0
            var admissions = 0
            XCTAssertThrowsError(try {
                _ = try window.waitForFilenameEcho(expected: expected, readValue: {
                    reads += 1; now += 5; return value
                })
                admissions += 1
            }()) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            XCTAssertEqual(reads, 2)
            XCTAssertEqual(admissions, 0)
        }
    }

    @MainActor
    func testFilenameEchoExpiredBeforeReadNeverResolvesNativeField() {
        for time in [10.0, 10.001] {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            now = time
            var reads = 0
            XCTAssertThrowsError(try window.waitForFilenameEcho(expected: "source-run", readValue: {
                reads += 1; return "source-run"
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            XCTAssertEqual(reads, 0)
        }
    }

    @MainActor
    func testFilenameEchoExactOrLateFullReturnCannotAdmitOrRenew() {
        for time in [10.0, 10.001] {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            var reads = 0
            XCTAssertThrowsError(try window.waitForFilenameEcho(expected: "source-run", readValue: {
                reads += 1; now = time; return "source-run"
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            XCTAssertThrowsError(try window.waitForFilenameEcho(expected: "source-run", readValue: {
                reads += 1; return "source-run"
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            XCTAssertEqual(reads, 1)
        }
    }

    @MainActor
    func testFilenameEchoFinalWaiterReturnStillChecksOriginalDeadline() {
        var returned = false
        var checks = 0
        let window = FilesNavigationReadiness(timeout: 10, clock: {
            guard returned else { return 0 }
            checks += 1
            // Native value and outer probe return in time; waiter return does not.
            return checks < 3 ? 9 : 10
        })
        var reads = 0
        XCTAssertThrowsError(try window.waitForFilenameEcho(expected: "source-run", readValue: {
            reads += 1; returned = true; return "source-run"
        })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
        XCTAssertEqual(reads, 1)
        XCTAssertEqual(checks, 3)
    }

    @MainActor
    func testFilenameEchoPreservesUniqueResolverErrorEvenWhenLate() {
        for time in [0.0, 11.0] {
            let native = NSError(domain: "UniqueFilenameResolution", code: 1)
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            var reads = 0
            XCTAssertThrowsError(try window.waitForFilenameEcho(expected: "source-run", readValue: {
                reads += 1; now = time; throw native
            })) { XCTAssertTrue(($0 as NSError) === native) }
            XCTAssertThrowsError(try window.perform { reads += 1 }) {
                XCTAssertTrue(($0 as NSError) === native)
            }
            RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            XCTAssertEqual(reads, 1)
        }
    }

    @MainActor
    func testFilenameEchoCancellationBeforeDuringOrBetweenReadsStopsWork() {
        for phase in ["before", "during", "pending"] {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            var reads = 0
            if phase == "before" { window.cancel() }
            XCTAssertThrowsError(try window.waitForFilenameEcho(expected: "source-run", readValue: {
                reads += 1
                if phase == "during" {
                    window.cancel()
                    return "source-run"
                }
                RunLoop.main.perform(inModes: [.default]) {
                    MainActor.assumeIsolated { window.cancel() }
                }
                return "source-"
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .cancelled) }
            RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            XCTAssertEqual(reads, phase == "before" ? 0 : 1)
        }
    }

    @MainActor
    func testFilenameEchoNativeReadCannotOverlapOrContinueAfterSuccess() throws {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var active = false
        var reads = 0
        XCTAssertEqual(try window.waitForFilenameEcho(expected: "source-run", readValue: {
            XCTAssertFalse(active)
            active = true
            defer { active = false }
            reads += 1
            RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            return reads == 1 ? "source-" : "source-run"
        }), "source-run")
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(reads, 2)
    }

    @MainActor
    func testSaveSnapshotUsesCurrentDirectTitleInsteadOfProviderEntryTitle() throws {
        for title in [TitleNode(.text, "Run folder"),
                      TitleNode(.button, "Run folder, Actions Menu", children: [TitleNode(.text, "Run folder")])] {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            let tree = savePicker([saveOwner([saveBar(title: title)])])
            var captures = 0
            let result = try window.captureSelection(folder: "Run folder", uniqueSnapshot: {
                captures += 1; return tree
            }, children: { $0.children }, attributes: { $0.item })
            XCTAssertEqual(result?.ownerIdentifier,
                           FilesNavigationReadiness.localStorageRootPrefix + "On My iPhone")
            XCTAssertEqual(captures, 1)
        }
    }

    @MainActor
    func testSaveSnapshotMissingOrWrongCurrentTitleNeverUsesOwnerTitleAsProof() throws {
        let wrongTitles = [TitleNode(.text, "Other folder"),
                           TitleNode(.button, "Run folder"),
                           TitleNode(.other, "", children: [TitleNode(.text, "Run folder")])]
        let trees = [savePicker([]), savePicker([saveOwner([])]),
                     savePicker([saveOwner([saveBar(actions: [])])])] + wrongTitles.map {
            savePicker([saveOwner([saveBar(title: $0)], title: "Run folder")])
        }
        for tree in trees {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            XCTAssertNil(try captureSave(tree, window: window))
        }
    }

    @MainActor
    func testSaveSnapshotRejectsWrongProviderRootTypeAndCrossBranchMatches() {
        let action = TitleNode(.button, "Save", identifier: "DOCPicker.actionButton")
        let trees = [
            TitleNode(.application, identifier: FilesNavigationReadiness.pickerIdentifier,
                      children: [saveOwner([saveBar()])]),
            TitleNode(.other, identifier: "Other Picker", children: [saveOwner([saveBar()])]),
            savePicker([TitleNode(.other, identifier: "DOC.browsingRoot Source: com.example.cloud, Title: Run folder",
                                 children: [saveBar()])]),
            savePicker([saveOwner([saveBar()], title: "")]),
            savePicker([saveOwner([saveBar()], title: String(repeating: "x", count: 1_025))]),
            savePicker([saveOwner([]), saveBar()]),
            savePicker([saveOwner([saveBar(actions: [])]), action]),
            savePicker([saveOwner([saveBar(actions: [TitleNode(.button, "Open", identifier: "DOCPicker.actionButton")])])])
        ]
        for tree in trees {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            XCTAssertThrowsError(try captureSave(tree, window: window)) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidSelectionSnapshot)
            }
            XCTAssertThrowsError(try window.perform { XCTFail("Invalid snapshot admitted later work") })
        }
    }

    @MainActor
    func testSaveSnapshotRejectsEveryDuplicateTypedScope() {
        let action = TitleNode(.button, "Save", identifier: "DOCPicker.actionButton")
        let bar = saveBar()
        let owner = saveOwner([bar])
        let trees = [savePicker([owner, savePicker([])]),
                     savePicker([owner, owner]), savePicker([saveOwner([bar, bar])]),
                     savePicker([saveOwner([.owner(children: [TitleNode(.text, "Run folder"),
                         TitleNode(.button, "Run folder, Actions Menu"), action])])]),
                     savePicker([saveOwner([saveBar(actions: [action, action])])])]
        for tree in trees {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            XCTAssertThrowsError(try captureSave(tree, window: window)) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidSelectionCount)
            }
        }
    }

    @MainActor
    func testSaveSnapshotEnforcesTotalNodeBoundAndRejectsLateCaptureOrTraversal() throws {
        let valid = saveOwner([saveBar()]) // Owner, bar, title and action: four nodes.
        let extras = Array(repeating: TitleNode(.unrelated), count: 4_091)
        let allowed = savePicker([valid] + extras)
        XCTAssertNotNil(try captureSave(allowed, window: FilesNavigationReadiness(timeout: 10, clock: { 0 })))
        let oversized = savePicker([valid] + extras + [TitleNode(.unrelated)])
        XCTAssertThrowsError(try captureSave(oversized, window: FilesNavigationReadiness(timeout: 10, clock: { 0 }))) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidSelectionSnapshot)
        }
        for lateStage in 0...2 {
            var now = 0.0
            var calls: [Int] = []
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            XCTAssertThrowsError(try window.captureSelection(folder: "Run folder", uniqueSnapshot: {
                calls.append(0); if lateStage == 0 { now = 10 }; return allowed
            }, children: {
                calls.append(2); if lateStage == 2 { now = 10 }; return $0.children
            }, attributes: {
                calls.append(1); if lateStage == 1 { now = 10 }; return $0.item
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            XCTAssertEqual(calls, Array(0...lateStage))
        }
    }

    @MainActor
    func testSaveReadinessRefreshesSnapshotAndBindsLiveChecksToLatestExactOwner() throws {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var captures = 0
        var owners: [String] = []
        XCTAssertTrue(try window.waitForSelection(observe: {
            captures += 1
            if captures == 1 { return nil }
            return try self.captureSave(self.savePicker([self.saveOwner([self.saveBar()],
                title: captures == 2 ? "On My iPhone" : "Run folder")]), window: window)
        }, enabled: {
            owners.append($0.ownerIdentifier); return captures == 3
        }, hittable: {
            owners.append($0.ownerIdentifier); return true
        }))
        XCTAssertEqual(captures, 3)
        XCTAssertEqual(owners, ["On My iPhone", "Run folder", "Run folder"].map {
            FilesNavigationReadiness.localStorageRootPrefix + $0
        })
    }

    @MainActor
    func testSaveTapTakesFreshSnapshotAndConsumesOnlyOneAction() throws {
        var captures = 0
        var calls: [String] = []
        let tree = savePicker([saveOwner([saveBar()])])
        func observe(_ window: FilesNavigationReadiness) throws -> FilesNavigationReadiness.SelectionObservation? {
            captures += 1; calls.append("snapshot")
            return try captureSave(tree, window: window)
        }
        let dialog = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        XCTAssertTrue(try dialog.waitForSelection(observe: { try observe(dialog) },
            enabled: { _ in calls.append("enabled"); return true },
            hittable: { _ in calls.append("hittable"); return true }))
        let saving = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        func save() throws {
            try saving.waitAndTapSelection(observe: { try observe(saving) },
                enabled: { _ in calls.append("enabled"); return true },
                hittable: { _ in calls.append("hittable"); return true },
                tap: { _ in calls.append("tap") })
        }
        try save()
        XCTAssertThrowsError(try save()) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .selectionAlreadyStarted)
        }
        XCTAssertEqual(captures, 2)
        XCTAssertEqual(calls, ["snapshot", "enabled", "hittable", "snapshot", "enabled", "hittable", "tap"])
    }

    @MainActor
    func testEverySaveOperationRejectsExactAndLateReturnWithoutFurtherWork() {
        for lateStage in 0...3 {
            for lateTime in [10.0, 10.001] {
                var now = 0.0
                var calls: [Int] = []
                let window = FilesNavigationReadiness(timeout: 10, clock: { now })
                func operation(_ stage: Int) { calls.append(stage); if stage == lateStage { now = lateTime } }
                XCTAssertThrowsError(try window.waitAndTapSelection(observe: {
                    operation(0); return .init(ownerIdentifier: "exact owner")
                }, enabled: { _ in operation(1); return true },
                   hittable: { _ in operation(2); return true }, tap: { _ in operation(3) })) {
                    XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired)
                }
                XCTAssertThrowsError(try window.perform { calls.append(4) })
                XCTAssertEqual(calls, Array(0...lateStage))
            }
        }
    }

    @MainActor
    func testEverySaveOperationPreservesNativeFailureAndDoesNotRetryTap() {
        final class NativeFailure: Error {}
        for failedStage in 0...3 {
            var now = 0.0
            var calls: [Int] = []
            let expected = NativeFailure()
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            func operation(_ stage: Int) throws {
                calls.append(stage); if stage == failedStage { now = 11; throw expected }
            }
            XCTAssertThrowsError(try window.waitAndTapSelection(observe: {
                try operation(0); return .init(ownerIdentifier: "exact owner")
            }, enabled: { _ in try operation(1); return true },
               hittable: { _ in try operation(2); return true }, tap: { _ in try operation(3) })) {
                XCTAssertTrue(($0 as? NativeFailure) === expected)
            }
            XCTAssertThrowsError(try window.perform { calls.append(4) })
            XCTAssertEqual(calls, Array(0...failedStage))
        }
    }

    @MainActor
    func testSelectionSnapshotPreservesUnresolvablePickerErrorBeforeTraversalOrAction() {
        final class ResolutionFailure: Error {
            let reason: String
            init(_ reason: String) { self.reason = reason }
        }
        for reason in ["missing picker", "ambiguous picker"] {
            var now = 0.0
            var resolutions = 0
            let expected = ResolutionFailure(reason)
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            XCTAssertThrowsError(try window.waitAndTapSelection(observe: {
                try window.captureSelection(folder: "Run folder", uniqueSnapshot: { () throws -> TitleNode in
                    resolutions += 1
                    now = 11 // The native error remains primary even on a late return.
                    throw expected
                }, children: { _ in XCTFail("Unresolved picker was traversed"); return [] },
                   attributes: { _ in XCTFail("Unresolved picker attributes read"); return .init(kind: .other, label: "") })
            }, enabled: { _ in XCTFail("Unresolved picker admitted a live query"); return true },
               hittable: { _ in XCTFail("Unresolved picker admitted a live query"); return true },
               tap: { _ in XCTFail("Unresolved picker admitted a tap") })) {
                XCTAssertTrue(($0 as? ResolutionFailure) === expected)
            }
            XCTAssertThrowsError(try window.perform { XCTFail("Resolution failure was not terminal") }) {
                XCTAssertTrue(($0 as? ResolutionFailure) === expected)
            }
            XCTAssertEqual(resolutions, 1)
        }
    }

    @MainActor
    func testSaveCancellationAndReentryPreventLaterChecksOrAnotherTap() {
        for reenter in [false, true] {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            var captures = 0
            var taps = 0
            func save() throws {
                try window.waitAndTapSelection(observe: {
                    captures += 1
                    if reenter {
                        XCTAssertThrowsError(try save())
                    } else { window.cancel() }
                    return .init(ownerIdentifier: "exact owner")
                }, enabled: { _ in XCTFail("After cancellation/reentry"); return true },
                   hittable: { _ in XCTFail("After cancellation/reentry"); return true }, tap: { _ in taps += 1 })
            }
            XCTAssertThrowsError(try save()) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure,
                               reenter ? .selectionAlreadyStarted : .cancelled)
            }
            RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            XCTAssertEqual(captures, 1)
            XCTAssertEqual(taps, 0)
        }
    }

    @MainActor
    func testSaveTapRemainsInsideOriginalOuterWaiter() {
        let window = FilesNavigationReadiness(timeout: 0.25)
        var taps = 0
        var nested: XCTWaiter.Result?
        XCTAssertThrowsError(try window.waitAndTapSelection(
            observe: { .init(ownerIdentifier: "exact owner") }, enabled: { _ in true }, hittable: { _ in true },
            tap: { _ in
                taps += 1
                nested = XCTWaiter.wait(for: [XCTestExpectation(description: "native save")], timeout: 2)
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
        XCTAssertEqual(nested, .interrupted)
        XCTAssertEqual(taps, 1)
    }

    @MainActor
    func testBackupSnapshotUsesSameCurrentFolderProofAndExactFileIdentity() throws {
        let filename = "backup-journey.roominventory"
        let file = TitleNode(.cell, "A display label with time and size",
                             identifier: filename + ", roominventory")
        let view = TitleNode(.collectionView, identifier: "File View", children: [file])
        let tree = savePicker([saveOwner([saveBar(actions: []), view])])
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        let observation = try window.captureSelection(folder: "Run folder", target: .backup(filename: filename),
            uniqueSnapshot: { tree }, children: { $0.children }, attributes: { $0.item })
        XCTAssertEqual(observation?.ownerIdentifier,
                       FilesNavigationReadiness.localStorageRootPrefix + "On My iPhone")
    }

    @MainActor
    func testBackupSnapshotNeverFallsBackToPartialFilenameLabelOrWrongType() throws {
        let filename = "backup-journey.roominventory"
        let exact = filename + ", roominventory"
        let files = [TitleNode(.cell, exact, identifier: filename),
                     TitleNode(.cell, exact, identifier: "backup-other.roominventory, roominventory"),
                     TitleNode(.text, exact, identifier: exact),
                     TitleNode(.cell, exact, identifier: exact + ".zip")]
        for file in files {
            let view = TitleNode(.collectionView, identifier: "File View", children: [file])
            let tree = savePicker([saveOwner([saveBar(actions: []), view])])
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            XCTAssertNil(try window.captureSelection(folder: "Run folder", target: .backup(filename: filename),
                uniqueSnapshot: { tree }, children: { $0.children }, attributes: { $0.item }))
        }
    }

    @MainActor
    func testBackupSnapshotRejectsDuplicateViewsCellsAndCrossBranchMatches() {
        let filename = "backup-journey.roominventory"
        let file = TitleNode(.cell, identifier: filename + ", roominventory")
        let view = TitleNode(.collectionView, identifier: "File View", children: [file])
        let emptyView = TitleNode(.collectionView, identifier: "File View")
        let trees: [(TitleNode, FilesNavigationReadiness.Failure)] = [
            (savePicker([saveOwner([saveBar(), view, view])]), .invalidSelectionCount),
            (savePicker([saveOwner([saveBar(), TitleNode(.collectionView, identifier: "File View",
                                                       children: [file, file])])]), .invalidSelectionCount),
            (savePicker([saveOwner([saveBar()]), view]), .invalidSelectionSnapshot),
            (savePicker([saveOwner([saveBar(), emptyView, file])]), .invalidSelectionSnapshot)
        ]
        for (tree, failure) in trees {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            XCTAssertThrowsError(try window.captureSelection(folder: "Run folder", target: .backup(filename: filename),
                uniqueSnapshot: { tree }, children: { $0.children }, attributes: { $0.item })) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, failure)
            }
        }
    }

    @MainActor
    func testFirstProbeIsImmediateAndOnMainRunLoop() throws {
        var now = 0.0
        let window = FilesNavigationReadiness(clock: { now })
        now = 29.25 // Less than the old predicate's first one-second delay.
        var calls = 0
        XCTAssertEqual(try window.waitForState {
            XCTAssertTrue(Thread.isMainThread)
            calls += 1
            return .targetFolder
        }, .targetFolder)
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testDelayedPositiveStateUsesOriginalThirtySecondAllowance() throws {
        for delay in [15.0, 20.0] {
            var now = 0.0
            let window = FilesNavigationReadiness(clock: { now })
            var calls = 0
            XCTAssertEqual(try window.waitForState {
                calls += 1
                if calls == 1 { now = delay; return nil }
                return .localEntry
            }, .localEntry)
            XCTAssertEqual(calls, 2)
            XCTAssertEqual(try window.remaining(), 30 - delay)
            now = 30
            XCTAssertThrowsError(try window.waitForState {
                calls += 1; return .back
            }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            XCTAssertEqual(calls, 2)
        }
    }

    @MainActor
    func testNilNeverBecomesBackAndExpiryStopsPolling() {
        var now = 0.0
        let window = FilesNavigationReadiness(clock: { now })
        var calls = 0
        XCTAssertThrowsError(try window.waitForState {
            calls += 1
            if calls == 2 { now = 30 }
            return nil
        }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(calls, 2)
    }

    @MainActor
    func testExplicitTenSecondAllowanceDoesNotAdmitExpiredQuery() {
        var now = 0.0
        let window = FilesNavigationReadiness(timeout: 10, clock: { now })
        now = 10
        var calls = 0
        XCTAssertThrowsError(try window.waitForState {
            calls += 1; return .browse
        }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
        XCTAssertThrowsError(try window.perform { calls += 1 })
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        XCTAssertEqual(calls, 0)
    }

    @MainActor
    func testExactAndLatePositiveStateCannotBeAccepted() {
        for time in [30.0, 30.001] {
            var now = 0.0
            let window = FilesNavigationReadiness(clock: { now })
            var calls = 0
            XCTAssertThrowsError(try window.waitForState {
                calls += 1; now = time; return .localRoot
            }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            XCTAssertEqual(calls, 1)
        }
    }

    @MainActor
    func testLateRemoteOperationPreventsNextQueryInSameProbe() {
        var now = 0.0
        let window = FilesNavigationReadiness(clock: { now })
        var queries = 0
        XCTAssertThrowsError(try window.waitForState {
            try window.perform { queries += 1; now = 30 }
            try window.perform { queries += 1 }
            return .back
        }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
        XCTAssertEqual(queries, 1)
    }

    @MainActor
    func testNativeErrorSurvivesLateReturnAndStopsFurtherWork() {
        enum NativeFailure: Error { case unavailable }
        var now = 0.0
        let window = FilesNavigationReadiness(clock: { now })
        var calls = 0
        XCTAssertThrowsError(try window.waitForState {
            calls += 1; now = 31; throw NativeFailure.unavailable
        }) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertThrowsError(try window.perform { calls += 1 }) {
            XCTAssertTrue($0 is NativeFailure)
        }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testRunLoopPumpingCannotReenterProbeOrLeaveTimerAfterSuccess() throws {
        let window = FilesNavigationReadiness(clock: { 0 })
        var calls = 0
        var probing = false
        XCTAssertEqual(try window.waitForState {
            XCTAssertFalse(probing)
            probing = true
            defer { probing = false }
            calls += 1
            RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            return calls == 1 ? nil : .browse
        }, .browse)
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(calls, 2)
    }

    @MainActor
    func testCancellationBeforeWaitNeverStartsProbe() {
        let window = FilesNavigationReadiness(clock: { 0 })
        window.cancel()
        XCTAssertThrowsError(try window.waitForState {
            XCTFail("Cancelled probe"); return .back
        }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .cancelled) }
    }

    @MainActor
    func testCancellationWhileWaitingInvalidatesScheduledProbe() {
        let window = FilesNavigationReadiness(clock: { 0 })
        var calls = 0
        XCTAssertThrowsError(try window.waitForState {
            calls += 1
            RunLoop.main.perform(inModes: [.default]) {
                MainActor.assumeIsolated { window.cancel() }
            }
            return nil
        }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .cancelled) }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testOuterTimeoutInterruptsNativeWaitWithoutAcceptingLateState() {
        let window = FilesNavigationReadiness(timeout: 0.25)
        var calls = 0
        var nested: XCTWaiter.Result?
        XCTAssertThrowsError(try window.waitForState {
            calls += 1
            nested = XCTWaiter.wait(for: [XCTestExpectation(description: "native query")], timeout: 2)
            return .targetFolder
        }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(nested, .interrupted)
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testFinalWaitReturnMustStillBeTimely() {
        var returned = false
        var checks = 0
        let window = FilesNavigationReadiness(clock: {
            guard returned else { return 0 }
            checks += 1
            return checks == 1 ? 29 : 30
        })
        XCTAssertThrowsError(try window.waitForState {
            returned = true; return .targetFolder
        }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
    }

    @MainActor
    func testInvalidAllowanceAndNonMonotonicClockCannotAdmitWork() {
        for timeout in [0.0, -1, 31, .infinity, .nan] {
            let window = FilesNavigationReadiness(timeout: timeout, clock: { 0 })
            XCTAssertThrowsError(try window.perform { XCTFail("Invalid allowance") }) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidAllowance)
            }
        }
        for invalidNow in [-1.0, .infinity, .nan] {
            var now = 0.0
            let window = FilesNavigationReadiness(clock: { now })
            now = invalidNow
            XCTAssertThrowsError(try window.perform { XCTFail("Invalid clock") }) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidClock)
            }
        }
    }

    @MainActor
    func testCreatedFolderObservationAcceptsExactTextOrActionButtonWithoutInteraction() throws {
        for title in [TitleNode(.text, "Run folder"),
                      TitleNode(.button, "Run folder, Actions Menu", children: [
                        TitleNode(.text, "Run folder")
                      ])] {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            now = 9.25
            var captures = 0
            XCTAssertTrue(try window.waitForCreatedFolderObservation(titleCount: {
                captures += 1
                return try self.titleCount(.owner(children: [title]), window: window)
            }))
            XCTAssertEqual(captures, 1)
            XCTAssertEqual(try window.remaining(), 0.75)
        }
    }

    @MainActor
    func testCreatedFolderObservationWaitsForExactDirectTitle() throws {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var polls = 0
        var captures = 0
        XCTAssertTrue(try window.waitForCreatedFolderObservation(titleCount: {
            polls += 1
            return try window.captureTargetFolderTitleCount(title: "Run folder",
                uniqueSnapshot: {
                    captures += 1
                    if polls == 1 {
                        return TitleNode.owner(children: [
                            TitleNode(.text, "Run folder suffix"),
                            TitleNode(.button, "Run folder"),
                            TitleNode(.other, children: [TitleNode(.text, "Run folder")])
                        ])
                    }
                    return TitleNode.owner(children: [TitleNode(.text, "Run folder")])
                }, children: { $0.children }, attributes: { $0.item })
        }))
        XCTAssertEqual(polls, 2)
        XCTAssertEqual(captures, 2)
    }

    @MainActor
    func testCreatedFolderObservationRejectsInvalidCountsAndStopsWork() {
        for count in [-1, 2, Int.max] {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            var calls = 0
            XCTAssertThrowsError(try window.waitForCreatedFolderObservation(titleCount: {
                calls += 1; return count
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidTitleCount) }
            XCTAssertThrowsError(try window.waitForCreatedFolderObservation(titleCount: {
                calls += 1; return 1
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidTitleCount) }
            XCTAssertEqual(calls, 1)
        }
    }

    @MainActor
    func testCreatedFolderObservationRejectsLateResultAndCannotRenewAllowance() {
        for time in [10.0, 10.001] {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            var calls = 0
            XCTAssertThrowsError(try window.waitForCreatedFolderObservation(titleCount: {
                calls += 1; now = time; return 1
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            XCTAssertThrowsError(try window.waitForCreatedFolderObservation(titleCount: {
                calls += 1; return 1
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            XCTAssertEqual(calls, 1)
        }
    }

    @MainActor
    func testCreatedFolderObservationFinalWaiterReturnMustStillBeTimely() {
        var returned = false
        var checks = 0
        let window = FilesNavigationReadiness(timeout: 10, clock: {
            guard returned else { return 0 }
            checks += 1
            // Both the count and the outer probe return in time. The final
            // waiter-return check reaches the same original deadline.
            return checks < 3 ? 9 : 10
        })
        XCTAssertThrowsError(try window.waitForCreatedFolderObservation(titleCount: {
            returned = true; return 1
        })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
        XCTAssertEqual(checks, 3)
    }

    @MainActor
    func testCreatedFolderObservationPreservesNativeErrorEvenWhenLate() {
        enum NativeFailure: Error { case unavailable }
        var now = 0.0
        let window = FilesNavigationReadiness(timeout: 10, clock: { now })
        var calls = 0
        XCTAssertThrowsError(try window.waitForCreatedFolderObservation(titleCount: {
            calls += 1; now = 11; throw NativeFailure.unavailable
        })) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertThrowsError(try window.perform { calls += 1 }) { XCTAssertTrue($0 is NativeFailure) }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testCreatedFolderObservationCancellationPreventsFurtherProbes() {
        for phase in ["before", "during", "pending"] {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            var calls = 0
            if phase == "before" { window.cancel() }
            XCTAssertThrowsError(try window.waitForCreatedFolderObservation(titleCount: {
                calls += 1
                if phase == "during" {
                    window.cancel()
                    return 1
                }
                RunLoop.main.perform(inModes: [.default]) {
                    MainActor.assumeIsolated { window.cancel() }
                }
                return 0
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .cancelled) }
            RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            XCTAssertEqual(calls, phase == "before" ? 0 : 1)
        }
    }

    @MainActor
    func testCreatedFolderObservationCannotReenterOrPollAfterSuccess() throws {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var active = false
        var calls = 0
        XCTAssertTrue(try window.waitForCreatedFolderObservation(titleCount: {
            try window.captureTargetFolderTitleCount(title: "Run folder", uniqueSnapshot: {
                XCTAssertFalse(active)
                active = true
                defer { active = false }
                calls += 1
                RunLoop.main.run(until: Date().addingTimeInterval(0.15))
                return TitleNode.owner(children: calls == 1 ? [] : [TitleNode(.text, "Run folder")])
            }, children: { $0.children }, attributes: { $0.item })
        }))
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(calls, 2)
    }

    @MainActor
    func testTargetFolderIsProbedImmediatelyWithOnlyOrderedPositiveQueries() throws {
        var now = 0.0
        let window = FilesNavigationReadiness(timeout: 10, clock: { now })
        now = 9.25
        var calls: [String] = []
        XCTAssertTrue(try window.waitForTargetFolder(
            titleCount: { calls.append("count"); return 1 },
            enabled: { calls.append("enabled"); return true },
            hittable: { calls.append("hittable"); return true }))
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(calls, ["count", "enabled", "hittable"])
    }

    @MainActor
    func testMissingTargetFolderWaitsWithoutQueryingAnAbsentTitle() throws {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var counts = 0
        var calls: [String] = []
        XCTAssertTrue(try window.waitForTargetFolder(
            titleCount: {
                counts += 1
                calls.append("count")
                return counts == 1 ? 0 : 1
            },
            enabled: { calls.append("enabled"); return true },
            hittable: { calls.append("hittable"); return true }))
        XCTAssertEqual(calls, ["count", "count", "enabled", "hittable"])
    }

    @MainActor
    func testInvalidOrDuplicateTargetTitlesFailWithoutChoosingOne() {
        for count in [-1, 2, Int.max] {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            var calls: [String] = []
            XCTAssertThrowsError(try window.waitForTargetFolder(
                titleCount: { calls.append("count"); return count },
                enabled: { calls.append("enabled"); return true },
                hittable: { calls.append("hittable"); return true })) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidTitleCount)
            }
            XCTAssertThrowsError(try window.perform { calls.append("after failure") }) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidTitleCount)
            }
            XCTAssertEqual(calls, ["count"])
        }
    }

    @MainActor
    func testDisabledOrNonhittableTargetRemainsPendingUntilReady() throws {
        for pendingProperty in ["enabled", "hittable"] {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            var polls = 0
            var calls: [String] = []
            XCTAssertTrue(try window.waitForTargetFolder(
                titleCount: { polls += 1; calls.append("count"); return 1 },
                enabled: {
                    calls.append("enabled")
                    return pendingProperty != "enabled" || polls > 1
                },
                hittable: {
                    calls.append("hittable")
                    return pendingProperty != "hittable" || polls > 1
                }))
            let first = pendingProperty == "enabled" ? ["count", "enabled"] : ["count", "enabled", "hittable"]
            XCTAssertEqual(calls, first + ["count", "enabled", "hittable"])
        }
    }

    @MainActor
    func testEveryTargetQueryRejectsExactOrLateReturnAndStopsFurtherWork() {
        for lateOperation in 0...2 {
            for lateTime in [10.0, 10.001] {
                var now = 0.0
                let window = FilesNavigationReadiness(timeout: 10, clock: { now })
                var calls: [Int] = []
                func query(_ index: Int) {
                    calls.append(index)
                    if index == lateOperation { now = lateTime }
                }
                XCTAssertThrowsError(try window.waitForTargetFolder(
                    titleCount: { query(0); return 1 },
                    enabled: { query(1); return true },
                    hittable: { query(2); return true })) {
                    XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired)
                }
                XCTAssertThrowsError(try window.waitForTargetFolder(
                    titleCount: { calls.append(3); return 1 },
                    enabled: { calls.append(4); return true },
                    hittable: { calls.append(5); return true })) {
                    XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired)
                }
                XCTAssertEqual(calls, Array(0...lateOperation))
            }
        }
    }

    @MainActor
    func testEveryTargetQueryPreservesNativeErrorEvenWhenLate() {
        enum NativeFailure: Error { case unavailable }
        for failingOperation in 0...2 {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            var calls: [Int] = []
            func query(_ index: Int) throws {
                calls.append(index)
                if index == failingOperation {
                    now = 11
                    throw NativeFailure.unavailable
                }
            }
            XCTAssertThrowsError(try window.waitForTargetFolder(
                titleCount: { try query(0); return 1 },
                enabled: { try query(1); return true },
                hittable: { try query(2); return true })) {
                XCTAssertTrue($0 is NativeFailure)
            }
            XCTAssertThrowsError(try window.perform { calls.append(3) }) {
                XCTAssertTrue($0 is NativeFailure)
            }
            RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            XCTAssertEqual(calls, Array(0...failingOperation))
        }
    }

    @MainActor
    func testTargetFolderWaitCannotRenewAnExpiredAllowance() {
        var now = 0.0
        let window = FilesNavigationReadiness(timeout: 10, clock: { now })
        now = 10
        var calls = 0
        XCTAssertThrowsError(try window.waitForTargetFolder(
            titleCount: { calls += 1; return 1 },
            enabled: { calls += 1; return true },
            hittable: { calls += 1; return true })) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired)
        }
        XCTAssertEqual(calls, 0)
    }

    @MainActor
    func testTargetFolderProbeCannotReenterOrContinueAfterSuccess() throws {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var active = false
        var counts = 0
        var positiveQueries = 0
        XCTAssertTrue(try window.waitForTargetFolder(
            titleCount: {
                XCTAssertFalse(active)
                active = true
                defer { active = false }
                counts += 1
                RunLoop.main.run(until: Date().addingTimeInterval(0.15))
                return counts == 1 ? 0 : 1
            },
            enabled: { positiveQueries += 1; return true },
            hittable: { positiveQueries += 1; return true }))
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(counts, 2)
        XCTAssertEqual(positiveQueries, 2)
    }

    @MainActor
    func testTitleSnapshotUsesExactDirectChildPredicate() throws {
        let root = TitleNode.owner(children: [
            TitleNode(.text, "Run folder"),
            TitleNode(.button, "Run folder, Actions Menu"),
            TitleNode(.other, "Run folder"),
            TitleNode(.button, "Run folder"),
            TitleNode(.text, "Run folder, Actions Menu"),
            TitleNode(.text, "Run folder suffix"),
            TitleNode(.other, children: [TitleNode(.text, "Run folder")])
        ])
        XCTAssertEqual(try titleCount(root, window: FilesNavigationReadiness(clock: { 0 })), 2)
    }

    @MainActor
    func testTitleSnapshotRejectsDuplicateDirectTitles() {
        let root = TitleNode.owner(children: [
            TitleNode(.text, "Run folder"), TitleNode(.button, "Run folder, Actions Menu")
        ])
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        XCTAssertThrowsError(try window.waitForTargetFolder(
            titleCount: { try self.titleCount(root, window: window) },
            enabled: { XCTFail("Duplicate title queried"); return true },
            hittable: { XCTFail("Duplicate title queried"); return true })) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidTitleCount)
        }
    }

    @MainActor
    func testMissingTitleOwnerResolutionFailsWithoutPolling() {
        // Model a throwing unique resolver; XCTest owns the actual missing-match
        // failure. Its error must not become a zero-title observation.
        let native = NSError(domain: "UniqueOwnerResolution", code: 1)
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var resolutions = 0
        XCTAssertThrowsError(try window.waitForCreatedFolderObservation(titleCount: {
            try window.captureTargetFolderTitleCount(title: "Run folder",
                uniqueSnapshot: { () throws -> TitleNode in
                    resolutions += 1
                    throw native
                }, children: { _ in XCTFail("Missing owner traversed"); return [] },
                attributes: { node in XCTFail("Missing owner inspected"); return node.item })
        })) { XCTAssertTrue(($0 as NSError) === native) }
        XCTAssertThrowsError(try window.perform { resolutions += 1 }) {
            XCTAssertTrue(($0 as NSError) === native)
        }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(resolutions, 1)
    }

    @MainActor
    func testAmbiguousTitleOwnerResolutionFailsWithoutChoosingOne() {
        let native = NSError(domain: "UniqueOwnerResolution", code: 2)
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var resolutions = 0
        XCTAssertThrowsError(try window.waitForCreatedFolderObservation(titleCount: {
            try window.captureTargetFolderTitleCount(title: "Run folder",
                uniqueSnapshot: { () throws -> TitleNode in
                    resolutions += 1
                    throw native
                }, children: { _ in XCTFail("Ambiguous owner traversed"); return [] },
                attributes: { node in XCTFail("Ambiguous owner inspected"); return node.item })
        })) { XCTAssertTrue(($0 as NSError) === native) }
        XCTAssertThrowsError(try window.perform { resolutions += 1 }) {
            XCTAssertTrue(($0 as NSError) === native)
        }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(resolutions, 1)
    }

    @MainActor
    func testTitleSnapshotUsesResolvedOwnerWhenApplicationTreeOmitsIt() throws {
        let application = TitleNode(.application)
        let owner = TitleNode.owner(children: [TitleNode(.button, "Run folder, Actions Menu")])
        XCTAssertTrue(application.children.isEmpty)
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var calls: [String] = []
        let count = try window.captureTargetFolderTitleCount(title: "Run folder",
            uniqueSnapshot: { calls.append("unique owner snapshot"); return owner },
            children: { $0.children }, attributes: { $0.item })
        XCTAssertEqual(count, 1)
        XCTAssertEqual(calls, ["unique owner snapshot"])
    }

    @MainActor
    func testTitleSnapshotRefreshesEveryProbeWithoutReusingAnEarlierMatch() throws {
        let present = TitleNode.owner(children: [TitleNode(.text, "Run folder")])
        let roots = [present, TitleNode.owner(), present]
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var captures = 0
        var enabledChecks = 0
        var hitChecks = 0
        XCTAssertTrue(try window.waitForTargetFolder(
            titleCount: {
                try window.captureTargetFolderTitleCount(title: "Run folder", uniqueSnapshot: {
                    let root = roots[min(captures, roots.count - 1)]
                    captures += 1
                    return root
                }, children: { $0.children }, attributes: { $0.item })
            }, enabled: { enabledChecks += 1; return captures == 3 },
            hittable: { hitChecks += 1; return true }))
        XCTAssertEqual(captures, 3)
        XCTAssertEqual(enabledChecks, 2)
        XCTAssertEqual(hitChecks, 1)
    }

    @MainActor
    func testTitleSnapshotRequiresNavigationBarRootAndExactIdentifier() {
        for root in [TitleNode(.application), TitleNode(.other,
                     identifier: "FullDocumentManagerViewControllerNavigationBar"),
                     TitleNode(.navigationBar, identifier: "OtherBar")] {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            XCTAssertThrowsError(try titleCount(root, window: window)) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidTitleSnapshot)
            }
            XCTAssertThrowsError(try window.perform { XCTFail("Invalid snapshot resumed") }) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidTitleSnapshot)
            }
        }
    }

    @MainActor
    func testTitleSnapshotResolutionUsesRemainingAllowanceOnce() throws {
        var now = 0.0
        let window = FilesNavigationReadiness(timeout: 10, clock: { now })
        var resolutions = 0
        XCTAssertTrue(try window.waitForCreatedFolderObservation(titleCount: {
            try window.captureTargetFolderTitleCount(title: "Run folder", uniqueSnapshot: {
                resolutions += 1
                now += 9.5
                return TitleNode.owner(children: [TitleNode(.button, "Run folder, Actions Menu")])
            }, children: { $0.children }, attributes: { $0.item })
        }))
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(resolutions, 1)
        XCTAssertEqual(try window.remaining(), 0.5)
    }

    @MainActor
    func testTitleSnapshotExpiredAdmissionNeverResolvesOwner() {
        for time in [10.0, 10.001] {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            now = time
            XCTAssertThrowsError(try window.captureTargetFolderTitleCount(title: "Run folder",
                uniqueSnapshot: { XCTFail("Expired owner resolved"); return TitleNode.owner() },
                children: { _ in XCTFail("Expired owner traversed"); return [] },
                attributes: { node in XCTFail("Expired owner inspected"); return node.item })) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired)
            }
        }
    }

    @MainActor
    func testTitleSnapshotRejectsExactOrLateCaptureBeforeTraversal() {
        for time in [10.0, 10.001] {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            XCTAssertThrowsError(try window.captureTargetFolderTitleCount(title: "Run folder",
                uniqueSnapshot: { now = time; return TitleNode.owner() },
                children: { _ in XCTFail("Late capture traversed"); return [] },
                attributes: { node in XCTFail("Late capture inspected"); return node.item })) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired)
            }
        }
    }

    @MainActor
    func testTitleSnapshotRejectsLateAttributesAndChildrenBeforeFurtherTraversal() {
        for stage in ["owner attributes", "children", "title attributes"] {
            var now = 0.0
            var calls: [String] = []
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            XCTAssertThrowsError(try window.captureTargetFolderTitleCount(title: "Run folder",
                uniqueSnapshot: { TitleNode.owner(children: [TitleNode(.text, "Run folder")]) },
                children: { node in
                    calls.append("children")
                    if stage == "children" { now = 10 }
                    return node.children
                }, attributes: { node in
                    let name = node.kind == .navigationBar ? "owner attributes" : "title attributes"
                    calls.append(name)
                    if stage == name { now = 10 }
                    return node.item
                })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
            let expected = ["owner attributes", "children", "title attributes"]
            XCTAssertEqual(calls, Array(expected.prefix(expected.firstIndex(of: stage)! + 1)))
        }
    }

    @MainActor
    func testTitleSnapshotPreservesNativeCaptureErrorEvenWhenLate() {
        enum NativeFailure: Error { case unavailable }
        var now = 0.0
        let window = FilesNavigationReadiness(timeout: 10, clock: { now })
        XCTAssertThrowsError(try window.captureTargetFolderTitleCount(title: "Run folder",
            uniqueSnapshot: { () throws -> TitleNode in now = 11; throw NativeFailure.unavailable },
            children: { _ in XCTFail("Failed capture traversed"); return [] },
            attributes: { node in XCTFail("Failed capture inspected"); return node.item })) {
            XCTAssertTrue($0 is NativeFailure)
        }
        XCTAssertThrowsError(try window.perform { XCTFail("Failed capture resumed") }) {
            XCTAssertTrue($0 is NativeFailure)
        }
    }

    @MainActor
    func testTitleSnapshotRejectsOversizedDirectChildrenBeforeInspection() {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        let root = TitleNode.owner(children:
            Array(repeating: TitleNode(.other), count: FilesNavigationReadiness.titleSnapshotNodeLimit))
        var inspected = 0
        XCTAssertThrowsError(try window.captureTargetFolderTitleCount(title: "Run folder",
            uniqueSnapshot: { root }, children: { $0.children },
            attributes: { node in inspected += 1; return node.item })) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidTitleSnapshot)
        }
        XCTAssertEqual(inspected, 1)
    }

    @MainActor
    func testTitleSnapshotDoesNotTraverseOrDoubleCountDescendantTitles() throws {
        let root = TitleNode.owner(children: [
            TitleNode(.button, "Run folder, Actions Menu", children: [TitleNode(.text, "Run folder")]),
            TitleNode(.other, children: [TitleNode(.text, "Run folder")])
        ])
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var childQueries = 0
        var inspected = 0
        let count = try window.captureTargetFolderTitleCount(title: "Run folder",
            uniqueSnapshot: { root }, children: { node in
                childQueries += 1
                XCTAssertTrue(node.kind == .navigationBar)
                return node.children
            }, attributes: { node in inspected += 1; return node.item })
        XCTAssertEqual(count, 1)
        XCTAssertEqual(childQueries, 1)
        XCTAssertEqual(inspected, 3)
    }

    @MainActor
    func testTitleSnapshotAcceptsExactNodeLimitAndStillFindsTheTitle() throws {
        let filler = Array(repeating: TitleNode(.other),
                           count: FilesNavigationReadiness.titleSnapshotNodeLimit - 2)
        let root = TitleNode.owner(children: filler + [TitleNode(.button, "Run folder, Actions Menu")])
        XCTAssertEqual(try titleCount(root, window: FilesNavigationReadiness(clock: { 0 })), 1)
    }

    @MainActor
    func testTitleSnapshotCancellationBeforeResolutionDoesNotQuery() {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        window.cancel()
        XCTAssertThrowsError(try window.captureTargetFolderTitleCount(title: "Run folder",
            uniqueSnapshot: { XCTFail("Cancelled owner resolved"); return TitleNode.owner() },
            children: { _ in XCTFail("Cancelled owner traversed"); return [] },
            attributes: { node in XCTFail("Cancelled owner inspected"); return node.item })) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .cancelled)
        }
    }

    @MainActor
    func testTitleSnapshotCancellationPreventsTraversal() {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        XCTAssertThrowsError(try window.captureTargetFolderTitleCount(title: "Run folder",
            uniqueSnapshot: { window.cancel(); return TitleNode.owner() },
            children: { _ in XCTFail("Cancelled capture traversed"); return [] },
            attributes: { node in XCTFail("Cancelled capture inspected"); return node.item })) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .cancelled)
        }
    }

    @MainActor
    func testTitleSnapshotDoesNotRelaxTheLivePropertyDeadline() {
        let root = TitleNode.owner(children: [TitleNode(.text, "Run folder")])
        for lateStage in ["enabled", "hittable"] {
            var now = 0.0
            var hits = 0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            XCTAssertThrowsError(try window.waitForTargetFolder(
                titleCount: { try self.titleCount(root, window: window) },
                enabled: { if lateStage == "enabled" { now = 10 }; return true },
                hittable: { hits += 1; now = 10; return true })) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired)
            }
            XCTAssertEqual(hits, lateStage == "enabled" ? 0 : 1)
        }
    }

    @MainActor
    func testFileSelectionChecksExactScopesInOrderAndTapsOnce() throws {
        var now = 0.0
        let window = FilesNavigationReadiness(timeout: 10, clock: { now })
        now = 9.25
        var calls: [String] = []
        func select() throws {
            try window.waitAndTapFile(
                pickerCount: { calls.append("picker"); return 1 },
                folderCount: { calls.append("folder"); return 1 },
                fileViewCount: { calls.append("view"); return 1 },
                fileCount: { calls.append("file"); return 1 },
                enabled: { calls.append("enabled"); return true },
                hittable: { calls.append("hittable"); return true },
                tap: { calls.append("tap") })
        }
        try select()
        XCTAssertThrowsError(try select()) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .selectionAlreadyStarted)
        }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(calls, ["picker", "folder", "view", "file", "enabled", "hittable", "tap"])
    }

    @MainActor
    func testMissingFileScopeWaitsWithoutQueryingItsDescendants() throws {
        for missingScope in 0...3 {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            var calls: [Int] = []
            var polls = 0
            func count(_ scope: Int) -> Int {
                if scope == 0 { polls += 1 }
                calls.append(scope)
                return polls == 1 && scope == missingScope ? 0 : 1
            }
            try window.waitAndTapFile(
                pickerCount: { count(0) }, folderCount: { count(1) },
                fileViewCount: { count(2) }, fileCount: { count(3) },
                enabled: { calls.append(4); return true },
                hittable: { calls.append(5); return true }, tap: { calls.append(6) })
            XCTAssertEqual(calls, Array(0...missingScope) + Array(0...6))
        }
    }

    @MainActor
    func testInvalidOrDuplicateFileScopesFailBeforeAnyDescendantOrTap() {
        for badScope in 0...3 {
            for badCount in [-1, 2, Int.max] {
                let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
                var calls: [Int] = []
                func count(_ scope: Int) -> Int {
                    calls.append(scope)
                    return scope == badScope ? badCount : 1
                }
                XCTAssertThrowsError(try window.waitAndTapFile(
                    pickerCount: { count(0) }, folderCount: { count(1) },
                    fileViewCount: { count(2) }, fileCount: { count(3) },
                    enabled: { calls.append(4); return true },
                    hittable: { calls.append(5); return true }, tap: { calls.append(6) })) {
                    XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidSelectionCount)
                }
                XCTAssertThrowsError(try window.perform { calls.append(7) }) {
                    XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .invalidSelectionCount)
                }
                XCTAssertEqual(calls, Array(0...badScope))
            }
        }
    }

    @MainActor
    func testDisabledOrNonhittableFileWaitsBeforeSingleTap() throws {
        for pendingProperty in 4...5 {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            var calls: [Int] = []
            var polls = 0
            func count(_ scope: Int) -> Int {
                if scope == 0 { polls += 1 }
                calls.append(scope)
                return 1
            }
            func ready(_ property: Int) -> Bool {
                calls.append(property)
                return property != pendingProperty || polls > 1
            }
            try window.waitAndTapFile(
                pickerCount: { count(0) }, folderCount: { count(1) },
                fileViewCount: { count(2) }, fileCount: { count(3) },
                enabled: { ready(4) }, hittable: { ready(5) }, tap: { calls.append(6) })
            XCTAssertEqual(calls, Array(0...pendingProperty) + Array(0...6))
        }
    }

    @MainActor
    func testEveryFileOperationRejectsExactOrLateReturnWithoutRetry() {
        for lateOperation in 0...6 {
            for lateTime in [10.0, 10.001] {
                var now = 0.0
                let window = FilesNavigationReadiness(timeout: 10, clock: { now })
                var calls: [Int] = []
                func operation(_ index: Int) {
                    calls.append(index)
                    if index == lateOperation { now = lateTime }
                }
                func select() throws {
                    try window.waitAndTapFile(
                        pickerCount: { operation(0); return 1 },
                        folderCount: { operation(1); return 1 },
                        fileViewCount: { operation(2); return 1 },
                        fileCount: { operation(3); return 1 },
                        enabled: { operation(4); return true },
                        hittable: { operation(5); return true }, tap: { operation(6) })
                }
                XCTAssertThrowsError(try select()) {
                    XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired)
                }
                XCTAssertThrowsError(try select()) {
                    XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired)
                }
                XCTAssertEqual(calls, Array(0...lateOperation))
            }
        }
    }

    @MainActor
    func testEveryFileOperationPreservesNativeErrorEvenWhenLate() {
        final class NativeFailure: Error {}
        for failedOperation in 0...6 {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            let expected = NativeFailure()
            var calls: [Int] = []
            func operation(_ index: Int) throws {
                calls.append(index)
                if index == failedOperation { now = 11; throw expected }
            }
            XCTAssertThrowsError(try window.waitAndTapFile(
                pickerCount: { try operation(0); return 1 },
                folderCount: { try operation(1); return 1 },
                fileViewCount: { try operation(2); return 1 },
                fileCount: { try operation(3); return 1 },
                enabled: { try operation(4); return true },
                hittable: { try operation(5); return true }, tap: { try operation(6) })) {
                XCTAssertTrue(($0 as? NativeFailure) === expected)
            }
            XCTAssertThrowsError(try window.perform { calls.append(7) }) {
                XCTAssertTrue(($0 as? NativeFailure) === expected)
            }
            XCTAssertEqual(calls, Array(0...failedOperation))
        }
    }

    @MainActor
    func testFileSelectionReentryCannotAdmitAnotherQueryOrTap() {
        for reenterAtTap in [false, true] {
            let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
            var queries = 0
            var taps = 0
            var reentrantOperations = 0
            func reenter() {
                XCTAssertThrowsError(try window.waitAndTapFile(
                    pickerCount: { reentrantOperations += 1; return 1 },
                    folderCount: { reentrantOperations += 1; return 1 },
                    fileViewCount: { reentrantOperations += 1; return 1 },
                    fileCount: { reentrantOperations += 1; return 1 },
                    enabled: { reentrantOperations += 1; return true },
                    hittable: { reentrantOperations += 1; return true },
                    tap: { reentrantOperations += 1 })) {
                    XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .selectionAlreadyStarted)
                }
            }
            XCTAssertThrowsError(try window.waitAndTapFile(
                pickerCount: {
                    queries += 1
                    if !reenterAtTap { reenter() }
                    return 1
                }, folderCount: { queries += 1; return 1 },
                fileViewCount: { queries += 1; return 1 }, fileCount: { queries += 1; return 1 },
                enabled: { queries += 1; return true }, hittable: { queries += 1; return true },
                tap: { taps += 1; reenter() })) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .selectionAlreadyStarted)
            }
            XCTAssertEqual(queries, reenterAtTap ? 6 : 1)
            XCTAssertEqual(taps, reenterAtTap ? 1 : 0)
            XCTAssertEqual(reentrantOperations, 0)
        }
    }

    @MainActor
    func testNavigationWaitCannotReenterFileSelectionWaiter() {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var taps = 0
        XCTAssertThrowsError(try window.waitAndTapFile(
            pickerCount: {
                XCTAssertThrowsError(try window.waitForState {
                    XCTFail("Reentrant navigation probe"); return .targetFolder
                }) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .alreadyWaiting) }
                return 1
            }, folderCount: { XCTFail("After reentry"); return 1 },
            fileViewCount: { XCTFail("After reentry"); return 1 },
            fileCount: { XCTFail("After reentry"); return 1 },
            enabled: { XCTFail("After reentry"); return true },
            hittable: { XCTFail("After reentry"); return true }, tap: { taps += 1 })) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .alreadyWaiting)
        }
        XCTAssertEqual(taps, 0)
    }

    @MainActor
    func testFileSelectionPumpingRunLoopCannotOverlapOrContinueAfterTap() throws {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var active = false
        var polls = 0
        var taps = 0
        try window.waitAndTapFile(
            pickerCount: {
                XCTAssertFalse(active)
                active = true
                defer { active = false }
                polls += 1
                RunLoop.main.run(until: Date().addingTimeInterval(0.15))
                return polls == 1 ? 0 : 1
            }, folderCount: { 1 }, fileViewCount: { 1 }, fileCount: { 1 },
            enabled: { true }, hittable: { true },
            tap: {
                taps += 1
                RunLoop.main.run(until: Date().addingTimeInterval(0.15))
            })
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(polls, 2)
        XCTAssertEqual(taps, 1)
    }

    @MainActor
    func testFileSelectionUsesExistingDeadlineAndHonorsCancellation() throws {
        for cancel in [false, true] {
            var now = 0.0
            let window = FilesNavigationReadiness(timeout: 10, clock: { now })
            XCTAssertEqual(try window.waitForState { .targetFolder }, .targetFolder)
            if cancel { window.cancel() } else { now = 10 }
            var calls = 0
            XCTAssertThrowsError(try window.waitAndTapFile(
                pickerCount: { calls += 1; return 1 }, folderCount: { calls += 1; return 1 },
                fileViewCount: { calls += 1; return 1 }, fileCount: { calls += 1; return 1 },
                enabled: { calls += 1; return true }, hittable: { calls += 1; return true },
                tap: { calls += 1 })) {
                XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, cancel ? .cancelled : .expired)
            }
            XCTAssertEqual(calls, 0)
        }
    }

    @MainActor
    func testFileSelectionCancellationDuringProbePreventsTap() {
        let window = FilesNavigationReadiness(timeout: 10, clock: { 0 })
        var calls = 0
        XCTAssertThrowsError(try window.waitAndTapFile(
            pickerCount: { calls += 1; window.cancel(); return 1 },
            folderCount: { XCTFail("Cancelled descendant"); return 1 },
            fileViewCount: { XCTFail("Cancelled descendant"); return 1 },
            fileCount: { XCTFail("Cancelled descendant"); return 1 },
            enabled: { XCTFail("Cancelled descendant"); return true },
            hittable: { XCTFail("Cancelled descendant"); return true },
            tap: { XCTFail("Cancelled tap") })) {
            XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .cancelled)
        }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testFileTapIsInsideTheActiveOuterWaiter() {
        let window = FilesNavigationReadiness(timeout: 0.25)
        var taps = 0
        var nested: XCTWaiter.Result?
        XCTAssertThrowsError(try window.waitAndTapFile(
            pickerCount: { 1 }, folderCount: { 1 }, fileViewCount: { 1 }, fileCount: { 1 },
            enabled: { true }, hittable: { true },
            tap: {
                taps += 1
                nested = XCTWaiter.wait(for: [XCTestExpectation(description: "native tap")], timeout: 2)
            })) { XCTAssertEqual($0 as? FilesNavigationReadiness.Failure, .expired) }
        RunLoop.main.run(until: Date().addingTimeInterval(0.15))
        XCTAssertEqual(nested, .interrupted)
        XCTAssertEqual(taps, 1)
    }
}
