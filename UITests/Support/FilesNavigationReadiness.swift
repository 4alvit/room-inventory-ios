import Foundation
import XCTest

/// One allowance for a positively observed Files navigation state.
/// A missing state remains pending; it never implies that Back is available.
@MainActor
final class FilesNavigationReadiness {
    enum State: Equatable { case targetFolder, localRoot, localEntry, browse, back }
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired, cancelled, interrupted, alreadyWaiting, invalidAllowance, invalidClock, invalidTitleCount

        var description: String { "Files navigation readiness: \(self.name)" }
        private var name: String {
            switch self {
            case .expired: "deadline expired"
            case .cancelled: "cancelled"
            case .interrupted: "wait interrupted"
            case .alreadyWaiting: "wait already active"
            case .invalidAllowance: "invalid allowance"
            case .invalidClock: "invalid monotonic clock"
            case .invalidTitleCount: "target folder title count is not zero or one"
            }
        }
    }

    private let clock: () -> TimeInterval
    private let end: TimeInterval
    private var lastTime: TimeInterval
    private var failure: Error?
    private var pending: PendingProbe?

    init(timeout: TimeInterval = 30,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.clock = clock
        let start = clock()
        lastTime = start
        end = start + timeout
        if !timeout.isFinite || timeout <= 0 || timeout > 30 {
            failure = Failure.invalidAllowance
        } else if !start.isFinite || !end.isFinite {
            failure = Failure.invalidClock
        }
    }

    func remaining() throws -> TimeInterval {
        if let failure { throw failure }
        let now = clock()
        guard now.isFinite, now >= lastTime else { throw remember(Failure.invalidClock) }
        lastTime = now
        let remaining = end - now
        guard remaining > 0 else { throw remember(Failure.expired) }
        return remaining
    }

    /// Each remote operation needs its own admission and return check. A query
    /// already in flight cannot be killed here, but its late result is rejected.
    func perform<Value>(_ operation: () throws -> Value) throws -> Value {
        _ = try remaining()
        do {
            let value = try operation()
            _ = try remaining()
            return value
        } catch {
            // Preserve a native error even when that operation also ran late.
            throw remember(error)
        }
    }

    func waitForState(probe: @escaping () throws -> State?) throws -> State {
        _ = try remaining()
        guard pending == nil else { throw remember(Failure.alreadyWaiting) }
        let work = PendingProbe(window: self, probe: probe)
        pending = work
        defer { work.stop(); pending = nil }
        RunLoop.main.perform(inModes: [.default]) {
            MainActor.assumeIsolated { work.poll() }
        }
        let result = XCTWaiter.wait(for: [work.ready], timeout: try remaining())
        if case let .failure(error) = work.result { throw error }
        _ = try remaining()
        guard result == .completed, case let .success(state) = work.result else {
            throw remember(result == .timedOut ? Failure.expired : Failure.interrupted)
        }
        return state
    }

    /// Confirm the newly created folder by its exact live title, without
    /// resolving the inline editor after Files has removed it.
    func waitForTargetFolder(titleCount: @escaping () throws -> Int,
                             enabled: @escaping () throws -> Bool,
                             hittable: @escaping () throws -> Bool) throws -> Bool {
        let state = try waitForState {
            let count = try self.perform(titleCount)
            guard count == 0 || count == 1 else { throw Failure.invalidTitleCount }
            guard count == 1 else { return nil }
            guard try self.perform(enabled) else { return nil }
            guard try self.perform(hittable) else { return nil }
            return .targetFolder
        }
        return state == .targetFolder
    }

    func cancel() {
        let error = remember(Failure.cancelled)
        pending?.finish(.failure(error))
    }

    private func remember(_ error: Error) -> Error {
        if failure == nil { failure = error }
        return error
    }

    @MainActor
    private final class PendingProbe {
        let ready = XCTestExpectation(description: "Files navigation state")
        private(set) var result: Result<State, Error>?
        private let window: FilesNavigationReadiness
        private let probe: () throws -> State?
        private var active = true
        private var timer: Timer?

        init(window: FilesNavigationReadiness, probe: @escaping () throws -> State?) {
            self.window = window
            self.probe = probe
        }

        func poll() {
            guard active else { return }
            do {
                let state = try window.perform(probe)
                guard active else { return }
                if let state {
                    finish(.success(state))
                } else {
                    // Schedule only after the previous probe returns. A remote
                    // query may pump the main run loop; probes must not overlap.
                    let next = Timer(timeInterval: 0.1, repeats: false) { [weak self] _ in
                        MainActor.assumeIsolated { self?.poll() }
                    }
                    timer = next
                    RunLoop.main.add(next, forMode: .default)
                }
            } catch {
                finish(.failure(error))
            }
        }

        func finish(_ result: Result<State, Error>) {
            guard active else { return }
            self.result = result
            stop()
            ready.fulfill()
        }

        func stop() {
            active = false
            timer?.invalidate()
            timer = nil
        }
    }
}
