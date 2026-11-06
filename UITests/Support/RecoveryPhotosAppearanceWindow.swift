import Foundation
import XCTest

/// The system Photos picker can present after its launch tap has returned.
/// Allow cold first presentation within one monotonic, nonrenewable window.
struct RecoveryPhotosAppearanceWindow {
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired, invalidOwnerCount, invalidImageCount, invalidSnapshot

        var description: String {
            switch self {
            case .expired: "Photos appearance deadline expired"
            case .invalidOwnerCount: "Photos content owner is ambiguous"
            case .invalidImageCount: "Photos content has multiple matching images"
            case .invalidSnapshot: "Photos content snapshot is invalid or oversized"
            }
        }
    }

    static let contentIdentifier = "photosView_content_scroll_view"
    static let snapshotNodeLimit = 4_096
    enum ItemKind { case scrollView, image, other }
    struct Item {
        let kind: ItemKind
        let identifier: String
        let label: String
    }
    struct Observation: Equatable {
        let imageCount: Int
        let label: String
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

    func perform<Value>(_ operation: () throws -> Value) throws -> Value {
        _ = try remaining()
        let result = try operation()
        _ = try remaining()
        return result
    }

    /// Resolve one exact Photos content owner, then inspect only its immutable
    /// tree. Count and label come from the same capture, never later live reads.
    func captureObservation<Node>(ownerCount: () throws -> Int,
                                  uniqueSnapshot: () throws -> Node,
                                  children: (Node) -> [Node],
                                  attributes: (Node) -> Item) throws -> Observation? {
        let count = try perform(ownerCount)
        guard count == 0 || count == 1 else { throw Failure.invalidOwnerCount }
        guard count == 1 else { return nil }
        let root = try perform(uniqueSnapshot)
        var pending = [root]
        var visited = 0
        var owners = 0
        var labels: [String] = []
        let photoPredicate = NSPredicate(format: "label BEGINSWITH[c] %@", "Photo,")
        while let node = pending.popLast() {
            let item = try perform { attributes(node) }
            let descendants = try perform { children(node) }
            try perform {
                guard visited + 1 + pending.count + descendants.count <= Self.snapshotNodeLimit,
                      item.identifier.utf8.count <= 1_024, item.label.utf8.count <= 1_024 else {
                    throw Failure.invalidSnapshot
                }
                if visited == 0 {
                    guard item.kind == .scrollView, item.identifier == Self.contentIdentifier else {
                        throw Failure.invalidSnapshot
                    }
                }
                if item.kind == .scrollView, item.identifier == Self.contentIdentifier { owners += 1 }
                guard owners <= 1 else { throw Failure.invalidOwnerCount }
                if item.kind == .image, photoPredicate.evaluate(with: ["label": item.label]) {
                    labels.append(item.label)
                    guard labels.count <= 1 else { throw Failure.invalidImageCount }
                }
            }
            visited += 1
            pending.append(contentsOf: descendants.reversed())
        }
        return try perform {
            labels.first.map { Observation(imageCount: labels.count, label: $0) }
        }
    }

    @MainActor
    func captureObservation(owners: XCUIElementQuery) throws -> Observation? {
        try captureObservation(ownerCount: { owners.count },
            uniqueSnapshot: { () throws -> any XCUIElementSnapshot in try owners.element.snapshot() },
            children: { $0.children }, attributes: { node in
                let kind: ItemKind
                switch node.elementType {
                case .scrollView: kind = .scrollView
                case .image: kind = .image
                default: kind = .other
                }
                return Item(kind: kind, identifier: node.identifier, label: node.label)
            })
    }

    /// Probe inside the active waiter, starting on its first run-loop turn.
    /// Avoid waitForExistence's additional existence check after its timeout.
    /// A native query already in flight may still return after the deadline;
    /// the same postcondition above rejects that result.
    @MainActor
    func waitForProbe(_ probe: @escaping @MainActor () -> Bool) throws -> Bool {
        try waitForObservation { probe() ? true : nil } ?? false
    }

    @MainActor
    func waitForObservation<Value>(_ probe: @escaping @MainActor () throws -> Value?) throws -> Value? {
        let pending = PendingProbe(window: self, probe: probe)
        defer { pending.stop() }
        _ = try remaining()
        RunLoop.main.perform(inModes: [.default]) {
            MainActor.assumeIsolated { pending.poll() }
        }
        let result = XCTWaiter.wait(for: [pending.ready], timeout: try remaining())
        // A native capture error remains primary even if its return is late.
        if case let .failure(error) = pending.result { throw error }
        _ = try remaining()
        guard result == .completed, case let .success(value) = pending.result else { return nil }
        return value
    }

    @MainActor
    private final class PendingProbe<Value> {
        let ready = XCTestExpectation(description: "Photos appearance probe")
        private(set) var result: Result<Value, Error>?
        private let window: RecoveryPhotosAppearanceWindow
        private let probe: @MainActor () throws -> Value?
        private var active = true
        private var timer: Timer?

        init(window: RecoveryPhotosAppearanceWindow, probe: @escaping @MainActor () throws -> Value?) {
            self.window = window
            self.probe = probe
        }

        func poll() {
            guard active, (try? window.remaining()) != nil else { return }
            do {
                let value = try window.perform(probe)
                guard active else { return }
                if let value {
                    finish(.success(value))
                    return
                }
                // Native queries may pump the run loop. Schedule only after
                // this query returns so a second probe cannot overlap it.
                // Give the app and remote Photos service a quiet interval
                // between full accessibility queries during cold presentation.
                // This delay still consumes the original appearance window.
                let next = Timer(timeInterval: 1, repeats: false) { [weak self] _ in
                    MainActor.assumeIsolated { self?.poll() }
                }
                timer = next
                RunLoop.main.add(next, forMode: .default)
            } catch {
                finish(.failure(error))
            }
        }

        private func finish(_ result: Result<Value, Error>) {
            guard active else { return }
            self.result = result
            active = false
            ready.fulfill()
        }

        func stop() {
            active = false
            timer?.invalidate()
            timer = nil
        }
    }
}
