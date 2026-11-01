import Foundation
import XCTest

/// One monotonic allowance covers publication, observation and validation.
/// Host accounting and durable capture can take longer on hosted Simulators.
struct RecoveryAcknowledgementWindow {
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired
        case waiterResult(Int)

        var description: String {
            switch self {
            case .expired: "Recovery runner bridge: acknowledgement deadline expired"
            case let .waiterResult(value):
                "Recovery runner bridge: acknowledgement waiter ended with result \(value)"
            }
        }
    }

    private let clock: () -> TimeInterval
    private let end: TimeInterval

    init(clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.clock = clock
        end = clock() + 60
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

    func observe(_ condition: () -> Bool) -> Bool {
        guard (try? remaining()) != nil else { return false }
        let observed = condition()
        guard (try? remaining()) != nil else { return false }
        return observed
    }

    func wait(_ operation: (TimeInterval) -> XCTWaiter.Result) throws {
        let result = operation(try remaining())
        guard result == .completed else { throw Failure.waiterResult(result.rawValue) }
        _ = try remaining()
    }
}
