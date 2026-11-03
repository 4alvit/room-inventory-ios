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
    func testNegativeProbeCanBeRetriedWithinRemainingFractionOfASecond() throws {
        var now = 0.0
        let window = RecoveryPhotosAppearanceWindow(clock: { now })
        now = 89.25
        var calls = 0
        XCTAssertTrue(try window.waitForProbe {
            calls += 1
            return calls == 2
        })
        XCTAssertEqual(calls, 2)
        XCTAssertEqual(try window.remaining(), 0.75)
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
}
