import XCTest

final class RecoveryPhotosAppearanceWindowTests: XCTestCase {
    func testSystemPickerAppearingAfterTwentySecondsIsAccepted() throws {
        var now = 100.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        now = 101
        XCTAssertTrue(try window.wait { remaining in
            XCTAssertEqual(remaining, 89)
            now = 121
            return true
        })
        XCTAssertEqual(try window.remaining(), 69)
    }

    func testColdFirstPresentationAtSixtyEightSecondsKeepsOriginalDeadline() throws {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        XCTAssertFalse(try window.wait { _ in
            now = 20
            return false
        })
        XCTAssertTrue(try window.wait { _ in
            now = 68
            return true
        })
        XCTAssertEqual(try window.remaining(), 22)
    }

    func testExactOrLateSuccessfulQueryCannotAuthorizeSelection() {
        for elapsed in [90.0, 90.001] {
            var now = 0.0
            let window = RecoveryPhotosAppearanceWindow(clock: { now })
            var selected = false
            XCTAssertThrowsError(try {
                let appeared = try window.wait { _ in now = elapsed; return true }
                selected = appeared
            }()) { XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired) }
            XCTAssertFalse(selected)
        }
    }

    func testExpiredWindowDoesNotStartAnotherQuery() {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        now = 90
        var queries = 0
        XCTAssertThrowsError(try window.wait { _ in queries += 1; return true }) {
            XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired)
        }
        XCTAssertEqual(queries, 0)
    }

    func testFalseResultIsPreservedWithoutRenewingBudget() throws {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        XCTAssertFalse(try window.wait { remaining in
            XCTAssertEqual(remaining, 90)
            now = 20
            return false
        })
        XCTAssertEqual(try window.remaining(), 70)
    }

    func testQueryFailureIsPreservedAndCannotAuthorizeSelection() {
        enum QueryFailure: Error { case unavailable }
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        var selected = false
        XCTAssertThrowsError(try {
            _ = try window.wait { _ in
                now = 91
                throw QueryFailure.unavailable
            }
            selected = true
        }()) { XCTAssertTrue($0 is QueryFailure) }
        XCTAssertFalse(selected)
    }

    @MainActor
    func testFirstProbeStartsBeforePredicatePollingDelay() throws {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        now = 89.5 // Less than the native predicate's initial one-second delay.
        var calls = 0
        XCTAssertTrue(try window.waitForProbe {
            XCTAssertTrue(Thread.isMainThread)
            calls += 1
            return true
        })
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testNegativeProbeLeavesAQuietIntervalBeforeNextQuery() throws {
        @MainActor final class Observation {
            var calls = 0
            var quietIntervalObserved = false
        }
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        now = 88
        let observation = Observation()
        var quietInterval: Timer?
        defer { quietInterval?.invalidate() }
        XCTAssertTrue(try window.waitForProbe {
            observation.calls += 1
            if observation.calls == 1 {
                let timer = Timer(timeInterval: 0.5, repeats: false) { _ in
                    MainActor.assumeIsolated {
                        XCTAssertEqual(observation.calls, 1)
                        observation.quietIntervalObserved = true
                    }
                }
                quietInterval = timer
                RunLoop.main.add(timer, forMode: .default)
                return false
            }
            XCTAssertTrue(observation.quietIntervalObserved)
            return observation.calls == 2
        })
        XCTAssertEqual(observation.calls, 2)
        XCTAssertTrue(observation.quietIntervalObserved)
        XCTAssertEqual(try window.remaining(), 2)
    }

    @MainActor
    func testOuterDeadlineInterruptsNestedWaitWithoutAnotherProbe() {
        let start = ProcessInfo.processInfo.systemUptime
        var used = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: {
            used + ProcessInfo.processInfo.systemUptime - start
        })
        used = 89.25
        var calls = 0
        var nested: XCTWaiter.Result?
        XCTAssertThrowsError(try window.waitForProbe {
            calls += 1
            nested = XCTWaiter.wait(for: [XCTestExpectation(description: "pending native query")], timeout: 3)
            return true
        }) { XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired) }
        XCTAssertEqual(nested, .interrupted)
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testNextProbeCannotReenterOperationPumpingRunLoop() throws {
        let window = RecoveryPhotosAppearanceWindow()
        var calls = 0
        var depth = 0
        var maximumDepth = 0
        XCTAssertTrue(try window.waitForProbe {
            calls += 1
            depth += 1
            maximumDepth = max(maximumDepth, depth)
            defer { depth -= 1 }
            if calls == 1 {
                let completed = XCTestExpectation(description: "slow first query")
                let timer = Timer(timeInterval: 1.1, repeats: false) { _ in completed.fulfill() }
                RunLoop.main.add(timer, forMode: .default)
                defer { timer.invalidate() }
                XCTAssertEqual(XCTWaiter.wait(for: [completed], timeout: 3), .completed)
                return false
            }
            return true
        })
        XCTAssertEqual(calls, 2)
        XCTAssertEqual(maximumDepth, 1)
    }

    @MainActor
    func testTimedOutWaitCancelsPendingTimerAndHasNoFinalQuery() throws {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        now = 89.5
        var calls = 0
        XCTAssertFalse(try window.waitForProbe { calls += 1; return false })
        let callsAtReturn = calls
        XCTAssertGreaterThan(callsAtReturn, 0)
        // The injected deadline remains open, so only waiter teardown can
        // prevent the pending timer from making an additional query.
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "pump canceled timer")], timeout: 1.05)
        XCTAssertEqual(calls, callsAtReturn)
    }

    @MainActor
    func testExpiredWindowDoesNotQueueFirstProbe() {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        now = 90
        var calls = 0
        XCTAssertThrowsError(try window.waitForProbe { calls += 1; return true }) {
            XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired)
        }
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "pump rejected first probe")], timeout: 0.01)
        XCTAssertEqual(calls, 0)
    }

    @MainActor
    func testExpirationAfterSchedulingClosesQueuedFirstProbe() {
        var clockReads = 0
        let window = RecoveryPhotosAppearanceWindow(clock: {
            clockReads += 1
            return clockReads <= 2 ? 0 : 90
        })
        var calls = 0
        XCTAssertThrowsError(try window.waitForProbe { calls += 1; return true }) {
            XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired)
        }
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "pump closed first probe")], timeout: 0.01)
        XCTAssertEqual(calls, 0)
    }

    @MainActor
    func testExactOrLateProbeCannotAuthorizeSelectionOrStartAnotherQuery() {
        for elapsed in [90.0, 90.001] {
            var now = 0.0
            let window = RecoveryPhotosAppearanceWindow(clock: { now })
            now = 89.25
            var calls = 0
            var selected = false
            XCTAssertThrowsError(try {
                selected = try window.waitForProbe {
                    calls += 1
                    now = elapsed
                    return true
                }
            }()) { XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired) }
            XCTAssertFalse(selected)
            XCTAssertEqual(calls, 1)
        }
    }

    private final class Node {
        let item: RecoveryPhotosAppearanceWindow.Item
        var children: [Node]
        init(_ kind: RecoveryPhotosAppearanceWindow.ItemKind = .other,
             identifier: String = "", label: String = "", children: [Node] = []) {
            item = .init(kind: kind, identifier: identifier, label: label)
            self.children = children
        }
    }

    private func owner(_ children: [Node] = []) -> Node {
        Node(.scrollView, identifier: RecoveryPhotosAppearanceWindow.contentIdentifier,
             children: children)
    }

    private func capture(_ root: Node, window: RecoveryPhotosAppearanceWindow,
                         count: Int = 1) throws -> RecoveryPhotosAppearanceWindow.Observation? {
        try window.captureObservation(ownerCount: { count }, uniqueSnapshot: { root },
                                      children: { $0.children }, attributes: { $0.item })
    }

    func testMissingPhotosOwnerDoesNotCaptureOrReadAttributes() throws {
        let window = RecoveryPhotosAppearanceWindow(clock: { 0 })
        let observed = try window.captureObservation(ownerCount: { 0 },
            uniqueSnapshot: { XCTFail("Missing owner must not resolve"); return self.owner() },
            children: { _ in XCTFail("No snapshot children"); return [] },
            attributes: { node in XCTFail("No attributes"); return node.item })
        XCTAssertNil(observed)
    }

    func testInvalidPhotosOwnerCountDoesNotCapture() {
        for count in [-1, 2] {
            let window = RecoveryPhotosAppearanceWindow(clock: { 0 })
            XCTAssertThrowsError(try window.captureObservation(ownerCount: { count },
                uniqueSnapshot: { XCTFail("Ambiguous owner must not resolve"); return self.owner() },
                children: { $0.children }, attributes: { $0.item })) {
                XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .invalidOwnerCount)
            }
        }
    }

    func testPhotosSnapshotRequiresExactOwnerTypeAndIdentifier() {
        for root in [Node(.other, identifier: RecoveryPhotosAppearanceWindow.contentIdentifier),
                     Node(.scrollView, identifier: "other content")] {
            XCTAssertThrowsError(try capture(root, window: .init(clock: { 0 }))) {
                XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .invalidSnapshot)
            }
        }
    }

    func testNestedDuplicatePhotosOwnerIsRejected() {
        XCTAssertThrowsError(try capture(owner([owner()]), window: .init(clock: { 0 }))) {
            XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .invalidOwnerCount)
        }
    }

    func testEmptyPhotosSnapshotRemainsPending() throws {
        XCTAssertNil(try capture(owner(), window: .init(clock: { 0 })))
    }

    func testOnlyMatchingImageTypeQualifiesForPhotosObservation() throws {
        let root = owner([Node(.other, label: "Photo, November 06"),
                          Node(.image, label: "Photo On A Rectangle"),
                          Node(.image, label: "Video, November 06")])
        XCTAssertNil(try capture(root, window: .init(clock: { 0 })))
    }

    func testPhotosObservationPreservesExactLabelFromSingleCapture() throws {
        let label = "pHoTo, November 06, 1:49 AM"
        let root = owner([Node(children: [Node(.image, label: label)])])
        var captures = 0
        let window = RecoveryPhotosAppearanceWindow(clock: { 0 })
        let observed = try window.captureObservation(ownerCount: { 1 },
            uniqueSnapshot: { captures += 1; return root },
            children: { $0.children }, attributes: { $0.item })
        root.children = [] // Later tree changes cannot change the observed count or label.
        XCTAssertEqual(captures, 1)
        XCTAssertEqual(observed, .init(imageCount: 1, label: label))
    }

    func testMultipleMatchingPhotosFailInsteadOfChoosingFirst() {
        let root = owner([Node(.image, label: "Photo, first"), Node(.image, label: "Photo, second")])
        XCTAssertThrowsError(try capture(root, window: .init(clock: { 0 }))) {
            XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .invalidImageCount)
        }
    }

    func testExactPhotosSnapshotNodeLimitIsAccepted() throws {
        let children = (0..<(RecoveryPhotosAppearanceWindow.snapshotNodeLimit - 1)).map { _ in Node() }
        XCTAssertNil(try capture(owner(children), window: .init(clock: { 0 })))
    }

    func testOversizedPhotosSnapshotIsRejectedBeforeTraversingChildren() {
        let root = owner((0..<RecoveryPhotosAppearanceWindow.snapshotNodeLimit).map { _ in Node() })
        var attributesRead = 0
        let window = RecoveryPhotosAppearanceWindow(clock: { 0 })
        XCTAssertThrowsError(try window.captureObservation(ownerCount: { 1 }, uniqueSnapshot: { root },
            children: { $0.children }, attributes: { attributesRead += 1; return $0.item })) {
            XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .invalidSnapshot)
        }
        XCTAssertEqual(attributesRead, 1)
    }

    func testOversizedPhotosSnapshotStringsAreRejected() {
        for node in [Node(.image, label: "Photo," + String(repeating: "x", count: 1_024)),
                     Node(identifier: String(repeating: "x", count: 1_025))] {
            XCTAssertThrowsError(try capture(owner([node]), window: .init(clock: { 0 }))) {
                XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .invalidSnapshot)
            }
        }
    }

    func testLatePhotosOwnerCountCannotStartSnapshot() {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        XCTAssertThrowsError(try window.captureObservation(ownerCount: { now = 90; return 1 },
            uniqueSnapshot: { XCTFail("Late count cannot start snapshot"); return self.owner() },
            children: { $0.children }, attributes: { $0.item })) {
            XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired)
        }
    }

    func testLatePhotosSnapshotCannotReadItsAttributes() {
        for elapsed in [90.0, 90.001] {
            var now = 0.0
            let window = RecoveryPhotosAppearanceWindow(clock: { now })
            XCTAssertThrowsError(try window.captureObservation(ownerCount: { 1 },
                uniqueSnapshot: { now = elapsed; return self.owner([Node(.image, label: "Photo, receipt")]) },
                children: { _ in XCTFail("Late snapshot cannot be traversed"); return [] },
                attributes: { node in XCTFail("Late snapshot cannot be read"); return node.item })) {
                XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired)
            }
        }
    }

    func testPhotosResolverAndCancellationErrorsRemainPrimaryAfterDeadline() {
        enum ResolverFailure: Error { case disappeared }
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        XCTAssertThrowsError(try window.captureObservation(ownerCount: { 1 },
            uniqueSnapshot: { () throws -> Node in now = 91; throw ResolverFailure.disappeared },
            children: { $0.children }, attributes: { $0.item })) {
            XCTAssertTrue($0 is ResolverFailure)
        }
        var cancellationTime = 0.0
        let canceledWindow = RecoveryPhotosAppearanceWindow(clock: { cancellationTime })
        XCTAssertThrowsError(try canceledWindow.captureObservation(ownerCount: { 1 },
            uniqueSnapshot: { () throws -> Node in cancellationTime = 91; throw CancellationError() },
            children: { $0.children }, attributes: { $0.item })) {
            XCTAssertTrue($0 is CancellationError)
        }
    }

    func testPhotosTraversalCannotReturnObservationAfterDeadline() {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        let root = owner([Node(.image, label: "Photo, receipt")])
        XCTAssertThrowsError(try window.captureObservation(ownerCount: { 1 }, uniqueSnapshot: { root },
            children: { $0.children }, attributes: { node in
                if node.item.kind == .image { now = 90 }
                return node.item
            })) { XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired) }
    }

    @MainActor
    func testThrowingPhotosObservationIsNotRetriedOrConvertedToAbsence() {
        enum SnapshotFailure: Error { case unavailable }
        let window = RecoveryPhotosAppearanceWindow(clock: { 0 })
        var calls = 0
        XCTAssertThrowsError(try window.waitForObservation { () throws -> Int? in
            calls += 1
            throw SnapshotFailure.unavailable
        }) { XCTAssertTrue($0 is SnapshotFailure) }
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "no retry after capture error")], timeout: 0.01)
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testLatePhotosObservationCannotEscapeWaiter() {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        var calls = 0
        XCTAssertThrowsError(try window.waitForObservation { () -> Int? in
            calls += 1
            now = 90
            return 1
        }) { XCTAssertEqual($0 as? RecoveryPhotosAppearanceWindow.Failure, .expired) }
        XCTAssertEqual(calls, 1)
    }
}
