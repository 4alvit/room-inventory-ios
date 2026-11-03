import Foundation
import XCTest

/// Observe a live query after a dismissal action without resolving a vanished
/// element. The caller separately verifies the resulting UI and saved data.
@MainActor
final class ElementDismissalReadiness {
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired

        var description: String { "Element dismissal deadline expired" }
    }

    private let window: RecoveryOCRReadinessWindow
    private(set) var lastCount: Int?

    init(clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        window = RecoveryOCRReadinessWindow(clock: clock)
    }

    func waitForDismissal(queryCount: @escaping () throws -> Int) throws -> Bool {
        var queryError: Error?
        do {
            let result = try window.waitForProbe {
                do {
                    let count = try self.window.perform(queryCount)
                    // A late, interrupted or throwing query is not an observed
                    // absence and must not overwrite the last timely count.
                    self.lastCount = count
                    return count == 0
                } catch {
                    queryError = error
                    return true // Stop polling; the error remains authoritative.
                }
            }
            if let queryError { throw queryError }
            _ = try window.remaining()
            return result == .completed && lastCount == 0
        } catch is RecoveryOCRReadinessWindow.Failure {
            throw Failure.expired
        }
    }
}
