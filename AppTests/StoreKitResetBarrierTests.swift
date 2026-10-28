import XCTest

@MainActor
final class StoreKitResetBarrierTests: XCTestCase {
    func testRequiresBothSessionLedgerAndEntitlementSequenceToBeEmpty() async throws {
        var instant = ContinuousClock().now
        let deadline = instant.advanced(by: .seconds(5))
        let states = [
            StoreKitResetState(sessionTransactions: 0, verifiedEntitlements: 1),
            StoreKitResetState(sessionTransactions: 1, verifiedEntitlements: 0),
            StoreKitResetState(sessionTransactions: 0, verifiedEntitlements: 0)
        ]
        var reads = 0
        let result = try await waitForStoreKitReset(
            deadline: deadline, now: { instant },
            pauseUntil: { instant = $0 },
            read: { defer { reads += 1 }; return states[reads] })
        XCTAssertTrue(result.clean)
        XCTAssertEqual(reads, 3)
        XCTAssertEqual(result.first, states.first)
        XCTAssertEqual(result.last, states.last)
    }

    func testDirtySessionFailsAtOriginalDeadlineAndRetainsCounts() async throws {
        var instant = ContinuousClock().now
        let deadline = instant.advanced(by: .milliseconds(200))
        let dirty = StoreKitResetState(sessionTransactions: 2, verifiedEntitlements: 1)
        let result = try await waitForStoreKitReset(
            deadline: deadline, now: { instant },
            pauseUntil: { instant = $0 }, read: { dirty })
        XCTAssertFalse(result.clean)
        XCTAssertEqual(instant, deadline)
        XCTAssertEqual(result.observations, 2)
        XCTAssertEqual(result.first, dirty)
        XCTAssertEqual(result.last, dirty)
    }

    func testLateCleanObservationCannotExtendDeadline() async throws {
        var instant = ContinuousClock().now
        let deadline = instant.advanced(by: .milliseconds(100))
        var pauses = 0
        let result = try await waitForStoreKitReset(
            deadline: deadline, now: { instant },
            pauseUntil: { _ in pauses += 1 },
            read: {
                instant = deadline
                return StoreKitResetState(sessionTransactions: 0, verifiedEntitlements: 0)
            })
        XCTAssertFalse(result.clean)
        XCTAssertEqual(result.observations, 1)
        XCTAssertEqual(pauses, 0)
    }

    func testExpiredDeadlineDoesNotReadOrPause() async throws {
        let instant = ContinuousClock().now
        var reads = 0
        var pauses = 0
        let result = try await waitForStoreKitReset(
            deadline: instant, now: { instant },
            pauseUntil: { _ in pauses += 1 },
            read: {
                reads += 1
                return StoreKitResetState(sessionTransactions: 0, verifiedEntitlements: 0)
            })
        XCTAssertFalse(result.clean)
        XCTAssertEqual(reads, 0)
        XCTAssertEqual(pauses, 0)
        XCTAssertNil(result.first)
        XCTAssertNil(result.last)
    }
}
