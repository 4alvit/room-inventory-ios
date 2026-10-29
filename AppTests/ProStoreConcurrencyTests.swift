import XCTest
import StoreKit
@testable import RoomInventory

@MainActor
final class ProStoreConcurrencyTests: XCTestCase {
    #if DEBUG
    func testProcessingDiagnosticObservesSuspendedRemovalWithoutRefreshing() async throws {
        let removal = ControlledSnapshot("suspended removal for passive observation")
        let scanner = ControlledScanner([removal])
        let store = ProStore(entitlementSnapshot: { await scanner.read($0) }, observeTransactionUpdates: false)
        defer { scanner.finishAll() }
        let task = Task {
            await self.apply(.verified(UpdateFixture(productID: store.productID,
                revocationDate: Date(timeIntervalSince1970: 1))), to: store)
        }
        defer { task.cancel() }
        guard await wait(for: removal.started) else { return }

        let before = store.processingDiagnostics
        XCTAssertEqual(before.listenerPhase, .disabled)
        XCTAssertEqual(before.lastUpdateKind, .removal)
        XCTAssertEqual(before.removalScansStarted, 1)
        XCTAssertEqual(before.removalUpdates, 1)
        XCTAssertEqual(before.lastStateWriteSource, .none)
        XCTAssertNil(before.lastStateWriteRevision)
        XCTAssertEqual(before.removalScansCompleted, 0)
        XCTAssertEqual(before.refreshesStarted, 0)
        let data = try JSONSerialization.data(withJSONObject: before.fields)
        XCTAssertLessThan(data.count, 1_024)
        XCTAssertFalse(store.isPro)

        // Observation must not add a query or manufacture a completion. The
        // deliberately held scan is released only by this synthetic producer.
        XCTAssertEqual(store.processingDiagnostics.removalScansStarted, 1)
        XCTAssertEqual(store.processingDiagnostics.removalScansCompleted, 0)
        removal.continuation.finish()
        await task.value
        XCTAssertEqual(store.processingDiagnostics.removalScansCompleted, 1)
        XCTAssertEqual(store.processingDiagnostics.lastObservedSnapshotFound, false)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteSource, .removal)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteRevision, 1)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteValue, false)
        XCTAssertFalse(store.isPro)
    }

    func testProcessingDiagnosticDistinguishesRejectedUpdateFromAppliedApproval() async throws {
        let store = ProStore(entitlementSnapshot: { _ in
            XCTFail("Neither rejected events nor verified approval require an entitlement query")
            return false
        }, observeTransactionUpdates: false)
        await apply(.unverified(UpdateFixture(productID: store.productID), .invalidSignature), to: store, accepted: false)
        XCTAssertEqual(store.processingDiagnostics.lastUpdateKind, .unverified)
        await apply(.verified(UpdateFixture(productID: "sensitive.synthetic.product")), to: store, accepted: false)
        XCTAssertEqual(store.processingDiagnostics.lastUpdateKind, .foreignProduct)
        await apply(.verified(UpdateFixture(productID: store.productID, productType: .consumable)), to: store, accepted: false)
        XCTAssertEqual(store.processingDiagnostics.lastUpdateKind, .unsupportedType)
        XCTAssertEqual(store.processingDiagnostics.rejected, 3)
        XCTAssertEqual(store.processingDiagnostics.unverifiedUpdates, 1)
        XCTAssertEqual(store.processingDiagnostics.foreignProductUpdates, 1)
        XCTAssertEqual(store.processingDiagnostics.unsupportedTypeUpdates, 1)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteSource, .none)
        XCTAssertNil(store.processingDiagnostics.lastStateWriteRevision)
        XCTAssertNil(store.processingDiagnostics.lastStateWriteValue)
        XCTAssertFalse(store.isPro)
        await apply(.verified(UpdateFixture(productID: store.productID)), to: store)
        XCTAssertEqual(store.processingDiagnostics.lastUpdateKind, .approval)
        XCTAssertEqual(store.processingDiagnostics.approvalsApplied, 1)
        XCTAssertEqual(store.processingDiagnostics.approvalUpdates, 1)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteSource, .approval)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteRevision, 1)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteValue, true)
        XCTAssertEqual(store.processingDiagnostics.received, 0, "Direct controls must not claim listener delivery")
        XCTAssertTrue(store.isPro)

        let data = try JSONSerialization.data(withJSONObject: store.processingDiagnostics.fields)
        XCTAssertLessThan(data.count, 1_024)
        let text = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertFalse(text.contains(store.productID))
        XCTAssertFalse(text.contains("sensitive.synthetic.product"))
    }
    func testProcessingDiagnosticFitsFullFailurePayloadAtMaximumCounters() throws {
        var state = ProStoreProcessingDiagnostics()
        let counters: [WritableKeyPath<ProStoreProcessingDiagnostics, UInt64>] = [
            \.received, \.rejected, \.unverifiedUpdates, \.foreignProductUpdates,
            \.unsupportedTypeUpdates, \.approvalUpdates, \.removalUpdates, \.approvalsApplied,
            \.removalScansStarted, \.removalScansCompleted, \.removalScansSuperseded,
            \.refreshesStarted, \.refreshesCompleted, \.refreshesSuperseded,
            \.finishesStarted, \.finishesCompleted
        ]
        for keyPath in counters { state[keyPath: keyPath] = .max }
        state.listenerPhase = .finishing
        state.lastUpdateKind = .unsupportedType
        state.lastObservedSnapshotFound = false
        state.recordStateWrite(.approval, revision: .max, value: false)
        let keys = ["pro.storeUnavailable", "pro.unavailable", "pro.unverified", "pro.ready",
            "pro.confirming", "pro.pending", "pro.cancelled", "pro.incomplete", "pro.failed",
            "pro.restored", "pro.notFound", "pro.restoreFailed", "pro.inactive"]
        for language in ["en", "ru"] {
            for key in keys {
                let message = ServiceL10n.text(key, language: language)
                XCTAssertNotEqual(message, key, "Use the actual packaged message")
                let fields: [String: Any] = [
                    "phase": "pending-failed-entitlements-after",
                    "uptime": Double.greatestFiniteMagnitude,
                    "session_transactions": UInt64.max,
                    "verified_product_entitlements": UInt64.max,
                    "verified_xcode_product_entitlements": UInt64.max,
                    "eligible_verified_product_entitlements": UInt64.max,
                    "store_isPro": false, "message": message
                ]
                let data = try JSONSerialization.data(
                    withJSONObject: fields.merging(state.fields) { _, new in new }, options: [.sortedKeys])
                XCTAssertLessThanOrEqual(data.count, 2_048, "\(language)/\(key) must fit the existing diagnostic limit")
            }
        }
    }
    #endif

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
        #if DEBUG
        XCTAssertEqual(store.processingDiagnostics.lastObservedSnapshotFound, false)
        XCTAssertEqual(store.processingDiagnostics.refreshesSuperseded, 1)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteSource, .refresh)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteRevision, 2)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteValue, true)
        #endif
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
        #if DEBUG
        XCTAssertEqual(store.processingDiagnostics.lastObservedSnapshotFound, true)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteSource, .removal)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteRevision, 3)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteValue, false)
        #endif
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
        #if DEBUG
        XCTAssertEqual(store.processingDiagnostics.lastObservedSnapshotFound, false)
        XCTAssertEqual(store.processingDiagnostics.removalScansSuperseded, 1)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteSource, .approval)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteRevision, 2)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteValue, true)
        #endif
    }

    func testLaterVerifiedSnapshotStillReconcilesAfterLiveEvent() async {
        let store = ProStore(entitlementSnapshot: { _ in false }, observeTransactionUpdates: false)
        await apply(.verified(UpdateFixture(productID: store.productID)), to: store)
        XCTAssertTrue(store.isPro)
        await store.refreshEntitlements()
        XCTAssertFalse(store.isPro, "No persistent override of later verified entitlement scans")
        #if DEBUG
        XCTAssertEqual(store.processingDiagnostics.approvalUpdates, 1)
        XCTAssertEqual(store.processingDiagnostics.approvalsApplied, 1)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteSource, .refresh)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteRevision, 2)
        XCTAssertEqual(store.processingDiagnostics.lastStateWriteValue, false)
        #endif
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
