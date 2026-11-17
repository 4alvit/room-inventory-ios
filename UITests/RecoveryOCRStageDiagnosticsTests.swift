import XCTest

final class RecoveryOCRStageDiagnosticsTests: XCTestCase {
    final class HostileNativeError: Error, CustomStringConvertible {
        var description: String { "SECRET arbitrary UI values / coordinates / token" }
    }

    func testClosedVocabularyAndNativeErrorPrivacy() {
        let error = HostileNativeError()
        XCTAssertEqual(RecoveryOCRReadinessWindow.Stage.allCases.map(\.rawValue),
            ["snapshot", "scan", "state", "liveMatches", "hittability", "coordinate", "origin", "currentFrame", "gestureAdmission"])
        for stage in RecoveryOCRReadinessWindow.Stage.allCases {
            let line = RecoveryOCRReadinessWindow.failureLine(stage: stage, error: error)
            XCTAssertEqual(line, "ROOM_OCR_STAGE_FAILURE stage=\(stage.rawValue) kind=native")
            XCTAssertFalse(line.contains("SECRET"))
        }
        XCTAssertEqual(RecoveryOCRReadinessWindow.failureLine(stage: .scan, error: RecoveryOCRReadinessWindow.Failure.expired),
            "ROOM_OCR_STAGE_FAILURE stage=scan kind=expired")
        XCTAssertEqual(RecoveryOCRReadinessWindow.failureLine(stage: .scan, error: RecoveryOCRReadinessWindow.Failure.invalidAllowance),
            "ROOM_OCR_STAGE_FAILURE stage=scan kind=invalid_allowance")
    }

    func testLateSuccessKeepsReadCountsAndRejectsNextOperation() {
        var now = 0.0, reads = 0, operations = 0
        let window = RecoveryOCRReadinessWindow(clock: { reads += 1; return now })
        XCTAssertThrowsError(try window.perform(stage: .coordinate) { operations += 1; now = 10; return true }) {
            XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired)
        }
        XCTAssertEqual(reads, 3) // init plus unchanged pre/post checks
        XCTAssertThrowsError(try window.perform(stage: .currentFrame) { operations += 1 })
        XCTAssertEqual(operations, 1)
        XCTAssertEqual(reads, 4)
    }

    func testNativeErrorIdentityAndNoPostErrorClockReadOrNextQuery() {
        let native = HostileNativeError()
        var reads = 0, nextQueries = 0
        let window = RecoveryOCRReadinessWindow(clock: { reads += 1; return 0 })
        XCTAssertThrowsError(try window.probe(snapshotStage: .snapshot, stateStage: .state,
            hittabilityStage: .hittability, snapshot: { throw native },
            stateReady: { (_: Int) in nextQueries += 1; return true },
            hittable: { nextQueries += 1; return true })) {
                XCTAssertTrue(($0 as? HostileNativeError) === native)
        }
        XCTAssertEqual(reads, 2) // initialization and original admission check only
        XCTAssertEqual(nextQueries, 0)
    }

    func testLabelledAndUnlabelledSuccessKeepExactClockReadAndOperationOrder() throws {
        func trace(labelled: Bool) throws -> [String] {
            var events: [String] = []
            let window = RecoveryOCRReadinessWindow(clock: { events.append("clock"); return 0 })
            _ = try window.probe(snapshotStage: labelled ? .snapshot : nil,
                stateStage: labelled ? .state : nil, hittabilityStage: labelled ? .hittability : nil,
                snapshot: { events.append("snapshot"); return 1 },
                stateReady: { _ in events.append("state"); return true },
                hittable: { events.append("hittability"); return true })
            _ = try window.remaining(stage: labelled ? .gestureAdmission : nil)
            return events
        }
        XCTAssertEqual(try trace(labelled: true), try trace(labelled: false))
    }

    func testLabelledRemainingFailsWithoutAnotherClockReadOrOperation() {
        var now = 0.0, reads = 0
        let window = RecoveryOCRReadinessWindow(clock: { reads += 1; return now })
        now = 10
        XCTAssertThrowsError(try window.remaining(stage: .gestureAdmission)) {
            XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired)
        }
        XCTAssertEqual(reads, 2)
    }
}
