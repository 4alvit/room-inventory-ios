import Foundation

/// The system Photos picker can present after its launch tap has returned.
/// Keep its appearance wait within one monotonic, nonrenewable allowance.
struct RecoveryPhotosAppearanceWindow {
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired

        var description: String { "Photos appearance deadline expired" }
    }

    private let clock: () -> TimeInterval
    private let end: TimeInterval

    init(clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.clock = clock
        end = clock() + 30
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
}
