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

    @MainActor
    func testExplicitThirtySecondsAcceptsOneTimelyQueryBeyondDefault() throws {
        for elapsed in [12.0, 29.999] {
            var now = 0.0
            var diagnosticNow = 100.0
            let dismissal = ElementDismissalReadiness(timeout: 30, clock: { now },
                                                     diagnosticClock: { diagnosticNow })
            var calls = 0
            XCTAssertTrue(try dismissal.waitForDismissal {
                calls += 1
                now = elapsed
                diagnosticNow += elapsed
                return 0
            })
            XCTAssertEqual(calls, 1)
            XCTAssertEqual(dismissal.allowance, 30)
            XCTAssertEqual(dismissal.lastCount, 0)
            XCTAssertEqual(dismissal.queryDiagnostics.returnedCount, 0)
            XCTAssertEqual(try XCTUnwrap(dismissal.queryDiagnostics.duration), elapsed, accuracy: 0.000001)
            XCTAssertFalse(dismissal.queryDiagnostics.threw)
        }
    }

    @MainActor
    func testExplicitThirtySecondsRejectsExactAndLateRawZero() {
        for elapsed in [30.0, 31.0] {
            var now = 0.0
            let dismissal = ElementDismissalReadiness(timeout: 30, clock: { now })
            XCTAssertThrowsError(try dismissal.waitForDismissal {
                now = elapsed
                return 0
            }) { XCTAssertEqual($0 as? ElementDismissalReadiness.Failure, .expired) }
            XCTAssertEqual(dismissal.queryDiagnostics.attempts, 1)
            XCTAssertEqual(dismissal.queryDiagnostics.returnedCount, 0)
            XCTAssertFalse(dismissal.queryDiagnostics.threw)
            XCTAssertNil(dismissal.lastCount)
        }
    }

    @MainActor
    func testLateRawZeroPreservesEarlierAdmittedPresentCount() {
        var now = 0.0
        let dismissal = ElementDismissalReadiness(timeout: 30, clock: { now })
        var calls = 0
        XCTAssertThrowsError(try dismissal.waitForDismissal {
            calls += 1
            if calls == 1 { now = 12; return 2 }
            now = 30
            return 0
        }) { XCTAssertEqual($0 as? ElementDismissalReadiness.Failure, .expired) }
        XCTAssertEqual(calls, 2)
        XCTAssertEqual(dismissal.queryDiagnostics.attempts, 2)
        XCTAssertEqual(dismissal.queryDiagnostics.returnedCount, 0)
        XCTAssertEqual(dismissal.lastCount, 2)
    }

    @MainActor
    func testExpiredExplicitWindowDoesNotStartQueryOrDiagnosticClock() {
        var now = 0.0
        var diagnosticReads = 0
        let dismissal = ElementDismissalReadiness(timeout: 30, clock: { now }, diagnosticClock: {
            diagnosticReads += 1
            return 0
        })
        now = 30
        var calls = 0
        XCTAssertThrowsError(try dismissal.waitForDismissal { calls += 1; return 0 })
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        XCTAssertEqual(calls, 0)
        XCTAssertEqual(diagnosticReads, 0)
        XCTAssertEqual(dismissal.queryDiagnostics.attempts, 0)
        XCTAssertNil(dismissal.queryDiagnostics.returnedCount)
    }

    @MainActor
    func testRepeatedWaitDoesNotRenewExplicitWindow() throws {
        var now = 0.0
        let dismissal = ElementDismissalReadiness(timeout: 30, clock: { now })
        now = 29
        var calls = 0
        XCTAssertTrue(try dismissal.waitForDismissal { calls += 1; return 0 })
        now = 30
        XCTAssertThrowsError(try dismissal.waitForDismissal { calls += 1; return 0 }) {
            XCTAssertEqual($0 as? ElementDismissalReadiness.Failure, .expired)
        }
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        XCTAssertEqual(calls, 1)
        XCTAssertEqual(dismissal.queryDiagnostics.attempts, 1)
    }

    @MainActor
    func testExplicitWindowFinalCheckRejectsEarlierTimelyZero() {
        var returned = false
        var checksAfterQuery = 0
        let dismissal = ElementDismissalReadiness(timeout: 30, clock: {
            guard returned else { return 0 }
            checksAfterQuery += 1
            return checksAfterQuery <= 2 ? 29 : 30
        })
        XCTAssertThrowsError(try dismissal.waitForDismissal { returned = true; return 0 }) {
            XCTAssertEqual($0 as? ElementDismissalReadiness.Failure, .expired)
        }
        XCTAssertEqual(dismissal.lastCount, 0)
        XCTAssertEqual(dismissal.queryDiagnostics.returnedCount, 0)
        XCTAssertEqual(dismissal.queryDiagnostics.attempts, 1)
    }

    @MainActor
    func testThrowingProbeClearsRawCountAndPreservesNativeErrorAfterExpiry() {
        enum QueryFailure: Error { case interrupted }
        var now = 0.0
        let dismissal = ElementDismissalReadiness(timeout: 30, clock: { now })
        var calls = 0
        XCTAssertThrowsError(try dismissal.waitForDismissal {
            calls += 1
            if calls == 1 { return 1 }
            now = 31
            throw QueryFailure.interrupted
        }) { XCTAssertTrue($0 is QueryFailure) }
        XCTAssertEqual(calls, 2)
        XCTAssertEqual(dismissal.lastCount, 1)
        XCTAssertEqual(dismissal.queryDiagnostics.attempts, 2)
        XCTAssertNil(dismissal.queryDiagnostics.returnedCount)
        XCTAssertTrue(dismissal.queryDiagnostics.threw)
    }

    @MainActor
    func testDiagnosticClockDoesNotChangeAdmissionAndInvalidDurationIsUnavailable() throws {
        for times in [[Double.nan, 1], [0, Double.infinity], [2, 1]] {
            var admissionReads = 0
            var diagnosticReads = 0
            let dismissal = ElementDismissalReadiness(timeout: 30, clock: {
                admissionReads += 1
                return 0
            }, diagnosticClock: {
                defer { diagnosticReads += 1 }
                return times[diagnosticReads]
            })
            var calls = 0
            XCTAssertTrue(try dismissal.waitForDismissal { calls += 1; return 0 })
            XCTAssertEqual(calls, 1)
            XCTAssertEqual(admissionReads, 8)
            XCTAssertEqual(diagnosticReads, 2)
            XCTAssertNil(dismissal.queryDiagnostics.duration)
            XCTAssertEqual(dismissal.lastCount, 0)
        }
    }

    @MainActor
    func testInvalidExplicitAllowanceDoesNotQuery() {
        for allowance in [0, -1, 30.001, Double.infinity, Double.nan] {
            let dismissal = ElementDismissalReadiness(timeout: allowance, clock: { 0 })
            var calls = 0
            XCTAssertThrowsError(try dismissal.waitForDismissal { calls += 1; return 0 })
            XCTAssertEqual(calls, 0)
            XCTAssertEqual(dismissal.queryDiagnostics.attempts, 0)
            XCTAssertNil(dismissal.lastCount)
        }
    }
}
