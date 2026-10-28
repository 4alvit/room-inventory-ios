import XCTest
import StoreKit
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

    func testVerifiedApprovalOverridesLaggingEmptyScanWithoutAnotherLookup() async {
        let older = ControlledSnapshot("empty scan before verified approval")
        let scanner = ControlledScanner([older])
        let store = ProStore(entitlementSnapshot: { await scanner.read($0) }, observeTransactionUpdates: false)
        defer { scanner.finishAll() }
        store.message = "This purchase is awaiting approval."
        let task = Task { await store.refreshEntitlements() }
        defer { task.cancel() }
        guard await wait(for: older.started) else { return }

        await apply(.verified(UpdateFixture(productID: store.productID)), to: store)
        XCTAssertTrue(store.isPro, "Verified approval must not wait for a lagging snapshot index")
        let ready = "Pro is ready. Thank you for supporting Room Inventory."
        XCTAssertEqual(store.message, ready)
        older.continuation.finish() // earlier scan completes false after the event
        await task.value
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(store.message, ready)
    }

    func testVerifiedRevocationReconcilesAndInvalidatesOlderEntitledScan() async {
        let older = ControlledSnapshot("entitled scan before verified revocation")
        let revoked = ControlledSnapshot("current snapshot after revocation")
        let scanner = ControlledScanner([older, revoked])
        let store = ProStore(entitlementSnapshot: { await scanner.read($0) }, observeTransactionUpdates: false)
        defer { scanner.finishAll() }
        await apply(.verified(UpdateFixture(productID: store.productID)), to: store)
        let task = Task { await store.refreshEntitlements() }
        defer { task.cancel() }
        guard await wait(for: older.started) else { return }
        older.continuation.yield(true)
        guard await wait(for: older.consumedValue) else { return }

        revoked.continuation.finish()
        await apply(.verified(UpdateFixture(productID: store.productID,
            revocationDate: Date(timeIntervalSince1970: 1))), to: store)
        XCTAssertFalse(store.isPro)
        let inactive = "Pro access is no longer active. Your saved inventory and exports remain available."
        XCTAssertEqual(store.message, inactive)
        older.continuation.finish()
        await task.value
        XCTAssertFalse(store.isPro, "An older scan cannot undo a newer verified revocation")
        XCTAssertEqual(store.message, inactive)
    }

    func testRejectedUpdatesNeitherUnlockNorInvalidateMatchingScan() async {
        let pending = ControlledSnapshot("matching scan alongside rejected updates")
        let scanner = ControlledScanner([pending])
        let store = ProStore(entitlementSnapshot: { await scanner.read($0) }, observeTransactionUpdates: false)
        defer { scanner.finishAll() }
        store.message = "Unchanged status"
        let task = Task { await store.refreshEntitlements() }
        defer { task.cancel() }
        guard await wait(for: pending.started) else { return }
        await apply(.unverified(UpdateFixture(productID: store.productID), .invalidSignature), to: store, accepted: false)
        await apply(.verified(UpdateFixture(productID: "com.example.foreign")), to: store, accepted: false)
        for type in [Product.ProductType.consumable, .autoRenewable, .nonRenewable] {
            await apply(.verified(UpdateFixture(productID: store.productID, productType: type)), to: store, accepted: false)
        }
        XCTAssertFalse(store.isPro)
        XCTAssertEqual(store.message, "Unchanged status")
        pending.continuation.yield(true)
        pending.continuation.finish()
        await task.value
        XCTAssertTrue(store.isPro, "Rejected updates must not invalidate this matching verified snapshot")
    }

    func testRevokedOlderOrUpgradedTransactionCannotRemoveCurrentRepurchase() async {
        let store = ProStore(entitlementSnapshot: { _ in true }, observeTransactionUpdates: false)
        await store.refreshEntitlements()
        store.message = "Pro purchase restored."
        await apply(.verified(UpdateFixture(productID: store.productID,
            revocationDate: Date(timeIntervalSince1970: 1))), to: store)
        XCTAssertTrue(store.isPro, "A different current verified purchase remains authoritative")
        XCTAssertEqual(store.message, "Pro purchase restored.")
        await apply(.verified(UpdateFixture(productID: store.productID, isUpgraded: true)), to: store)
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(store.message, "Pro purchase restored.")
        let empty = ProStore(entitlementSnapshot: { _ in false }, observeTransactionUpdates: false)
        await apply(.verified(UpdateFixture(productID: empty.productID, isUpgraded: true)), to: empty)
        XCTAssertFalse(empty.isPro, "An upgraded event alone cannot grant rights")
    }

    func testSlowRevocationSnapshotCannotUndoLaterVerifiedApproval() async {
        let revoked = ControlledSnapshot("lagging revocation snapshot")
        let scanner = ControlledScanner([revoked])
        let store = ProStore(entitlementSnapshot: { await scanner.read($0) }, observeTransactionUpdates: false)
        defer { scanner.finishAll() }
        let old = Task {
            await self.apply(.verified(UpdateFixture(productID: store.productID,
                revocationDate: Date(timeIntervalSince1970: 1))), to: store)
        }
        defer { old.cancel() }
        guard await wait(for: revoked.started) else { return }
        await apply(.verified(UpdateFixture(productID: store.productID)), to: store)
        revoked.continuation.finish()
        await old.value
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(store.message, "Pro is ready. Thank you for supporting Room Inventory.")
    }

    func testLaterVerifiedSnapshotStillReconcilesAfterLiveEvent() async {
        let store = ProStore(entitlementSnapshot: { _ in false }, observeTransactionUpdates: false)
        await apply(.verified(UpdateFixture(productID: store.productID)), to: store)
        XCTAssertTrue(store.isPro)
        await store.refreshEntitlements()
        XCTAssertFalse(store.isPro, "No persistent override of later verified entitlement scans")
    }

    private func apply(_ result: VerificationResult<UpdateFixture>, to store: ProStore, accepted: Bool = true) async {
        let observed = await store.applyTransactionUpdate(result)
        XCTAssertEqual(observed, accepted)
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

// Synthetic typed verification results exercise state/revision policy only.
// They do not claim signature verification or native StoreKit acceptance.
private struct UpdateFixture: ProEntitlementTransaction {
    let productID: String
    var productType: Product.ProductType = .nonConsumable
    var revocationDate: Date? = nil
    var isUpgraded = false
}
