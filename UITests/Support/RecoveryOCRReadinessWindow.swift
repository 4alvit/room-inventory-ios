import Foundation

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
