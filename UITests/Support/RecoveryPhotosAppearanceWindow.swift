import Foundation
import XCTest

/// The system Photos picker can present after its launch tap has returned.
/// Allow cold first presentation within one monotonic, nonrenewable window.
struct RecoveryPhotosAppearanceWindow {
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired

        var description: String { "Photos appearance deadline expired" }
    }

    private let clock: () -> TimeInterval
    private let end: TimeInterval

    init(clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.clock = clock
        end = clock() + 90
    }

    func remaining() throws -> TimeInterval {
        let value = end - clock()
        guard value > 0 else { throw Failure.expired }
        return value
    }

    func wait(_ operation: (TimeInterval) throws -> Bool) throws -> Bool {
        let result = try operation(remaining())
        // XCTest may finish an in-flight query after its wait times out.
        // Even a successful late result cannot authorize photo selection.
        _ = try remaining()
        return result
    }

    /// Probe inside the active waiter, starting on its first run-loop turn.
    /// Avoid waitForExistence's additional existence check after its timeout.
    /// A native query already in flight may still return after the deadline;
    /// the same postcondition above rejects that result.
    @MainActor
    func waitForProbe(_ probe: @escaping @MainActor () -> Bool) throws -> Bool {
        let pending = PendingProbe(window: self, probe: probe)
        defer { pending.stop() }
        _ = try remaining()
        RunLoop.main.perform(inModes: [.default]) {
            MainActor.assumeIsolated { pending.poll() }
        }
        return try wait { remaining in
            XCTWaiter.wait(for: [pending.ready], timeout: remaining) == .completed
        }
    }

    @MainActor
    private final class PendingProbe {
        let ready = XCTestExpectation(description: "Photos appearance probe")
        private let window: RecoveryPhotosAppearanceWindow
        private let probe: @MainActor () -> Bool
        private var active = true
        private var timer: Timer?

        init(window: RecoveryPhotosAppearanceWindow, probe: @escaping @MainActor () -> Bool) {
            self.window = window
            self.probe = probe
        }

        func poll() {
            guard active, (try? window.remaining()) != nil else { return }
            let appeared = probe()
            guard active, (try? window.remaining()) != nil else { return }
            if appeared {
                active = false
                ready.fulfill()
            } else {
                // Native queries may pump the run loop. Schedule only after
                // this query returns so a second probe cannot overlap it.
                // Leave room for another query within the original deadline
                // when the remote Photos service answers slowly.
                let next = Timer(timeInterval: 0.1, repeats: false) { [weak self] _ in
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
}
