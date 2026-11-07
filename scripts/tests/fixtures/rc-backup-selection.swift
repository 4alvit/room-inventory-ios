// Host regression for the actual RC selection and filename observer bodies. The host validation
// inserts that method at RC_SELECT_BACKUP_BODY, changing only XCUI type names
// to the fixtures below, and renames the unchanged shared helper to Readiness.
// No Simulator, product app, network or private state is involved.
import XCTest

@MainActor
private final class SelectionFixture {
    static var current: SelectionFixture!
    let runID = "D13A8615-B837-4BC1-A532-8D0196B26F6F"
    var now = 0.0
    var realClock = false
    var readinessDepth = 0
    var nativeTapReadinessDepths: [Int] = []
    var afterReservation: (() -> Void)?
    var folderMode = false
    var folderWindows: [TimeInterval] = []
    var folderQueries: [String] = []
    var folderPickerIDs = [701]
    var folderBarsByPicker = [701: [901]]
    var folderBarIdentifiers = [901: "FullDocumentManagerViewControllerNavigationBar"]
    // Direct New Folder is a positive semantic hypothesis, not an extracted AX
    // identity. The retained iPad counterexample is the sidebar More action.
    var folderControls: [Int: [FolderControl]] = [
        701: [.init(id: 801, identifier: "New Folder", label: "New Folder"),
              .init(id: 802, identifier: "SidebarMore", label: "More")],
        901: [.init(id: 803, identifier: "OverflowBarButtonItem", label: "More"),
              .init(id: 805, identifier: "SidebarMore", label: "More")]
    ]
    var folderDisabled = Set<Int>()
    var folderUnhittable = Set<Int>()
    var folderMenuMatches = [804]
    var folderMenuOpen = false
    var folderTapSeconds = 0.0
    var beforeFolderQuery: ((String) -> Void)?
    var beforeFolderEnabled: ((Int) -> Void)?
    var beforeFolderHittable: ((Int) -> Void)?
    var beforeFolderTap: ((Int) -> Void)?
    struct FolderControl {
        let id: Int
        let identifier: String
        let label: String
    }
    func folderQuery(_ scope: String) {
        folderQueries.append(scope); beforeFolderQuery?(scope)
    }
    var presentationMode = false
    var presentationWindows: [TimeInterval] = []
    var shareDiagnostics: [[String: Any]] = []
    var shareMatches = [401]
    var shareIdentifier = "actionGroupCell"
    var shareLabel = "Save to Files"
    var shareResolves = 0
    var shareTapSeconds = 0.0
    var shareEnabled = true
    var shareHittable = true
    var beforeShareResolve: (() -> Void)?
    var beforeShareTap: (() -> Void)?
    var saveIdentifier = "Save"
    var saveCount = 1
    var saveQueries = 0
    var saveEnabled = true
    var saveHittable = true
    var beforeSaveQuery: (() -> Void)?
    var beforeSaveEnabled: (() -> Void)?
    var beforeSaveHittable: (() -> Void)?
    let recordName = "RC Room bounded-transition"
    var recordMatches = [201]
    var recordLabel = "RC Room bounded-transition, 0 items"
    var recordWindows: [TimeInterval] = []
    var recordResolves = 0
    var recordTapSeconds = 0.0
    var beforeRecordResolve: (() -> Void)?
    var beforeRecordTap: (() -> Void)?
    var navigationIdentifier = "RC Room bounded-transition"
    var navigationCount = 1
    var navigationQueries = 0
    var beforeNavigationQuery: (() -> Void)?
    var beforeNavigationEnabled: (() -> Void)?
    var beforeNavigationHittable: (() -> Void)?
    var activeWindow: Readiness?
    var filenamePickerMatches = [0]
    var filenameMatches = [101]
    var filenameValues: [String?] = []
    var filenameReads: [Int] = []
    var filenameQueries = 0
    var filenameWindows: [TimeInterval] = []
    var beforeFilenameQuery: (() -> Void)?
    var beforeFilenameValue: (() -> Void)?
    var snapshots = 0
    var resolves = 0
    var gates: [String] = []
    var taps: [Int] = []
    var confirmations = 0
    var nodes: [Node] = []
    var matches = [1]
    var beforeSnapshot: (() -> Void)?
    var beforeResolve: (() -> Void)?
    var beforeEnabled: (() -> Void)?
    var beforeHittable: (() -> Void)?
    var tapError: Error?
    var nativeErrorTime = 30.0
    var disabledFirst = false
    var pendingExpires = false
    var root: Node { nodes[0] }
    var filename: String { "backup-" + runID + ".roominventory" }
    var folder: String { "RC-" + runID }
    var ownerID = Readiness.localStorageRootPrefix + "On My iPhone"
    var resolvedOwners: [String] = []
    var resolvedFiles: [String] = []
    var uniqueScopes: [String] = []

    struct Node {
        let item: Readiness.TitleItem
        var children: [Node]
        init(_ kind: Readiness.TitleKind, _ label: String = "", id: String = "", children: [Node] = []) {
            item = .init(kind: kind, label: label, identifier: id)
            self.children = children
        }
    }
    func makeTree(title: String? = nil, fileID: String? = nil) {
        let bar = Node(.navigationBar, id: Readiness.navigationBarIdentifier,
                       children: [Node(.button, (title ?? folder) + ", Actions Menu")])
        let file = Node(.cell, "Presentation time and size are not identity",
                        id: fileID ?? filename + ", roominventory")
        let view = Node(.collectionView, id: "File View", children: [file])
        let owner = Node(.other, id: ownerID, children: [bar, view])
        nodes = [Node(.other, id: Readiness.pickerIdentifier, children: [owner])]
    }
}

@MainActor
private final class FixtureElement {
    let f: SelectionFixture
    let scope: String
    let id: Int
    init(_ f: SelectionFixture, _ scope: String, _ id: Int = 0) { self.f=f; self.scope=scope; self.id=id }
    var otherElements: FixtureQuery { .init(f, "owner") }
    var buttons: FixtureFolderQuery { .init(f, "controls", parent: id) }
    var navigationBars: FixtureFolderQuery { .init(f, "bars", parent: id) }
    var collectionViews: FixtureQuery { .init(f, "list") }
    var cells: FixtureQuery { .init(f, "file") }
    var textFields: FixtureQuery { .init(f, "filename") }
    var value: Any? {
        XCTAssertEqual(scope, "filename")
        f.filenameReads.append(id)
        f.beforeFilenameValue?()
        return f.filenameValues.isEmpty ? nil : f.filenameValues.removeFirst()
    }
    var isEnabled: Bool {
        f.gates.append("enabled:\(id)"); f.beforeEnabled?()
        return !(f.disabledFirst && f.resolves == 1)
    }
    var isHittable: Bool { f.gates.append("hittable:\(id)"); f.beforeHittable?(); return true }
    func tap() throws {
        f.taps.append(id)
        if let error=f.tapError { f.now=30; throw error }
    }
}

@MainActor
private final class FixtureQuery {
    let f: SelectionFixture
    let scope: String
    var identifier = ""
    var predicate: NSPredicate?
    func matching(_ predicate: NSPredicate) -> FixtureQuery { self.predicate=predicate; return self }
    func acceptsPicker(_ identifier: String) -> Bool {
        predicate?.evaluate(with: ["identifier": identifier, "label": "", "value": "", "placeholderValue": ""]) == true
    }
    init(_ f: SelectionFixture, _ scope: String) { self.f=f; self.scope=scope }
    func matching(identifier: String) -> FixtureQuery {
        self.identifier=identifier
        if scope == "owner" { f.resolvedOwners.append(identifier) }
        if scope == "file" { f.resolvedFiles.append(identifier) }
        return self
    }
    var element: FixtureElement {
        f.uniqueScopes.append(scope)
        return FixtureElement(f, scope)
    }
    var allElementsBoundByAccessibilityElement: [FixtureElement] {
        if scope == "picker" {
            XCTAssertTrue(acceptsPicker(Readiness.pickerIdentifier))
            XCTAssertFalse(acceptsPicker("not-the-picker"))
            if f.folderMode {
                f.folderQuery("picker")
                return f.folderPickerIDs.map { FixtureElement(f, scope, $0) }
            }
            f.filenameQueries += 1; f.beforeFilenameQuery?()
            return f.filenamePickerMatches.map { FixtureElement(f, scope, $0) }
        }
        if scope == "filename" {
            XCTAssertEqual(identifier, "DOCPicker.filenameTextField")
            return f.filenameMatches.map { FixtureElement(f, scope, $0) }
        }
        f.resolves += 1; f.beforeResolve?()
        return f.matches.map { FixtureElement(f, scope, $0) }
    }
}

@MainActor
private final class FixtureFolderElement {
    let f: SelectionFixture
    let id: Int
    let identifier: String
    let label: String
    init(_ f: SelectionFixture, _ id: Int, identifier: String = "", label: String = "") {
        self.f=f; self.id=id; self.identifier=identifier; self.label=label
    }
    var buttons: FixtureFolderQuery { .init(f, "controls", parent: id) }
    var isEnabled: Bool {
        f.gates.append("enabled:\(id)"); f.beforeFolderEnabled?(id)
        return !f.folderDisabled.contains(id)
    }
    var isHittable: Bool {
        f.gates.append("hittable:\(id)"); f.beforeFolderHittable?(id)
        return !f.folderUnhittable.contains(id)
    }
    func tap() {
        f.nativeTapReadinessDepths.append(f.readinessDepth); f.taps.append(id)
        if identifier == "OverflowBarButtonItem" && label == "More" { f.folderMenuOpen=true }
        f.now += f.folderTapSeconds; f.beforeFolderTap?(id)
    }
}

@MainActor
private final class FixtureFolderQuery {
    let f: SelectionFixture
    let scope: String
    let parent: Int
    var identifier: String?
    var predicate: NSPredicate?
    init(_ f: SelectionFixture, _ scope: String, parent: Int) { self.f=f; self.scope=scope; self.parent=parent }
    func matching(identifier: String) -> FixtureFolderQuery { self.identifier=identifier; return self }
    func matching(_ predicate: NSPredicate) -> FixtureFolderQuery { self.predicate=predicate; return self }
    var allElementsBoundByAccessibilityElement: [FixtureFolderElement] {
        f.folderQuery("\(scope):\(parent)")
        if scope == "bars" {
            return (f.folderBarsByPicker[parent] ?? []).filter { f.folderBarIdentifiers[$0] == identifier }
                .map { FixtureFolderElement(f, $0) }
        }
        XCTAssertEqual(scope, "controls")
        return (f.folderControls[parent] ?? []).filter { item in
            if let identifier { return item.identifier == identifier || item.label == identifier }
            return predicate?.evaluate(with: ["identifier": item.identifier, "label": item.label]) == true
        }.map { FixtureFolderElement(f, $0.id, identifier: $0.identifier, label: $0.label) }
    }
}

@MainActor
private final class FixtureRecordElement {
    let f: SelectionFixture
    let scope: String
    let id: Int
    init(_ f: SelectionFixture, _ scope: String, _ id: Int) { self.f=f; self.scope=scope; self.id=id }
    var isEnabled: Bool {
        if scope == "navigation" { f.beforeNavigationEnabled?() }
        f.beforeEnabled?(); return true
    }
    var isHittable: Bool {
        if scope == "navigation" { f.beforeNavigationHittable?() }
        f.beforeHittable?(); return true
    }
    // Matches XCUIElement.tap's nonthrowing Swift signature. The transport
    // adapter below can inject a native action error after this single event.
    func tap() { f.nativeTapReadinessDepths.append(f.readinessDepth); f.taps.append(id); f.now += f.recordTapSeconds; f.beforeRecordTap?() }
}

@MainActor
private final class FixtureRecordQuery {
    let f: SelectionFixture
    let scope: String
    var identifier = ""
    var predicate: NSPredicate?
    init(_ f: SelectionFixture, _ scope: String) { self.f=f; self.scope=scope }
    func matching(_ predicate: NSPredicate) -> FixtureRecordQuery { self.predicate=predicate; return self }
    func matching(identifier: String) -> FixtureRecordQuery { self.identifier=identifier; return self }
    var allElementsBoundByAccessibilityElement: [FixtureRecordElement] {
        XCTAssertEqual(scope, "record")
        f.recordResolves += 1; f.beforeRecordResolve?()
        guard predicate?.evaluate(with: ["label": f.recordLabel]) == true else { return [] }
        return f.recordMatches.map { FixtureRecordElement(f, scope, $0) }
    }
    var count: Int {
        XCTAssertEqual(scope, "navigation")
        f.navigationQueries += 1; f.beforeNavigationQuery?()
        return identifier == f.navigationIdentifier ? f.navigationCount : 0
    }
    var firstMatch: FixtureRecordElement { .init(f, scope, 301) }
}

@MainActor
private final class FixturePresentationElement {
    let f: SelectionFixture
    let scope: String
    let id: Int
    init(_ f: SelectionFixture, _ scope: String, _ id: Int) { self.f=f; self.scope=scope; self.id=id }
    var isEnabled: Bool {
        if scope == "folder-menu" { f.gates.append("enabled:\(id)"); f.beforeFolderEnabled?(id); return !f.folderDisabled.contains(id) }
        if scope == "save" { f.beforeSaveEnabled?(); return f.saveEnabled }
        f.beforeEnabled?(); return f.shareEnabled
    }
    var isHittable: Bool {
        if scope == "folder-menu" { f.gates.append("hittable:\(id)"); f.beforeFolderHittable?(id); return !f.folderUnhittable.contains(id) }
        if scope == "save" { f.beforeSaveHittable?(); return f.saveHittable }
        f.beforeHittable?(); return f.shareHittable
    }
    func tap() {
        f.nativeTapReadinessDepths.append(f.readinessDepth); f.taps.append(id)
        if scope == "folder-menu" { f.now += f.folderTapSeconds; f.beforeFolderTap?(id) }
        else { f.now += f.shareTapSeconds; f.beforeShareTap?() }
    }
}

@MainActor
private final class FixturePresentationQuery {
    let f: SelectionFixture
    let scope: String
    var identifier = ""
    var predicate: NSPredicate?
    init(_ f: SelectionFixture, _ scope: String) { self.f=f; self.scope=scope }
    func matching(_ predicate: NSPredicate) -> FixturePresentationQuery { self.predicate=predicate; return self }
    var allElementsBoundByAccessibilityElement: [FixturePresentationElement] {
        if scope == "folder-menu" {
            XCTAssertEqual(identifier, "New Folder"); f.folderQuery("menu")
            return (f.folderMenuOpen ? f.folderMenuMatches : []).map { FixturePresentationElement(f, scope, $0) }
        }
        XCTAssertEqual(scope, "share")
        f.shareResolves += 1; f.beforeShareResolve?()
        guard predicate?.evaluate(with: ["identifier": f.shareIdentifier, "label": f.shareLabel]) == true else { return [] }
        return f.shareMatches.map { FixturePresentationElement(f, scope, $0) }
    }
    var count: Int {
        XCTAssertEqual(scope, "save")
        f.saveQueries += 1; f.beforeSaveQuery?()
        return identifier == f.saveIdentifier ? f.saveCount : 0
    }
    var firstMatch: FixturePresentationElement { .init(f, scope, 501) }
}

@MainActor
private final class FixtureButtonQueries {
    let f: SelectionFixture
    init(_ f: SelectionFixture) { self.f=f }
    func matching(_ predicate: NSPredicate) -> FixtureRecordQuery { FixtureRecordQuery(f, "record").matching(predicate) }
    func matching(identifier: String) -> FixturePresentationQuery {
        let q=FixturePresentationQuery(f, f.folderMode ? "folder-menu" : "save"); q.identifier=identifier; return q
    }
}

@MainActor
private final class FixtureApp {
    let f: SelectionFixture
    init(_ f: SelectionFixture) { self.f=f }
    var otherElements: FixtureQuery { .init(f, "picker") }
    var buttons: FixtureButtonQueries { .init(f) }
    var cells: FixturePresentationQuery { .init(f, "share") }
    var navigationBars: FixtureRecordQuery { .init(f, "navigation") }
    var alerts: FixtureQuery { .init(f, "alert") }
}

// Only native query/snapshot transport is replaced. The classifier, deadlines,
// native-error precedence and active single-action waiter are the real helper.
@MainActor
private final class FilesNavigationReadiness {
    typealias Failure = Readiness.Failure
    typealias SelectionObservation = Readiness.SelectionObservation
    typealias SelectionTarget = Readiness.SelectionTarget
    static var systemProviderAllowance: TimeInterval { Readiness.systemProviderAllowance }
    static var pickerIdentifier: String { Readiness.pickerIdentifier }
    static var navigationBarIdentifier: String { Readiness.navigationBarIdentifier }
    let native: Readiness
    let f: SelectionFixture
    init(timeout: TimeInterval) {
        f=SelectionFixture.current!
        let clock=f
        native=Readiness(timeout: timeout, clock: { clock.realClock ? ProcessInfo.processInfo.systemUptime : clock.now })
        f.activeWindow=native
        if f.presentationMode { f.presentationWindows.append(timeout) }
        if f.folderMode { f.folderWindows.append(timeout) }
    }
    private init(recordWindow: Readiness, fixture: SelectionFixture) {
        native=recordWindow; f=fixture; f.activeWindow=native
        f.recordWindows.append(40)
    }
    static func recordTransition() -> FilesNavigationReadiness {
        let f=SelectionFixture.current!
        return FilesNavigationReadiness(recordWindow: Readiness.recordTransition(
            clock: { f.realClock ? ProcessInfo.processInfo.systemUptime : f.now }), fixture: f)
    }
    func perform<T>(_ op: () throws -> T) throws -> T {
        try native.perform {
            let before=self.f.taps.count
            let value=try op()
            if self.f.taps.count > before, let error=self.f.tapError { self.f.now=self.f.nativeErrorTime; throw error }
            return value
        }
    }
    func waitAndTapBoundElement<Element>(matchingElements: @escaping () throws -> [Element],
        enabled: @escaping (Element) throws -> Bool, hittable: @escaping (Element) throws -> Bool,
        tap: @escaping (Element) throws -> Void) throws {
        f.readinessDepth += 1
        do {
            try native.waitAndTapBoundElement(matchingElements: matchingElements, enabled: enabled, hittable: hittable, tap: { element in
                let before=self.f.taps.count
                try tap(element)
                // Old-path A/B transport only: a reservation is not a native tap.
                if self.f.taps.count > before, let error=self.f.tapError { self.f.now=self.f.nativeErrorTime; throw error }
            })
        } catch { f.readinessDepth -= 1; throw error }
        f.readinessDepth -= 1
        f.afterReservation?()
    }
    func waitForTargetFolder(titleCount: @escaping () throws -> Int,
        enabled: @escaping () throws -> Bool, hittable: @escaping () throws -> Bool) throws -> Bool {
        try native.waitForTargetFolder(titleCount: titleCount, enabled: enabled, hittable: hittable)
    }
    func waitForFilenameEcho(expected: String, readValue: @escaping () throws -> String?) throws -> String {
        f.filenameWindows.append(Self.systemProviderAllowance)
        return try native.waitForFilenameEcho(expected: expected, readValue: readValue)
    }
    func captureSelection(folder: String, target: SelectionTarget, pickers: FixtureQuery) throws -> SelectionObservation? {
        f.snapshots += 1
        let result = try native.captureSelection(folder: folder, target: target, uniqueSnapshot: {
            self.f.beforeSnapshot?()
            guard pickers.acceptsPicker(self.f.root.item.identifier) else {
                throw Readiness.Failure.invalidSelectionSnapshot
            }
            return self.f.root
        }, children: { $0.children }, attributes: { $0.item })
        if result == nil && f.pendingExpires { f.now = 31 }
        return result
    }
    func waitAndTapSelection(observe: @escaping () throws -> SelectionObservation?,
                             enabled: @escaping (SelectionObservation) throws -> Bool,
                             hittable: @escaping (SelectionObservation) throws -> Bool,
                             tap: @escaping (SelectionObservation) throws -> Void) throws {
        try native.waitAndTapSelection(observe: observe, enabled: enabled, hittable: hittable, tap: tap)
    }
}

@MainActor
private enum FixtureShareDiagnostic {
    static var uptime: TimeInterval { SelectionFixture.current.now }
    static func emit(_ text: String) {
        XCTAssertLessThanOrEqual(text.utf8.count, 4_096)
        let record = try! JSONSerialization.jsonObject(with: Data(text.utf8)) as! [String: Any]
        SelectionFixture.current.shareDiagnostics.append(record)
    }
}

@MainActor
private final class RCBody {
    let runID: String
    init(_ f: SelectionFixture) { runID=f.runID }
    func select(_ label: String, _ app: FixtureApp) throws { XCTAssertEqual(label, "Restore a backup") }
    func folder(_ create: Bool, _ app: FixtureApp) throws { XCTAssertFalse(create) }
    func ready(_ query: FixtureQuery) throws {
        XCTAssertEqual(query.scope, "alert")
        XCTAssertEqual(query.identifier, "Replace the current inventory?")
        query.f.confirmations += 1
    }
    // RC_SELECT_BACKUP_BODY
    // RC_FILENAME_ECHO_BODY
    // RC_OPEN_RECORD_BODY
    // RC_EXPORT_DESTINATION_BODY
    // RC_BOUND_ACTION_BODY
    // RC_FOLDER_CREATION_BODY
    func create(_ f: SelectionFixture, pad: Bool) throws { f.folderMode=true; try beginFolderCreation(FixtureApp(f), isPad: pad) }
    func bound(_ f: SelectionFixture, _ window: FilesNavigationReadiness, action: @escaping (Int) throws -> Void) throws {
        try performBoundTap(window, matchingElements: { f.recordResolves += 1; return f.recordMatches },
            enabled: { _ in f.beforeEnabled?(); return true }, hittable: { _ in f.beforeHittable?(); return true },
            tap: { identity in f.nativeTapReadinessDepths.append(f.readinessDepth); f.taps.append(identity); try action(identity) })
    }
    func present(_ f: SelectionFixture) throws { f.presentationMode=true; try openExportDestination(FixtureApp(f)) }
    func open(_ f: SelectionFixture) throws { try openRecord(f.recordName, FixtureApp(f)) }
    func echo(_ f: SelectionFixture, _ expected: String) throws -> String {
        try observeExportedFilename(expected, FixtureApp(f))
    }
    func run(_ f: SelectionFixture) throws { try selectBackup(FixtureApp(f)) }
}

// Minimal transports for the exact native constructors and success/catch tail.
private final class PredicateQuery {
    var predicate: NSPredicate!
    func matching(_ value: NSPredicate) -> PredicateQuery { predicate=value; return self }
    func matches(_ nodes: [[String: String]]) -> [[String: String]] { nodes.filter { predicate.evaluate(with: $0) } }
}
private struct PredicateApp { var otherElements: PredicateQuery { PredicateQuery() } }
@MainActor
private enum PickerConstructors {
    static func make() -> [PredicateQuery] {
        let app=PredicateApp()
        return [
    // PICKER_CONSTRUCTORS
        ]
    }
}
@MainActor
private final class FixtureSampleOutput {
    static let standardOutput=FixtureSampleOutput()
    var writes: [Data]=[]
    func write(contentsOf data: Data) throws { writes.append(data) }
}
@MainActor
private final class FailureJournalBody {
    enum FixtureError: Error { case original, journal, capture }
    let runID="D13A8615-B837-4BC1-A532-8D0196B26F6F"
    let app=0
    let file: URL
    var events: [String]=[]
    var journalError=false
    var captureError=false
    var duringCapture: (() throws -> Void)?
    init(_ file: URL) { self.file=file }
    func journal(status: String, failure: String? = nil) throws {
        events.append("journal:"+status)
        if journalError { throw FixtureError.journal }
        try Data((status+":"+(failure ?? "")).utf8).write(to: file)
    }
    func capture(_ name: String, _ app: Int) throws {
        events.append("capture:"+name)
        try duringCapture?()
        if captureError { throw FixtureError.capture }
    }
    func run(_ operation: () throws -> Void) throws {
        do {
            try operation()
    // RC_FAILURE_JOURNAL_TAIL
    }
}

final class RCBackupSelectionRegressionTests: XCTestCase {
    @MainActor
    private func fixture() -> SelectionFixture {
        let f=SelectionFixture(); f.makeTree(); SelectionFixture.current=f; return f
    }
    @MainActor
    private func fails(_ f: SelectionFixture, _ expected: Readiness.Failure) {
        XCTAssertThrowsError(try RCBody(f).run(f)) { XCTAssertEqual($0 as? Readiness.Failure, expected) }
        XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.confirmations, 0)
    }
    @MainActor
    func testRetainedStaleProviderTitleUsesCurrentFolderAndExactFile() throws {
        let f=fixture(); try RCBody(f).run(f)
        XCTAssertEqual(f.resolvedOwners, [Readiness.localStorageRootPrefix + "On My iPhone"])
        XCTAssertEqual(f.resolvedFiles, [f.filename + ", roominventory"])
        XCTAssertEqual(f.uniqueScopes, ["picker", "owner", "list"])
        XCTAssertEqual(f.resolves, 1); XCTAssertEqual(f.snapshots, 1)
        XCTAssertEqual(f.gates, ["enabled:1", "hittable:1"])
        XCTAssertEqual(f.taps, [1]); XCTAssertEqual(f.confirmations, 1)
    }
    @MainActor
    func testCurrentProviderTitleAlsoWorks() throws {
        let f=fixture(); f.ownerID=Readiness.localStorageRootPrefix+f.folder; f.makeTree()
        try RCBody(f).run(f); XCTAssertEqual(f.taps, [1])
    }
    @MainActor
    func testWrongFolderNeverResolvesOrTapsAnOtherwiseExactFile() {
        let f=fixture(); f.makeTree(title: "Other folder"); f.pendingExpires=true
        fails(f, .expired); XCTAssertEqual(f.resolves, 0)
    }
    @MainActor
    func testWrongOrPartialFilenameNeverAdmitsLiveLookup() {
        for suffix in [".zip", "", ", other"] {
            let f=fixture(); f.makeTree(fileID: f.filename+suffix); f.pendingExpires=true
            fails(f, .expired); XCTAssertEqual(f.resolves, 0)
        }
    }
    @MainActor
    func testDuplicateOwnersViewsOrExactFilesAreTerminal() {
        for scope in 0..<3 {
            let f=fixture()
            if scope == 0 { f.nodes[0].children.append(f.nodes[0].children[0]) }
            if scope == 1 { f.nodes[0].children[0].children.append(f.nodes[0].children[0].children[1]) }
            if scope == 2 { f.nodes[0].children[0].children[1].children.append(f.nodes[0].children[0].children[1].children[0]) }
            fails(f, .invalidSelectionCount); XCTAssertEqual(f.resolves, 0)
        }
    }
    @MainActor
    func testFileOutsideObservedOwnerCannotAuthorizeTap() {
        let f=fixture(); let view=f.nodes[0].children[0].children.removeLast()
        f.nodes[0].children.append(view); fails(f, .invalidSelectionSnapshot)
        XCTAssertEqual(f.resolves, 0)
    }
    @MainActor
    func testForeignProviderCannotAuthorizeTap() {
        let f=fixture(); f.ownerID="DOC.browsingRoot Source: other, Title: On My iPhone"; f.makeTree()
        fails(f, .invalidSelectionSnapshot); XCTAssertEqual(f.resolves, 0)
    }
    @MainActor
    func testAmbiguousLiveFileDoesNotUseFirstMatch() {
        let f=fixture(); f.matches=[1,2]; fails(f, .invalidSelectionCount)
        XCTAssertEqual(f.resolves, 1); XCTAssertTrue(f.gates.isEmpty)
    }
    @MainActor
    func testUnreadyProbeRefreshesIdentityBeforeSecondTapAdmission() throws {
        let f=fixture(); f.disabledFirst=true
        f.beforeResolve={ f.matches=f.resolves == 1 ? [1] : [2] }
        try RCBody(f).run(f)
        XCTAssertEqual(f.resolves, 2); XCTAssertEqual(f.snapshots, 2)
        XCTAssertEqual(f.gates, ["enabled:1", "enabled:2", "hittable:2"])
        XCTAssertEqual(f.taps, [2])
    }
    @MainActor
    func testMissingLiveFileCannotReusePreviousDisabledIdentity() {
        let f=fixture(); f.disabledFirst=true
        f.beforeResolve={ if f.resolves == 2 { f.matches=[]; f.now=29.9 } }
        f.beforeSnapshot={ if f.snapshots == 3 { f.now=30 } }
        fails(f, .expired)
        XCTAssertEqual(f.gates, ["enabled:1"]); XCTAssertEqual(f.resolves, 2)
    }
    @MainActor
    func testBoundFileSurvivesChangedResolverWithoutASecondLookup() throws {
        let f=fixture(); f.beforeEnabled={ f.matches=[2] }
        try RCBody(f).run(f)
        XCTAssertEqual(f.resolves, 1); XCTAssertEqual(f.gates, ["enabled:1", "hittable:1"])
        XCTAssertEqual(f.taps, [1])
    }
    @MainActor
    func testLateSnapshotOrLookupCannotReachAnyGate() {
        for step in 0..<2 {
            let f=fixture()
            if step == 0 { f.beforeSnapshot={f.now=30} } else { f.beforeResolve={f.now=30} }
            fails(f, .expired); XCTAssertTrue(f.gates.isEmpty)
        }
    }
    @MainActor
    func testLateEnabledOrHittableCannotTap() {
        for step in 0..<2 {
            let f=fixture()
            if step == 0 { f.beforeEnabled={f.now=30} } else { f.beforeHittable={f.now=30} }
            fails(f, .expired)
        }
    }
    @MainActor
    func testNativeTapErrorIsNotRetriedOrReplacedWithTimeout() {
        enum NativeError: Error { case expected }
        let f=fixture(); f.tapError=NativeError.expected
        XCTAssertThrowsError(try RCBody(f).run(f)) { XCTAssertTrue($0 is NativeError) }
        XCTAssertEqual(f.taps, [1]); XCTAssertEqual(f.resolves, 1); XCTAssertEqual(f.confirmations, 0)
    }
    @MainActor
    func testFilenameImmediateExactEchoUsesOneUniqueBoundRead() throws {
        let f=fixture(); f.filenameValues=["csv-"+f.runID]
        XCTAssertEqual(try RCBody(f).echo(f, "csv-"+f.runID), "csv-"+f.runID)
        XCTAssertEqual(f.filenameQueries, 1); XCTAssertEqual(f.filenameReads, [101])
        XCTAssertEqual(f.filenameWindows, [30]); XCTAssertTrue(f.taps.isEmpty)
    }
    @MainActor
    func testFilenameMissingPartialThenExactEchoRefreshesTheFieldWithoutAction() throws {
        let f=fixture(); let expected="csv-"+f.runID
        f.filenameValues=["csv-", expected]
        f.beforeFilenameQuery={
            f.now += 1
            f.filenameMatches=f.filenameQueries == 1 ? [] : [100+f.filenameQueries]
        }
        XCTAssertEqual(try RCBody(f).echo(f, expected), expected)
        XCTAssertEqual(f.filenameQueries, 3); XCTAssertEqual(f.filenameReads, [102,103])
        XCTAssertEqual(f.filenameWindows, [30]); XCTAssertTrue(f.taps.isEmpty)
    }
    @MainActor
    func testFilenameWrongOrPartialEchoNeverRenewsOrReturnsSuccess() {
        for value in ["csv-", "wrong", "csv-"+fixture().runID+".csv"] {
            let f=fixture(); f.filenameValues=[value, value]
            f.beforeFilenameValue={f.now += 15}
            XCTAssertThrowsError(try RCBody(f).echo(f, "csv-"+f.runID)) {
                XCTAssertEqual($0 as? Readiness.Failure, .expired)
            }
            XCTAssertEqual(f.filenameReads.count, 2); XCTAssertEqual(f.filenameWindows, [30])
            XCTAssertTrue(f.taps.isEmpty)
        }
    }
    @MainActor
    func testFilenameExactValueReturnedAtDeadlineFails() {
        let f=fixture(); f.filenameValues=["csv-"+f.runID]
        f.beforeFilenameValue={f.now=30}
        XCTAssertThrowsError(try RCBody(f).echo(f, "csv-"+f.runID)) {
            XCTAssertEqual($0 as? Readiness.Failure, .expired)
        }
        XCTAssertEqual(f.filenameQueries, 1); XCTAssertEqual(f.filenameReads, [101])
        XCTAssertTrue(f.taps.isEmpty)
    }
    @MainActor
    func testFilenameDuplicatePickerOrFieldIsTerminalWithoutReadingOrActions() {
        for picker in [true,false] {
            let f=fixture()
            if picker { f.filenamePickerMatches=[0,1] } else { f.filenameMatches=[101,102] }
            XCTAssertThrowsError(try RCBody(f).echo(f, "csv-"+f.runID)) {
                XCTAssertEqual($0 as? Readiness.Failure, .invalidSelectionCount)
            }
            XCTAssertTrue(f.filenameReads.isEmpty); XCTAssertEqual(f.filenameQueries, 1)
            XCTAssertTrue(f.taps.isEmpty)
        }
    }
    @MainActor
    func testFilenameMissingPickerRemainsPendingWithinSameWindow() throws {
        let f=fixture(); f.filenameValues=["csv-"+f.runID]
        f.beforeFilenameQuery={
            f.now += 1; f.filenamePickerMatches=f.filenameQueries == 1 ? [] : [0]
        }
        XCTAssertEqual(try RCBody(f).echo(f, "csv-"+f.runID), "csv-"+f.runID)
        XCTAssertEqual(f.filenameQueries, 2); XCTAssertEqual(f.filenameReads, [101])
        XCTAssertEqual(f.filenameWindows, [30]); XCTAssertTrue(f.taps.isEmpty)
    }
    @MainActor
    func testFilenameNilValueRemainsPendingThenUsesFreshIdentity() throws {
        let f=fixture(); f.filenameValues=[nil,"csv-"+f.runID]
        f.beforeFilenameQuery={f.filenameMatches=[100+f.filenameQueries]}
        XCTAssertEqual(try RCBody(f).echo(f, "csv-"+f.runID), "csv-"+f.runID)
        XCTAssertEqual(f.filenameReads, [101,102]); XCTAssertEqual(f.filenameWindows, [30])
        XCTAssertTrue(f.taps.isEmpty)
    }
    @MainActor
    func testFilenameLatePickerLookupCannotReadOrStartAnotherProbe() {
        let f=fixture(); f.beforeFilenameQuery={f.now=30;f.filenamePickerMatches=[]}
        XCTAssertThrowsError(try RCBody(f).echo(f, "csv-"+f.runID)) {
            XCTAssertEqual($0 as? Readiness.Failure, .expired)
        }
        XCTAssertEqual(f.filenameQueries, 1); XCTAssertTrue(f.filenameReads.isEmpty)
        XCTAssertEqual(f.filenameWindows, [30]); XCTAssertTrue(f.taps.isEmpty)
    }

    @MainActor
    func testGenericAllowanceStillRejectsMoreThanThirtySeconds() throws {
        let f=fixture()
        XCTAssertEqual(try Readiness(timeout: 30, clock: { f.now }).remaining(), 30)
        for timeout in [30.001, 40, 0, -1, Double.infinity, Double.nan] {
            let window=Readiness(timeout: timeout, clock: { f.now })
            XCTAssertThrowsError(try window.remaining()) {
                XCTAssertEqual($0 as? Readiness.Failure, .invalidAllowance)
            }
        }
        XCTAssertEqual(Readiness.systemProviderAllowance, 30)
    }
    @MainActor
    func testRecordFactoryKeepsOneAbsoluteFortySecondDeadline() throws {
        let f=fixture(); f.now=100
        let window=Readiness.recordTransition(clock: { f.now })
        XCTAssertEqual(try window.remaining(), 40)
        f.now=139.999; XCTAssertEqual(try window.remaining(), 0.001, accuracy: 0.00001)
        f.now=140
        XCTAssertThrowsError(try window.remaining()) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        f.now=141
        XCTAssertThrowsError(try window.remaining()) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
    }
    @MainActor
    func testRecordFactoryRejectsInvalidAndBackwardClocks() throws {
        let f=fixture()
        for now in [Double.nan, Double.infinity] {
            let window=Readiness.recordTransition(clock: { now })
            XCTAssertThrowsError(try window.remaining()) { XCTAssertEqual($0 as? Readiness.Failure, .invalidClock) }
        }
        f.now=100; let window=Readiness.recordTransition(clock: { f.now }); f.now=99
        XCTAssertThrowsError(try window.remaining()) { XCTAssertEqual($0 as? Readiness.Failure, .invalidClock) }
    }
    @MainActor
    func testRecordMeasuredNativeTapUsesRemainingExplicitAllowance() throws {
        let f=fixture(); f.recordTapSeconds=30.5; f.beforeNavigationQuery={f.now += 8.5}
        try RCBody(f).open(f)
        XCTAssertEqual(f.recordWindows, [40]); XCTAssertEqual(f.now, 39, accuracy: 0.00001)
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.navigationQueries, 1)
    }
    @MainActor
    func testRecordBoundIdentitySurvivesResolverChangeAndTapsOnce() throws {
        let f=fixture(); f.beforeEnabled={f.recordMatches=[202]}
        try RCBody(f).open(f)
        XCTAssertEqual(f.recordResolves, 1); XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.recordWindows, [40])
    }
    @MainActor
    func testRecordAmbiguousRowNeverTapsOrChecksDestination() {
        let f=fixture(); f.recordMatches=[201,202]
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .invalidSelectionCount) }
        XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.navigationQueries, 0)
    }
    @MainActor
    func testRecordLateRowObservationCannotTap() {
        let f=fixture(); f.beforeRecordResolve={f.now=40}
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.navigationQueries, 0)
    }
    @MainActor
    func testRecordLateNativeTapCannotStartDestinationProbe() {
        let f=fixture(); f.recordTapSeconds=40
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.navigationQueries, 0)
    }
    @MainActor
    func testRecordDestinationUsesRemainingDeadlineWithoutRenewal() {
        let f=fixture(); f.recordTapSeconds=39; f.beforeNavigationQuery={f.now += 0.6}
        f.beforeNavigationEnabled={f.now += 0.3}; f.beforeNavigationHittable={f.now += 0.2}
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertEqual(f.recordWindows, [40]); XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.navigationQueries, 1)
    }
    @MainActor
    func testRecordWrongOrMissingDestinationNeverRenewsOrRetaps() {
        for wrong in [true,false] {
            let f=fixture(); f.recordTapSeconds=30.5
            if wrong { f.navigationIdentifier="Wrong room" } else { f.navigationCount=0 }
            f.beforeNavigationQuery={f.now += 5}
            XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
            XCTAssertEqual(f.recordWindows, [40]); XCTAssertEqual(f.taps, [201])
        }
    }
    @MainActor
    func testRecordDuplicateDestinationFailsAfterOnlyOneTap() {
        let f=fixture(); f.navigationCount=2
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .invalidTitleCount) }
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.navigationQueries, 1)
    }
    @MainActor
    func testRecordNativeErrorRemainsPrimaryEvenWhenItReturnsLate() {
        enum NativeError: Error { case expected }
        let f=fixture(); f.tapError=NativeError.expected; f.nativeErrorTime=40.1
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertTrue($0 is NativeError) }
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.navigationQueries, 0)
    }
    @MainActor
    func testRecordCancellationAfterTapCannotReachDestination() {
        let f=fixture(); f.beforeRecordTap={f.activeWindow?.cancel()}
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .cancelled) }
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.navigationQueries, 0)
    }

    @MainActor
    func testShareDelayedPresentationUsesOneProviderWindowAndBoundAction() throws {
        let f=fixture(); f.beforeShareResolve={
            f.now += 6; f.shareMatches=f.shareResolves == 1 ? [] : [402]
        }; f.shareTapSeconds=0.4; f.beforeSaveQuery={f.now += 0.4}
        try RCBody(f).present(f)
        XCTAssertEqual(f.presentationWindows, [30]); XCTAssertEqual(f.now, 12.8, accuracy: 0.00001)
        XCTAssertEqual(f.shareResolves, 2); XCTAssertEqual(f.taps, [402]); XCTAssertEqual(f.saveQueries, 1)
    }
    @MainActor
    func testShareBoundIdentityIsNotReplacedBeforeItsSingleTap() throws {
        let f=fixture(); f.beforeEnabled={f.shareMatches=[402]}
        try RCBody(f).present(f)
        XCTAssertEqual(f.shareResolves, 1); XCTAssertEqual(f.taps, [401]); XCTAssertEqual(f.presentationWindows, [30])
    }
    @MainActor
    func testShareWrongExactIdentifierOrLabelNeverTaps() {
        for wrongIdentifier in [true,false] {
            let f=fixture(); if wrongIdentifier { f.shareIdentifier="other" } else { f.shareLabel="Save elsewhere" }
            f.beforeShareResolve={f.now += 15}
            XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
            XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.saveQueries, 0); XCTAssertEqual(f.presentationWindows, [30])
        }
    }
    @MainActor
    func testShareDuplicateActionsNeverTapOrProbeSave() {
        let f=fixture(); f.shareMatches=[401,402]
        XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertEqual($0 as? Readiness.Failure, .invalidSelectionCount) }
        XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.saveQueries, 0)
    }
    @MainActor
    func testShareLateQueryCannotTap() {
        let f=fixture(); f.beforeShareResolve={f.now=30}
        XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.saveQueries, 0)
    }
    @MainActor
    func testShareLateTapCannotProbeSave() {
        let f=fixture(); f.shareTapSeconds=30
        XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertEqual(f.taps, [401]); XCTAssertEqual(f.saveQueries, 0)
    }
    @MainActor
    func testShareSaveReadinessDebitsRemainingOriginalWindow() {
        let f=fixture(); f.shareTapSeconds=29; f.beforeSaveQuery={f.now += 0.6}
        f.beforeSaveEnabled={f.now += 0.3}; f.beforeSaveHittable={f.now += 0.2}
        XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertEqual(f.taps, [401]); XCTAssertEqual(f.saveQueries, 1); XCTAssertEqual(f.presentationWindows, [30])
    }
    @MainActor
    func testShareMissingWrongOrDuplicateSaveIsNotSuccessOrAnotherTap() {
        for mode in 0..<3 {
            let f=fixture()
            if mode == 0 { f.saveCount=0 } else if mode == 1 { f.saveIdentifier="Other" } else { f.saveCount=2 }
            f.beforeSaveQuery={f.now += 15}
            XCTAssertThrowsError(try RCBody(f).present(f)) {
                XCTAssertEqual($0 as? Readiness.Failure, mode == 2 ? .invalidTitleCount : .expired)
            }
            XCTAssertEqual(f.taps, [401]); XCTAssertEqual(f.presentationWindows, [30])
        }
    }
    @MainActor
    func testShareSaveMustBecomeEnabledAndHittableWithoutRetapping() throws {
        let f=fixture(); f.beforeSaveQuery={
            f.now += 1; f.saveEnabled=f.saveQueries >= 2; f.saveHittable=f.saveQueries >= 3
        }
        try RCBody(f).present(f)
        XCTAssertEqual(f.taps, [401]); XCTAssertEqual(f.saveQueries, 3); XCTAssertEqual(f.presentationWindows, [30])
    }
    @MainActor
    func testShareNativeErrorRemainsPrimaryWhenLate() {
        enum NativeError: Error { case expected }
        let f=fixture(); f.tapError=NativeError.expected
        XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertTrue($0 is NativeError) }
        XCTAssertEqual(f.taps, [401]); XCTAssertEqual(f.saveQueries, 0)
    }
    @MainActor
    func testShareCancellationAfterTapCannotProbeSave() {
        let f=fixture(); f.beforeShareTap={f.activeWindow?.cancel()}
        XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertEqual($0 as? Readiness.Failure, .cancelled) }
        XCTAssertEqual(f.taps, [401]); XCTAssertEqual(f.saveQueries, 0)
    }

    @MainActor
    func testShareDisabledOrUnhittableActionRemainsUntappedUntilFreshReadyProbe() throws {
        let f=fixture(); f.beforeShareResolve={
            f.now += 5; f.shareEnabled=f.shareResolves >= 2; f.shareHittable=f.shareResolves >= 3
            f.shareMatches=[400+f.shareResolves]
            XCTAssertTrue(f.taps.isEmpty)
        }
        try RCBody(f).present(f)
        XCTAssertEqual(f.shareResolves, 3); XCTAssertEqual(f.taps, [403]); XCTAssertEqual(f.presentationWindows, [30])
    }
    @MainActor
    func testShareLateEnabledOrHittableCannotTap() {
        for enabled in [true,false] {
            let f=fixture()
            if enabled { f.beforeEnabled={f.now=30} } else { f.beforeHittable={f.now=30} }
            XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
            XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.saveQueries, 0)
        }
    }

    @MainActor
    func testShareDiagnosticUsesReturnedCountsWithoutExtraQueries() throws {
        let f=fixture(); f.beforeShareResolve={ f.now += 6; f.shareMatches=f.shareResolves == 1 ? [] : [402] }
        try RCBody(f).present(f)
        XCTAssertEqual(f.shareDiagnostics.count, 1)
        let d=f.shareDiagnostics[0]
        XCTAssertEqual(d["action_queries"] as? Int, 2); XCTAssertEqual(d["action_returns"] as? Int, 2)
        XCTAssertEqual(d["last_action_count"] as? Int, 1); XCTAssertEqual(d["save_queries"] as? Int, 1)
        XCTAssertEqual(d["save_returns"] as? Int, 1); XCTAssertEqual(d["last_save_count"] as? Int, 1)
        XCTAssertEqual(d["last_stage"] as? String, "complete"); XCTAssertEqual(d["completed"] as? Bool, true)
        XCTAssertEqual(d["tap_started"] as? Bool, true); XCTAssertEqual(d["tap_returned"] as? Bool, true)
        XCTAssertEqual(d["elapsed_seconds"] as? Double, 12); XCTAssertEqual(d["observed_remaining_seconds"] as? Double, 18)
        XCTAssertEqual(f.shareResolves, 2); XCTAssertEqual(f.saveQueries, 1); XCTAssertEqual(f.taps, [402])
    }
    @MainActor
    func testShareDiagnosticDistinguishesMissingDisabledAndUnhittableWithoutTap() {
        for mode in 0..<3 {
            let f=fixture()
            if mode == 0 { f.shareMatches=[] } else if mode == 1 { f.shareEnabled=false } else { f.shareHittable=false }
            f.beforeShareResolve={ if f.shareResolves == 2 { f.now=30 } }
            if mode == 1 { f.beforeEnabled={f.now=30} }
            if mode == 2 { f.beforeHittable={f.now=30} }
            XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
            XCTAssertEqual(f.shareDiagnostics.count, 1); let d=f.shareDiagnostics[0]
            XCTAssertEqual(d["last_stage"] as? String, ["action-query","action-enabled","action-hittable"][mode])
            XCTAssertEqual(d["last_action_count"] as? Int, mode == 0 ? 0 : 1)
            if mode == 1 { XCTAssertEqual(d["last_action_enabled"] as? Bool, false) }
            if mode == 2 { XCTAssertEqual(d["last_action_hittable"] as? Bool, false) }
            XCTAssertEqual(d["tap_started"] as? Bool, false); XCTAssertEqual(d["completed"] as? Bool, false)
            XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.saveQueries, 0)
        }
    }
    @MainActor
    func testShareDiagnosticLateTapIsReturnedButNotCompleted() {
        let f=fixture(); f.shareTapSeconds=30
        XCTAssertThrowsError(try RCBody(f).present(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        let d=f.shareDiagnostics[0]
        XCTAssertEqual(d["last_stage"] as? String, "action-tap"); XCTAssertEqual(d["tap_started"] as? Bool, true)
        XCTAssertEqual(d["tap_returned"] as? Bool, true); XCTAssertEqual(d["completed"] as? Bool, false)
        XCTAssertEqual(d["observed_remaining_seconds"] as? Double, 0); XCTAssertEqual(f.saveQueries, 0)
    }
    @MainActor
    func testShareDiagnosticCannotReplaceNativeErrorOrCancellation() {
        enum OriginalError: Error { case native }
        for cancel in [false,true] {
            let f=fixture()
            if cancel { f.beforeShareTap={f.activeWindow?.cancel()} } else { f.tapError=OriginalError.native }
            XCTAssertThrowsError(try RCBody(f).present(f)) {
                if cancel { XCTAssertEqual($0 as? Readiness.Failure, .cancelled) } else { XCTAssertTrue($0 is OriginalError) }
            }
            XCTAssertEqual(f.shareDiagnostics.count, 1); let d=f.shareDiagnostics[0]
            XCTAssertEqual(d["tap_started"] as? Bool, true); XCTAssertEqual(d["completed"] as? Bool, false)
            XCTAssertEqual(f.taps, [401]); XCTAssertEqual(f.saveQueries, 0)
        }
    }

    @MainActor
    func testRecordAndShareNativeActionsOccurAfterReadinessWaiterReturns() throws {
        let record=fixture(); try RCBody(record).open(record)
        XCTAssertEqual(record.nativeTapReadinessDepths, [0]); XCTAssertEqual(record.recordResolves, 1)
        let share=fixture(); try RCBody(share).present(share)
        XCTAssertEqual(share.nativeTapReadinessDepths, [0]); XCTAssertEqual(share.shareResolves, 1)
    }
    @MainActor
    func testCancellationBetweenReservationAndNativeActionNeverTaps() {
        for share in [false,true] {
            let f=fixture(); f.afterReservation={f.activeWindow?.cancel()}
            XCTAssertThrowsError(try share ? RCBody(f).present(f) : RCBody(f).open(f)) {
                XCTAssertEqual($0 as? Readiness.Failure, .cancelled)
            }
            XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.navigationQueries+f.saveQueries, 0)
        }
    }
    @MainActor
    func testDeadlineBetweenReservationAndNativeActionNeverTaps() {
        for share in [false,true] {
            let f=fixture(); f.afterReservation={f.now=share ? 30 : 40}
            XCTAssertThrowsError(try share ? RCBody(f).present(f) : RCBody(f).open(f)) {
                XCTAssertEqual($0 as? Readiness.Failure, .expired)
            }
            XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.navigationQueries+f.saveQueries, 0)
        }
    }
    @MainActor
    func testReservationRetainsSameIdentityWithoutAnotherResolution() throws {
        let f=fixture(); f.afterReservation={f.recordMatches=[999]}
        try RCBody(f).open(f)
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.recordResolves, 1)
    }
    @MainActor
    func testReentryAtReservationOrNativeActionCannotConsumeAnotherAction() {
        for beforeAction in [true,false] {
            let f=fixture(); let window=FilesNavigationReadiness(timeout: 20); let body=RCBody(f)
            let again: () -> Void = {
                do {
                    try body.bound(f, window, action: { _ in XCTFail("second native action") })
                    XCTFail("reentry must fail")
                } catch { XCTAssertEqual(error as? Readiness.Failure, .selectionAlreadyStarted) }
            }
            if beforeAction { f.afterReservation=again }
            XCTAssertThrowsError(try body.bound(f, window, action: { _ in if !beforeAction { again() } })) {
                XCTAssertEqual($0 as? Readiness.Failure, .selectionAlreadyStarted)
            }
            XCTAssertEqual(f.recordResolves, 1); XCTAssertEqual(f.taps.count, beforeAction ? 0 : 1)
        }
    }
    @MainActor
    func testCompletedNativeActionCannotBeRepeatedUsingSameWindow() throws {
        let f=fixture(); let window=FilesNavigationReadiness(timeout: 20); let body=RCBody(f)
        try body.bound(f, window, action: { _ in })
        XCTAssertThrowsError(try body.bound(f, window, action: { _ in XCTFail("second native action") })) {
            XCTAssertEqual($0 as? Readiness.Failure, .selectionAlreadyStarted)
        }
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.recordResolves, 1)
    }
    @MainActor
    func testOutsideActionPreservesThrownTransportErrorWhenLateAndCancelled() {
        enum TransportFailure: Error { case expected }
        let f=fixture(); let window=FilesNavigationReadiness(timeout: 20)
        XCTAssertThrowsError(try RCBody(f).bound(f, window, action: { _ in
            f.now=20; window.native.cancel(); throw TransportFailure.expected
        })) { XCTAssertTrue($0 is TransportFailure) }
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.nativeTapReadinessDepths, [0])
    }
    @MainActor
    func testActualNestedWaiterABPreservesLateFailureWithoutArtificialInterruption() {
        // Real host XCTest waiters with a0.25s outer and1s completion signal.
        // The wide separation avoids racing XCTest's watchdog scheduling.
        for outside in [false,true] {
            let f=fixture(); f.realClock=true
            let window=FilesNavigationReadiness(timeout: 0.25)
            let began=ProcessInfo.processInfo.systemUptime
            var nested: XCTWaiter.Result?
            let action: (Int) throws -> Void = { _ in
                let completed=XCTestExpectation(description: "surrogate native synchronization")
                let timer=Timer(timeInterval: 1, repeats: false) { _ in completed.fulfill() }
                RunLoop.main.add(timer, forMode: .default)
                defer { timer.invalidate() }
                nested=XCTWaiter.wait(for: [completed], timeout: 2)
            }
            if outside {
                XCTAssertThrowsError(try RCBody(f).bound(f, window, action: action)) {
                    XCTAssertEqual($0 as? Readiness.Failure, .expired)
                }
                XCTAssertEqual(nested, .completed); XCTAssertEqual(f.nativeTapReadinessDepths, [0])
            } else {
                XCTAssertThrowsError(try window.waitAndTapBoundElement(matchingElements: { [201] },
                    enabled: { _ in true }, hittable: { _ in true }, tap: { id in
                        f.nativeTapReadinessDepths.append(f.readinessDepth); f.taps.append(id); try action(id)
                    })) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
                XCTAssertEqual(nested, .interrupted); XCTAssertEqual(f.nativeTapReadinessDepths, [1])
            }
            print("ROOM_RC_WAITER_AB outside=\(outside) nested=\(nested?.rawValue ?? -1) elapsed=\(ProcessInfo.processInfo.systemUptime-began) taps=\(f.taps.count)")
            XCTAssertEqual(f.taps, [201])
        }
    }
    @MainActor
    func testOutsideNativeNestedWaiterCompletesWithinOriginalWindow() throws {
        let f=fixture(); f.realClock=true
        let window=FilesNavigationReadiness(timeout: 1)
        var nested: XCTWaiter.Result?
        try RCBody(f).bound(f, window, action: { _ in
            let completed=XCTestExpectation(description: "timely native synchronization")
            let timer=Timer(timeInterval: 0.01, repeats: false) { _ in completed.fulfill() }
            RunLoop.main.add(timer, forMode: .default)
            defer { timer.invalidate() }
            nested=XCTWaiter.wait(for: [completed], timeout: 0.5)
        })
        XCTAssertEqual(nested, .completed); XCTAssertEqual(f.nativeTapReadinessDepths, [0]); XCTAssertEqual(f.taps, [201])
        XCTAssertGreaterThan(try window.native.remaining(), 0)
    }

    @MainActor
    func testPadFolderCreationUsesDirectOwnedActionAndNeverSidebarMore() throws {
        let f=fixture(); try RCBody(f).create(f, pad: true)
        XCTAssertEqual(f.taps, [801]); XCTAssertEqual(f.nativeTapReadinessDepths, [0])
        XCTAssertEqual(f.folderQueries, ["picker", "controls:701"])
        XCTAssertEqual(f.folderWindows, [10]); XCTAssertFalse(f.folderMenuOpen)
    }
    @MainActor
    func testPhoneFolderCreationUsesContentOverflowThenExactMenu() throws {
        let f=fixture(); try RCBody(f).create(f, pad: false)
        XCTAssertEqual(f.taps, [803,804]); XCTAssertEqual(f.nativeTapReadinessDepths, [0,0])
        XCTAssertEqual(f.folderQueries, ["picker", "bars:701", "controls:901", "menu"])
        XCTAssertEqual(f.folderWindows, [10,10])
    }
    @MainActor
    func testPadMissingDirectActionNeverFallsBackToGlobalOrSidebarControls() {
        let f=fixture(); f.folderControls[701]?.removeFirst(); f.folderMenuOpen=true
        f.beforeFolderQuery={ _ in f.now += 2 }
        XCTAssertThrowsError(try RCBody(f).create(f, pad: true)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertTrue(f.taps.isEmpty); XCTAssertFalse(f.folderQueries.contains("menu")); XCTAssertEqual(f.folderWindows,[10])
    }
    @MainActor
    func testPadUnreadyDirectActionNeverFallsBackToMore() {
        for disabled in [true,false] {
            let f=fixture(); if disabled { f.folderDisabled=[801] } else { f.folderUnhittable=[801] }
            f.beforeFolderQuery={ _ in f.now += 2 }
            XCTAssertThrowsError(try RCBody(f).create(f, pad: true)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
            XCTAssertTrue(f.taps.isEmpty); XCTAssertFalse(f.folderQueries.contains("menu")); XCTAssertFalse(f.folderMenuOpen)
        }
    }
    @MainActor
    func testFolderCreationRejectsDuplicatePickersAndDirectActions() {
        for owner in [true,false] {
            let f=fixture()
            if owner { f.folderPickerIDs=[701,702] }
            else { f.folderControls[701]?.append(.init(id: 806,identifier: "New Folder",label: "New Folder")) }
            XCTAssertThrowsError(try RCBody(f).create(f, pad: true)) { XCTAssertEqual($0 as? Readiness.Failure, .invalidSelectionCount) }
            XCTAssertTrue(f.taps.isEmpty); XCTAssertTrue(f.gates.isEmpty)
        }
    }
    @MainActor
    func testFolderCreationCannotUseActionFromAnotherPicker() {
        let f=fixture(); f.folderPickerIDs=[702]; f.beforeFolderQuery={ _ in f.now += 2 }
        XCTAssertThrowsError(try RCBody(f).create(f, pad: true)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertTrue(f.taps.isEmpty); XCTAssertFalse(f.folderQueries.contains("controls:701"))
    }
    @MainActor
    func testPhoneWrongBarOrSidebarMoreCannotAuthorizeMenu() {
        for wrongBar in [true,false] {
            let f=fixture()
            if wrongBar { f.folderBarIdentifiers[901]="SidebarNavigationBar" }
            else { f.folderControls[901]?.removeFirst() }
            f.beforeFolderQuery={ _ in f.now += 1 }
            XCTAssertThrowsError(try RCBody(f).create(f, pad: false)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
            XCTAssertTrue(f.taps.isEmpty); XCTAssertFalse(f.folderQueries.contains("menu")); XCTAssertEqual(f.folderWindows,[10])
        }
    }
    @MainActor
    func testPhoneRequiresBothExactOverflowIdentifierAndLabel() {
        for wrongIdentifier in [true,false] {
            let f=fixture()
            f.folderControls[901]=[.init(id: 803,identifier: wrongIdentifier ? "Other" : "OverflowBarButtonItem",
                                        label: wrongIdentifier ? "More" : "More Actions")]
            f.beforeFolderQuery={ _ in f.now += 1 }
            XCTAssertThrowsError(try RCBody(f).create(f, pad: false)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
            XCTAssertTrue(f.taps.isEmpty); XCTAssertFalse(f.folderMenuOpen)
        }
    }
    @MainActor
    func testPhoneDuplicateContentBarsOrOverflowActionsFailClosed() {
        for bar in [true,false] {
            let f=fixture()
            if bar { f.folderBarsByPicker[701]=[901,902];f.folderBarIdentifiers[902]=Readiness.navigationBarIdentifier }
            else { f.folderControls[901]?.append(.init(id:806,identifier:"OverflowBarButtonItem",label:"More")) }
            XCTAssertThrowsError(try RCBody(f).create(f,pad:false)) { XCTAssertEqual($0 as? Readiness.Failure,.invalidSelectionCount) }
            XCTAssertTrue(f.taps.isEmpty);XCTAssertFalse(f.folderQueries.contains("menu"))
        }
    }
    @MainActor
    func testFolderScopeQueriesReturningAtDeadlineNeverReachLiveGate() {
        for scope in ["picker","controls:701","bars:701","controls:901"] {
            let f=fixture();f.beforeFolderQuery={ if $0==scope { f.now=10 } }
            XCTAssertThrowsError(try RCBody(f).create(f,pad:scope=="picker" || scope=="controls:701")) {
                XCTAssertEqual($0 as? Readiness.Failure,.expired)
            }
            XCTAssertTrue(f.taps.isEmpty);XCTAssertTrue(f.gates.isEmpty)
        }
    }
    @MainActor
    func testFolderLiveGateReturningAtDeadlineNeverTaps() {
        for enabled in [true,false] {
            let f=fixture()
            if enabled { f.beforeFolderEnabled={ _ in f.now=10 } }
            else { f.beforeFolderHittable={ _ in f.now=10 } }
            XCTAssertThrowsError(try RCBody(f).create(f,pad:true)) { XCTAssertEqual($0 as? Readiness.Failure,.expired) }
            XCTAssertTrue(f.taps.isEmpty)
        }
    }
    @MainActor
    func testFolderLateNativeActionFailsWithoutNextRouteOrMenu() {
        for pad in [true,false] {
            let f=fixture();f.folderTapSeconds=10
            XCTAssertThrowsError(try RCBody(f).create(f,pad:pad)) { XCTAssertEqual($0 as? Readiness.Failure,.expired) }
            XCTAssertEqual(f.taps,pad ? [801] : [803]);XCTAssertEqual(f.folderWindows,[10])
            XCTAssertFalse(f.folderQueries.contains("menu"));XCTAssertEqual(f.nativeTapReadinessDepths,[0])
        }
    }
    @MainActor
    func testFolderCancelledOrExpiredAfterReservationNeverTaps() {
        for cancelled in [true,false] {
            let f=fixture();f.afterReservation={ if cancelled { f.activeWindow?.cancel() } else { f.now=10 } }
            XCTAssertThrowsError(try RCBody(f).create(f,pad:true)) {
                XCTAssertEqual($0 as? Readiness.Failure,cancelled ? .cancelled : .expired)
            }
            XCTAssertTrue(f.taps.isEmpty)
        }
    }
    @MainActor
    func testFolderFreshProbeBindsReplacementIdentityOnlyOnceReady() throws {
        let f=fixture();f.folderDisabled=[801];var probes=0
        f.beforeFolderQuery={ scope in
            if scope=="controls:701" { probes += 1;if probes==2 { f.folderControls[701]=[.init(id:807,identifier:"New Folder",label:"New Folder")] } }
        }
        try RCBody(f).create(f,pad:true)
        XCTAssertEqual(f.taps,[807]);XCTAssertEqual(f.gates,["enabled:801","enabled:807","hittable:807"])
    }
    @MainActor
    func testFolderDisappearingUnreadyIdentityCannotBeReused() {
        let f=fixture();f.folderDisabled=[801];var probes=0
        f.beforeFolderQuery={ scope in
            if scope=="controls:701" { probes += 1;if probes==2 { f.folderControls[701]=[];f.now=9 };if probes==3 { f.now=10 } }
        }
        XCTAssertThrowsError(try RCBody(f).create(f,pad:true)) { XCTAssertEqual($0 as? Readiness.Failure,.expired) }
        XCTAssertTrue(f.taps.isEmpty);XCTAssertEqual(f.gates,["enabled:801"])
    }
    @MainActor
    func testFolderReservationKeepsExactBoundIdentityWithoutRequery() throws {
        let f=fixture();f.afterReservation={ f.folderControls[701]=[.init(id:807,identifier:"New Folder",label:"New Folder")] }
        try RCBody(f).create(f,pad:true)
        XCTAssertEqual(f.taps,[801]);XCTAssertEqual(f.folderQueries,["picker","controls:701"])
    }
    @MainActor
    func testFolderNativeErrorRemainsPrimaryAndNeverStartsPhoneMenu() {
        enum NativeFailure: Error { case expected }
        let f=fixture();f.tapError=NativeFailure.expected;f.beforeFolderTap={ _ in f.activeWindow?.cancel() }
        XCTAssertThrowsError(try RCBody(f).create(f,pad:false)) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertEqual(f.taps,[803]);XCTAssertEqual(f.folderWindows,[10]);XCTAssertFalse(f.folderQueries.contains("menu"))
    }
    @MainActor
    func testPhoneDuplicateNewFolderMenuCannotProduceSecondTap() {
        let f=fixture();f.folderMenuMatches=[804,808]
        XCTAssertThrowsError(try RCBody(f).create(f,pad:false)) { XCTAssertEqual($0 as? Readiness.Failure,.invalidSelectionCount) }
        XCTAssertEqual(f.taps,[803]);XCTAssertEqual(f.folderWindows,[10,10])
    }

    @MainActor
    func testAllFiveActualPickerConstructorsMatchExactIdentifierOnly() {
        let exact=["identifier": Readiness.pickerIdentifier, "label": "foreign", "value": "", "placeholderValue": ""]
        let queries=PickerConstructors.make(); XCTAssertEqual(queries.count, 5)
        for query in queries { XCTAssertEqual(query.matches([exact]), [exact]) }
    }
    @MainActor
    func testAllFiveActualPickerConstructorsExcludeEveryAliasField() {
        for key in ["label", "value", "placeholderValue"] {
            var alias=["identifier": "unrelated", "label": "", "value": "", "placeholderValue": ""]
            alias[key]=Readiness.pickerIdentifier
            for query in PickerConstructors.make() { XCTAssertTrue(query.matches([alias]).isEmpty) }
        }
    }
    @MainActor
    func testActualPickerConstructorsPreserveMissingAndDuplicateCounts() {
        let exact=["identifier": Readiness.pickerIdentifier]
        for query in PickerConstructors.make() {
            XCTAssertEqual(query.matches([]).count, 0)
            XCTAssertEqual(query.matches([exact, exact]).count, 2)
            XCTAssertTrue(query.matches([["identifier": Readiness.pickerIdentifier+" suffix"]]).isEmpty)
        }
    }
    @MainActor
    func testBackupWrongPickerIdentifierCannotReachLiveFileOrTap() {
        let f=fixture(); f.nodes=[.init(.other, Readiness.pickerIdentifier, id: "alias-only", children: f.root.children)]
        fails(f, .invalidSelectionSnapshot); XCTAssertEqual(f.resolves, 0)
    }
    @MainActor
    private func journalFixture(_ check: (FailureJournalBody) throws -> Void) throws {
        let directory=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        FixtureSampleOutput.standardOutput.writes=[]
        try check(FailureJournalBody(directory.appendingPathComponent("journey.json")))
    }
    @MainActor
    func testActualFailureTailPersistsBeforeCaptureThrowsAndRethrowsOriginal() throws {
        try journalFixture { body in
            body.captureError=true
            XCTAssertThrowsError(try body.run { throw FailureJournalBody.FixtureError.original }) {
                XCTAssertEqual($0 as? FailureJournalBody.FixtureError, .original)
            }
            XCTAssertEqual(body.events, ["journal:failed", "capture:failure"])
            XCTAssertEqual(try String(contentsOf: body.file, encoding: .utf8), "failed:original")
            XCTAssertEqual(FixtureSampleOutput.standardOutput.writes.count, 1)
        }
    }
    @MainActor
    func testActualFailureTailHasDurableJournalWhileCaptureIsStillBlocked() throws {
        try journalFixture { body in
            body.duringCapture={
                XCTAssertEqual(try String(contentsOf: body.file, encoding: .utf8), "failed:original")
                // A bounded blocking transport stands in for screenshot RPC latency.
                Thread.sleep(forTimeInterval: 0.02)
                XCTAssertEqual(try String(contentsOf: body.file, encoding: .utf8), "failed:original")
            }
            XCTAssertThrowsError(try body.run { throw FailureJournalBody.FixtureError.original }) {
                XCTAssertEqual($0 as? FailureJournalBody.FixtureError, .original)
            }
            XCTAssertEqual(body.events, ["journal:failed", "capture:failure"])
        }
    }
    @MainActor
    func testActualFailureTailJournalErrorStillCapturesAndRethrowsOriginal() throws {
        try journalFixture { body in
            body.journalError=true; body.captureError=true
            XCTAssertThrowsError(try body.run { throw FailureJournalBody.FixtureError.original }) {
                XCTAssertEqual($0 as? FailureJournalBody.FixtureError, .original)
            }
            XCTAssertEqual(body.events, ["journal:failed", "capture:failure"])
            XCTAssertFalse(FileManager.default.fileExists(atPath: body.file.path))
        }
    }
    @MainActor
    func testActualSuccessTailOnlyWritesCompleteWithoutFailureDiagnostics() throws {
        try journalFixture { body in
            try body.run {}
            XCTAssertEqual(body.events, ["journal:complete"])
            XCTAssertEqual(try String(contentsOf: body.file, encoding: .utf8), "complete:")
            XCTAssertTrue(FixtureSampleOutput.standardOutput.writes.isEmpty)
        }
    }

}
