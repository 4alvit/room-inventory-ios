import XCTest

final class ExportReturnReadinessTests: XCTestCase {
    private let home = "Recovery Home 12345678"
    private let viewport = CGRect(x: 0, y: 0, width: 402, height: 874)

    @MainActor
    private func node(_ kind: ExportReturnReadiness.Kind, id: String = "", label: String = "",
                      enabled: Bool = true, frame: CGRect = CGRect(x: 20, y: 100, width: 100, height: 40),
                      parent: Int? = nil) -> ExportReturnReadiness.Element {
        .init(kind: kind, identifier: id, label: label, enabled: enabled, frame: frame, parent: parent)
    }

    @MainActor
    private func dashboard() -> ExportReturnReadiness.Observation {
        .init(frame: viewport, elements: [
            node(.button, id: "inventory.exportMenu"),
            node(.button, label: home + ", 1 room · 1 item"),
            node(.text, label: home, parent: 1)
        ])
    }

    @MainActor
    private func share() -> ExportReturnReadiness.Observation {
        .init(frame: viewport, elements: [
            node(.other, id: "ActivityListView", frame: viewport),
            node(.other, id: "ShareSheet.RemoteContainerView", frame: viewport, parent: 0),
            node(.navigationBar, id: "UIActivityContentView",
                 frame: CGRect(x: 16, y: 64, width: 370, height: 88), parent: 1),
            node(.button, id: "header.closeButton", label: "Close",
                 frame: CGRect(x: 330, y: 70, width: 35, height: 35), parent: 2)
        ])
    }

    @MainActor
    func testImmediateDashboardUsesOneSnapshotAndOneHomeHit() throws {
        var now = 0.0
        let wait = ExportReturnReadiness(homeName: home, clock: { now })
        now = 9.25 // Less than XCTest's former one-second predicate delay remains.
        var snapshots = 0
        var hits: [ExportReturnReadiness.Target] = []
        XCTAssertTrue(try wait.waitForReturn(observe: {
            snapshots += 1
            return self.dashboard()
        }, isHittable: { hits.append($0); return true }, close: { XCTFail("Unexpected Close") }))
        XCTAssertEqual(snapshots, 1)
        XCTAssertEqual(hits, [.home])
        XCTAssertFalse(wait.closeAttempted)
        XCTAssertEqual(wait.diagnostic["schema_version"] as? Int, 2)
        XCTAssertEqual(wait.diagnostic["native_hit_target"] as? String, "home")
        XCTAssertNil(wait.diagnostic["export_hittable"])
    }

    @MainActor
    func testSnapshotDelayLeavesBudgetForOneNativeHomeHit() throws {
        var now = 0.0
        let wait = ExportReturnReadiness(homeName: home, clock: { now })
        var snapshots = 0
        var hits = 0
        XCTAssertTrue(try wait.waitForReturn(observe: {
            snapshots += 1
            now += 8.1
            return self.dashboard()
        }, isHittable: { _ in
            // Every native hit costs the same time, including a redundant one.
            // This closure also works with the previous two-target helper.
            hits += 1
            now += 1.3
            return true
        }, close: { XCTFail("Unexpected Close") }))
        XCTAssertEqual(snapshots, 1)
        XCTAssertEqual(hits, 1)
        XCTAssertEqual(now, 9.4, accuracy: 0.000_001)
        XCTAssertFalse(wait.closeAttempted)
    }

    @MainActor
    func testOmittedRemoteFilesStillCannotExposeDashboardBehindShareOwner() throws {
        let base = dashboard()
        for owner in ["inventory.exportShare", "ActivityListView", "ShareSheet.RemoteContainerView"] {
            let observation = ExportReturnReadiness.Observation(frame: viewport,
                elements: base.elements + [node(.other, id: owner)])
            let wait = ExportReturnReadiness(homeName: home, clock: { 0 })
            XCTAssertFalse(try wait.poll(observe: { observation }, isHittable: { _ in
                XCTFail("Underlying dashboard must not be queried"); return true
            }, close: { XCTFail("No identified Close") }))
        }
    }

    @MainActor
    func testWrongDuplicateOrUnboundDashboardAnchorsAreRejected() throws {
        let base = dashboard().elements
        let cases = [
            [base[1], node(.text, label: home, parent: 0)],
            base + [base[0]],
            base + [base[1]],
            [base[0], node(.button, label: home + "9, 1 room · 1 item"), base[2]],
            [base[0], base[1], node(.text, label: "Another home", parent: 1)],
            [base[0], base[1], node(.text, label: home)],
            [node(.other, id: "inventory.exportMenu"), base[1], base[2]]
        ]
        for nodes in cases {
            XCTAssertEqual(try ExportReturnReadiness.decision(.init(frame: viewport, elements: nodes),
                homeName: home), .pending)
        }
    }

    @MainActor
    func testDisabledOffscreenEmptyAndNonfiniteAnchorsAreRejected() throws {
        let base = dashboard().elements
        for index in [0, 1] {
            for replacement in [
                node(.button, id: base[index].identifier, label: base[index].label, enabled: false),
                node(.button, id: base[index].identifier, label: base[index].label,
                     frame: CGRect(x: 390, y: 100, width: 40, height: 40)),
                node(.button, id: base[index].identifier, label: base[index].label, frame: .zero),
                node(.button, id: base[index].identifier, label: base[index].label,
                     frame: CGRect(x: CGFloat.infinity, y: 0, width: 40, height: 40))
            ] {
                var nodes = base
                nodes[index] = replacement
                XCTAssertEqual(try ExportReturnReadiness.decision(.init(frame: viewport, elements: nodes),
                    homeName: home), .pending)
            }
        }
    }

    @MainActor
    func testNonhittableHomeRejectsDashboardWithoutAnotherNativeHit() throws {
        let wait = ExportReturnReadiness(homeName: home, clock: { 0 })
        var hits: [ExportReturnReadiness.Target] = []
        XCTAssertFalse(try wait.poll(observe: { self.dashboard() }, isHittable: {
            hits.append($0); return false
        }, close: { XCTFail("Unexpected Close") }))
        XCTAssertEqual(hits, [.home])
        XCTAssertEqual(wait.lastHomeHittable, false)
    }

    @MainActor
    func testOnlyIdentifiedOwnedCloseCanBeAdmitted() throws {
        let base = share().elements
        let cases = [
            [node(.other), base[1], base[2], base[3]],
            [base[0], base[1], base[2], node(.button, label: "Close", parent: 2)],
            [base[0], base[1], base[2], node(.button, id: "header.closeButton", label: "Close")],
            base + [base[3]],
            base + [node(.other, id: "ActivityListView")],
            base + [node(.button, id: "DOCPicker.actionButton", label: "Save")],
            base + [node(.alert)]
        ]
        // The first case still has a valid RemoteContainer owner; remove both
        // known owner identifiers to test the genuinely unowned header.
        var unowned = cases[0]
        unowned[1] = node(.other, parent: 0)
        for nodes in [unowned] + Array(cases.dropFirst()) {
            XCTAssertEqual(try ExportReturnReadiness.decision(.init(frame: viewport, elements: nodes),
                homeName: home), .pending)
        }
    }

    @MainActor
    func testCloseNeedsEnabledGeometryAndNativeHit() throws {
        let base = share().elements
        for closeNode in [
            node(.button, id: "header.closeButton", label: "Close", enabled: false, parent: 2),
            node(.button, id: "header.closeButton", label: "Close",
                 frame: CGRect(x: 330, y: 300, width: 35, height: 35), parent: 2)
        ] {
            var nodes = base; nodes[3] = closeNode
            XCTAssertEqual(try ExportReturnReadiness.decision(.init(frame: viewport, elements: nodes),
                homeName: home), .pending)
        }
        let wait = ExportReturnReadiness(homeName: home, clock: { 0 })
        XCTAssertFalse(try wait.poll(observe: { self.share() }, isHittable: { _ in false },
                                     close: { XCTFail("Nonhittable Close") }))
        XCTAssertFalse(wait.closeAttempted)
    }

    @MainActor
    func testOneCloseThenFreshDashboardObservationIsRequired() throws {
        let wait = ExportReturnReadiness(homeName: home, clock: { 0 })
        var closes = 0
        XCTAssertFalse(try wait.poll(observe: { self.share() }, isHittable: { _ in true },
                                     close: { closes += 1 }))
        XCTAssertFalse(try wait.poll(observe: { self.share() }, isHittable: { _ in
            XCTFail("Must not hit-test a second Close"); return true
        }, close: { closes += 1 }))
        XCTAssertTrue(try wait.poll(observe: { self.dashboard() }, isHittable: { _ in true },
                                    close: { closes += 1 }))
        XCTAssertEqual(closes, 1)
    }

    @MainActor
    func testWaiterObservesFreshDashboardAfterOneCloseWithoutReentry() throws {
        let wait = ExportReturnReadiness(homeName: home, clock: { 0 })
        var snapshots = 0
        var closes = 0
        var observing = false
        var hits: [ExportReturnReadiness.Target] = []
        XCTAssertTrue(try wait.waitForReturn(observe: {
            XCTAssertFalse(observing)
            observing = true
            defer { observing = false }
            snapshots += 1
            // Pumping the run loop must not reenter the active probe.
            RunLoop.main.run(until: Date().addingTimeInterval(1.1))
            return closes == 0 ? self.share() : self.dashboard()
        }, isHittable: { hits.append($0); return true }, close: { closes += 1 }))
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        XCTAssertEqual(snapshots, 2)
        XCTAssertEqual(closes, 1)
        XCTAssertEqual(hits, [.shareClose, .home])
    }

    @MainActor
    func testDeadlineAtWaitReturnRejectsPreviouslyTimelyDashboard() {
        var finalHitReturned = false
        var checksAfterHit = 0
        let wait = ExportReturnReadiness(homeName: home, clock: {
            guard finalHitReturned else { return 0 }
            checksAfterHit += 1
            // Hit postcheck, poll admission and pending-probe postcheck pass;
            // final admission after the completed waiter reaches the deadline.
            return checksAfterHit <= 3 ? 9 : 10
        })
        XCTAssertThrowsError(try wait.waitForReturn(observe: { self.dashboard() }, isHittable: {
            if $0 == .home { finalHitReturned = true }
            return true
        }, close: { XCTFail("Unexpected Close") })) {
            XCTAssertTrue($0 is ExportReturnReadiness.Failure)
        }
        XCTAssertEqual(wait.lastHomeHittable, true)
    }

    @MainActor
    func testThrowingCloseConsumesAllowanceAndWrapperPropagatesError() {
        enum NativeFailure: Error { case close }
        let wait = ExportReturnReadiness(homeName: home, clock: { 0 })
        var closes = 0
        XCTAssertThrowsError(try wait.waitForReturn(observe: { self.share() }, isHittable: { _ in true },
            close: { closes += 1; throw NativeFailure.close })) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertTrue(wait.closeAttempted)
        XCTAssertFalse(try wait.poll(observe: { self.share() }, isHittable: { _ in true },
                                     close: { closes += 1 }))
        XCTAssertEqual(closes, 1)
    }

    @MainActor
    func testExpiredWindowDoesNotObserveOrAct() {
        var now = 0.0
        let wait = ExportReturnReadiness(homeName: home, clock: { now })
        now = 10
        XCTAssertThrowsError(try wait.waitForReturn(observe: {
            XCTFail("Expired snapshot"); return self.dashboard()
        }, isHittable: { _ in XCTFail("Expired hit test"); return true },
        close: { XCTFail("Expired Close") }))
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        XCTAssertEqual(wait.observations, 0)
    }

    @MainActor
    func testLateSnapshotOrHitCannotAuthorizeReturnOrClose() {
        for stage in ["snapshot", "home", "close"] {
            var now = 0.0
            let wait = ExportReturnReadiness(homeName: home, clock: { now })
            var closes = 0
            XCTAssertThrowsError(try wait.poll(observe: {
                if stage == "snapshot" { now = 10 }
                return stage == "close" ? self.share() : self.dashboard()
            }, isHittable: { target in
                if (stage == "home" && target == .home)
                    || (stage == "close" && target == .shareClose) { now = 10 }
                return true
            }, close: { closes += 1 }))
            XCTAssertEqual(closes, 0)
        }
    }

    @MainActor
    func testCloseReturningLateFailsAndCannotBeRepeated() {
        var now = 0.0
        let wait = ExportReturnReadiness(homeName: home, clock: { now })
        var closes = 0
        XCTAssertThrowsError(try wait.poll(observe: { self.share() }, isHittable: { _ in true },
            close: { closes += 1; now = 10.001 }))
        XCTAssertTrue(wait.closeAttempted)
        XCTAssertThrowsError(try wait.poll(observe: { self.dashboard() }, isHittable: { _ in true },
            close: { closes += 1 }))
        XCTAssertEqual(closes, 1)
    }

    @MainActor
    func testObservationAndHitErrorsPropagateWithoutAction() {
        enum NativeFailure: Error { case observation, hit }
        for stage in ["observation", "hit"] {
            let wait = ExportReturnReadiness(homeName: home, clock: { 0 })
            XCTAssertThrowsError(try wait.waitForReturn(observe: {
                if stage == "observation" { throw NativeFailure.observation }
                return self.dashboard()
            }, isHittable: { _ in throw NativeFailure.hit }, close: { XCTFail("Unexpected Close") })) {
                XCTAssertTrue($0 is NativeFailure)
            }
            XCTAssertFalse(wait.closeAttempted)
        }
    }

    @MainActor
    func testInvalidHierarchyAndBoundCannotBeAccepted() {
        let invalid = [node(.other, parent: 0)]
        let oversized = Array(repeating: node(.other), count: 10_001)
        for nodes in [invalid, oversized] {
            XCTAssertThrowsError(try ExportReturnReadiness.decision(.init(frame: viewport, elements: nodes),
                homeName: home))
        }
    }
}
