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
    var presentationMode = false
    var presentationWindows: [TimeInterval] = []
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
            XCTAssertEqual(identifier, Readiness.pickerIdentifier)
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
    func tap() { f.taps.append(id); f.now += f.recordTapSeconds; f.beforeRecordTap?() }
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
        if scope == "save" { f.beforeSaveEnabled?(); return f.saveEnabled }
        f.beforeEnabled?(); return f.shareEnabled
    }
    var isHittable: Bool {
        if scope == "save" { f.beforeSaveHittable?(); return f.saveHittable }
        f.beforeHittable?(); return f.shareHittable
    }
    func tap() { f.taps.append(id); f.now += f.shareTapSeconds; f.beforeShareTap?() }
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
        let q=FixturePresentationQuery(f, "save"); q.identifier=identifier; return q
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
    let native: Readiness
    let f: SelectionFixture
    init(timeout: TimeInterval) {
        f=SelectionFixture.current!
        let clock=f
        native=Readiness(timeout: timeout, clock: { clock.now })
        f.activeWindow=native; if timeout == 20 { f.recordWindows.append(timeout) }
        if f.presentationMode { f.presentationWindows.append(timeout) }
    }
    func perform<T>(_ op: () throws -> T) throws -> T { try native.perform(op) }
    func waitAndTapBoundElement<Element>(matchingElements: @escaping () throws -> [Element],
        enabled: @escaping (Element) throws -> Bool, hittable: @escaping (Element) throws -> Bool,
        tap: @escaping (Element) throws -> Void) throws {
        try native.waitAndTapBoundElement(matchingElements: matchingElements, enabled: enabled, hittable: hittable, tap: { element in
            try tap(element)
            if let error = self.f.tapError { self.f.now=30; throw error }
        })
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
    func present(_ f: SelectionFixture) throws { f.presentationMode=true; try openExportDestination(FixtureApp(f)) }
    func open(_ f: SelectionFixture) throws { try openRecord(f.recordName, FixtureApp(f)) }
    func echo(_ f: SelectionFixture, _ expected: String) throws -> String {
        try observeExportedFilename(expected, FixtureApp(f))
    }
    func run(_ f: SelectionFixture) throws { try selectBackup(FixtureApp(f)) }
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
    func testRecordSlowNativeTapUsesRemainingOriginalTargetAllocation() throws {
        let f=fixture(); f.recordTapSeconds=10.2; f.beforeNavigationQuery={f.now += 0.8}
        try RCBody(f).open(f)
        XCTAssertEqual(f.recordWindows, [20]); XCTAssertEqual(f.now, 11, accuracy: 0.00001)
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.navigationQueries, 1)
    }
    @MainActor
    func testRecordBoundIdentitySurvivesResolverChangeAndTapsOnce() throws {
        let f=fixture(); f.beforeEnabled={f.recordMatches=[202]}
        try RCBody(f).open(f)
        XCTAssertEqual(f.recordResolves, 1); XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.recordWindows, [20])
    }
    @MainActor
    func testRecordAmbiguousRowNeverTapsOrChecksDestination() {
        let f=fixture(); f.recordMatches=[201,202]
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .invalidSelectionCount) }
        XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.navigationQueries, 0)
    }
    @MainActor
    func testRecordLateRowObservationCannotTap() {
        let f=fixture(); f.beforeRecordResolve={f.now=20}
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertTrue(f.taps.isEmpty); XCTAssertEqual(f.navigationQueries, 0)
    }
    @MainActor
    func testRecordLateNativeTapCannotStartDestinationProbe() {
        let f=fixture(); f.recordTapSeconds=20
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.navigationQueries, 0)
    }
    @MainActor
    func testRecordDestinationUsesRemainingDeadlineWithoutRenewal() {
        let f=fixture(); f.recordTapSeconds=19; f.beforeNavigationQuery={f.now += 0.6}
        f.beforeNavigationEnabled={f.now += 0.3}; f.beforeNavigationHittable={f.now += 0.2}
        XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
        XCTAssertEqual(f.recordWindows, [20]); XCTAssertEqual(f.taps, [201]); XCTAssertEqual(f.navigationQueries, 1)
    }
    @MainActor
    func testRecordWrongOrMissingDestinationNeverRenewsOrRetaps() {
        for wrong in [true,false] {
            let f=fixture(); f.recordTapSeconds=10.2
            if wrong { f.navigationIdentifier="Wrong room" } else { f.navigationCount=0 }
            f.beforeNavigationQuery={f.now += 5}
            XCTAssertThrowsError(try RCBody(f).open(f)) { XCTAssertEqual($0 as? Readiness.Failure, .expired) }
            XCTAssertEqual(f.recordWindows, [20]); XCTAssertEqual(f.taps, [201])
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
        let f=fixture(); f.tapError=NativeError.expected
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

}
