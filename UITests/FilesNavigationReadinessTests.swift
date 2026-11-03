import XCTest

final class FilesNavigationReadinessTests: XCTestCase {
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
}
