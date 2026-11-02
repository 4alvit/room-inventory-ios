import XCTest

final class RecoveryOCRReadinessWindowTests: XCTestCase {
    func testOneSnapshotServesStateAndGeometryWithinSharedBudget() throws {
        var now = 100.0
        let window = RecoveryOCRReadinessWindow(clock: { now })
        var snapshots = 0
        var hitTests = 0
        let observation = try window.probe(snapshot: {
            snapshots += 1
            now += 3
            return "same snapshot"
        }, stateReady: {
            XCTAssertEqual($0, "same snapshot")
            now += 1
            return true
        }, hittable: {
            hitTests += 1
            now += 3
            return true
        })
        XCTAssertEqual(observation, "same snapshot")
        try window.perform { now += 2 } // Geometry and its evidence use the remainder.
        XCTAssertEqual(try window.remaining(), 1)
        XCTAssertEqual(snapshots, 1)
        XCTAssertEqual(hitTests, 1)
    }

    func testLateSnapshotStateOrHitTestCannotAdmitTapOrNextStage() {
        for delayedStage in 0..<3 {
            for elapsed in [10.0, 10.001] {
                var now = 0.0
                let window = RecoveryOCRReadinessWindow(clock: { now })
                var stages = [String]()
                var tapped = false
                XCTAssertThrowsError(try {
                    _ = try window.probe(snapshot: {
                        stages.append("snapshot")
                        if delayedStage == 0 { now = elapsed }
                        return true
                    }, stateReady: { state in
                        stages.append("state")
                        if delayedStage == 1 { now = elapsed }
                        return state
                    }, hittable: {
                        stages.append("hittable")
                        if delayedStage == 2 { now = elapsed }
                        return true
                    })
                    _ = try window.remaining()
                    tapped = true
                }()) { XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired) }
                XCTAssertEqual(stages.count, delayedStage + 1)
                XCTAssertFalse(tapped)
            }
        }
    }

    func testUnreadyStateAvoidsRemoteHitTestAndDoesNotRenewDeadline() throws {
        var now = 0.0
        let window = RecoveryOCRReadinessWindow(clock: { now })
        var hitTests = 0
        let observation = try window.probe(snapshot: { now = 3; return false },
            stateReady: { $0 }, hittable: { hitTests += 1; return true })
        XCTAssertNil(observation)
        XCTAssertEqual(hitTests, 0)
        now = 9
        XCTAssertEqual(try window.remaining(), 1)
        now = 10
        var queried = false
        XCTAssertThrowsError(try window.probe(snapshot: { queried = true; return true },
            stateReady: { $0 }, hittable: { true }))
        XCTAssertFalse(queried)
    }

    func testNonHittableSnapshotCannotBecomeReady() throws {
        let window = RecoveryOCRReadinessWindow(clock: { 0 })
        XCTAssertNil(try window.probe(snapshot: { "visible" }, stateReady: { _ in true },
                                      hittable: { false }))
    }

    func testLateGeometryOrEvidenceCannotAdmitTap() throws {
        for delayedStage in 0..<2 {
            var now = 0.0
            let window = RecoveryOCRReadinessWindow(clock: { now })
            _ = try window.probe(snapshot: { true }, stateReady: { $0 }, hittable: { true })
            var tapped = false
            XCTAssertThrowsError(try {
                for stage in 0..<2 {
                    try window.perform { if stage == delayedStage { now = 10 } }
                }
                _ = try window.remaining()
                tapped = true
            }())
            XCTAssertFalse(tapped)
        }
    }

    func testObservationErrorIsNotConvertedToReadinessOrRetried() {
        enum InvalidSnapshot: Error { case duplicateTarget }
        let window = RecoveryOCRReadinessWindow(clock: { 0 })
        var hitTests = 0
        XCTAssertThrowsError(try window.probe(snapshot: { true }, stateReady: { _ in
            throw InvalidSnapshot.duplicateTarget
        }, hittable: { hitTests += 1; return true })) {
            XCTAssertTrue($0 is InvalidSnapshot)
        }
        XCTAssertEqual(hitTests, 0)
    }

    @MainActor
    func testFirstProbeRunsInsideWaiterBeforePredicatePollingDelay() throws {
        let start = ProcessInfo.processInfo.systemUptime
        var used = 0.0
        let window = RecoveryOCRReadinessWindow(clock: {
            used + ProcessInfo.processInfo.systemUptime - start
        })
        used = 9.25 // Leave less than the predicate's one-second initial delay.
        var calls = 0
        var nested: XCTWaiter.Result?
        let result = try window.waitForProbe {
            XCTAssertTrue(Thread.isMainThread)
            calls += 1
            nested = XCTWaiter.wait(for: [XCTestExpectation(description: "pending native operation")], timeout: 3)
            return true
        }
        XCTAssertEqual(calls, 1)
        XCTAssertEqual(nested, .interrupted)
        XCTAssertEqual(result, .timedOut)
    }

    @MainActor
    func testNextProbeCannotReenterOperationPumpingMainRunLoop() throws {
        let window = RecoveryOCRReadinessWindow()
        var calls = 0
        var depth = 0
        var maximumDepth = 0
        let result = try window.waitForProbe {
            calls += 1
            depth += 1
            maximumDepth = max(maximumDepth, depth)
            defer { depth -= 1 }
            if calls == 1 {
                let completed = XCTestExpectation(description: "slow first probe")
                let timer = Timer(timeInterval: 1.1, repeats: false) { _ in completed.fulfill() }
                RunLoop.main.add(timer, forMode: .default)
                defer { timer.invalidate() }
                XCTAssertEqual(XCTWaiter.wait(for: [completed], timeout: 3), .completed)
                return false
            }
            return true
        }
        XCTAssertEqual(result, .completed)
        XCTAssertEqual(calls, 2)
        XCTAssertEqual(maximumDepth, 1)
    }

    @MainActor
    func testWaiterExitCancelsPendingProbeTimer() throws {
        var now = 0.0
        let window = RecoveryOCRReadinessWindow(clock: { now })
        now = 9.5
        var calls = 0
        XCTAssertEqual(try window.waitForProbe { calls += 1; return false }, .timedOut)
        // Keep the injected window open: only teardown of the waiter can
        // prevent its one-second timer from making a late call here.
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "pump canceled timer")], timeout: 1.05)
        XCTAssertEqual(calls, 1)
    }

    @MainActor
    func testExpiredWindowDoesNotScheduleFirstProbe() {
        var now = 0.0
        let window = RecoveryOCRReadinessWindow(clock: { now })
        now = 10
        var calls = 0
        XCTAssertThrowsError(try window.waitForProbe { calls += 1; return true }) {
            XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired)
        }
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "pump rejected first probe")], timeout: 0.01)
        XCTAssertEqual(calls, 0)
    }

    @MainActor
    func testDeadlineAfterSchedulingClosesQueuedFirstProbe() {
        var clockReads = 0
        let window = RecoveryOCRReadinessWindow(clock: {
            clockReads += 1
            // Initialization and scheduling are timely; waiter admission is not.
            return clockReads <= 2 ? 0 : 10
        })
        var calls = 0
        XCTAssertThrowsError(try window.waitForProbe { calls += 1; return true }) {
            XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired)
        }
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "pump closed first probe")], timeout: 0.01)
        XCTAssertEqual(calls, 0)
    }

    @MainActor
    func testLateProbeCannotFulfillReadinessOrScheduleAnotherProbe() throws {
        for elapsed in [10.0, 10.001] {
            var now = 0.0
            let window = RecoveryOCRReadinessWindow(clock: { now })
            now = 9.5
            var calls = 0
            let result = try window.waitForProbe {
                calls += 1
                now = elapsed
                return true
            }
            XCTAssertEqual(result, .timedOut)
            XCTAssertEqual(calls, 1)
            XCTAssertThrowsError(try window.remaining())
        }
    }

    @MainActor
    func testCapturedObservationErrorStopsWaitWithoutAnotherQuery() throws {
        enum InvalidSnapshot: Error { case duplicateTarget }
        let window = RecoveryOCRReadinessWindow()
        var calls = 0
        var capturedError: Error?
        let result = try window.waitForProbe {
            do {
                _ = try window.probe(snapshot: {
                    calls += 1
                    throw InvalidSnapshot.duplicateTarget
                }, stateReady: { _ in XCTFail("Invalid snapshot reached state query"); return true },
                   hittable: { XCTFail("Invalid snapshot reached hit test"); return true })
                return false
            } catch {
                capturedError = error
                return true
            }
        }
        XCTAssertEqual(result, .completed)
        XCTAssertTrue(capturedError is InvalidSnapshot)
        XCTAssertEqual(calls, 1)
    }
}
