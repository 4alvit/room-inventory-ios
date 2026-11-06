import Foundation
import XCTest

/// One allowance for a positively observed Files navigation state.
/// A missing state remains pending; it never implies that Back is available.
@MainActor
final class FilesNavigationReadiness {
    /// Fixed allowance for system Files-provider observations and action admission.
    /// Generic explicit windows keep their existing deadline and maximum.
    static let systemProviderAllowance: TimeInterval = 30

    enum State: Equatable { case targetFolder, localRoot, localEntry, browse, back }
    enum TitleKind { case application, navigationBar, text, button, other, collectionView, cell, unrelated }
    struct TitleItem {
        let kind: TitleKind
        let label: String
        let identifier: String
        let enabled: Bool

        init(kind: TitleKind, label: String, identifier: String = "", enabled: Bool = true) {
            self.kind = kind
            self.label = label
            self.identifier = identifier
            self.enabled = enabled
        }
    }
    static let navigationBarIdentifier = "FullDocumentManagerViewControllerNavigationBar"
    static let titleSnapshotNodeLimit = 4_096
    static let pickerIdentifier = "Browse View (Picker)"
    static let localStorageRootPrefix = "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: "
    struct SelectionObservation {
        let ownerIdentifier: String
    }
    struct NavigationCaptureDiagnostics {
        var queryAttempts = 0
        var queriesCompleted = 0
        var snapshotAttempts = 0
        var snapshotsCompleted = 0
        var lastQueryDuration: TimeInterval?
        var lastQueryRemainingAtStart: TimeInterval?
        var lastSnapshotDuration: TimeInterval?
        var lastSnapshotRemainingAtStart: TimeInterval?
        var lastPickerCount: Int?
        var lastNodeCount = 0
        var stage = "not_started"
    }
    private(set) var navigationCaptureDiagnostics = NavigationCaptureDiagnostics()
    enum TitleCaptureStage: String {
        case notStarted = "not_started"
        case nativeSnapshot = "native_snapshot"
        case nativeReturned = "native_returned"
        case localValidation = "local_validation"
        case completed
    }
    private(set) var titleCaptureStage = TitleCaptureStage.notStarted
    enum SelectionTarget { case save; case backup(filename: String) }
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired, cancelled, interrupted, alreadyWaiting, invalidAllowance, invalidClock, invalidTitleCount
        case invalidTitleSnapshot
        case invalidSelectionCount, selectionAlreadyStarted
        case invalidSelectionSnapshot
        case invalidNavigationSnapshot, invalidNavigationCount

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
            case .invalidSelectionSnapshot: "invalid or oversized Files selection snapshot"
            case .invalidNavigationSnapshot: "invalid or oversized Files navigation snapshot"
            case .invalidNavigationCount: "Files navigation scope is ambiguous"
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

    /// Resolve all exact matches once and retain their accessibility identities.
    /// Snapshot only the sole bound result; never re-query it by result index.
    /// Query and snapshot are separate operations under the same deadline.
    func captureBoundNavigationState<Element, Node>(folder: String, localTitle: String,
                                                     matchingElements: () throws -> [Element],
                                                     snapshot: (Element) throws -> Node,
                                                     children: (Node) -> [Node],
                                                     attributes: (Node) -> TitleItem) throws -> State? {
        let elements = try perform {
            navigationCaptureDiagnostics.queryAttempts += 1
            navigationCaptureDiagnostics.stage = "query"
            navigationCaptureDiagnostics.lastPickerCount = nil
            navigationCaptureDiagnostics.lastNodeCount = 0
            navigationCaptureDiagnostics.lastQueryDuration = nil
            navigationCaptureDiagnostics.lastSnapshotDuration = nil
            navigationCaptureDiagnostics.lastSnapshotRemainingAtStart = nil
            let started = lastTime
            navigationCaptureDiagnostics.lastQueryRemainingAtStart = end - started
            defer {
                let finished = clock()
                let elapsed = finished - started
                if finished.isFinite, elapsed.isFinite, elapsed >= 0 {
                    navigationCaptureDiagnostics.lastQueryDuration = elapsed
                }
            }
            let matches = try matchingElements()
            navigationCaptureDiagnostics.queriesCompleted += 1
            return matches
        }
        navigationCaptureDiagnostics.lastPickerCount = elements.count
        guard elements.count <= 1 else { throw remember(Failure.invalidNavigationCount) }
        guard let element = elements.first else {
            navigationCaptureDiagnostics.stage = "missing"
            return nil
        }
        let root = try perform {
            navigationCaptureDiagnostics.snapshotAttempts += 1
            navigationCaptureDiagnostics.stage = "snapshot"
            let started = lastTime
            navigationCaptureDiagnostics.lastSnapshotRemainingAtStart = end - started
            defer {
                let finished = clock()
                let elapsed = finished - started
                if finished.isFinite, elapsed.isFinite, elapsed >= 0 {
                    navigationCaptureDiagnostics.lastSnapshotDuration = elapsed
                }
            }
            let captured = try snapshot(element)
            navigationCaptureDiagnostics.snapshotsCompleted += 1
            return captured
        }
        navigationCaptureDiagnostics.stage = "classification"
        // Count and snapshot below are now local values. The classifier retains
        // its exact picker, owner, title and descendant checks.
        let state = try captureNavigationState(folder: folder, localTitle: localTitle,
            pickerCount: { elements.count }, uniqueSnapshot: { root },
            children: children, attributes: { node in
                navigationCaptureDiagnostics.lastNodeCount += 1
                return attributes(node)
            })
        navigationCaptureDiagnostics.stage = state == nil ? "pending" : "ready"
        return state
    }

    /// One immutable picker tree decides the navigation state. Missing owners
    /// are pending; resolver errors propagate. Snapshot readiness never claims
    /// native hittability: navigation actions still use their live tap gates.
    func captureNavigationState<Node>(folder: String, localTitle: String,
                                       pickerCount: () throws -> Int,
                                       uniqueSnapshot: () throws -> Node,
                                       children: (Node) -> [Node],
                                       attributes: (Node) -> TitleItem) throws -> State? {
        let count = try perform(pickerCount)
        guard count == 0 || count == 1 else { throw remember(Failure.invalidNavigationCount) }
        guard count == 1 else { return nil }
        let root = try perform(uniqueSnapshot)
        var pending: [(Node, Int?)] = [(root, nil)]
        var items: [TitleItem] = []
        var parents: [Int?] = []
        while let (node, parent) = pending.popLast() {
            let item = try perform { attributes(node) }
            let descendants = try perform { children(node) }
            try perform {
                guard items.count + pending.count + descendants.count < Self.titleSnapshotNodeLimit else {
                    throw Failure.invalidNavigationSnapshot
                }
            }
            let index = items.count
            items.append(item)
            parents.append(parent)
            pending.append(contentsOf: descendants.reversed().map { ($0, Optional(index)) })
        }
        return try perform {
            guard !folder.isEmpty, !localTitle.isEmpty, folder != localTitle,
                  items.first?.kind == .other,
                  items.first?.identifier == Self.pickerIdentifier else {
                throw Failure.invalidNavigationSnapshot
            }
            func unique(_ matches: [Int]) throws -> Int? {
                guard matches.count <= 1 else { throw Failure.invalidNavigationCount }
                return matches.first
            }
            func below(_ child: Int, _ ancestor: Int) -> Bool {
                var parent = parents[child]
                while let index = parent {
                    if index == ancestor { return true }
                    parent = parents[index]
                }
                return false
            }
            _ = try unique(items.indices.filter {
                items[$0].kind == .other && items[$0].identifier == Self.pickerIdentifier
            })
            let owner = try unique(items.indices.filter {
                items[$0].kind == .other && items[$0].identifier.hasPrefix("DOC.browsingRoot Source: ")
            })
            let bar = try unique(items.indices.filter {
                items[$0].kind == .navigationBar && items[$0].identifier == Self.navigationBarIdentifier
            })
            if let owner {
                guard items[owner].identifier.utf8.count <= 1_024 else { throw Failure.invalidNavigationSnapshot }
            }
            if let owner, let bar, below(bar, owner),
               items[owner].identifier.hasPrefix(Self.localStorageRootPrefix),
               items[owner].identifier.count > Self.localStorageRootPrefix.count {
                func title(_ text: String) throws -> Int? {
                    try unique(items.indices.filter {
                        parents[$0] == bar && ((items[$0].kind == .text && items[$0].label == text)
                            || (items[$0].kind == .button && items[$0].label == text + ", Actions Menu"))
                    })
                }
                let target = try title(folder)
                let local = try title(localTitle)
                guard target == nil || local == nil else { throw Failure.invalidNavigationCount }
                if let target { return items[target].enabled ? .targetFolder : nil }
                if let local { return items[local].enabled ? .localRoot : nil }
            }
            // Only actionable row/button types qualify; nested labels cannot
            // create a second match. The provider title is not a current-folder title.
            var insideBar = Array(repeating: false, count: items.count)
            for index in items.indices {
                if let parent = parents[index] {
                    insideBar[index] = insideBar[parent] || items[parent].kind == .navigationBar
                }
            }
            let entry = try unique(items.indices.filter { candidate in
                (items[candidate].kind == .cell || items[candidate].kind == .button)
                    && (items[candidate].label == localTitle || items[candidate].label.hasPrefix(localTitle + ","))
                    && items[candidate].identifier != "BackButton"
                    && !insideBar[candidate]
            })
            if let entry, items[entry].enabled { return .localEntry }
            let browse = try unique(items.indices.filter {
                items[$0].kind == .button && (items[$0].label == "Browse" || items[$0].identifier == "Browse")
            })
            if let browse, items[browse].enabled { return .browse }
            if let bar {
                let back = try unique(items.indices.filter {
                    parents[$0] == bar && items[$0].kind == .button
                        && ["Back", "Locations", "Browse"].contains(items[$0].label)
                })
                if let back, items[back].enabled { return .back }
            }
            return nil
        }
    }

    func captureNavigationState(folder: String, localTitle: String,
                                 app: XCUIApplication) throws -> State? {
        let pickers = app.otherElements.matching(NSPredicate(format: "identifier == %@", Self.pickerIdentifier))
        return try captureBoundNavigationState(folder: folder, localTitle: localTitle,
            matchingElements: { pickers.allElementsBoundByAccessibilityElement },
            snapshot: { (element: XCUIElement) throws -> any XCUIElementSnapshot in try element.snapshot() },
            children: { $0.children }, attributes: { node in
                let kind: TitleKind
                switch node.elementType {
                case .application: kind = .application
                case .other: kind = .other
                case .navigationBar: kind = .navigationBar
                case .staticText: kind = .text
                case .button: kind = .button
                case .collectionView: kind = .collectionView
                case .cell: kind = .cell
                default: kind = .unrelated
                }
                return TitleItem(kind: kind, label: node.label, identifier: node.identifier,
                                 enabled: node.isEnabled)
            })
    }

    /// Observe the result of one completed filename input. Missing, partial or
    /// wrong values stay pending; only the full exact value can admit Save.
    /// Every fresh native read shares this window's original deadline.
    func waitForFilenameEcho(expected: String,
                             readValue: @escaping () throws -> String?) throws -> String {
        try waitForResult {
            let value = try self.perform(readValue)
            return value == expected ? value : nil
        }
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
        let root = try perform {
            titleCaptureStage = .nativeSnapshot
            let captured = try uniqueSnapshot()
            titleCaptureStage = .nativeReturned
            return captured
        }
        titleCaptureStage = .localValidation
        let count = try targetFolderTitleCount(title: title, root: root,
                                               children: children, attributes: attributes)
        titleCaptureStage = .completed
        return count
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

    /// The browsing-root title can describe the provider entry location rather
    /// than the current folder. Bind current location to the bar's direct title
    /// in one immutable, uniquely resolved remote picker snapshot instead.
    func captureSelection<Node>(folder: String, target: SelectionTarget = .save, uniqueSnapshot: () throws -> Node,
                                  children: (Node) -> [Node],
                                  attributes: (Node) -> TitleItem) throws -> SelectionObservation? {
        let root = try perform(uniqueSnapshot)
        var pending: [(Node, Int?)] = [(root, nil)]
        var items: [TitleItem] = []
        var parents: [Int?] = []
        while let (node, parent) = pending.popLast() {
            let item = try perform { attributes(node) }
            let descendants = try perform { children(node) }
            try perform {
                guard items.count + pending.count + descendants.count < Self.titleSnapshotNodeLimit else {
                    throw Failure.invalidSelectionSnapshot
                }
            }
            let index = items.count
            items.append(item)
            parents.append(parent)
            pending.append(contentsOf: descendants.reversed().map { ($0, Optional(index)) })
        }
        return try perform {
            guard !folder.isEmpty, items.first?.kind == .other,
                  items.first?.identifier == Self.pickerIdentifier else { throw Failure.invalidSelectionSnapshot }
            func unique(_ matches: [Int]) throws -> Int? {
                guard matches.count <= 1 else { throw Failure.invalidSelectionCount }
                return matches.first
            }
            func below(_ child: Int, _ ancestor: Int) -> Bool {
                var parent = parents[child]
                while let index = parent {
                    if index == ancestor { return true }
                    parent = parents[index]
                }
                return false
            }
            _ = try unique(items.indices.filter {
                items[$0].kind == .other && items[$0].identifier == Self.pickerIdentifier
            })
            guard let owner = try unique(items.indices.filter {
                items[$0].kind == .other && items[$0].identifier.hasPrefix("DOC.browsingRoot Source: ")
            }) else { return nil }
            let ownerID = items[owner].identifier
            guard below(owner, 0), ownerID.hasPrefix(Self.localStorageRootPrefix),
                  ownerID.count > Self.localStorageRootPrefix.count,
                  ownerID.utf8.count <= 1_024 else { throw Failure.invalidSelectionSnapshot }
            guard let bar = try unique(items.indices.filter {
                items[$0].kind == .navigationBar && items[$0].identifier == Self.navigationBarIdentifier
            }) else { return nil }
            guard below(bar, owner) else { throw Failure.invalidSelectionSnapshot }
            guard try unique(items.indices.filter {
                parents[$0] == bar && ((items[$0].kind == .text && items[$0].label == folder)
                    || (items[$0].kind == .button && items[$0].label == folder + ", Actions Menu"))
            }) != nil else { return nil }
            switch target {
            case .save:
                guard let save = try unique(items.indices.filter {
                    items[$0].kind == .button && items[$0].identifier == "DOCPicker.actionButton"
                }) else { return nil }
                guard below(save, bar), items[save].label == "Save" else { throw Failure.invalidSelectionSnapshot }
            case let .backup(filename):
                guard filename.hasSuffix(".roominventory"), filename.count > ".roominventory".count else {
                    throw Failure.invalidSelectionSnapshot
                }
                guard let files = try unique(items.indices.filter {
                    items[$0].kind == .collectionView && items[$0].identifier == "File View"
                }) else { return nil }
                guard below(files, owner) else { throw Failure.invalidSelectionSnapshot }
                guard let file = try unique(items.indices.filter {
                    items[$0].kind == .cell && items[$0].identifier == filename + ", roominventory"
                }) else { return nil }
                guard below(file, files) else { throw Failure.invalidSelectionSnapshot }
            }
            return SelectionObservation(ownerIdentifier: ownerID)
        }
    }

    func captureSelection(folder: String, target: SelectionTarget = .save,
                          pickers: XCUIElementQuery) throws -> SelectionObservation? {
        // Callers have already observed positive Files navigation. As with the
        // title-capture adapter, a missing/ambiguous owner's native resolution
        // error is terminal. Missing descendants in a resolved picker remain
        // pending. Do not substitute an app snapshot that can omit remote Files.
        try captureSelection(folder: folder, target: target,
            uniqueSnapshot: { () throws -> any XCUIElementSnapshot in try pickers.element.snapshot() },
            children: { $0.children }, attributes: { node in
                let kind: TitleKind
                switch node.elementType {
                case .other: kind = .other
                case .navigationBar: kind = .navigationBar
                case .staticText: kind = .text
                case .button: kind = .button
                case .collectionView: kind = .collectionView
                case .cell: kind = .cell
                default: kind = .unrelated
                }
                return TitleItem(kind: kind, label: node.label, identifier: node.identifier)
            })
    }

    private func readySelection(observe: () throws -> SelectionObservation?,
                                 enabled: (SelectionObservation) throws -> Bool,
                                 hittable: (SelectionObservation) throws -> Bool) throws -> SelectionObservation? {
        guard let observation = try perform(observe) else { return nil }
        guard try perform({ try enabled(observation) }),
              try perform({ try hittable(observation) }) else { return nil }
        return observation
    }

    func waitForSelection(observe: @escaping () throws -> SelectionObservation?,
                           enabled: @escaping (SelectionObservation) throws -> Bool,
                           hittable: @escaping (SelectionObservation) throws -> Bool) throws -> Bool {
        let _: SelectionObservation = try waitForResult {
            try self.readySelection(observe: observe, enabled: enabled, hittable: hittable)
        }
        return true
    }

    func waitAndTapSelection(observe: @escaping () throws -> SelectionObservation?,
                              enabled: @escaping (SelectionObservation) throws -> Bool,
                              hittable: @escaping (SelectionObservation) throws -> Bool,
                              tap: @escaping (SelectionObservation) throws -> Void) throws {
        _ = try remaining()
        guard !selectionStarted else { throw remember(Failure.selectionAlreadyStarted) }
        selectionStarted = true
        let _: SelectionObservation = try waitForResult {
            guard let observation = try self.readySelection(observe: observe, enabled: enabled, hittable: hittable) else {
                return nil
            }
            guard !self.tapConsumed else { throw Failure.selectionAlreadyStarted }
            self.tapConsumed = true
            try self.perform { try tap(observation) }
            return observation
        }
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
