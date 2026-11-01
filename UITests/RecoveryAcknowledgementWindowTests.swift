import XCTest

final class RecoveryAcknowledgementWindowTests: XCTestCase {
    func testHostedCaptureCompletesWithinOneAllowance() throws {
        var now = 100.0
        let window = RecoveryAcknowledgementWindow(clock: { now })
        try window.perform { now += 2 } // Publication and its attachment consume time.
        try window.wait { remaining in
            XCTAssertEqual(remaining, 58)
            now = 149.449
            return .completed
        }
        try window.perform { now += 1 } // ACK read and validation.
        XCTAssertEqual(try window.remaining(), 9.551, accuracy: 0.0001)
    }

    func testExactOrLateCompletionCannotAdvanceBarrier() {
        for elapsed in [60.0, 60.001] {
            var now = 0.0
            let window = RecoveryAcknowledgementWindow(clock: { now })
            var committed = false
            XCTAssertThrowsError(try {
                try window.wait { _ in now = elapsed; return .completed }
                committed = true
            }()) { XCTAssertEqual($0 as? RecoveryAcknowledgementWindow.Failure, .expired) }
            XCTAssertFalse(committed)
        }
    }

    func testExpiredPublicationDoesNotStartWait() {
        var now = 0.0
        let window = RecoveryAcknowledgementWindow(clock: { now })
        var waited = false
        XCTAssertThrowsError(try {
            try window.perform { now = 60 }
            try window.wait { _ in waited = true; return .completed }
        }())
        XCTAssertFalse(waited)
    }

    func testLateObservationIsRejectedWithoutRenewingDeadline() throws {
        var now = 0.0
        let window = RecoveryAcknowledgementWindow(clock: { now })
        now = 10
        XCTAssertFalse(window.observe { false })
        now = 50
        XCTAssertEqual(try window.remaining(), 10)
        XCTAssertFalse(window.observe { now = 60; return true })
        var inspectedAgain = false
        XCTAssertFalse(window.observe { inspectedAgain = true; return true })
        XCTAssertFalse(inspectedAgain)
    }

    func testLateReadsOrEvidenceCannotCommitBarrier() {
        for delayedStage in 0..<3 { // ACK read, evidence attachment, request reread.
            var now = 0.0
            let window = RecoveryAcknowledgementWindow(clock: { now })
            var stages = 0
            var committed = false
            XCTAssertThrowsError(try {
                try window.wait { _ in now = 49.449; return .completed }
                for stage in 0..<3 {
                    try window.perform {
                        stages += 1
                        if stage == delayedStage { now = 60 }
                    }
                }
                _ = try window.remaining()
                committed = true
            }()) { XCTAssertEqual($0 as? RecoveryAcknowledgementWindow.Failure, .expired) }
            XCTAssertEqual(stages, delayedStage + 1)
            XCTAssertFalse(committed)
        }
    }

    func testUnsuccessfulWaitRetainsExactResultAndDoesNotReadACK() {
        for result: XCTWaiter.Result in [.timedOut, .interrupted, .incorrectOrder, .invertedFulfillment] {
            let window = RecoveryAcknowledgementWindow(clock: { 0 })
            var readACK = false
            XCTAssertThrowsError(try {
                try window.wait { _ in result }
                try window.perform { readACK = true }
            }()) { XCTAssertEqual($0 as? RecoveryAcknowledgementWindow.Failure, .waiterResult(result.rawValue)) }
            XCTAssertFalse(readACK)
        }
    }

    func testValidationFailureIsPreservedAndCannotCommitBarrier() {
        enum InvalidACK: Error { case wrongNonce }
        let window = RecoveryAcknowledgementWindow(clock: { 0 })
        var committed = false
        XCTAssertThrowsError(try {
            try window.wait { _ in .completed }
            try window.perform { throw InvalidACK.wrongNonce }
            committed = true
        }()) { XCTAssertTrue($0 is InvalidACK) }
        XCTAssertFalse(committed)
    }
}
