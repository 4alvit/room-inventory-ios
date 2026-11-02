import XCTest

final class CSVSharePhaseTimingTests: XCTestCase {
    func testOneDeadlineIsNotRenewedAfterReadinessOrClose() {
        let phase = CSVSharePhaseTiming(start: 100)
        XCTAssertEqual(phase.deadline, 115)
        XCTAssertEqual(phase.remaining(at: 111), 4)
        XCTAssertEqual(phase.remaining(at: 113), 2)
        XCTAssertEqual(phase.remaining(at: 116), -1)
        XCTAssertEqual(phase.deadline, 115)
    }

    func testNoActionAtOrAfterDeadline() {
        let phase = CSVSharePhaseTiming(start: 100)
        XCTAssertTrue(phase.permitsAction(at: 114.999))
        XCTAssertFalse(phase.permitsAction(at: 115))
        XCTAssertFalse(phase.permitsAction(at: 115.001))
    }

    func testCloseConsumesTheOriginalBudget() {
        let phase = CSVSharePhaseTiming(start: 100)
        XCTAssertTrue(phase.permitsAction(at: 114))
        XCTAssertFalse(phase.acceptsReturn(waitStartedAt: 115.1,
            waiterCompleted: true, finishedAt: 115.2))
    }

    func testWaiterCannotTurnLateObservationIntoSuccess() {
        let phase = CSVSharePhaseTiming(start: 100)
        XCTAssertFalse(phase.acceptsReturn(waitStartedAt: 114,
            waiterCompleted: true, finishedAt: 115.001))
    }

    func testWaiterMustCompleteEvenWhenTimeRemains() {
        let phase = CSVSharePhaseTiming(start: 100)
        XCTAssertFalse(phase.acceptsReturn(waitStartedAt: 112,
            waiterCompleted: false, finishedAt: 113))
    }

    func testCompletedReturnAtDeadlineMatchesInclusiveFinalBoundary() {
        let phase = CSVSharePhaseTiming(start: 100)
        XCTAssertTrue(phase.acceptsReturn(waitStartedAt: 114,
            waiterCompleted: true, finishedAt: 115))
    }

    func testLateWaitCannotPassWithEarlierResultTimestamp() {
        let phase = CSVSharePhaseTiming(start: 100)
        XCTAssertFalse(phase.acceptsReturn(waitStartedAt: 115,
            waiterCompleted: true, finishedAt: 114.9))
        XCTAssertFalse(phase.acceptsReturn(waitStartedAt: 113,
            waiterCompleted: true, finishedAt: 112))
    }

    func testOriginCannotMoveBackwards() {
        let phase = CSVSharePhaseTiming(start: 100)
        XCTAssertFalse(phase.permitsAction(at: 99))
        XCTAssertFalse(phase.acceptsReturn(waitStartedAt: 99,
            waiterCompleted: true, finishedAt: 101))
    }

    func testRecordedUpperDeadlineFixtureDoesNotAcceptLateReturn() {
        // 130.34 is the first recorded query, hence an upper-bound origin,
        // not a claim about the unlogged exact deadline in the failed run.
        let phase = CSVSharePhaseTiming(start: 130.34)
        XCTAssertEqual(phase.remaining(at: 142.83), 2.51, accuracy: 0.000001)
        XCTAssertFalse(phase.acceptsReturn(waitStartedAt: 145.35,
            waiterCompleted: true, finishedAt: 145.36))
    }

    func testFiniteObservationIsRequired() {
        let phase = CSVSharePhaseTiming(start: 100)
        XCTAssertFalse(phase.permitsAction(at: .nan))
        XCTAssertFalse(phase.permitsAction(at: .infinity))
        XCTAssertFalse(phase.acceptsReturn(waitStartedAt: 112,
            waiterCompleted: true, finishedAt: .nan))
    }
}
