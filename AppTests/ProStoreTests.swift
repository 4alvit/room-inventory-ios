import XCTest
import StoreKit
import StoreKitTest
@testable import RoomInventory

@MainActor
final class ProStoreTests: XCTestCase {
    private func verifiedEntitlements() async -> [StoreKit.Transaction] {
        var transactions: [StoreKit.Transaction] = []
        for await result in StoreKit.Transaction.currentEntitlements {
            if case .verified(let transaction) = result { transactions.append(transaction) }
        }
        return transactions
    }

    private func makeSession() async throws -> SKTestSession {
        let config = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "RoomInventory", withExtension: "storekit"))
        let session = try SKTestSession(contentsOf: config)
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(5))
        var ready = false
        defer { if !ready { session.clearTransactions() } }
        let beforeSession = session.allTransactions()
        let beforeEntitlements = await verifiedEntitlements()
        session.resetToDefaultState()
        session.clearTransactions()
        session.disableDialogs = true
        // StoreKit's session ledger and the app-facing entitlement sequence must both
        // observe the reset before a new store or purchase can belong to this test.
        let result = try await waitForStoreKitReset(
            deadline: deadline,
            now: { clock.now },
            pauseUntil: { try await clock.sleep(until: $0) },
            read: {
                let entitlements = await self.verifiedEntitlements()
                return StoreKitResetState(
                    sessionTransactions: session.allTransactions().count,
                    verifiedEntitlements: entitlements.count)
            })
        guard result.clean else {
            XCTFail("StoreKit reset did not settle: before session=\(beforeSession.count), "
                + "entitlements=\(beforeEntitlements.count); \(result.diagnostic)")
            throw StoreKitResetFailure.notClean
        }
        ready = true
        return session
    }

    private enum StoreKitResetFailure: Error { case notClean }

    private func requireCurrentLocalPurchase(_ session: SKTestSession, store: ProStore) async throws {
        _ = try XCTUnwrap(session.allTransactions().first {
            $0.productIdentifier == store.productID
        }, "Purchase must appear in this test's clean StoreKit session")
        let entitlements = await verifiedEntitlements()
        _ = try XCTUnwrap(entitlements.first {
            $0.productID == store.productID && $0.productType == .nonConsumable
                && $0.environment == .xcode && $0.revocationDate == nil
        }, "Purchase must provide a verified Xcode entitlement for this product")
    }

    // Observe live updates without refreshing the state under test.
    private func waitForObservedEntitlement(_ expected: Bool, store: ProStore) async {
        for _ in 0..<50 {
            if store.isPro == expected { return }
            try? await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertEqual(store.isPro, expected)
    }

    func testNoPurchaseDoesNotUnlockAndPriceIsFromStoreKit() async throws {
        let session = try await makeSession()
        defer { session.clearTransactions() }
        let store = ProStore()
        await store.load()
        XCTAssertFalse(store.isPro)
        XCTAssertNotNil(store.displayPrice)
    }

    func testPurchaseUnlocksNewStoreAndRefundRemovesEntitlement() async throws {
        let session = try await makeSession()
        defer { session.clearTransactions() }
        let store = ProStore()
        await store.load()
        XCTAssertFalse(store.isPro, "A clean session must not inherit another test's entitlement")
        await store.purchase()
        await waitForObservedEntitlement(true, store: store)
        XCTAssertEqual(store.message, "Pro is ready. Thank you for supporting Room Inventory.")
        try await requireCurrentLocalPurchase(session, store: store)
        let reopened = ProStore()
        XCTAssertNil(reopened.message)
        await reopened.load()
        // Both stores must begin entitled; otherwise false could mask a missing refund update.
        XCTAssertTrue(store.isPro)
        XCTAssertTrue(reopened.isPro)
        // Loading a finished purchase must update its status without a new transaction event.
        XCTAssertEqual(reopened.message, "Pro is ready. Thank you for supporting Room Inventory.")
        let transaction = try XCTUnwrap(session.allTransactions().first)
        try session.refundTransaction(identifier: transaction.identifier)
        await waitForObservedEntitlement(false, store: store)
        await waitForObservedEntitlement(false, store: reopened)
        XCTAssertEqual(store.message, "Pro access is no longer active. Your saved inventory and exports remain available.")
        XCTAssertEqual(reopened.message, "Pro access is no longer active. Your saved inventory and exports remain available.")
        XCTAssertFalse(store.isBusy)
    }

    func testRestoreUsesVerifiedLocalPurchase() async throws {
        let session = try await makeSession()
        defer { session.clearTransactions() }
        let purchaser = ProStore()
        await purchaser.load()
        XCTAssertFalse(purchaser.isPro, "A clean session must not inherit another test's entitlement")
        await purchaser.purchase()
        XCTAssertTrue(purchaser.isPro)
        try await requireCurrentLocalPurchase(session, store: purchaser)

        // Fail before AppStore.sync if test configuration accidentally targets a real store.
        var localTransaction: StoreKit.Transaction?
        for await result in StoreKit.Transaction.currentEntitlements {
            if case .verified(let transaction) = result,
               transaction.productID == purchaser.productID,
               transaction.environment == .xcode {
                localTransaction = transaction
            }
        }
        _ = try XCTUnwrap(localTransaction, "Restore requires a verified Xcode test transaction")
        let restored = ProStore()
        await restored.restore()
        XCTAssertTrue(restored.isPro)
        XCTAssertEqual(restored.message, "Pro purchase restored.")
        XCTAssertFalse(restored.isBusy)

        // Refreshing an unchanged entitlement must preserve the restore result.
        await restored.load()
        XCTAssertEqual(restored.message, "Pro purchase restored.")

        let transaction = try XCTUnwrap(session.allTransactions().first)
        try session.refundTransaction(identifier: transaction.identifier)
        // A foreground refresh can observe the refund before the updates listener.
        await restored.load()
        await waitForObservedEntitlement(false, store: restored)
        XCTAssertEqual(restored.message, "Pro access is no longer active. Your saved inventory and exports remain available.")
    }

    func testPendingPurchaseRequiresApprovalBeforeUnlocking() async throws {
        let session = try await makeSession()
        defer { session.clearTransactions() }
        session.askToBuyEnabled = true
        let store = ProStore()
        await store.load()
        XCTAssertFalse(store.isPro, "A clean session must not inherit another test's entitlement")
        await store.purchase()
        XCTAssertFalse(store.isPro)
        XCTAssertTrue(store.message?.contains("awaiting approval") == true)
        let transaction = try XCTUnwrap(session.allTransactions().first)
        try session.approveAskToBuyTransaction(identifier: transaction.identifier)
        await waitForObservedEntitlement(true, store: store)
        XCTAssertEqual(store.message, "Pro is ready. Thank you for supporting Room Inventory.")
    }
}
