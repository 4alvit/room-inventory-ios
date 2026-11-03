import XCTest

final class ElementDismissalReadinessTests: XCTestCase {
    @MainActor
    func testImmediateZeroCountCompletesBeforePredicatePollingDelay() throws {
        var now = 0.0
        let dismissal = ElementDismissalReadiness(clock: { now })
        now = 9.25
        var calls = 0
        XCTAssertTrue(try dismissal.waitForDismissal {
            XCTAssertTrue(Thread.isMainThread)
            calls += 1
            return 0
        })
        XCTAssertEqual(calls, 1)
        XCTAssertEqual(dismissal.lastCount, 0)
    }

    @MainActor
    func testPresentAndDuplicateControlsAreNotAbsence() throws {
        for presentCount in [1, 2] {
            let dismissal = ElementDismissalReadiness(clock: { 0 })
            var calls = 0
            XCTAssertTrue(try dismissal.waitForDismissal {
                calls += 1
                return calls == 1 ? presentCount : 0
            })
            XCTAssertEqual(calls, 2)
            XCTAssertEqual(dismissal.lastCount, 0)
        }
    }

    @MainActor
    func testExactAndLateZeroCountCannotAuthorizeDismissal() {
        for elapsed in [10.0, 10.001] {
            var now = 0.0
            let dismissal = ElementDismissalReadiness(clock: { now })
            var calls = 0
            XCTAssertThrowsError(try dismissal.waitForDismissal {
                calls += 1
                now = elapsed
                return 0
            }) { XCTAssertEqual($0 as? ElementDismissalReadiness.Failure, .expired) }
            XCTAssertEqual(calls, 1)
            XCTAssertNil(dismissal.lastCount)
        }
    }

    @MainActor
    func testLateZeroDoesNotReplaceLastTimelyPresentCount() {
        var now = 0.0
        let dismissal = ElementDismissalReadiness(clock: { now })
        var calls = 0
        XCTAssertThrowsError(try dismissal.waitForDismissal {
            calls += 1
            if calls == 1 { return 1 }
            now = 10
            return 0
        }) { XCTAssertEqual($0 as? ElementDismissalReadiness.Failure, .expired) }
        XCTAssertEqual(calls, 2)
        XCTAssertEqual(dismissal.lastCount, 1)
    }

    @MainActor
    func testDeadlineAtWaitReturnRejectsPreviouslyTimelyZero() {
        var queryReturned = false
        var checksAfterQuery = 0
        let dismissal = ElementDismissalReadiness(clock: {
            guard queryReturned else { return 0 }
            checksAfterQuery += 1
            // The query postcheck and pending probe postcheck are timely;
            // the final admission check after the completed waiter is not.
            return checksAfterQuery <= 2 ? 9 : 10
        })
        XCTAssertThrowsError(try dismissal.waitForDismissal {
            queryReturned = true
            return 0
        }) { XCTAssertEqual($0 as? ElementDismissalReadiness.Failure, .expired) }
        XCTAssertEqual(dismissal.lastCount, 0)
    }

    @MainActor
    func testExpiredWindowDoesNotEvaluateQuery() {
        var now = 0.0
        let dismissal = ElementDismissalReadiness(clock: { now })
        now = 10
        var calls = 0
        XCTAssertThrowsError(try dismissal.waitForDismissal {
            calls += 1
            return 0
        }) { XCTAssertEqual($0 as? ElementDismissalReadiness.Failure, .expired) }
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        XCTAssertEqual(calls, 0)
        XCTAssertNil(dismissal.lastCount)
    }

    @MainActor
    func testQueryErrorIsPreservedEvenIfDeadlineExpires() {
        enum QueryFailure: Error { case interrupted }
        for expires in [false, true] {
            var now = 0.0
            let dismissal = ElementDismissalReadiness(clock: { now })
            var calls = 0
            XCTAssertThrowsError(try dismissal.waitForDismissal {
                calls += 1
                if expires { now = 11 }
                throw QueryFailure.interrupted
            }) { XCTAssertTrue($0 is QueryFailure) }
            RunLoop.main.run(until: Date().addingTimeInterval(0.02))
            XCTAssertEqual(calls, 1)
            XCTAssertNil(dismissal.lastCount)
        }
    }

    @MainActor
    func testOuterWaitInterruptsQueryAndRejectsItsZeroResult() {
        let start = ProcessInfo.processInfo.systemUptime
        var used = 0.0
        let dismissal = ElementDismissalReadiness(clock: {
            used + ProcessInfo.processInfo.systemUptime - start
        })
        used = 9.25
        var calls = 0
        var nestedResult: XCTWaiter.Result?
        XCTAssertThrowsError(try dismissal.waitForDismissal {
            calls += 1
            nestedResult = XCTWaiter.wait(for: [XCTestExpectation(description: "pending query")], timeout: 3)
            return 0
        }) { XCTAssertEqual($0 as? ElementDismissalReadiness.Failure, .expired) }
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        XCTAssertEqual(nestedResult, .interrupted)
        XCTAssertEqual(calls, 1)
        XCTAssertNil(dismissal.lastCount)
    }
}
