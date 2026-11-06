import Foundation
import XCTest

/// Snapshot, hit testing and tap admission share one readiness allowance.
struct RecoveryOCRReadinessWindow {
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired, invalidAllowance

        var description: String {
            self == .expired ? "OCR readiness deadline expired" : "Invalid readiness allowance"
        }
    }

    private let clock: () -> TimeInterval
    private let end: TimeInterval
    private let validAllowance: Bool

    static let coldKeyboardSetupAllowance: TimeInterval = 90

    /// Only cold keyboard setup uses this allowance; generic callers retain 30s maximum.
    static func coldKeyboardSetup(
        clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }
    ) -> Self {
        Self(coldKeyboardSetupClock: clock)
    }

    private init(coldKeyboardSetupClock clock: @escaping () -> TimeInterval) {
        self.clock = clock
        validAllowance = true
        end = clock() + Self.coldKeyboardSetupAllowance
    }

    init(timeout: TimeInterval = 10,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.clock = clock
        validAllowance = timeout.isFinite && timeout > 0 && timeout <= 30
        end = clock() + timeout
    }

    func remaining() throws -> TimeInterval {
        guard validAllowance else { throw Failure.invalidAllowance }
        let value = end - clock()
        guard value > 0 else { throw Failure.expired }
        return value
    }

    /// Start the first probe inside the active waiter, without the predicate
    /// expectation's initial polling delay. A nested XCTest wait can still be
    /// interrupted by this outer waiter; this is not a hard wall-clock kill.
    @MainActor
    func waitForProbe(_ probe: @escaping @MainActor () -> Bool) throws -> XCTWaiter.Result {
        let pending = PendingProbe(window: self, probe: probe)
        defer { pending.stop() }
        _ = try remaining()
        RunLoop.main.perform(inModes: [.default]) {
            MainActor.assumeIsolated { pending.poll() }
        }
        let result = XCTWaiter.wait(for: [pending.ready], timeout: try remaining())
        // Expiration wakes the waiter without turning a late probe into readiness.
        // Return a result so callers can still prioritize a captured native error.
        return result == .completed && pending.expired ? .timedOut : result
    }

    @MainActor
    private final class PendingProbe {
        let ready = XCTestExpectation(description: "OCR readiness probe")
        private let window: RecoveryOCRReadinessWindow
        private let probe: @MainActor () -> Bool
        private var active = true
        private var timer: Timer?
        private(set) var expired = false

        init(window: RecoveryOCRReadinessWindow, probe: @escaping @MainActor () -> Bool) {
            self.window = window
            self.probe = probe
        }

        func poll() {
            guard active else { return }
            guard (try? window.remaining()) != nil else { finishExpired(); return }
            let finished = probe()
            guard active else { return }
            guard (try? window.remaining()) != nil else { finishExpired(); return }
            if finished {
                active = false
                ready.fulfill()
            } else {
                // Schedule only after the previous probe has returned: native
                // queries may pump this run loop and must not reenter a probe.
                let next = Timer(timeInterval: 1, repeats: false) { [weak self] _ in
                    MainActor.assumeIsolated { self?.poll() }
                }
                timer = next
                RunLoop.main.add(next, forMode: .default)
            }
        }
        private func finishExpired() {
            guard active else { return }
            expired = true
            stop()
            ready.fulfill()
        }
        func stop() {
            active = false
            timer?.invalidate()
            timer = nil
        }
    }

    func perform<Value>(_ operation: () throws -> Value) throws -> Value {
        _ = try remaining()
        let value = try operation()
        _ = try remaining()
        return value
    }

    /// State and geometry can reuse this same snapshot after a successful probe.
    /// Never start another remote query after an earlier stage returned late.
    func probe<Snapshot>(snapshot: () throws -> Snapshot,
                         stateReady: (Snapshot) throws -> Bool,
                         hittable: () throws -> Bool) throws -> Snapshot? {
        let observation = try perform(snapshot)
        guard try perform({ try stateReady(observation) }) else { return nil }
        guard try perform(hittable) else { return nil }
        return observation
    }
}
