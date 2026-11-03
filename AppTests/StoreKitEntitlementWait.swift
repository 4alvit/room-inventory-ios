import Foundation

struct StoreKitEntitlementWaitResult {
    let matched: Bool
    let lastObserved: Bool?
    let observations: Int
}

/// Observe the store only. Never refresh entitlements, repeat a purchase, or
/// reset the deadline while StoreKit delivers an asynchronous transaction.
@MainActor
func waitForStoreKitEntitlement(
    expected: Bool,
    deadline: ContinuousClock.Instant,
    now: @MainActor () -> ContinuousClock.Instant,
    pauseUntil: @MainActor (ContinuousClock.Instant) async throws -> Void,
    read: @MainActor () -> Bool
) async throws -> StoreKitEntitlementWaitResult {
    try Task.checkCancellation()
    var lastObserved: Bool?
    var observations = 0
    while now() < deadline {
        try Task.checkCancellation()
        let value = read()
        observations += 1
        lastObserved = value
        try Task.checkCancellation()
        // Even a matching observation cannot authorize success at/after expiry.
        guard now() < deadline else { break }
        if value == expected {
            return StoreKitEntitlementWaitResult(matched: true,
                lastObserved: lastObserved, observations: observations)
        }
        try await pauseUntil(min(deadline, now().advanced(by: .milliseconds(100))))
    }
    try Task.checkCancellation()
    return StoreKitEntitlementWaitResult(matched: false,
        lastObserved: lastObserved, observations: observations)
}
