import Foundation
import XCTest

/// One allowance for a positively observed Files navigation state.
/// A missing state remains pending; it never implies that Back is available.
@MainActor
final class FilesNavigationReadiness {
    enum State: Equatable { case targetFolder, localRoot, localEntry, browse, back }
    enum TitleKind { case application, navigationBar, text, button, other }
    struct TitleItem {
        let kind: TitleKind
        let label: String
        let identifier: String

        init(kind: TitleKind, label: String, identifier: String = "") {
            self.kind = kind
            self.label = label
            self.identifier = identifier
        }
    }
    static let navigationBarIdentifier = "FullDocumentManagerViewControllerNavigationBar"
    static let titleSnapshotNodeLimit = 4_096
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired, cancelled, interrupted, alreadyWaiting, invalidAllowance, invalidClock, invalidTitleCount
        case invalidTitleSnapshot
        case invalidSelectionCount, selectionAlreadyStarted

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
            case .invalidTitleSnapshot: "invalid or oversized folder title snapshot"
            case .invalidSelectionCount: "file selection scope count is not zero or one"
            case .selectionAlreadyStarted: "file selection already started"
            }
        }
    }

    private let clock: () -> TimeInterval
    private let end: TimeInterval
    private var lastTime: TimeInterval
    private var failure: Error?
    private var cancelPending: ((Error) -> Void)?
    private var selectionStarted = false
    private var tapConsumed = false

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
        try waitForResult(probe: probe)
    }

    private func waitForResult<Value>(probe: @escaping () throws -> Value?) throws -> Value {
        _ = try remaining()
        guard cancelPending == nil else { throw remember(Failure.alreadyWaiting) }
        let work = PendingProbe(window: self, probe: probe)
        cancelPending = { work.finish(.failure($0)) }
        defer { work.stop(); cancelPending = nil }
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

    /// Capture through a resolver that requires a unique Files bar. Missing or
    /// ambiguous owners remain resolver failures, never an absent title.
    func captureTargetFolderTitleCount<Node>(title: String, uniqueSnapshot: () throws -> Node,
                                             children: (Node) -> [Node],
                                             attributes: (Node) -> TitleItem) throws -> Int {
        let root = try perform(uniqueSnapshot)
        return try targetFolderTitleCount(title: title, root: root,
                                          children: children, attributes: attributes)
    }

    /// Inspect only the captured owner's direct children. A button's nested text
    /// is not another title, and no additional live query is needed here.
    private func targetFolderTitleCount<Node>(title: String, root: Node,
                                              children: (Node) -> [Node],
                                              attributes: (Node) -> TitleItem) throws -> Int {
        let owner = try perform { attributes(root) }
        try perform {
            guard owner.kind == .navigationBar,
                  owner.identifier == Self.navigationBarIdentifier else {
                throw Failure.invalidTitleSnapshot
            }
        }
        let titles = try perform { children(root) }
        try perform {
            guard titles.count < Self.titleSnapshotNodeLimit else {
                throw Failure.invalidTitleSnapshot
            }
        }
        var count = 0
        for node in titles {
            let item = try perform { attributes(node) }
            if (item.kind == .text && item.label == title)
                || (item.kind == .button && item.label == title + ", Actions Menu") {
                count += 1
            }
        }
        return count
    }

    func captureTargetFolderTitleCount(title: String, navigationBars: XCUIElementQuery) throws -> Int {
        // `element` requires one match. Keep its resolution and snapshot inside
        // perform's deadline checks, without a separate remote count query.
        try captureTargetFolderTitleCount(title: title,
            uniqueSnapshot: { () throws -> any XCUIElementSnapshot in try navigationBars.element.snapshot() },
            children: { $0.children }, attributes: { node in
                let kind: TitleKind
                switch node.elementType {
                case .application: kind = .application
                case .navigationBar: kind = .navigationBar
                case .staticText: kind = .text
                case .button: kind = .button
                default: kind = .other
                }
                return TitleItem(kind: kind, label: node.label, identifier: node.identifier)
            })
    }

    /// Observe the folder opened by creation. Its unique exact title proves the
    /// navigation state; no interaction with that title is required.
    func waitForCreatedFolderObservation(titleCount: @escaping () throws -> Int) throws -> Bool {
        let state = try waitForState {
            let count = try self.perform(titleCount)
            guard count == 0 || count == 1 else { throw Failure.invalidTitleCount }
            return count == 1 ? .targetFolder : nil
        }
        return state == .targetFolder
    }

    /// Require current native readiness when the target itself must be interactive.
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

    /// Check each exact typed scope before its descendants. The direct tap is
    /// inside the same active waiter as readiness, with no second generic wait.
    /// Calling this selection again, including from a native callback, fails.
    func waitAndTapFile(pickerCount: @escaping () throws -> Int,
                        folderCount: @escaping () throws -> Int,
                        fileViewCount: @escaping () throws -> Int,
                        fileCount: @escaping () throws -> Int,
                        enabled: @escaping () throws -> Bool,
                        hittable: @escaping () throws -> Bool,
                        tap: @escaping () throws -> Void) throws {
        _ = try remaining()
        guard !selectionStarted else { throw remember(Failure.selectionAlreadyStarted) }
        selectionStarted = true
        let _: Bool = try waitForResult {
            for query in [pickerCount, folderCount, fileViewCount, fileCount] {
                let count = try self.perform(query)
                guard count == 0 || count == 1 else { throw Failure.invalidSelectionCount }
                guard count == 1 else { return nil }
            }
            guard try self.perform(enabled) else { return nil }
            guard try self.perform(hittable) else { return nil }
            guard !self.tapConsumed else { throw Failure.selectionAlreadyStarted }
            self.tapConsumed = true
            try self.perform(tap)
            return true
        }
    }

    func cancel() {
        let error = remember(Failure.cancelled)
        cancelPending?(error)
    }

    private func remember(_ error: Error) -> Error {
        if failure == nil { failure = error }
        return error
    }

    @MainActor
    private final class PendingProbe<Value> {
        let ready = XCTestExpectation(description: "Files navigation state")
        private(set) var result: Result<Value, Error>?
        private let window: FilesNavigationReadiness
        private let probe: () throws -> Value?
        private var active = true
        private var timer: Timer?

        init(window: FilesNavigationReadiness, probe: @escaping () throws -> Value?) {
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

        func finish(_ result: Result<Value, Error>) {
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
