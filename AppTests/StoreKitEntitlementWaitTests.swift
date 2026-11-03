import XCTest

@MainActor
final class StoreKitEntitlementWaitTests: XCTestCase {
    func testAcceptsApprovalAfterFormerFiveSecondWindow() async throws {
        let start = ContinuousClock().now
        var instant = start
        let arrival = start.advanced(by: .milliseconds(5300))
        let result = try await waitForStoreKitEntitlement(expected: true,
            deadline: start.advanced(by: .seconds(10)), now: { instant },
            pauseUntil: { instant = $0 }, read: { instant >= arrival })
        XCTAssertTrue(result.matched)
        XCTAssertEqual(result.lastObserved, true)
        XCTAssertEqual(instant, arrival)
        XCTAssertEqual(result.observations, 54)
    }

    func testObservesRefundWithoutChangingTheProducer() async throws {
        var instant = ContinuousClock().now
        var values = [true, false].makeIterator()
        var reads = 0
        let result = try await waitForStoreKitEntitlement(expected: false,
            deadline: instant.advanced(by: .seconds(10)), now: { instant },
            pauseUntil: { instant = $0 }, read: {
                reads += 1
                return values.next()!
            })
        XCTAssertTrue(result.matched)
        XCTAssertEqual(result.lastObserved, false)
        XCTAssertEqual(reads, 2)
    }

    func testUnchangedStateStopsAtOriginalDeadline() async throws {
        var instant = ContinuousClock().now
        let deadline = instant.advanced(by: .milliseconds(250))
        var reads = 0
        let result = try await waitForStoreKitEntitlement(expected: true,
            deadline: deadline, now: { instant }, pauseUntil: { instant = $0 },
            read: { reads += 1; return false })
        XCTAssertFalse(result.matched)
        XCTAssertEqual(result.lastObserved, false)
        XCTAssertEqual(result.observations, 3)
        XCTAssertEqual(reads, 3)
        XCTAssertEqual(instant, deadline)
    }

    func testExactAndLateMatchingObservationsCannotSucceed() async throws {
        for lateness in [Duration.zero, .milliseconds(1)] {
            var instant = ContinuousClock().now
            let deadline = instant.advanced(by: .seconds(10))
            var pauses = 0
            let result = try await waitForStoreKitEntitlement(expected: true,
                deadline: deadline, now: { instant }, pauseUntil: { _ in pauses += 1 },
                read: { instant = deadline.advanced(by: lateness); return true })
            XCTAssertFalse(result.matched)
            XCTAssertEqual(result.lastObserved, true)
            XCTAssertEqual(result.observations, 1)
            XCTAssertEqual(pauses, 0)
        }
    }

    func testExpiredDeadlineDoesNotReadOrPause() async throws {
        let instant = ContinuousClock().now
        var reads = 0
        var pauses = 0
        let result = try await waitForStoreKitEntitlement(expected: true,
            deadline: instant, now: { instant }, pauseUntil: { _ in pauses += 1 },
            read: { reads += 1; return true })
        XCTAssertFalse(result.matched)
        XCTAssertNil(result.lastObserved)
        XCTAssertEqual(result.observations, 0)
        XCTAssertEqual(reads, 0)
        XCTAssertEqual(pauses, 0)
    }

    func testCancellationPropagatesWithoutAnotherObservation() async {
        let instant = ContinuousClock().now
        var reads = 0
        do {
            _ = try await waitForStoreKitEntitlement(expected: true,
                deadline: instant.advanced(by: .seconds(10)), now: { instant },
                pauseUntil: { _ in throw CancellationError() },
                read: { reads += 1; return false })
            XCTFail("Cancellation must not become success or an ordinary timeout")
        } catch {
            XCTAssertTrue(error is CancellationError)
        }
        XCTAssertEqual(reads, 1)
    }

    func testPausePastDeadlineDoesNotReadAgain() async throws {
        var instant = ContinuousClock().now
        let deadline = instant.advanced(by: .seconds(10))
        var reads = 0
        let result = try await waitForStoreKitEntitlement(expected: true,
            deadline: deadline, now: { instant },
            pauseUntil: { _ in instant = deadline.advanced(by: .milliseconds(1)) },
            read: { reads += 1; return reads > 1 })
        XCTAssertFalse(result.matched)
        XCTAssertEqual(result.lastObserved, false)
        XCTAssertEqual(reads, 1)
    }

    func testCancellationAtEntryOrExpiredPauseRemainsCancellation() async {
        for cancelAtPause in [false, true] {
            var instant = ContinuousClock().now
            let deadline = instant.advanced(by: cancelAtPause ? .seconds(10) : .zero)
            var reads = 0
            let operation = Task { @MainActor in
                try await waitForStoreKitEntitlement(expected: true,
                    deadline: deadline, now: { instant },
                    pauseUntil: { _ in
                        instant = deadline
                        withUnsafeCurrentTask { $0?.cancel() }
                    }, read: { reads += 1; return false })
            }
            // This actor has not yielded, so entry cancellation precedes the read.
            if !cancelAtPause { operation.cancel() }
            do {
                _ = try await operation.value
                XCTFail("Expiry must not hide cancellation")
            } catch {
                XCTAssertTrue(error is CancellationError)
            }
            XCTAssertEqual(reads, cancelAtPause ? 1 : 0)
        }
    }
}
