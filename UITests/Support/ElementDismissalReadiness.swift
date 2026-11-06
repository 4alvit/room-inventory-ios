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

    struct QueryDiagnostics {
        var attempts = 0
        var returnedCount: Int?
        var duration: TimeInterval?
        var threw = false
    }

    let allowance: TimeInterval
    private let window: RecoveryOCRReadinessWindow
    private let diagnosticClock: () -> TimeInterval
    private(set) var lastCount: Int?
    private(set) var queryDiagnostics = QueryDiagnostics()

    init(timeout: TimeInterval = 10,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         diagnosticClock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        allowance = timeout
        self.diagnosticClock = diagnosticClock
        window = RecoveryOCRReadinessWindow(timeout: timeout, clock: clock)
    }

    func waitForDismissal(queryCount: @escaping () throws -> Int) throws -> Bool {
        var queryError: Error?
        do {
            let result = try window.waitForProbe {
                do {
                    let count = try self.window.perform {
                        self.queryDiagnostics.attempts += 1
                        self.queryDiagnostics.returnedCount = nil
                        self.queryDiagnostics.duration = nil
                        self.queryDiagnostics.threw = false
                        let start = self.diagnosticClock()
                        defer {
                            let finish = self.diagnosticClock()
                            let duration = finish - start
                            if start.isFinite && finish.isFinite && duration.isFinite && duration >= 0 {
                                self.queryDiagnostics.duration = duration
                            }
                        }
                        do {
                            let value = try queryCount()
                            // Diagnostic only: the window's postcheck must still
                            // admit this result before it can update lastCount.
                            self.queryDiagnostics.returnedCount = value
                            return value
                        } catch {
                            self.queryDiagnostics.threw = true
                            throw error
                        }
                    }
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
