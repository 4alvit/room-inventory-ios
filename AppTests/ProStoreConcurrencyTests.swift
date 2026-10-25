import XCTest
@testable import RoomInventory

@MainActor
final class ProStoreConcurrencyTests: XCTestCase {
    func testOlderEntitledScanCannotUndoNewerRevocationOrItsMessage() async {
        let initial = ControlledSnapshot("initial entitlement")
        let older = ControlledSnapshot("older entitled scan")
        let newer = ControlledSnapshot("newer revoked scan")
        let scanner = ControlledScanner([initial, older, newer])
        let store = ProStore(entitlementSnapshot: { await scanner.read($0) }, observeTransactionUpdates: false)
        defer { scanner.finishAll() }

        initial.continuation.yield(true)
        initial.continuation.finish()
        await store.refreshEntitlements()
        XCTAssertTrue(store.isPro)

        let olderTask = Task { await store.refreshEntitlements() }
        defer { olderTask.cancel() }
        guard await wait(for: older.started) else { return }
        older.continuation.yield(true)
        // The older scan has seen a valid entitlement but has not ended yet.
        guard await wait(for: older.consumedValue) else { return }

        let newerTask = Task { await store.refreshEntitlements() }
        defer { newerTask.cancel() }
        guard await wait(for: newer.started) else { return }
        newer.continuation.finish()
        await newerTask.value
        XCTAssertFalse(store.isPro)
        let revokedMessage = "Pro access is no longer active. Your saved inventory and exports remain available."
        XCTAssertEqual(store.message, revokedMessage)

        older.continuation.finish()
        await olderTask.value
        XCTAssertFalse(store.isPro, "An older completed scan must not restore revoked access")
        XCTAssertEqual(store.message, revokedMessage, "An older scan must not replace the live revocation status")
    }

    func testOlderEmptyScanCannotUndoNewerEntitlementOrItsMessage() async {
        let older = ControlledSnapshot("older empty scan")
        let newer = ControlledSnapshot("newer entitled scan")
        let scanner = ControlledScanner([older, newer])
        let store = ProStore(entitlementSnapshot: { await scanner.read($0) }, observeTransactionUpdates: false)
        defer { scanner.finishAll() }

        let olderTask = Task { await store.refreshEntitlements() }
        defer { olderTask.cancel() }
        guard await wait(for: older.started) else { return }

        let newerTask = Task { await store.refreshEntitlements() }
        defer { newerTask.cancel() }
        guard await wait(for: newer.started) else { return }
        newer.continuation.yield(true)
        newer.continuation.finish()
        await newerTask.value
        XCTAssertTrue(store.isPro)
        let readyMessage = "Pro is ready. Thank you for supporting Room Inventory."
        XCTAssertEqual(store.message, readyMessage)

        older.continuation.finish()
        await olderTask.value
        XCTAssertTrue(store.isPro, "An older empty scan must not revoke newer access")
        XCTAssertEqual(store.message, readyMessage)
    }

    private func wait(for expectation: XCTestExpectation) async -> Bool {
        let result = await XCTWaiter.fulfillment(of: [expectation], timeout: 3)
        XCTAssertEqual(result, .completed)
        return result == .completed
    }
}

@MainActor
private final class ControlledSnapshot {
    let stream: AsyncStream<Bool>
    let continuation: AsyncStream<Bool>.Continuation
    let started: XCTestExpectation
    let consumedValue: XCTestExpectation

    init(_ description: String) {
        let pair = AsyncStream<Bool>.makeStream()
        stream = pair.stream
        continuation = pair.continuation
        started = XCTestExpectation(description: "Started \(description)")
        consumedValue = XCTestExpectation(description: "Consumed a value in \(description)")
    }
}

@MainActor
private final class ControlledScanner {
    let snapshots: [ControlledSnapshot]
    private var index = 0

    init(_ snapshots: [ControlledSnapshot]) { self.snapshots = snapshots }

    func read(_ productID: String) async -> Bool {
        XCTAssertFalse(productID.isEmpty)
        guard index < snapshots.count else {
            XCTFail("Unexpected entitlement scan")
            return false
        }
        let snapshot = snapshots[index]
        index += 1
        snapshot.started.fulfill()
        var found = false
        for await value in snapshot.stream {
            found = found || value
            snapshot.consumedValue.fulfill()
        }
        return found
    }

    func finishAll() {
        for snapshot in snapshots { snapshot.continuation.finish() }
    }
}
