import XCTest
import CoreGraphics

private enum RecoveryJourneyFailure: Error {
    case assertion(String, String, String)
}
private enum OCRFixtureFailure: Error { case native }
private enum OCRFixtureType: UInt { case other, collectionView, `switch`, navigationBar, toolbar, button, tabBar, keyboard, alert }
@MainActor
private protocol OCRFixtureSnapshot {
    var elementType: OCRFixtureType { get }
    var identifier: String { get }
    var title: String { get }
    var label: String { get }
    var placeholderValue: String? { get }
    var value: Any? { get }
    var isEnabled: Bool { get }
    var frame: CGRect { get }
    var children: [any OCRFixtureSnapshot] { get }
}
@MainActor
private struct OCRSnapshot: OCRFixtureSnapshot {
    var elementType: OCRFixtureType = .other
    var identifier = ""
    var title = ""
    var label = ""
    var placeholderValue: String?
    var value: Any?
    var isEnabled = true
    var frame = CGRect(x: 0, y: 0, width: 402, height: 874)
    var children: [any OCRFixtureSnapshot] = []
}
private final class OCRPredicateObject: NSObject {
    @objc var identifier: String
    @objc var label: String
    @objc var value: String
    @objc var placeholderValue: String
    init(identifier: String, alias: String = "") {
        self.identifier = identifier; label = alias; value = alias; placeholderValue = alias
    }
}
@MainActor
private final class OCRFixture {
    static var current: OCRFixture!
    var now = 0.0
    var events: [String] = []
    var onEvent: ((String) -> Void)?
    var liveIDs = [1]
    var attributes = [1: OCRPredicateObject(identifier: "ocr.select.model")]
    var hittable = true
    var endpointOffset = 0.0
    var dragged = false
    var failSelected = false
    var snapshotError = false
    var snapshotSwitchCount = 1
    var selectedInitially = false
    let frame = CGRect(x: 309, y: 352, width: 61, height: 28)
    func event(_ value: String) { events.append(value); onEvent?(value) }
    func snapshot() throws -> any OCRFixtureSnapshot {
        event(dragged ? "selected-snapshot" : "snapshot")
        if snapshotError { throw OCRFixtureFailure.native }
        if dragged && failSelected { now += 10 }
        let value = dragged || selectedInitially ? "1" : "0"
        let targets = (0..<snapshotSwitchCount).map { _ in
            OCRSnapshot(elementType: .switch, identifier: "ocr.select.model", value: value, frame: frame)
        }
        let form = OCRSnapshot(elementType: .collectionView, frame: CGRect(x: 0, y: 100, width: 402, height: 700), children: targets)
        let nav = OCRSnapshot(elementType: .navigationBar, identifier: "Review recognized text", frame: CGRect(x: 0, y: 0, width: 402, height: 90))
        return OCRSnapshot(children: [nav, form])
    }
}
@MainActor
private final class OCRFixtureElement {
    let f: OCRFixture
    let identity: Int
    init(_ f: OCRFixture, _ identity: Int) { self.f = f; self.identity = identity }
    var isHittable: Bool { f.event("hit:\(identity)"); return f.hittable }
    func coordinate(withNormalizedOffset point: CGVector) -> OCRFixtureCoordinate {
        f.event("coordinate:\(identity):\(point.dx)")
        return OCRFixtureCoordinate(f, identity, point.dx)
    }
}
@MainActor
private final class OCRFixtureCoordinate {
    let f: OCRFixture
    let identity: Int
    let x: Double
    enum Velocity { case slow }
    init(_ f: OCRFixture, _ identity: Int, _ x: Double) { self.f = f; self.identity = identity; self.x = x }
    var screenPoint: CGPoint {
        f.event("point:\(identity):\(x)")
        return CGPoint(x: f.frame.minX + f.frame.width * x + f.endpointOffset, y: f.frame.midY)
    }
    func press(forDuration: Double, thenDragTo other: OCRFixtureCoordinate, withVelocity: Velocity, thenHoldForDuration: Double) {
        f.event("drag:\(identity):\(other.identity)"); f.dragged = true
    }
}
@MainActor
private struct OCRFixtureQuery {
    let f: OCRFixture
    var predicate: NSPredicate?
    func matching(_ value: NSPredicate) -> Self { Self(f: f, predicate: value) }
    var element: OCRFixtureElement { .init(f, -1) }
    var allElementsBoundByAccessibilityElement: [OCRFixtureElement] {
        f.event("bind")
        return f.liveIDs.filter { predicate!.evaluate(with: f.attributes[$0]!) }.map { .init(f, $0) }
    }
}
@MainActor
private struct OCRFixtureApp {
    let f: OCRFixture
    var switches: OCRFixtureQuery { .init(f: f) }
    func snapshot() throws -> any OCRFixtureSnapshot { try f.snapshot() }
}
@MainActor
private struct OCRLedger {
    let f: OCRFixture
    func require(_ name: String, _ value: Bool) throws {
        if name.contains("entire switch") { f.event("geometry-evidence") }
        guard value else { throw RecoveryJourneyFailure.assertion(name, "false", "true") }
    }
    func require(_ name: String, actual: String, expected: String) throws {
        guard actual == expected else { throw RecoveryJourneyFailure.assertion(name, actual, expected) }
    }
}
@MainActor
private struct RecoveryOCRReadinessWindow {
    let actual: OCRNativeReadinessWindow
    init() { let f = OCRFixture.current!; actual = .init(clock: { f.now }) }
    func remaining() throws -> TimeInterval { try actual.remaining() }
    func perform<T>(_ body: () throws -> T) throws -> T { try actual.perform(body) }
    func probe<T>(snapshot: () throws -> T, stateReady: (T) throws -> Bool, hittable: () throws -> Bool) throws -> T? {
        try actual.probe(snapshot: snapshot, stateReady: stateReady, hittable: hittable)
    }
    func waitForProbe(_ probe: @escaping @MainActor () -> Bool) throws -> XCTWaiter.Result { try actual.waitForProbe(probe) }
}
@MainActor
private struct RecoveryOCRSelectionWindow {
    typealias Observation = OCRNativeSelectionWindow.Observation
    let actual: OCRNativeSelectionWindow
    init() { let f = OCRFixture.current!; actual = .init(clock: { f.now }) }
    func remaining() throws -> TimeInterval { try actual.remaining() }
    func observe<T>(identifier: String, snapshot: () throws -> T, children: (T) -> [T], isSwitch: (T) -> Bool, identifierOf: (T) -> String, value: (T) -> String?) throws -> Observation {
        try actual.observe(identifier: identifier, snapshot: snapshot, children: children, isSwitch: isSwitch, identifierOf: identifierOf, value: value)
    }
}
@MainActor
private final class OCRBody {
    let f: OCRFixture
    init(_ f: OCRFixture) { self.f = f }
    var ledger: OCRLedger { .init(f: f) }
    func reveal(_ target: OCRFixtureElement, app: OCRFixtureApp) throws { f.event("reveal") }
    func run() throws { try selectOCRField("model", app: .init(f: f)) }
    // RECOVERY_OCR_SELECTION_BODY
}

final class RecoveryOCRSelectionRegressionTests: XCTestCase {
    @MainActor private func fixture() -> OCRFixture { let f = OCRFixture(); OCRFixture.current = f; return f }
    @MainActor func testActualOCRUsesOneExactBoundIdentityThroughOneDragAndSelectedProof() throws {
        let f = fixture()
        f.onEvent = { event in if event == "hit:1" { f.liveIDs = [2]; f.attributes[2] = .init(identifier: "ocr.select.model") } }
        try OCRBody(f).run()
        XCTAssertEqual(f.events.filter { $0 == "bind" }.count, 1)
        XCTAssertEqual(f.events.filter { $0.hasPrefix("coordinate:") }, ["coordinate:1:0.25", "coordinate:1:0.75"])
        XCTAssertEqual(f.events.filter { $0.hasPrefix("point:") }, ["point:1:0.25", "point:1:0.75"])
        XCTAssertEqual(f.events.filter { $0.hasPrefix("drag:") }, ["drag:1:1"])
        XCTAssertTrue(f.events.contains("selected-snapshot"))
    }
    @MainActor func testActualOCRExactIdentifierExcludesLabelValueAndPlaceholderAliases() throws {
        let f = fixture(); f.liveIDs = [1,2]; f.attributes[2] = .init(identifier: "other", alias: "ocr.select.model")
        try OCRBody(f).run(); XCTAssertTrue(f.dragged)
        XCTAssertFalse(f.events.contains("hit:2"))
    }
    @MainActor func testActualOCRMissingOrDuplicateLiveTargetNeverGestures() {
        for ids in [[], [1,2]] {
            let f = fixture(); f.liveIDs = ids; f.attributes[2] = .init(identifier: "ocr.select.model")
            if ids.isEmpty { f.onEvent = { if $0 == "bind" { f.now = 10 } } }
            XCTAssertThrowsError(try OCRBody(f).run()); XCTAssertFalse(f.dragged)
            XCTAssertFalse(f.events.contains { $0.hasPrefix("coordinate:") })
        }
    }
    @MainActor func testActualOCRTimelyEmptyProbeHasNoLiveGatesAndUsesFreshNextBinding() throws {
        let f = fixture(); f.liveIDs = []; var probes = 0
        f.onEvent = { event in
            if event == "snapshot" {
                probes += 1
                if probes == 2 {
                    XCTAssertEqual(f.events.filter { $0 == "bind" }.count, 1)
                    XCTAssertFalse(f.events.contains { $0.hasPrefix("hit:") || $0.hasPrefix("coordinate:") })
                    f.liveIDs = [2]; f.attributes[2] = .init(identifier: "ocr.select.model"); f.now = 9
                }
            }
        }
        try OCRBody(f).run()
        XCTAssertEqual(f.events.filter { $0 == "bind" }.count, 2)
        XCTAssertEqual(f.events.filter { $0.hasPrefix("drag:") }, ["drag:2:2"])
        XCTAssertFalse(f.events.contains("hit:1"))
    }
    @MainActor func testActualOCRLateOrEqualRemoteStageNeverAdmitsNextOperation() {
        let ordered = ["bind", "hit:1", "coordinate:1:0.25", "coordinate:1:0.75", "point:1:0.25", "point:1:0.75"]
        for stage in ordered {
            for elapsed in [10.0, 10.001] {
                let f = fixture(); f.onEvent = { if $0 == stage { f.now = elapsed } }
                XCTAssertThrowsError(try OCRBody(f).run()); XCTAssertFalse(f.dragged)
                XCTAssertEqual(f.events.last, stage)
            }
        }
    }
    @MainActor func testActualOCRNonhittableProbeRefreshesBindingWithoutRenewingWindow() throws {
        let f = fixture(); var hits = 0
        f.onEvent = { event in
            if event.hasPrefix("hit:") {
                hits += 1; f.hittable = hits > 1
                if hits == 1 { f.liveIDs = [2]; f.attributes[2] = .init(identifier: "ocr.select.model"); f.now = 8 }
                else { f.now = 9 }
            }
        }
        try OCRBody(f).run(); XCTAssertEqual(f.events.filter { $0 == "bind" }.count, 2)
        XCTAssertEqual(f.events.filter { $0.hasPrefix("drag:") }, ["drag:2:2"])
    }
    @MainActor func testActualOCRUnreadyProbeCannotLeakBindingOrRenewDeadline() {
        let f = fixture(); var hits = 0
        f.onEvent = { event in
            if event.hasPrefix("hit:") { hits += 1; f.hittable = hits > 1; f.now = hits == 1 ? 9 : 10 }
        }
        XCTAssertThrowsError(try OCRBody(f).run()); XCTAssertFalse(f.dragged)
        XCTAssertFalse(f.events.contains { $0.hasPrefix("coordinate:") })
    }
    @MainActor func testActualOCRGeometryEvidenceConsumesOriginalReadinessBudget() {
        let f = fixture(); f.onEvent = { if $0 == "geometry-evidence" { f.now = 10 } }
        XCTAssertThrowsError(try OCRBody(f).run()); XCTAssertFalse(f.dragged)
        XCTAssertFalse(f.events.contains { $0.hasPrefix("coordinate:") })
    }
    @MainActor func testActualOCRChangedEndpointsNeverGesture() {
        let f = fixture(); f.endpointOffset = 1
        XCTAssertThrowsError(try OCRBody(f).run()); XCTAssertFalse(f.dragged)
    }
    @MainActor func testActualOCRSnapshotErrorStopsBeforeBinding() {
        let f = fixture(); f.snapshotError = true
        XCTAssertThrowsError(try OCRBody(f).run()) { XCTAssertTrue(String(describing: $0).contains("native")) }
        XCTAssertFalse(f.events.contains("bind")); XCTAssertFalse(f.dragged)
    }
    @MainActor func testActualOCRDuplicateSnapshotStopsBeforeLiveQuery() {
        let f = fixture(); f.snapshotSwitchCount = 2
        XCTAssertThrowsError(try OCRBody(f).run()); XCTAssertFalse(f.events.contains("bind")); XCTAssertFalse(f.dragged)
    }
    @MainActor func testActualOCRSuccessfulDragStillRequiresTimelySelectedState() {
        let f = fixture(); f.failSelected = true
        XCTAssertThrowsError(try OCRBody(f).run()); XCTAssertTrue(f.dragged)
        XCTAssertEqual(f.events.filter { $0.hasPrefix("drag:") }.count, 1)
    }
}
