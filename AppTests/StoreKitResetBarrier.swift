import Foundation

struct StoreKitResetState: Equatable {
    let sessionTransactions: Int
    let verifiedEntitlements: Int
    var clean: Bool { sessionTransactions == 0 && verifiedEntitlements == 0 }
}

struct StoreKitResetResult {
    let clean: Bool
    let first: StoreKitResetState?
    let last: StoreKitResetState?
    let observations: Int

    var diagnostic: String {
        "observations=\(observations), first=\(String(describing: first)), last=\(String(describing: last))"
    }
}

// Test-only barrier. Never resets StoreKit, purchases, refreshes a ProStore, or
// retries a behavior assertion. The deadline is fixed before the first read.
@MainActor
func waitForStoreKitReset(
    deadline: ContinuousClock.Instant,
    now: @MainActor () -> ContinuousClock.Instant,
    pauseUntil: @MainActor (ContinuousClock.Instant) async throws -> Void,
    read: @MainActor () async -> StoreKitResetState
) async throws -> StoreKitResetResult {
    var first: StoreKitResetState?
    var last: StoreKitResetState?
    var observations = 0
    while now() < deadline {
        let state = await read()
        observations += 1
        if first == nil { first = state }
        last = state
        // A late clean snapshot cannot retroactively satisfy the barrier.
        guard now() < deadline else { break }
        if state.clean {
            return StoreKitResetResult(clean: true, first: first, last: last, observations: observations)
        }
        try await pauseUntil(min(deadline, now().advanced(by: .milliseconds(100))))
    }
    return StoreKitResetResult(clean: false, first: first, last: last, observations: observations)
}
