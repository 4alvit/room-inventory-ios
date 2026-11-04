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
