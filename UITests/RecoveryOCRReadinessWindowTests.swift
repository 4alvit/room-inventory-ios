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
}
