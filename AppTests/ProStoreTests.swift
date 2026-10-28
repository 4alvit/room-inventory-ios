import XCTest
import StoreKit
import StoreKitTest
import InventoryCore
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

    @discardableResult
    private func diagnostic(_ phase: String, _ fields: [String: Any] = [:]) -> String {
        let value = fields.merging(["phase": phase,
            "uptime": ProcessInfo.processInfo.systemUptime]) { _, new in new }
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
              data.count <= 2_048, let text = String(data: data, encoding: .utf8) else {
            XCTFail("StoreKit diagnostic exceeded its bounded fixed-field shape")
            return "diagnostic unavailable"
        }
        print("ROOM_STOREKIT_DIAGNOSTIC " + text)
        let attachment = XCTAttachment(string: text)
        attachment.name = "StoreKit-" + phase
        attachment.lifetime = .keepAlways
        add(attachment)
        return text
    }

    private func catalogProbe(_ phase: String, session: SKTestSession,
                              expected: SKTestFailures.LoadProducts, productID: String) async -> String {
        diagnostic(phase + "-setting-before")
        let configured = await session.simulatedError(forAPI: .loadProducts)
        XCTAssertEqual(configured, expected, "Catalog error setting changed: \(phase)")
        let setting = String(String(describing: configured).prefix(192))
        diagnostic(phase + "-products-before", ["setting_matches": configured == expected,
                    "setting": setting])
        do {
            let products = try await Product.products(for: [productID])
            return diagnostic(phase + "-products-after", ["outcome": "returned",
                "count": products.count, "matching_product_count": products.filter { $0.id == productID }.count,
                "setting_matches": configured == expected, "setting": setting])
        } catch {
            let value = error as NSError
            return diagnostic(phase + "-products-after", ["outcome": "threw",
                "error_type": String(String(reflecting: type(of: error)).prefix(96)),
                "error_domain": String(value.domain.prefix(96)), "error_code": value.code,
                "setting_matches": configured == expected, "setting": setting])
        }
    }

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
        diagnostic("pending-approval-before", ["session_transactions": session.allTransactions().count,
            "store_isPro": store.isPro])
        try session.approveAskToBuyTransaction(identifier: transaction.identifier)
        diagnostic("pending-approval-after", ["session_transactions": session.allTransactions().count])
        await waitForObservedEntitlement(true, store: store)
        var observation = "approval observed"
        if !store.isPro {
            diagnostic("pending-failed-entitlements-before")
            let current = await verifiedEntitlements()
            observation = diagnostic("pending-failed-entitlements-after", [
                "session_transactions": session.allTransactions().count,
                "verified_product_entitlements": current.filter { $0.productID == store.productID }.count,
                "verified_xcode_product_entitlements": current.filter {
                    $0.productID == store.productID && $0.environment == .xcode && $0.revocationDate == nil
                }.count, "store_isPro": store.isPro, "message": store.message ?? "<nil>"])
        }
        XCTAssertEqual(store.message, "Pro is ready. Thank you for supporting Room Inventory.", observation)
    }

    func testNativeCancellationPreservesUnpaidInventoryAndOriginal() async throws {
        try await checkNativePurchasePreservation(previouslyPurchased: false)
    }

    func testRepeatedNonConsumablePurchasePreservesVerifiedEntitlementAndOriginal() async throws {
        try await checkNativePurchasePreservation(previouslyPurchased: true)
    }

    private func checkNativePurchasePreservation(previouslyPurchased: Bool) async throws {
        let session = try await makeSession()
        defer { session.resetToDefaultState(); session.clearTransactions() }
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("StoreKitCancellation-\(UUID())", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let repository = try InventoryRepository(rootURL: directory)
        let original = try XCTUnwrap(Data(base64Encoded:
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6tX8AAAAASUVORK5CYII="))
        let attachment = try repository.importAttachment(data: original,
            originalName: "synthetic.png", mediaType: "image/png", kind: .receipt)
        let inventory = Inventory(homes: [InventoryHome(name: "Saved home", rooms: [
            InventoryRoom(name: "Saved room", items: [
                InventoryItem(name: "Saved item", attachments: [attachment])
            ])
        ])])
        try repository.save(inventory)
        let manifestURL = directory.appendingPathComponent("inventory.json")
        let manifest = try Data(contentsOf: manifestURL)
        let store = ProStore()
        await store.load()
        XCTAssertFalse(store.isPro)
        XCTAssertNotNil(store.displayPrice)

        let initialFailure = await session.simulatedError(forAPI: .purchase)
        let setup = diagnostic("cancellation-setup", ["previously_purchased": previouslyPurchased,
            "setting": String(String(describing: initialFailure).prefix(192)),
            "store_isPro": store.isPro, "session_transactions": session.allTransactions().count])
        XCTAssertNil(initialFailure, setup)
        // Each producer owns a clean session. The paid case verifies an already-owned
        // non-consumable; only the unpaid case injects purchase failures.
        if previouslyPurchased {
            diagnostic("cancellation-setup-purchase-before", ["previously_purchased": true])
            await store.purchase()
            diagnostic("cancellation-setup-purchase-after", ["store_isPro": store.isPro,
                "store_isBusy": store.isBusy, "message": store.message ?? "<nil>",
                "session_transactions": session.allTransactions().count])
            await waitForObservedEntitlement(true, store: store)
            try await requireCurrentLocalPurchase(session, store: store)
        }

        let products = try await Product.products(for: [store.productID])
        let product = try XCTUnwrap(products.first)
        let before = await verifiedEntitlements()
        let beforeIDs = Set(before.map(\.id))
        let beforeOriginalIDs = Set(before.map(\.originalID))
        let details: String
        if previouslyPurchased {
            guard before.count == 1, let owned = before.first,
                  owned.productID == store.productID, owned.productType == .nonConsumable,
                  owned.environment == .xcode, owned.revocationDate == nil else {
                XCTFail("Paid precondition requires exactly one expected verified local entitlement")
                return
            }
            // A non-consumable is purchased once. Re-purchasing an owned product
            // may return its verified ownership, so it cannot calibrate cancellation.
            diagnostic("owned-purchase-before")
            switch try await product.purchase() {
            case .success(.verified(let transaction)):
                guard transaction.productID == store.productID,
                      transaction.productType == .nonConsumable,
                      transaction.environment == .xcode,
                      transaction.revocationDate == nil,
                      beforeOriginalIDs.contains(transaction.originalID) else {
                    XCTFail("Owned purchase must verify the same local non-consumable purchase")
                    return
                }
                details = diagnostic("owned-purchase-after", ["outcome": "returned_verified_success",
                    "same_original_purchase": true])
                await transaction.finish()
            case .success(.unverified):
                XCTFail("Owned purchase returned an unverified transaction")
                return
            case .userCancelled:
                XCTFail("Owned purchase unexpectedly returned cancellation without error injection")
                return
            case .pending:
                XCTFail("Owned purchase unexpectedly requires approval")
                return
            @unknown default:
                XCTFail("Owned purchase returned an unknown result")
                return
            }
            await store.purchase()
            XCTAssertEqual(store.message, ServiceL10n.text("pro.ready"), details)
        } else {
            // Record the actual injected native cancellation route. This does not
            // prove tapping Cancel in the system payment sheet.
            try await session.setSimulatedError(.generic(.userCancelled), forAPI: .purchase)
            let configured = await session.simulatedError(forAPI: .purchase)
            XCTAssertEqual(configured, .generic(.userCancelled))
            diagnostic("cancellation-calibration-before", ["previously_purchased": previouslyPurchased,
                "setting": String(String(describing: configured).prefix(192))])
            let route: String
            do {
                switch try await product.purchase() {
                case .userCancelled:
                    route = "returned_userCancelled"
                case .pending:
                    let details = diagnostic("cancellation-calibration-after", ["outcome": "returned_pending"])
                    XCTFail("Configured cancellation produced a pending purchase: \(details)")
                    return
                case .success(let verification):
                    let verified: Bool
                    if case .verified = verification { verified = true } else { verified = false }
                    let details = diagnostic("cancellation-calibration-after", ["outcome": "returned_success", "verified": verified])
                    XCTFail("Configured cancellation produced a successful purchase: \(details)")
                    return
                @unknown default:
                    XCTFail("Configured cancellation produced an unknown purchase result")
                    return
                }
            } catch StoreKitError.userCancelled {
                route = "thrown_userCancelled"
            } catch {
                let value = error as NSError
                diagnostic("cancellation-calibration-after", ["outcome": "thrown_other",
                    "error_type": String(String(reflecting: type(of: error)).prefix(96)),
                    "error_domain": String(value.domain.prefix(96)), "error_code": value.code])
                throw error
            }
            details = diagnostic("cancellation-calibration-after", ["outcome": route,
                "previously_purchased": previouslyPurchased])
            await store.purchase()
            XCTAssertEqual(store.message, ServiceL10n.text("pro.cancelled"), details)
        }
        XCTAssertFalse(store.isBusy)
        XCTAssertEqual(store.isPro, previouslyPurchased)
        let after = await verifiedEntitlements()
        if previouslyPurchased {
            guard after.count == 1, let owned = after.first,
                  owned.productID == store.productID, owned.productType == .nonConsumable,
                  owned.environment == .xcode, owned.revocationDate == nil else {
                XCTFail("Owned purchase must preserve exactly one expected verified local entitlement")
                return
            }
            // Restore-style transactions can have a new id; ownership must still
            // refer to the same original purchase, with no extra entitlement.
            XCTAssertEqual(Set(after.map(\.originalID)), beforeOriginalIDs)
        } else {
            XCTAssertEqual(Set(after.map(\.id)), beforeIDs)
        }
        let reopened = ProStore()
        await reopened.load()
        XCTAssertEqual(reopened.isPro, previouslyPurchased)
        if previouslyPurchased {
            try await requireCurrentLocalPurchase(session, store: reopened)
        }
        let reopenedInventory = InventoryStore(rootURL: directory)
        await reopenedInventory.load()
        XCTAssertTrue(reopenedInventory.hasLoaded)
        XCTAssertEqual(reopenedInventory.inventory, inventory)
        XCTAssertEqual(try Data(contentsOf: manifestURL), manifest)
        XCTAssertEqual(try repository.data(for: attachment), original)
        if !previouslyPurchased {
            // A fresh unpaid purchase exercises the generic failure route; an
            // already-owned non-consumable may return ownership without that route.
            let failure: SKTestFailures.Purchase = .generic(
                .networkError(URLError(.notConnectedToInternet)))
            try await session.setSimulatedError(failure, forAPI: .purchase)
            let configuredFailure = await session.simulatedError(forAPI: .purchase)
            XCTAssertEqual(configuredFailure, failure)
            diagnostic("unpaid-failure-before", ["setting_matches": configuredFailure == failure])
            await store.purchase()
            let failed = diagnostic("unpaid-failure-after", ["store_isPro": store.isPro,
                "store_isBusy": store.isBusy, "message": store.message ?? "<nil>"])
            XCTAssertEqual(store.message, ServiceL10n.text("pro.failed"), failed)
            XCTAssertFalse(store.isBusy)
            XCTAssertFalse(store.isPro)
            let afterFailure = await verifiedEntitlements()
            XCTAssertEqual(Set(afterFailure.map(\.id)), beforeIDs)
            XCTAssertEqual(try Data(contentsOf: manifestURL), manifest)
            XCTAssertEqual(try repository.data(for: attachment), original)
        }
    }

    func testCatalogFailureOnNewStoresUsesVerifiedReceiptAndRespectsRefund() async throws {
        let session = try await makeSession()
        defer { session.resetToDefaultState(); session.clearTransactions() }
        // This simulates only the product API error; it does not disconnect networking.
        let failure: SKTestFailures.LoadProducts = .generic(
            .networkError(URLError(.notConnectedToInternet)))
        try await session.setSimulatedError(failure, forAPI: .loadProducts)
        let configured = await session.simulatedError(forAPI: .loadProducts)
        XCTAssertEqual(configured, failure)
        let fresh = ProStore()
        let freshProbe = await catalogProbe("catalog-fresh", session: session,
            expected: failure, productID: fresh.productID)
        diagnostic("catalog-fresh-load-before")
        await fresh.load()
        let freshOutcome = diagnostic("catalog-fresh-load-after", ["isPro": fresh.isPro,
            "display_price_present": fresh.displayPrice != nil, "message": fresh.message ?? "<nil>"])
        XCTAssertFalse(fresh.isPro, "Catalog failure cannot create purchase rights")
        XCTAssertNil(fresh.displayPrice, freshProbe + "; " + freshOutcome)
        XCTAssertEqual(fresh.message, ServiceL10n.text("pro.storeUnavailable"), freshProbe + "; " + freshOutcome)
        let emptyEntitlements = await verifiedEntitlements()
        XCTAssertTrue(emptyEntitlements.isEmpty)

        try await session.setSimulatedError(nil, forAPI: .loadProducts)
        let purchaser = ProStore()
        await purchaser.load()
        XCTAssertNotNil(purchaser.displayPrice)
        await purchaser.purchase()
        await waitForObservedEntitlement(true, store: purchaser)
        try await requireCurrentLocalPurchase(session, store: purchaser)
        let transaction = try XCTUnwrap(session.allTransactions().first {
            $0.productIdentifier == purchaser.productID
        })

        try await session.setSimulatedError(failure, forAPI: .loadProducts)
        let reopened = ProStore()
        let paidProbe = await catalogProbe("catalog-paid", session: session,
            expected: failure, productID: reopened.productID)
        diagnostic("catalog-paid-load-before")
        await reopened.load()
        let paidOutcome = diagnostic("catalog-paid-load-after", ["isPro": reopened.isPro,
            "display_price_present": reopened.displayPrice != nil, "message": reopened.message ?? "<nil>"])
        XCTAssertTrue(reopened.isPro, "A verified receipt survives catalog failure on a new store")
        XCTAssertNil(reopened.displayPrice, paidProbe + "; " + paidOutcome)
        XCTAssertEqual(reopened.message, ServiceL10n.text("pro.storeUnavailable"), paidProbe + "; " + paidOutcome)
        try await requireCurrentLocalPurchase(session, store: reopened)

        try session.refundTransaction(identifier: transaction.identifier)
        await waitForObservedEntitlement(false, store: purchaser)
        await waitForObservedEntitlement(false, store: reopened)
        let afterRefund = ProStore()
        let refundProbe = await catalogProbe("catalog-refund", session: session,
            expected: failure, productID: afterRefund.productID)
        diagnostic("catalog-refund-load-before")
        await afterRefund.load()
        let refundOutcome = diagnostic("catalog-refund-load-after", ["isPro": afterRefund.isPro,
            "display_price_present": afterRefund.displayPrice != nil, "message": afterRefund.message ?? "<nil>"])
        XCTAssertFalse(afterRefund.isPro, "Catalog failure must not preserve revoked purchase rights")
        XCTAssertNil(afterRefund.displayPrice, refundProbe + "; " + refundOutcome)
        XCTAssertEqual(afterRefund.message, ServiceL10n.text("pro.storeUnavailable"), refundProbe + "; " + refundOutcome)
        let finalEntitlements = await verifiedEntitlements()
        XCTAssertFalse(finalEntitlements.contains {
            $0.productID == purchaser.productID && $0.revocationDate == nil
        })
    }
}
