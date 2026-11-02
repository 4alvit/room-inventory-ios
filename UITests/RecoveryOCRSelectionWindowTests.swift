import XCTest

final class RecoveryOCRSelectionWindowTests: XCTestCase {
    private struct Node {
        var isSwitch = false
        var identifier = ""
        var value: String?
        var children = [Node]()
    }

    private let target = "ocr.select.model"

    private func observe(_ window: RecoveryOCRSelectionWindow,
                         snapshot: () throws -> Node,
                         children: ((Node) -> [Node])? = nil) throws -> RecoveryOCRSelectionWindow.Observation {
        try window.observe(identifier: target, snapshot: snapshot,
            children: children ?? { $0.children }, isSwitch: { $0.isSwitch },
            identifierOf: { $0.identifier }, value: { $0.value })
    }

    private var selected: Node { Node(isSwitch: true, identifier: target, value: "1") }

    func testImmediateSlowSnapshotCanConfirmSelectionWithoutAnotherQuery() throws {
        var now = 0.0
        let window = RecoveryOCRSelectionWindow(clock: { now })
        var queries = 0
        let state = try observe(window, snapshot: {
            queries += 1
            now = 9.3
            return Node(children: [selected])
        })
        XCTAssertTrue(state.selected)
        XCTAssertEqual(state.value, "1")
        XCTAssertEqual(state.matches, 1)
        XCTAssertEqual(queries, 1)
        XCTAssertEqual(try window.remaining(), 0.7, accuracy: 0.000001)
    }

    func testExactOrLateSnapshotCannotConfirmSelection() {
        for elapsed in [10.0, 10.001] {
            var now = 0.0
            let window = RecoveryOCRSelectionWindow(clock: { now })
            var traversed = false
            XCTAssertThrowsError(try observe(window, snapshot: {
                now = elapsed
                return selected
            }, children: { _ in traversed = true; return [] })) {
                XCTAssertEqual($0 as? RecoveryOCRSelectionWindow.Failure, .expired)
            }
            XCTAssertFalse(traversed)
        }
    }

    func testTraversalSharesSnapshotDeadlineEvenAfterFindingSelectedTarget() {
        var now = 0.0
        let window = RecoveryOCRSelectionWindow(clock: { now })
        XCTAssertThrowsError(try observe(window, snapshot: { selected }, children: { _ in
            now = 10
            return []
        })) { XCTAssertEqual($0 as? RecoveryOCRSelectionWindow.Failure, .expired) }
    }

    func testUnselectedObservationDoesNotRenewDeadlineOrPermitExpiredQuery() throws {
        var now = 0.0
        let window = RecoveryOCRSelectionWindow(clock: { now })
        let state = try observe(window, snapshot: {
            now = 7
            return Node(isSwitch: true, identifier: target, value: "0")
        })
        XCTAssertFalse(state.selected)
        XCTAssertEqual(try window.remaining(), 3)
        now = 10
        var queries = 0
        XCTAssertThrowsError(try observe(window, snapshot: { queries += 1; return selected })) {
            XCTAssertEqual($0 as? RecoveryOCRSelectionWindow.Failure, .expired)
        }
        XCTAssertEqual(queries, 0)
    }

    func testOnlyExactTypedUniqueSelectedSwitchCanConfirmSelection() throws {
        let window = RecoveryOCRSelectionWindow(clock: { 0 })
        for node in [Node(), Node(identifier: target, value: "1"),
                     Node(isSwitch: true, identifier: "ocr.select.purchasePrice", value: "1"),
                     Node(isSwitch: true, identifier: target, value: "0"),
                     Node(isSwitch: true, identifier: target),
                     Node(isSwitch: true, identifier: target, value: "true")] {
            XCTAssertFalse(try observe(window, snapshot: { node }).selected)
        }
        XCTAssertThrowsError(try observe(window, snapshot: { Node(children: [selected, selected]) })) {
            XCTAssertEqual($0 as? RecoveryOCRSelectionWindow.Failure, .duplicateSwitch)
        }
    }

    func testTraversalRejectsOversizedSnapshotEvenWhenFirstTargetIsSelected() {
        let window = RecoveryOCRSelectionWindow(clock: { 0 })
        let root = Node(children: [selected] + Array(repeating: Node(), count: 9_999))
        XCTAssertThrowsError(try observe(window, snapshot: { root })) {
            XCTAssertEqual($0 as? RecoveryOCRSelectionWindow.Failure, .nodeLimit)
        }
    }

    func testNativeSnapshotErrorIsPreservedEvenWhenItReturnsLate() {
        enum SnapshotError: Error { case unavailable }
        var now = 0.0
        let window = RecoveryOCRSelectionWindow(clock: { now })
        var traversed = false
        XCTAssertThrowsError(try observe(window, snapshot: {
            now = 11
            throw SnapshotError.unavailable
        }, children: { _ in traversed = true; return [] })) {
            XCTAssertTrue($0 is SnapshotError)
        }
        XCTAssertFalse(traversed)
    }
}
