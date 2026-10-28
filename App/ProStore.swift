import Foundation
import Observation
import StoreKit

// Read-only projection for deterministic verification/state-ordering controls.
// Production feeds this receiver Apple's VerificationResult<Transaction> only.
protocol ProEntitlementTransaction {
    var productID: String { get }
    var productType: Product.ProductType { get }
    var revocationDate: Date? { get }
    var isUpgraded: Bool { get }
}
extension StoreKit.Transaction: ProEntitlementTransaction {}

/// Entitlements come exclusively from verified StoreKit transactions.
@MainActor @Observable
final class ProStore {
    typealias EntitlementSnapshot = @MainActor @Sendable (String) async -> Bool

    private(set) var isPro = false
    private(set) var displayPrice: String?
    private(set) var isBusy = false
    var message: String?
    private var product: Product?
    // Only MainActor mutates this handle; nonisolated access permits cancellation in deinit.
    @ObservationIgnored nonisolated(unsafe) private var updates: Task<Void, Never>?
    @ObservationIgnored private let entitlementSnapshot: EntitlementSnapshot
    @ObservationIgnored private var entitlementRevision: UInt64 = 0
    let productID: String

    init(entitlementSnapshot: EntitlementSnapshot? = nil, observeTransactionUpdates: Bool = true) {
        productID = Bundle.main.object(forInfoDictionaryKey: "ProProductID") as? String
            ?? "com.alvit.roominventory.pro"
        self.entitlementSnapshot = entitlementSnapshot ?? Self.verifiedEntitlementSnapshot
        guard observeTransactionUpdates else { return }
        updates = Task { [weak self] in
            for await result in Transaction.updates {
                guard let self else { return }
                guard await self.applyTransactionUpdate(result),
                      case .verified(let transaction) = result else { continue }
                await transaction.finish()
            }
        }
    }

    deinit { updates?.cancel() }

    func load() async {
        await refreshEntitlements()
        do {
            product = try await Product.products(for: [productID]).first
            displayPrice = product?.displayPrice
            if product == nil {
                message = ServiceL10n.text("pro.storeUnavailable")
            }
        } catch {
            message = ServiceL10n.text("pro.storeUnavailable")
        }
    }

    func purchase() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        message = nil
        do {
            if product == nil { await load() }
            guard let product else {
                message = ServiceL10n.text("pro.unavailable")
                return
            }
            switch try await product.purchase() {
            case .success(let result):
                guard case .verified(let transaction) = result,
                      transaction.productID == productID else {
                    message = ServiceL10n.text("pro.unverified")
                    return
                }
                await refreshEntitlements()
                await transaction.finish()
                message = isPro ? ServiceL10n.text("pro.ready") : ServiceL10n.text("pro.confirming")
            case .pending:
                message = ServiceL10n.text("pro.pending")
            case .userCancelled:
                message = ServiceL10n.text("pro.cancelled")
            @unknown default:
                message = ServiceL10n.text("pro.incomplete")
            }
        } catch StoreKitError.userCancelled {
            message = ServiceL10n.text("pro.cancelled")
        } catch {
            message = ServiceL10n.text("pro.failed")
        }
    }

    func restore() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try await AppStore.sync()
            await refreshEntitlements()
            message = isPro ? ServiceL10n.text("pro.restored") : ServiceL10n.text("pro.notFound")
        } catch {
            message = ServiceL10n.text("pro.restoreFailed")
        }
    }

    func refreshEntitlements() async {
        entitlementRevision &+= 1
        let revision = entitlementRevision
        let found = await entitlementSnapshot(productID)
        // A newer scan may finish while this one is suspended in StoreKit.
        // Publish the entitlement and its status only from the latest scan.
        guard revision == entitlementRevision else { return }
        if isPro != found {
            message = found
                ? ServiceL10n.text("pro.ready")
                : ServiceL10n.text("pro.inactive")
        }
        isPro = found
    }

    @discardableResult
    func applyTransactionUpdate<T: ProEntitlementTransaction>(_ result: VerificationResult<T>) async -> Bool {
        guard case .verified(let transaction) = result,
              transaction.productID == productID,
              transaction.productType == .nonConsumable else { return false }
        entitlementRevision &+= 1
        let revision = entitlementRevision
        let found: Bool
        if transaction.revocationDate != nil || transaction.isUpgraded {
            // A revoked older transaction must not remove a newer repurchase.
            // Preserve aggregate verified-receipt reconciliation for removals.
            found = await entitlementSnapshot(productID)
        } else {
            // A verified approval already grants this nonconsumable entitlement;
            // the separate currentEntitlements index may not reflect it yet.
            found = true
        }
        guard revision == entitlementRevision else { return true }
        if isPro != found {
            message = found
                ? ServiceL10n.text("pro.ready")
                : ServiceL10n.text("pro.inactive")
        }
        isPro = found
        return true
    }

    private static func verifiedEntitlementSnapshot(productID: String) async -> Bool {
        var found = false
        for await result in Transaction.currentEntitlements {
            guard case .verified(let transaction) = result,
                  transaction.productID == productID,
                  transaction.productType == .nonConsumable,
                  transaction.revocationDate == nil, !transaction.isUpgraded else { continue }
            found = true
        }
        return found
    }
}
