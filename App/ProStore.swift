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

#if DEBUG
// Fixed-size, read-only diagnostics. No transaction IDs, receipts, product names,
// additional StoreKit queries, or logging from the production listener.
struct ProStoreProcessingDiagnostics {
    enum ListenerPhase: String { case disabled, scheduled, waiting, applying, finishing, ended }
    enum UpdateKind: String { case none, unverified, foreignProduct, unsupportedType, approval, removal }
    enum StateWriteSource: String { case none, refresh, approval, removal }
    var listenerPhase: ListenerPhase = .disabled
    var received: UInt64 = 0
    var rejected: UInt64 = 0
    var unverifiedUpdates: UInt64 = 0
    var foreignProductUpdates: UInt64 = 0
    var unsupportedTypeUpdates: UInt64 = 0
    var approvalUpdates: UInt64 = 0
    var removalUpdates: UInt64 = 0
    var approvalsApplied: UInt64 = 0
    var removalScansStarted: UInt64 = 0
    var removalScansCompleted: UInt64 = 0
    var removalScansSuperseded: UInt64 = 0
    var refreshesStarted: UInt64 = 0
    var refreshesCompleted: UInt64 = 0
    var refreshesSuperseded: UInt64 = 0
    var finishesStarted: UInt64 = 0
    var finishesCompleted: UInt64 = 0
    var lastUpdateKind: UpdateKind = .none
    // Completed scans are observations, including scans superseded by a newer
    // revision. Only recordStateWrite identifies an actual assignment to isPro.
    var lastObservedSnapshotFound: Bool?
    var lastStateWriteSource: StateWriteSource = .none
    var lastStateWriteRevision: UInt64?
    var lastStateWriteValue: Bool?

    mutating func recordUpdateKind(_ kind: UpdateKind) {
        lastUpdateKind = kind
        switch kind {
        case .unverified: unverifiedUpdates &+= 1
        case .foreignProduct: foreignProductUpdates &+= 1
        case .unsupportedType: unsupportedTypeUpdates &+= 1
        case .approval: approvalUpdates &+= 1
        case .removal: removalUpdates &+= 1
        case .none: break
        }
    }

    mutating func recordStateWrite(_ source: StateWriteSource, revision: UInt64, value: Bool) {
        lastStateWriteSource = source
        lastStateWriteRevision = revision
        lastStateWriteValue = value
    }

    var fields: [String: Any] {
        ["listener_phase": listenerPhase.rawValue,
         "updates_received": received, "updates_rejected": rejected,
         "updates_unverified": unverifiedUpdates,
         "updates_foreign_product": foreignProductUpdates,
         "updates_unsupported_type": unsupportedTypeUpdates,
         "updates_approval": approvalUpdates, "updates_removal": removalUpdates,
         "approvals_applied": approvalsApplied,
         "removal_scans_started": removalScansStarted,
         "removal_scans_completed": removalScansCompleted,
         "removal_scans_superseded": removalScansSuperseded,
         "refreshes_started": refreshesStarted, "refreshes_completed": refreshesCompleted,
         "refreshes_superseded": refreshesSuperseded,
         "finishes_started": finishesStarted, "finishes_completed": finishesCompleted,
         "last_update_kind": lastUpdateKind.rawValue,
         "last_observed_snapshot_found": lastObservedSnapshotFound.map { $0 as Any } ?? NSNull(),
         "state_write_source": lastStateWriteSource.rawValue,
         "state_write_revision": lastStateWriteRevision.map { $0 as Any } ?? NSNull(),
         "state_write_value": lastStateWriteValue.map { $0 as Any } ?? NSNull()]
    }
}
#endif

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
    #if DEBUG
    @ObservationIgnored private(set) var processingDiagnostics = ProStoreProcessingDiagnostics()
    #endif
    let productID: String

    init(entitlementSnapshot: EntitlementSnapshot? = nil, observeTransactionUpdates: Bool = true) {
        productID = Bundle.main.object(forInfoDictionaryKey: "ProProductID") as? String
            ?? "com.alvit.roominventory.pro"
        self.entitlementSnapshot = entitlementSnapshot ?? Self.verifiedEntitlementSnapshot
        guard observeTransactionUpdates else { return }
        #if DEBUG
        processingDiagnostics.listenerPhase = .scheduled
        #endif
        updates = Task { [weak self] in
            #if DEBUG
            self?.processingDiagnostics.listenerPhase = .waiting
            defer { self?.processingDiagnostics.listenerPhase = .ended }
            #endif
            for await result in Transaction.updates {
                guard let self else { return }
                #if DEBUG
                // Diagnostics must not extend the store's lifetime across finish().
                weak var diagnosticStore = self
                self.processingDiagnostics.received &+= 1
                self.processingDiagnostics.listenerPhase = .applying
                defer { diagnosticStore?.processingDiagnostics.listenerPhase = .waiting }
                #endif
                guard await self.applyTransactionUpdate(result),
                      case .verified(let transaction) = result else { continue }
                #if DEBUG
                diagnosticStore?.processingDiagnostics.listenerPhase = .finishing
                diagnosticStore?.processingDiagnostics.finishesStarted &+= 1
                #endif
                await transaction.finish()
                #if DEBUG
                diagnosticStore?.processingDiagnostics.finishesCompleted &+= 1
                #endif
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
        #if DEBUG
        processingDiagnostics.refreshesStarted &+= 1
        #endif
        let found = await entitlementSnapshot(productID)
        #if DEBUG
        processingDiagnostics.refreshesCompleted &+= 1
        processingDiagnostics.lastObservedSnapshotFound = found
        if revision != entitlementRevision { processingDiagnostics.refreshesSuperseded &+= 1 }
        #endif
        // A newer scan may finish while this one is suspended in StoreKit.
        // Publish the entitlement and its status only from the latest scan.
        guard revision == entitlementRevision else { return }
        if isPro != found {
            message = found
                ? ServiceL10n.text("pro.ready")
                : ServiceL10n.text("pro.inactive")
        }
        isPro = found
        #if DEBUG
        processingDiagnostics.recordStateWrite(.refresh, revision: revision, value: found)
        #endif
    }

    @discardableResult
    func applyTransactionUpdate<T: ProEntitlementTransaction>(_ result: VerificationResult<T>) async -> Bool {
        #if DEBUG
        let kind = updateKind(result)
        processingDiagnostics.recordUpdateKind(kind)
        if kind == .unverified || kind == .foreignProduct || kind == .unsupportedType {
            processingDiagnostics.rejected &+= 1
        }
        #endif
        guard case .verified(let transaction) = result,
              transaction.productID == productID,
              transaction.productType == .nonConsumable else { return false }
        entitlementRevision &+= 1
        let revision = entitlementRevision
        let found: Bool
        if transaction.revocationDate != nil || transaction.isUpgraded {
            // A revoked older transaction must not remove a newer repurchase.
            // Preserve aggregate verified-receipt reconciliation for removals.
            #if DEBUG
            processingDiagnostics.removalScansStarted &+= 1
            #endif
            found = await entitlementSnapshot(productID)
            #if DEBUG
            processingDiagnostics.removalScansCompleted &+= 1
            processingDiagnostics.lastObservedSnapshotFound = found
            if revision != entitlementRevision { processingDiagnostics.removalScansSuperseded &+= 1 }
            #endif
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
        #if DEBUG
        if kind == .approval { processingDiagnostics.approvalsApplied &+= 1 }
        processingDiagnostics.recordStateWrite(kind == .approval ? .approval : .removal,
            revision: revision, value: found)
        #endif
        return true
    }

    #if DEBUG
    private func updateKind<T: ProEntitlementTransaction>(_ result: VerificationResult<T>) -> ProStoreProcessingDiagnostics.UpdateKind {
        guard case .verified(let transaction) = result else { return .unverified }
        guard transaction.productID == productID else { return .foreignProduct }
        guard transaction.productType == .nonConsumable else { return .unsupportedType }
        return transaction.revocationDate != nil || transaction.isUpgraded ? .removal : .approval
    }
    #endif

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
