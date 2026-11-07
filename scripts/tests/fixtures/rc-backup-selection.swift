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
private final class FixtureApp {
    let f: SelectionFixture
    init(_ f: SelectionFixture) { self.f=f }
    var otherElements: FixtureQuery { .init(f, "picker") }
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
    }
    func perform<T>(_ op: () throws -> T) throws -> T { try native.perform(op) }
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

}
