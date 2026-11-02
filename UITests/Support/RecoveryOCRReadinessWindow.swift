import Foundation
import XCTest

/// Snapshot, hit testing and tap admission share one readiness allowance.
struct RecoveryOCRReadinessWindow {
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired

        var description: String { "OCR readiness deadline expired" }
    }

    private let clock: () -> TimeInterval
    private let end: TimeInterval

    init(clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.clock = clock
        end = clock() + 10
    }

    func remaining() throws -> TimeInterval {
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
        return XCTWaiter.wait(for: [pending.ready], timeout: try remaining())
    }

    @MainActor
    private final class PendingProbe {
        let ready = XCTestExpectation(description: "OCR readiness probe")
        private let window: RecoveryOCRReadinessWindow
        private let probe: @MainActor () -> Bool
        private var active = true
        private var timer: Timer?

        init(window: RecoveryOCRReadinessWindow, probe: @escaping @MainActor () -> Bool) {
            self.window = window
            self.probe = probe
        }

        func poll() {
            guard active, (try? window.remaining()) != nil else { return }
            let finished = probe()
            guard active, (try? window.remaining()) != nil else { return }
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
