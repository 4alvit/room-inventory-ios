import XCTest

@MainActor
final class NameEntryKeyboardReadinessTests: XCTestCase {
    private struct SnapshotNode {
        var item: NameEntryKeyboardReadiness.FieldItem
        var children: [SnapshotNode] = []

        init(field: Bool = false, identifier: String = "", enabled: Bool = true,
             placeholder: String? = nil, children: [SnapshotNode] = []) {
            item = .init(isTextField: field, identifier: identifier,
                         enabled: enabled, placeholder: placeholder)
            self.children = children
        }
    }

    @MainActor
    private final class Harness {
        var now = 0.0
        var observation = NameEntryKeyboardReadiness.Observation()
        var entryNameCount = 1
        var continueHittable = true
        var fieldEnabled = true
        var fieldHittable = true
        var keyboardCount = 1
        var advanceAt: [String: Double] = [:]
        var events: [String] = []
        var afterEvidence: ((NameEntryKeyboardReadiness.EvidenceStage) -> Void)?
        let allowance: NameEntryKeyboardReadiness.ContinueAllowance
        let timing: NameEntryKeyboardReadiness.Timing
        var clockReads = 0
        lazy var subject = NameEntryKeyboardReadiness(allowance: allowance, timing: timing, clock: { [unowned self] in
            self.clockReads += 1
            return self.now
        })

        init(allowance: NameEntryKeyboardReadiness.ContinueAllowance = .init(),
             timing: NameEntryKeyboardReadiness.Timing = .sharedTenSeconds) {
            self.allowance = allowance
            self.timing = timing
        }
        func stage(_ name: String) { events.append(name); now += advanceAt[name, default: 0] }
        func recordEvidence(_ value: NameEntryKeyboardReadiness.EvidenceStage) {
            stage("evidence-" + value.rawValue)
            afterEvidence?(value)
        }
        func poll(observe: (() throws -> NameEntryKeyboardReadiness.Observation)? = nil) throws -> Bool {
            try subject.poll(observe: observe ?? { self.stage("observe"); return self.observation },
                continueHittable: { self.stage("continue-hit"); return self.continueHittable },
                tapContinue: { self.stage("continue-tap") },
                entryNameCount: { self.stage("entry-count"); return self.entryNameCount },
                fieldEnabled: { self.stage("field-enabled"); return self.fieldEnabled },
                fieldHittable: { self.stage("field-hit"); return self.fieldHittable },
                keyboardCount: { self.stage("keyboard-count"); return self.keyboardCount },
                evidence: { self.recordEvidence($0) })
        }
        func tapField() throws { try subject.tapField { self.stage("field-tap") } }
        func wait(observe: (() throws -> NameEntryKeyboardReadiness.Observation)? = nil,
                  tapContinue: (() throws -> Void)? = nil,
                  keyboardCount: (() throws -> Int)? = nil) throws {
            try subject.waitForField(observe: observe ?? { self.stage("observe"); return self.observation },
                continueHittable: { self.stage("continue-hit"); return self.continueHittable },
                tapContinue: tapContinue ?? { self.stage("continue-tap") },
                entryNameCount: { self.stage("entry-count"); return self.entryNameCount },
                fieldEnabled: { self.stage("field-enabled"); return self.fieldEnabled },
                fieldHittable: { self.stage("field-hit"); return self.fieldHittable },
                keyboardCount: keyboardCount ?? { self.stage("keyboard-count"); return self.keyboardCount },
                evidence: { self.recordEvidence($0) })
        }
        func showIntroduction() {
            observation = .init(introductionCount: 1,
                exactMarkerCount: 1, continueButtonCount: 1, continueEnabled: true)
        }
    }

    func testRecognizerRequiresExactTextAndTypedButtonWithoutCountingItsTextChild() {
        typealias Item = NameEntryKeyboardReadiness.Item
        let marker = Item(kind: .text, label: NameEntryKeyboardReadiness.introductionText, enabled: true)
        let button = Item(kind: .button, label: "Continue", enabled: true)
        let child = Item(kind: .text, label: "Continue", enabled: true)
        let exact = NameEntryKeyboardReadiness.recognize(introductionCount: 1,
            items: [marker, button, child])
        XCTAssertEqual(exact.exactMarkerCount, 1)
        XCTAssertEqual(exact.continueButtonCount, 1)
        XCTAssertTrue(exact.continueEnabled)
        for items in [[Item(kind: .text, label: "Different tutorial", enabled: true), button],
                      [Item(kind: .other, label: NameEntryKeyboardReadiness.introductionText, enabled: true), button]] {
            XCTAssertEqual(NameEntryKeyboardReadiness.recognize(introductionCount: 1,
                items: items).exactMarkerCount, 0)
        }
        XCTAssertEqual(NameEntryKeyboardReadiness.recognize(introductionCount: 1,
            items: [marker, child]).continueButtonCount, 0)
        XCTAssertEqual(NameEntryKeyboardReadiness.recognize(introductionCount: 1,
            items: [marker, Item(kind: .button, label: "Continue elsewhere", enabled: true)]).continueButtonCount, 0)
        let duplicates = NameEntryKeyboardReadiness.recognize(introductionCount: 1,
            items: [marker, marker, button, button])
        XCTAssertEqual(duplicates.exactMarkerCount, 2)
        XCTAssertEqual(duplicates.continueButtonCount, 2)
        XCTAssertFalse(duplicates.continueEnabled)
    }

    func testFieldSnapshotRequiresExactTypedIdentityAndPreservesAttributes() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        let root = SnapshotNode(children: [
            .init(identifier: "entry.name"),
            .init(field: true, identifier: "entry.name.other"),
            .init(field: true, identifier: "ENTRY.NAME"),
            .init(children: [.init(field: true, identifier: "entry.name",
                                   enabled: false, placeholder: "Home name")])
        ])
        let result = try h.subject.captureNameField(snapshot: { root },
            children: { $0.children }, attributes: { $0.item })
        XCTAssertEqual(result.count, 1)
        XCTAssertEqual(result.onlyField?.enabled, false)
        XCTAssertEqual(result.onlyField?.placeholder, "Home name")
    }

    func testFieldSnapshotCountsDeepDuplicatesAndDoesNotReuseEarlierCapture() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        let field = SnapshotNode(field: true, identifier: "entry.name", placeholder: "")
        var root = SnapshotNode(children: [field])
        let capture = {
            try h.subject.captureNameField(snapshot: { root },
                children: { $0.children }, attributes: { $0.item })
        }
        XCTAssertEqual(try capture().onlyField?.placeholder, "")
        root = SnapshotNode(children: [field, .init(children: [field])])
        let duplicate = try capture()
        XCTAssertEqual(duplicate.count, 2)
        XCTAssertNil(duplicate.onlyField)
        root = SnapshotNode()
        let absent = try capture()
        XCTAssertEqual(absent.count, 0)
        XCTAssertNil(absent.onlyField)
    }

    func testFieldSnapshotRejectsOversizedTraversalBeforeVisitingChildren() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        let limit = NameEntryKeyboardReadiness.fieldSnapshotNodeLimit
        let maximum = SnapshotNode(children: Array(repeating: SnapshotNode(), count: limit - 1))
        XCTAssertEqual(try h.subject.captureNameField(snapshot: { maximum },
            children: { $0.children }, attributes: { $0.item }).count, 0)
        let oversized = SnapshotNode(children: Array(repeating: SnapshotNode(), count: limit))
        var visits = 0
        XCTAssertThrowsError(try h.subject.captureNameField(snapshot: { oversized },
            children: { $0.children }, attributes: { visits += 1; return $0.item })) {
            XCTAssertTrue($0 is NameEntryKeyboardReadiness.Failure)
        }
        XCTAssertEqual(visits, 1)
        XCTAssertThrowsError(try h.subject.captureNameField(snapshot: {
            XCTFail("A failed traversal cannot be retried"); return SnapshotNode()
        }, children: { $0.children }, attributes: { $0.item }))
    }

    func testFieldSnapshotRejectsLateCaptureAndTraversalWithoutFurtherReads() {
        let stages = ["snapshot", "attributes", "children"]
        for stage in stages {
            let h = Harness(timing: .keyboardSetupThenInput)
            var reads: [String] = []
            @MainActor func record(_ name: String) {
                reads.append(name)
                if name == stage { h.now = 30 }
            }
            XCTAssertThrowsError(try h.subject.captureNameField(snapshot: {
                record("snapshot"); return SnapshotNode(field: true, identifier: "entry.name")
            }, children: { node in
                record("children"); return node.children
            }, attributes: { node in
                record("attributes"); return node.item
            })) { XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired) }
            let expected = Array(stages.prefix(stages.firstIndex(of: stage)! + 1))
            XCTAssertEqual(reads, expected)
            h.now = 0
            XCTAssertThrowsError(try h.subject.captureNameField(snapshot: {
                XCTFail("Late capture cannot be retried"); return SnapshotNode()
            }, children: { $0.children }, attributes: { $0.item }))
        }
    }

    func testFieldSnapshotPreservesNativeErrorAfterEarlierValidCapture() throws {
        enum NativeFailure: Error { case snapshot }
        let h = Harness(timing: .keyboardSetupThenInput)
        let field = SnapshotNode(field: true, identifier: "entry.name")
        XCTAssertEqual(try h.subject.captureNameField(snapshot: { field },
            children: { $0.children }, attributes: { $0.item }).count, 1)
        XCTAssertThrowsError(try h.subject.captureNameField(snapshot: { () throws -> SnapshotNode in
            h.now = 31; throw NativeFailure.snapshot
        }, children: { $0.children }, attributes: { $0.item })) { XCTAssertTrue($0 is NativeFailure) }
        h.now = 0
        XCTAssertThrowsError(try h.subject.perform { XCTFail("Native error remains terminal") }) {
            XCTAssertTrue($0 is NativeFailure)
        }
    }

    func testAbsentTutorialRequiresLiveFieldReadinessAndOneRealTap() throws {
        let h = Harness()
        XCTAssertTrue(try h.poll())
        try h.tapField()
        XCTAssertEqual(h.events, ["observe", "entry-count", "field-enabled", "field-hit", "field-tap"])
        XCTAssertFalse(h.subject.continueAttempted)
        XCTAssertFalse(h.subject.dismissedIntroduction)
        XCTAssertThrowsError(try h.tapField())
    }

    func testExactIntroductionIsTappedOnceAndFieldWaitsForDisappearance() throws {
        let h = Harness(); h.showIntroduction()
        XCTAssertFalse(try h.poll())
        XCTAssertFalse(try h.poll())
        XCTAssertThrowsError(try h.tapField())
        XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, 1)
        XCTAssertFalse(h.events.contains("entry-count"))
        XCTAssertNil(h.subject.entryNameCount)
        XCTAssertFalse(h.events.contains("field-enabled"))
        h.observation = .init()
        XCTAssertTrue(try h.poll())
        try h.tapField()
        XCTAssertTrue(h.subject.dismissedIntroduction)
        XCTAssertEqual(h.events.filter { $0 == "field-tap" }.count, 1)
        XCTAssertEqual(h.events.filter { $0.hasPrefix("evidence-") },
            ["evidence-beforeContinue", "evidence-dismissedAndFieldReady"])
    }

    func testMissingWrongDuplicateOrDisabledEvidenceCannotAuthorizeContinue() throws {
        for kind in 0..<7 {
            let h = Harness(); h.showIntroduction()
            switch kind {
            case 0: h.observation.introductionCount = 2
            case 1: h.observation.exactMarkerCount = 0 // Includes wrong text.
            case 2: h.observation.exactMarkerCount = 2
            case 3: h.observation.continueButtonCount = 0 // Includes wrong label/type.
            case 4: h.observation.continueButtonCount = 2
            case 5: h.observation.continueEnabled = false
            default: h.continueHittable = false
            }
            XCTAssertFalse(try h.poll(), "case \(kind)")
            XCTAssertThrowsError(try h.tapField())
            XCTAssertFalse(h.events.contains("continue-tap"))
            XCTAssertFalse(h.events.contains("entry-count"))
            XCTAssertFalse(h.events.contains("field-tap"))
        }
    }

    func testIntroductionDoesNotEvaluateAThrowingEntryCountQuery() throws {
        enum NativeFailure: Error { case entryCount }
        let h = Harness(); h.showIntroduction()
        XCTAssertFalse(try h.subject.poll(observe: { h.stage("observe"); return h.observation },
            continueHittable: { h.stage("continue-hit"); return true },
            tapContinue: { h.stage("continue-tap") }, entryNameCount: {
                h.stage("unexpected-entry-count")
                throw NativeFailure.entryCount
            }, fieldEnabled: { h.stage("unexpected-field-enabled"); return true },
            fieldHittable: { h.stage("unexpected-field-hit"); return true }))
        XCTAssertEqual(h.events, ["observe", "continue-hit", "continue-tap"])
        XCTAssertTrue(h.allowance.attempted)
        XCTAssertNil(h.subject.entryNameCount)
        XCTAssertTrue(h.subject.diagnostic["entry_name_count"] is NSNull)
        XCTAssertThrowsError(try h.tapField())
    }

    func testAbsentOrDismissedIntroductionStillRequiresUniqueEntryField() throws {
        for dismissed in [false, true] {
            for count in [0, 2] {
                let h = Harness()
                if dismissed {
                    h.showIntroduction()
                    XCTAssertFalse(try h.poll())
                    h.observation = .init()
                }
                h.entryNameCount = count
                let priorEvents = h.events.count
                XCTAssertFalse(try h.poll())
                XCTAssertEqual(Array(h.events.dropFirst(priorEvents)), ["observe", "entry-count"])
                XCTAssertEqual(h.subject.entryNameCount, count)
                XCTAssertEqual(h.subject.dismissedIntroduction, dismissed)
                XCTAssertNil(h.subject.fieldEnabled)
                XCTAssertNil(h.subject.fieldHittable)
                XCTAssertThrowsError(try h.tapField())
                XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, dismissed ? 1 : 0)
            }
        }
    }

    func testLateEntryCountAfterDismissalCannotBecomeFieldEvidence() throws {
        for elapsed in [10.0, 10.001] {
            let h = Harness(); h.showIntroduction()
            XCTAssertFalse(try h.poll())
            h.observation = .init()
            h.advanceAt["entry-count"] = elapsed
            XCTAssertThrowsError(try h.poll())
            XCTAssertTrue(h.subject.dismissedIntroduction)
            XCTAssertNil(h.subject.entryNameCount)
            XCTAssertTrue(h.subject.diagnostic["entry_name_count"] is NSNull)
            XCTAssertFalse(h.events.contains("field-enabled"))
            XCTAssertThrowsError(try h.tapField())
            XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, 1)
        }
    }

    func testUnrelatedContinueWithoutOwnerDoesNotAuthorizeAnAction() throws {
        let h = Harness()
        h.observation.continueButtonCount = 1
        h.fieldHittable = false
        XCTAssertFalse(try h.poll())
        XCTAssertFalse(h.events.contains("continue-hit"))
        XCTAssertFalse(h.events.contains("continue-tap"))
        XCTAssertThrowsError(try h.tapField())
    }

    func testConsumedAllowanceCannotTapReappearingIntroductionInAnotherEntry() throws {
        let allowance = NameEntryKeyboardReadiness.ContinueAllowance()
        let first = Harness(allowance: allowance); first.showIntroduction()
        XCTAssertFalse(try first.poll())
        let second = Harness(allowance: allowance); second.showIntroduction()
        XCTAssertFalse(try second.poll())
        XCTAssertFalse(second.subject.continueAttempted)
        XCTAssertFalse(second.events.contains("continue-tap"))
        XCTAssertThrowsError(try second.tapField())
    }

    func testLateObservationCannotStartAnyLiveQueryOrTap() {
        for elapsed in [10.0, 10.001] {
            let h = Harness(); h.showIntroduction(); h.advanceAt["observe"] = elapsed
            XCTAssertThrowsError(try h.poll())
            XCTAssertEqual(h.events, ["observe"])
            XCTAssertNil(h.subject.observation)
            XCTAssertNil(h.subject.fieldEnabled)
            XCTAssertNil(h.subject.fieldHittable)
            XCTAssertTrue(h.subject.diagnostic["entry_name_count"] is NSNull)
            XCTAssertThrowsError(try h.tapField())
        }
    }

    func testLateContinueHitTestOrEvidenceCannotTap() {
        for stage in ["continue-hit", "evidence-beforeContinue"] {
            let h = Harness(); h.showIntroduction(); h.advanceAt[stage] = 10
            XCTAssertThrowsError(try h.poll())
            XCTAssertFalse(h.events.contains("continue-tap"))
            XCTAssertFalse(h.subject.continueAttempted)
        }
    }

    func testLateContinueReturnConsumesAllowanceWithoutAuthorizingField() {
        let h = Harness(); h.showIntroduction(); h.advanceAt["continue-tap"] = 10
        XCTAssertThrowsError(try h.poll())
        XCTAssertTrue(h.subject.continueAttempted)
        XCTAssertThrowsError(try h.poll())
        XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, 1)
        XCTAssertThrowsError(try h.tapField())
    }

    func testDisabledOrCoveredFieldCannotBeTappedAfterDismissal() throws {
        for disabled in [true, false] {
            let h = Harness(); h.showIntroduction(); XCTAssertFalse(try h.poll())
            h.observation = .init()
            h.fieldEnabled = !disabled
            h.fieldHittable = disabled
            XCTAssertFalse(try h.poll())
            XCTAssertThrowsError(try h.tapField())
        }
    }

    func testLateFieldStagesCannotAuthorizeTap() {
        for stage in ["entry-count", "field-enabled", "field-hit"] {
            let h = Harness(); h.advanceAt[stage] = 10
            XCTAssertThrowsError(try h.poll())
            XCTAssertThrowsError(try h.tapField())
            XCTAssertFalse(h.events.contains("field-tap"))
            if stage == "entry-count" {
                XCTAssertNil(h.subject.entryNameCount)
                XCTAssertTrue(h.subject.diagnostic["entry_name_count"] is NSNull)
                XCTAssertFalse(h.events.contains("field-enabled"))
            }
            if stage == "field-enabled" { XCTAssertFalse(h.events.contains("field-hit")) }
        }
    }

    func testDeadlineBetweenReadinessAndTapPreventsAction() throws {
        let h = Harness(); XCTAssertTrue(try h.poll()); h.now = 10
        XCTAssertThrowsError(try h.tapField())
        XCTAssertFalse(h.events.contains("field-tap"))
        XCTAssertFalse(h.subject.fieldTapAttempted)
    }

    func testLateFieldTapReturnFailsWithoutSecondTap() throws {
        let h = Harness(); XCTAssertTrue(try h.poll()); h.advanceAt["field-tap"] = 10
        XCTAssertThrowsError(try h.tapField())
        XCTAssertThrowsError(try h.tapField())
        XCTAssertEqual(h.events.filter { $0 == "field-tap" }.count, 1)
    }
    func testActualWrapperDismissesIntroductionThenTapsFieldOnce() throws {
        let h = Harness(); h.showIntroduction()
        let introduction = h.observation
        var observations = 0
        try h.subject.waitAndTapField(observe: {
            h.stage("observe")
            observations += 1
            return observations == 1 ? introduction : .init()
        }, continueHittable: { h.stage("continue-hit"); return true },
        tapContinue: { h.stage("continue-tap") },
        entryNameCount: { h.stage("entry-count"); return 1 },
        fieldEnabled: { h.stage("field-enabled"); return true },
        fieldHittable: { h.stage("field-hit"); return true },
        tapField: { h.stage("field-tap") }, evidence: { h.stage("evidence-" + $0.rawValue) })
        XCTAssertEqual(observations, 2)
        XCTAssertEqual(h.events, ["observe", "continue-hit", "evidence-beforeContinue", "continue-tap",
            "observe", "entry-count", "field-enabled", "field-hit", "evidence-dismissedAndFieldReady", "field-tap"])
        XCTAssertTrue(h.subject.dismissedIntroduction)
        XCTAssertTrue(h.subject.fieldTapAttempted)
    }

    func testActualWrapperStopsOnThrowingObservationWithoutAnyAction() {
        enum NativeFailure: Error { case observation }
        let h = Harness()
        XCTAssertThrowsError(try h.subject.waitAndTapField(observe: {
            h.stage("observe")
            throw NativeFailure.observation
        }, continueHittable: { h.stage("unexpected-continue-hit"); return true },
        tapContinue: { h.stage("unexpected-continue-tap") },
        entryNameCount: { h.stage("unexpected-entry-count"); return 1 },
        fieldEnabled: { h.stage("unexpected-field-enabled"); return true },
        fieldHittable: { h.stage("unexpected-field-hit"); return true },
        tapField: { h.stage("unexpected-field-tap") }, evidence: { _ in h.stage("unexpected-evidence") })) {
            XCTAssertTrue($0 is NativeFailure)
        }
        XCTAssertEqual(h.events, ["observe"])
        XCTAssertFalse(h.allowance.attempted)
        XCTAssertNil(h.subject.observation)
        XCTAssertFalse(h.subject.fieldTapAttempted)
    }

    func testActualWrapperKeepsConsumedContinueAllowanceAfterThrow() throws {
        enum NativeFailure: Error { case continueAction }
        let h = Harness(); h.showIntroduction()
        XCTAssertThrowsError(try h.subject.waitAndTapField(observe: {
            h.stage("observe"); return h.observation
        }, continueHittable: { h.stage("continue-hit"); return true }, tapContinue: {
            h.stage("continue-tap"); throw NativeFailure.continueAction
        }, entryNameCount: { h.stage("unexpected-entry-count"); return 1 },
        fieldEnabled: { h.stage("unexpected-field-enabled"); return true },
        fieldHittable: { h.stage("unexpected-field-hit"); return true },
        tapField: { h.stage("unexpected-field-tap") }, evidence: { h.stage("evidence-" + $0.rawValue) })) {
            XCTAssertTrue($0 is NativeFailure)
        }
        XCTAssertEqual(h.events, ["observe", "continue-hit", "evidence-beforeContinue", "continue-tap"])
        XCTAssertTrue(h.subject.continueAttempted)
        XCTAssertFalse(h.subject.fieldTapAttempted)
        let later = Harness(allowance: h.allowance); later.showIntroduction()
        XCTAssertFalse(try later.poll())
        XCTAssertEqual(later.events, ["observe"])
    }

    func testActualWrapperStopsOnThrowingEntryCountAfterDismissal() {
        enum NativeFailure: Error { case entryCount }
        let h = Harness(); h.showIntroduction()
        let introduction = h.observation
        var observations = 0
        XCTAssertThrowsError(try h.subject.waitAndTapField(observe: {
            h.stage("observe")
            observations += 1
            return observations == 1 ? introduction : .init()
        }, continueHittable: { h.stage("continue-hit"); return true },
        tapContinue: { h.stage("continue-tap") }, entryNameCount: {
            h.stage("entry-count")
            throw NativeFailure.entryCount
        }, fieldEnabled: { h.stage("unexpected-field-enabled"); return true },
        fieldHittable: { h.stage("unexpected-field-hit"); return true },
        tapField: { h.stage("unexpected-field-tap") }, evidence: { h.stage("evidence-" + $0.rawValue) })) {
            XCTAssertTrue($0 is NativeFailure)
        }
        XCTAssertEqual(h.events, ["observe", "continue-hit", "evidence-beforeContinue", "continue-tap",
            "observe", "entry-count"])
        XCTAssertEqual(observations, 2)
        XCTAssertTrue(h.subject.dismissedIntroduction)
        XCTAssertNil(h.subject.entryNameCount)
        XCTAssertFalse(h.subject.fieldTapAttempted)
        XCTAssertTrue(h.allowance.attempted)
    }

    func testExactEchoIsProbedImmediatelyAfterOneInputWithoutAnotherQuery() throws {
        let h = Harness()
        XCTAssertTrue(try h.poll())
        h.events.removeAll()
        h.now = 9.25 // A delayed first poll would miss the original deadline.
        try h.subject.perform { h.stage("type") }
        let value = try h.subject.waitForExactValue("Test Home") {
            h.stage("read")
            return "Test Home"
        }
        XCTAssertEqual(value, "Test Home")
        XCTAssertEqual(h.events, ["type", "read"])
        XCTAssertEqual(h.subject.echoDiagnostic["matched"] as? Bool, true)
        XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") {
            h.stage("unexpected-read")
            return "Test Home"
        })
        XCTAssertEqual(h.events, ["type", "read"])
    }

    func testExactEchoWaitsThroughPartialAndNilValuesWithoutRepeatingInput() throws {
        let h = Harness()
        XCTAssertTrue(try h.poll())
        h.events.removeAll()
        h.now = 6
        try h.subject.perform { h.stage("type") }
        let values: [String?] = ["Test", nil, "Test Home"]
        var reads = 0
        let value = try h.subject.waitForExactValue("Test Home") {
            h.stage("read")
            h.now += 0.5
            defer { reads += 1 }
            return values[reads]
        }
        try h.subject.perform { h.stage("record-typed"); XCTAssertEqual(value, "Test Home") }
        XCTAssertEqual(h.events, ["type", "read", "read", "read", "record-typed"])
        XCTAssertEqual(h.subject.echoDiagnostic["timely_observation_count"] as? Int, 3)
        XCTAssertEqual(h.subject.echoDiagnostic["mismatch_observed"] as? Bool, true)
        XCTAssertTrue(h.subject.echoDiagnostic["last_mismatching_value"] is NSNull)
    }

    func testExactEchoAtOrAfterOriginalDeadlineIsRejectedWithoutFurtherQueries() throws {
        for end in [10.0, 10.001] {
            let h = Harness()
            XCTAssertTrue(try h.poll())
            h.events.removeAll()
            h.now = 9.75
            try h.subject.perform { h.stage("type") }
            XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") {
                h.stage("read")
                h.now = end
                return "Test Home"
            }) {
                XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired)
            }
            XCTAssertThrowsError(try h.subject.perform { h.stage("unexpected-read") })
            XCTAssertEqual(h.events, ["type", "read"])
            XCTAssertEqual(h.subject.echoDiagnostic["timely_observation_count"] as? Int, 0)
            XCTAssertEqual(h.subject.echoDiagnostic["matched"] as? Bool, false)
        }
    }

    func testExactEchoPreservesQueryErrorEvenWhenLateWithoutRepeatingInput() throws {
        enum NativeFailure: Error { case read }
        for late in [false, true] {
            let h = Harness()
            XCTAssertTrue(try h.poll())
            h.events.removeAll()
            h.now = 9.75
            try h.subject.perform { h.stage("type") }
            XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") {
                h.stage("read")
                if late { h.now = 10 }
                throw NativeFailure.read
            }) {
                XCTAssertTrue($0 is NativeFailure)
            }
            XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") {
                h.stage("unexpected-read")
                return "Test Home"
            })
            XCTAssertEqual(h.events, ["type", "read"])
            XCTAssertEqual(h.subject.echoDiagnostic["timely_observation_count"] as? Int, 0)
        }
    }

    func testLateEchoIntroductionRequiresFreshAbsenceAfterOneContinue() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        _ = h.subject
        h.now = 20
        try h.wait()
        h.events.removeAll()
        try h.subject.typeTextOnce { h.stage("type"); h.now += 1 }
        h.showIntroduction()
        let value = try h.subject.waitForExactValue("Test Home", observeIntroduction: {
            h.stage("observe"); h.now += 0.25; return h.observation
        }, continueHittable: { h.stage("continue-hit"); return true }, tapContinue: {
            h.stage("continue-tap"); h.now += 1; h.observation = .init()
        }) {
            h.stage("read"); h.now += 1; return "Test Home"
        }
        XCTAssertEqual(value, "Test Home")
        XCTAssertEqual(h.events, ["type", "observe", "continue-hit", "continue-tap", "observe", "read", "observe"])
        XCTAssertTrue(h.subject.dismissedIntroduction)
        XCTAssertTrue(h.allowance.attempted)
        XCTAssertFalse(h.subject.fieldTapAttempted)
        XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("Input cannot repeat after Continue") })
        let clockReads = h.clockReads
        let diagnostic = h.subject.echoDiagnostic
        XCTAssertEqual(diagnostic["setup_elapsed_seconds"] as? Double, 20)
        XCTAssertEqual(diagnostic["input_elapsed_seconds"] as? Double, 3.75)
        XCTAssertEqual(diagnostic["echo_introduction_observation_count"] as? Int, 3)
        XCTAssertEqual(diagnostic["echo_introduction_count"] as? Int, 0)
        XCTAssertEqual(diagnostic["echo_saw_introduction"] as? Bool, true)
        XCTAssertEqual(diagnostic["echo_continue_attempted_once"] as? Bool, true)
        XCTAssertEqual(diagnostic["timely_observation_count"] as? Int, 1)
        XCTAssertEqual(diagnostic["matched"] as? Bool, true)
        XCTAssertLessThanOrEqual(try JSONSerialization.data(withJSONObject: diagnostic).count, 4096)
        XCTAssertEqual(h.clockReads, clockReads)
    }

    func testIntroductionArrivingDuringExactEchoDiscardsValueUntilNewRead() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        try h.wait()
        h.events.removeAll()
        try h.subject.typeTextOnce { h.stage("type") }
        var reads = 0
        let value = try h.subject.waitForExactValue("Test Home", observeIntroduction: {
            h.stage("observe"); return h.observation
        }, continueHittable: { h.stage("continue-hit"); return true }, tapContinue: {
            h.stage("continue-tap"); h.observation = .init()
        }) {
            h.stage("read"); reads += 1
            if reads == 1 { h.showIntroduction() }
            return "Test Home"
        }
        XCTAssertEqual(value, "Test Home")
        XCTAssertEqual(reads, 2)
        XCTAssertEqual(h.events, ["type", "observe", "read", "observe", "continue-hit", "continue-tap",
                                 "observe", "read", "observe"])
        XCTAssertEqual(h.subject.echoDiagnostic["timely_observation_count"] as? Int, 2)
        XCTAssertEqual(h.subject.echoDiagnostic["echo_continue_attempted_once"] as? Bool, true)
        XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("Never retype after a late introduction") })
    }

    func testEchoBlockedByUnrecognizedDisabledOrConsumedIntroductionDoesNotReadOrAct() throws {
        for kind in 0..<8 {
            let allowance = NameEntryKeyboardReadiness.ContinueAllowance()
            if kind == 7 {
                let previous = Harness(allowance: allowance)
                previous.showIntroduction()
                XCTAssertFalse(try previous.poll())
            }
            let h = Harness(allowance: allowance, timing: .keyboardSetupThenInput)
            try h.wait()
            h.events.removeAll()
            try h.subject.typeTextOnce { h.stage("type") }
            h.now = 9.5
            h.showIntroduction()
            switch kind {
            case 0: h.observation.introductionCount = 2
            case 1: h.observation.exactMarkerCount = 0
            case 2: h.observation.exactMarkerCount = 2
            case 3: h.observation.continueButtonCount = 0
            case 4: h.observation.continueButtonCount = 2
            case 5: h.observation.continueEnabled = false
            case 6: h.continueHittable = false
            default: break
            }
            XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home", observeIntroduction: {
                h.stage("observe"); h.now += 0.25; return h.observation
            }, continueHittable: { h.stage("continue-hit"); return h.continueHittable }, tapContinue: {
                XCTFail("Unrecognized or already consumed Continue cannot act")
            }) {
                XCTFail("A known present owner blocks even an exact value"); return "Test Home"
            })
            XCTAssertFalse(h.subject.continueAttempted)
            XCTAssertEqual(h.allowance.attempted, kind == 7)
            XCTAssertEqual(h.events.filter { $0 == "continue-hit" }.count, kind == 6 ? 1 : 0)
            XCTAssertEqual(h.subject.echoDiagnostic["timely_observation_count"] as? Int, 0)
            XCTAssertEqual(h.subject.echoDiagnostic["matched"] as? Bool, false)
        }
    }

    func testPersistentEchoIntroductionCannotPassOrTapAgain() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        try h.wait()
        h.events.removeAll()
        try h.subject.typeTextOnce { h.stage("type") }
        h.now = 8.5
        h.showIntroduction()
        XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home", observeIntroduction: {
            h.stage("observe"); h.now += 0.25; return h.observation
        }, continueHittable: { h.stage("continue-hit"); return true }, tapContinue: {
            h.stage("continue-tap") // Deliberately leave the owner present.
        }) {
            XCTFail("A tap cannot stand in for owner disappearance"); return "Test Home"
        })
        XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, 1)
        XCTAssertEqual(h.events.filter { $0 == "continue-hit" }.count, 1)
        XCTAssertFalse(h.subject.dismissedIntroduction)
        XCTAssertEqual(h.subject.echoDiagnostic["echo_introduction_count"] as? Int, 1)
        XCTAssertEqual(h.subject.echoDiagnostic["echo_continue_attempted_once"] as? Bool, true)
        XCTAssertEqual(h.subject.echoDiagnostic["matched"] as? Bool, false)
        let events = h.events
        h.now = 0
        XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("Input cannot be retried") })
        XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") { XCTFail("Echo cannot restart"); return "Test Home" })
        XCTAssertEqual(h.events, events)
    }

    func testEveryLateEchoIntroductionStageRetainsOriginalInputDeadline() throws {
        for end in [10.0, 10.001] {
            for stage in ["observe", "continue-hit", "continue-tap", "read", "final-observe"] {
                let h = Harness(timing: .keyboardSetupThenInput)
                try h.wait()
                h.events.removeAll()
                try h.subject.typeTextOnce { h.stage("type") }
                h.now = 9.75
                if stage.hasPrefix("continue-") { h.showIntroduction() }
                var observations = 0
                @MainActor func record(_ name: String) {
                    h.stage(name)
                    if name == stage { h.now = end }
                }
                XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home", observeIntroduction: {
                    observations += 1
                    record(observations == 1 ? "observe" : "final-observe")
                    return h.observation
                }, continueHittable: { record("continue-hit"); return true }, tapContinue: {
                    record("continue-tap")
                }) { record("read"); return "Test Home" }) {
                    XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired, stage)
                }
                XCTAssertEqual(h.events.last, stage)
                XCTAssertEqual(h.subject.echoDiagnostic["matched"] as? Bool, false)
                XCTAssertEqual(h.allowance.attempted, stage == "continue-tap")
                let events = h.events
                h.now = 0
                XCTAssertThrowsError(try h.subject.perform { XCTFail("Late stage remains terminal") })
                XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("No retyping") })
                XCTAssertThrowsError(try h.wait())
                XCTAssertEqual(h.events, events)
            }
        }
    }

    func testThrowingEchoIntroductionStagesPreserveErrorAndConsumedAction() throws {
        enum NativeFailure: Error { case operation }
        for stage in ["observe", "continue-hit", "continue-tap", "read", "final-observe"] {
            let h = Harness(timing: .keyboardSetupThenInput)
            try h.wait()
            h.events.removeAll()
            try h.subject.typeTextOnce { h.stage("type") }
            h.now = 9.75
            if stage.hasPrefix("continue-") { h.showIntroduction() }
            var observations = 0
            @MainActor func record(_ name: String) throws {
                h.stage(name)
                if name == stage { h.now = 11; throw NativeFailure.operation }
            }
            XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home", observeIntroduction: {
                observations += 1
                try record(observations == 1 ? "observe" : "final-observe")
                return h.observation
            }, continueHittable: { try record("continue-hit"); return true }, tapContinue: {
                try record("continue-tap")
            }) { try record("read"); return "Test Home" }) { XCTAssertTrue($0 is NativeFailure, stage) }
            XCTAssertEqual(h.events.last, stage)
            XCTAssertEqual(h.allowance.attempted, stage == "continue-tap")
            XCTAssertEqual(h.subject.echoDiagnostic["echo_continue_attempted_once"] as? Bool, stage == "continue-tap")
            XCTAssertEqual(h.subject.echoDiagnostic["matched"] as? Bool, false)
            let events = h.events
            h.now = 0
            XCTAssertThrowsError(try h.subject.perform { XCTFail("Preserve original error") }) { XCTAssertTrue($0 is NativeFailure) }
            XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("No retyping") })
            XCTAssertEqual(h.events, events)
        }
    }

    func testUnmatchedEchoTimeoutRetainsBoundedLastValueForFailureDiagnostic() throws {
        let cases = [(String(repeating: "\n", count: 1000), String(repeating: "\n", count: 256)),
                     (String(repeating: "a", count: 255) + "😀", String(repeating: "a", count: 255))]
        for (mismatch, expectedPrefix) in cases {
            let h = Harness()
            XCTAssertTrue(try h.poll())
            h.events.removeAll()
            h.now = 9.5
            try h.subject.perform { h.stage("type") }
            XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") {
                h.stage("read")
                return mismatch
            })
            var diagnostic = h.subject.echoDiagnostic
            diagnostic["result"] = "failed"
            diagnostic["stage"] = "echo"
            let retained = try XCTUnwrap(diagnostic["last_mismatching_value"] as? String)
            XCTAssertEqual(retained, expectedPrefix)
            XCTAssertLessThanOrEqual(retained.utf8.count, 256)
            XCTAssertEqual(diagnostic["last_mismatching_value_truncated"] as? Bool, true)
            XCTAssertEqual(diagnostic["matched"] as? Bool, false)
            XCTAssertEqual(diagnostic["timely_observation_count"] as? Int, 1)
            XCTAssertLessThanOrEqual(try JSONSerialization.data(withJSONObject: diagnostic).count, 4096)
            XCTAssertEqual(h.events, ["type", "read"])
        }
    }

    func testSplitSetupCanCompleteAfterTenSecondsThenUseOneSeparateInputWindow() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        h.showIntroduction()
        var observations = 0
        try h.wait(observe: {
            h.stage("observe")
            observations += 1
            if observations <= 2 { h.now += 12 }
            return observations == 1 ? h.observation : .init()
        })
        XCTAssertEqual(h.now, 24)
        XCTAssertEqual(observations, 3)
        XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, 1)
        XCTAssertTrue(h.subject.dismissedIntroduction)
        try h.subject.typeTextOnce { h.stage("type"); h.now += 5 }
        XCTAssertEqual(try h.subject.waitForExactValue("Test Home") {
            h.stage("read"); h.now += 2; return "Test Home"
        }, "Test Home")
        XCTAssertEqual(h.now, 31) // Beyond setup's deadline, within the one input window.
        let reads = h.clockReads
        let diagnostic = h.subject.echoDiagnostic
        XCTAssertEqual(diagnostic["setup_elapsed_seconds"] as? Double, 24)
        XCTAssertEqual(diagnostic["input_elapsed_seconds"] as? Double, 7)
        XCTAssertEqual(diagnostic["active_phase"] as? String, "input")
        XCTAssertEqual(diagnostic["input_attempted_once"] as? Bool, true)
        XCTAssertLessThanOrEqual(try JSONSerialization.data(withJSONObject: diagnostic).count, 4096)
        XCTAssertEqual(h.clockReads, reads)
        XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
        XCTAssertFalse(h.events.contains("field-tap"))
        XCTAssertEqual(h.events.suffix(2), ["type", "read"])
    }

    func testAutofocusedSetupSkipsCoordinateHitTestAfterKeyboardIntroduction() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        h.showIntroduction()
        h.fieldHittable = false
        h.advanceAt["field-hit"] = 100 // This query must never run in the autofocus path.
        var observations = 0
        try h.wait(observe: {
            h.stage("observe")
            observations += 1
            if observations == 1 { h.now = 12; return h.observation }
            h.now = 24
            return .init()
        })
        XCTAssertEqual(h.events, ["observe", "continue-hit", "evidence-beforeContinue", "continue-tap",
            "observe", "entry-count", "field-enabled", "keyboard-count", "evidence-dismissedAndFieldReady", "observe"])
        XCTAssertNil(h.subject.fieldHittable) // Unknown, never fabricated as true.
        XCTAssertEqual(h.subject.entryNameCount, 1)
        XCTAssertEqual(h.subject.fieldEnabled, true)
        XCTAssertThrowsError(try h.tapField())
        try h.subject.typeTextOnce { h.stage("type"); h.now = 29 }
        XCTAssertEqual(try h.subject.waitForExactValue("Test Home") {
            h.stage("echo"); h.now = 31; return "Test Home"
        }, "Test Home")
        XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
        XCTAssertEqual(h.events.suffix(2), ["type", "echo"])

        let shared = Harness()
        shared.fieldHittable = false
        XCTAssertFalse(try shared.poll())
        XCTAssertEqual(shared.events, ["observe", "entry-count", "field-enabled", "field-hit"])
        XCTAssertThrowsError(try shared.tapField())
    }

    func testAutofocusedInputWaitsForKeyboardWithinSetupWindow() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        var observations = 0
        try h.wait(keyboardCount: {
            h.stage("keyboard-count")
            observations += 1
            h.now += observations == 1 ? 4 : 8
            XCTAssertTrue(h.subject.echoDiagnostic["input_elapsed_seconds"] is NSNull)
            XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("Keyboard is not ready") })
            return observations == 1 ? 0 : 1
        })
        XCTAssertEqual(observations, 2)
        XCTAssertEqual(h.subject.keyboardCount, 1)
        XCTAssertEqual(h.subject.echoDiagnostic["keyboard_count"] as? Int, 1)
        XCTAssertEqual(h.subject.echoDiagnostic["setup_elapsed_seconds"] as? Double, 12)
        try h.subject.typeTextOnce { h.stage("type"); h.now += 3 }
        XCTAssertEqual(try h.subject.waitForExactValue("Test Home") {
            h.stage("echo"); h.now += 2; return "Test Home"
        }, "Test Home")
        XCTAssertEqual(h.subject.echoDiagnostic["input_elapsed_seconds"] as? Double, 5)
        XCTAssertFalse(h.events.contains("field-tap"))
        XCTAssertFalse(h.events.contains("field-hit"))
    }

    func testMissingOrDuplicateKeyboardCannotStartInputOrRenewSetup() {
        for count in [0, 2] {
            let h = Harness(timing: .keyboardSetupThenInput)
            h.keyboardCount = count
            h.advanceAt["keyboard-count"] = 16
            XCTAssertThrowsError(try h.wait()) {
                XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired)
            }
            XCTAssertEqual(h.subject.echoDiagnostic["setup_completed"] as? Bool, false)
            XCTAssertTrue(h.subject.echoDiagnostic["input_elapsed_seconds"] is NSNull)
            let events = h.events
            h.now = 0
            XCTAssertThrowsError(try h.wait())
            XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("No unique keyboard") })
            XCTAssertEqual(h.events, events)
        }
    }

    func testKeyboardPresentationRechecksLateIntroductionBeforeInput() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        var keyboards = 0
        try h.wait(tapContinue: {
            h.stage("continue-tap")
            h.observation = .init()
        }, keyboardCount: {
            h.stage("keyboard-count")
            keyboards += 1
            if keyboards == 1 { h.showIntroduction() }
            return 1
        })
        XCTAssertEqual(keyboards, 2)
        XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, 1)
        XCTAssertTrue(h.subject.dismissedIntroduction)
        XCTAssertEqual(h.subject.diagnostic["keyboard_count"] as? Int, 1)
        try h.subject.typeTextOnce { h.stage("type") }
        XCTAssertEqual(h.events.filter { $0 == "type" }.count, 1)
        XCTAssertFalse(h.events.contains("field-tap"))
    }

    func testKeyboardObservationPreservesNativeErrorAndCancellation() {
        enum NativeFailure: Error { case keyboard }
        for cancelled in [false, true] {
            let h = Harness(timing: .keyboardSetupThenInput)
            XCTAssertThrowsError(try h.wait(keyboardCount: {
                h.stage("keyboard-count")
                h.now = 31
                if cancelled { throw CancellationError() }
                throw NativeFailure.keyboard
            })) {
                if cancelled { XCTAssertTrue($0 is CancellationError) }
                else { XCTAssertTrue($0 is NativeFailure) }
            }
            XCTAssertEqual(h.events, ["observe", "entry-count", "field-enabled", "keyboard-count"])
            XCTAssertNil(h.subject.keyboardCount)
            XCTAssertTrue(h.subject.echoDiagnostic["keyboard_count"] is NSNull)
            XCTAssertTrue(h.subject.echoDiagnostic["input_elapsed_seconds"] is NSNull)
            let events = h.events
            h.now = 0
            XCTAssertThrowsError(try h.wait())
            XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("Observation failed") })
            XCTAssertEqual(h.events, events)
        }
    }

    func testTapBasedEntryDoesNotRequireAnExistingSoftwareKeyboard() throws {
        let h = Harness()
        h.keyboardCount = 0
        h.advanceAt["keyboard-count"] = 100
        try h.wait()
        try h.tapField()
        XCTAssertNil(h.subject.keyboardCount)
        XCTAssertFalse(h.events.contains("keyboard-count"))
        XCTAssertEqual(h.events.suffix(2), ["field-hit", "field-tap"])
    }

    func testBothInputModesStillRejectMissingDuplicateAndDisabledFields() throws {
        for timing in [NameEntryKeyboardReadiness.Timing.sharedTenSeconds, .keyboardSetupThenInput] {
            for (count, enabled) in [(0, true), (2, true), (1, false)] {
                let h = Harness(timing: timing)
                h.entryNameCount = count
                h.fieldEnabled = enabled
                XCTAssertFalse(try h.poll())
                XCTAssertFalse(h.events.contains("field-hit"))
                XCTAssertThrowsError(try h.tapField())
                XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("Invalid field cannot receive input") })
                XCTAssertEqual(h.events.filter { $0 == "observe" }.count, 1)
            }
        }
    }

    func testSplitSetupExactOrLateOperationsCannotActivateInputOrRestart() {
        for end in [30.0, 30.001] {
            for stage in ["observe", "continue-hit", "continue-tap", "entry-count", "field-enabled", "keyboard-count"] {
                let h = Harness(timing: .keyboardSetupThenInput)
                _ = h.subject // Start the immutable setup window at zero.
                h.now = 29.99
                if stage.hasPrefix("continue-") { h.showIntroduction() }
                h.advanceAt[stage] = end - h.now
                XCTAssertThrowsError(try h.wait(), stage) {
                    XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired)
                }
                let events = h.events
                XCTAssertEqual(h.subject.echoDiagnostic["setup_completed"] as? Bool, false)
                XCTAssertTrue(h.subject.echoDiagnostic["input_elapsed_seconds"] is NSNull)
                h.now = 0 // Even a clock rollback cannot revive a failed setup.
                XCTAssertThrowsError(try h.wait())
                XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
                XCTAssertEqual(h.events, events)
                XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, stage == "continue-tap" ? 1 : 0)
            }
        }
    }

    func testSplitSetupNativeErrorStaysTerminalAndPreservesConsumedContinue() {
        enum NativeFailure: Error { case action }
        let h = Harness(timing: .keyboardSetupThenInput)
        h.showIntroduction()
        _ = h.subject
        h.now = 29.99
        XCTAssertThrowsError(try h.wait(tapContinue: {
            h.stage("continue-tap"); h.now = 31; throw NativeFailure.action
        })) { XCTAssertTrue($0 is NativeFailure) }
        let events = h.events
        h.now = 0
        XCTAssertThrowsError(try h.wait()) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertThrowsError(try h.subject.perform { h.stage("unexpected-query") }) {
            XCTAssertTrue($0 is NativeFailure)
        }
        XCTAssertEqual(h.events, events)
        XCTAssertTrue(h.allowance.attempted)
        let later = Harness(allowance: h.allowance, timing: .keyboardSetupThenInput)
        later.showIntroduction()
        XCTAssertFalse(try later.poll())
        XCTAssertEqual(later.events, ["observe"])
    }

    func testSplitInputRequiresCompletedWaitAndCannotRenewEitherPhase() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        XCTAssertTrue(try h.poll())
        XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
        XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") {
            h.stage("unexpected-read"); return "Test Home"
        })
        h.now = 20
        try h.wait()
        let events = h.events
        XCTAssertThrowsError(try h.wait())
        XCTAssertThrowsError(try h.poll())
        XCTAssertThrowsError(try h.tapField())
        h.now = 30
        XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") }) {
            XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired)
        }
        XCTAssertThrowsError(try h.wait())
        XCTAssertEqual(h.events, events)
    }

    func testSplitInitialReadInputAndEchoRejectExactOrLateInputDeadline() throws {
        for end in [30.0, 30.001] {
            for stage in ["initial-value", "type", "echo"] {
                let h = Harness(timing: .keyboardSetupThenInput)
                _ = h.subject
                h.now = 20
                try h.wait()
                h.events.removeAll()
                h.now = 29.99
                if stage == "initial-value" {
                    XCTAssertThrowsError(try h.subject.perform { h.stage(stage); h.now = end })
                } else if stage == "type" {
                    XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage(stage); h.now = end })
                } else {
                    try h.subject.typeTextOnce { h.stage("type") }
                    XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") {
                        h.stage(stage); h.now = end; return "Test Home"
                    })
                }
                let events = h.events
                XCTAssertThrowsError(try h.subject.perform { h.stage("unexpected-query") })
                XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
                XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") {
                    h.stage("unexpected-echo"); return "Test Home"
                })
                XCTAssertThrowsError(try h.wait())
                XCTAssertEqual(h.events, events)
                XCTAssertEqual(h.subject.echoDiagnostic["matched"] as? Bool, false)
            }
        }
    }

    func testSplitThrowingInputIsNotRepeatedOrFollowedByEcho() throws {
        enum NativeFailure: Error { case input }
        let h = Harness(timing: .keyboardSetupThenInput)
        try h.wait()
        h.events.removeAll()
        XCTAssertThrowsError(try h.subject.typeTextOnce {
            h.stage("type"); h.now = 11; throw NativeFailure.input
        }) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
        XCTAssertThrowsError(try h.subject.waitForExactValue("Test Home") {
            h.stage("unexpected-read"); return "Test Home"
        }) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertEqual(h.events, ["type"])
        XCTAssertEqual(h.subject.echoDiagnostic["input_attempted_once"] as? Bool, true)
    }

    func testSplitWaitRejectsReentryAndLeavesNoPendingProbe() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        try h.wait(observe: {
            h.stage("observe")
            XCTAssertThrowsError(try h.wait())
            XCTAssertThrowsError(try h.poll())
            RunLoop.main.run(until: Date().addingTimeInterval(0.02))
            return .init()
        })
        let events = h.events
        RunLoop.main.run(until: Date().addingTimeInterval(1.05))
        XCTAssertEqual(h.events, events)
        XCTAssertEqual(h.events.filter { $0 == "observe" }.count, 2)
        XCTAssertEqual(h.subject.echoDiagnostic["setup_completed"] as? Bool, true)
    }

    func testSplitFinalObservationCatchesLateIntroductionBeforeSingleInput() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        h.showIntroduction()
        let introduction = h.observation
        var observations = 0
        try h.wait(observe: {
            h.stage("observe")
            observations += 1
            if observations == 2 {
                XCTAssertEqual(h.events.suffix(4), ["entry-count", "field-enabled", "keyboard-count", "observe"])
                XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
                XCTAssertTrue(h.subject.echoDiagnostic["input_elapsed_seconds"] is NSNull)
            }
            return observations == 2 ? introduction : .init()
        }, tapContinue: {
            h.stage("continue-tap")
            XCTAssertEqual(observations, 2)
            XCTAssertTrue(h.subject.echoDiagnostic["input_elapsed_seconds"] is NSNull)
        })
        XCTAssertEqual(observations, 4)
        XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, 1)
        XCTAssertEqual(h.events.filter { $0 == "entry-count" }.count, 2)
        XCTAssertTrue(h.subject.dismissedIntroduction)
        XCTAssertEqual(h.subject.echoDiagnostic["setup_completed"] as? Bool, true)
        try h.subject.typeTextOnce { h.stage("type") }
        XCTAssertEqual(try h.subject.waitForExactValue("Test Home") {
            h.stage("echo"); return "Test Home"
        }, "Test Home")
        XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
        XCTAssertEqual(h.events.filter { $0 == "type" }.count, 1)
        XCTAssertFalse(h.events.contains("unexpected-type"))
    }

    func testSplitFinalIntroductionRequiresEnabledHittableUnconsumedContinue() throws {
        for mode in 0..<3 {
            let allowance = NameEntryKeyboardReadiness.ContinueAllowance()
            if mode == 2 {
                let prior = Harness(allowance: allowance)
                prior.showIntroduction()
                XCTAssertFalse(try prior.poll())
            }
            let h = Harness(allowance: allowance, timing: .keyboardSetupThenInput)
            h.showIntroduction()
            if mode == 0 { h.observation.continueEnabled = false }
            if mode == 1 { h.continueHittable = false }
            var observations = 0
            XCTAssertFalse(try h.poll(observe: {
                observations += 1
                return observations == 1 ? .init() : h.observation
            }))
            XCTAssertEqual(observations, 2)
            XCTAssertFalse(h.events.contains("continue-tap"))
            XCTAssertFalse(h.subject.continueAttempted)
            XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("Input is not ready") })
        }
    }

    func testSplitFinalIntroductionThrowConsumesAllowanceWithoutAdmittingInput() {
        enum NativeFailure: Error { case tap }
        let h = Harness(timing: .keyboardSetupThenInput)
        h.showIntroduction()
        var observations = 0
        XCTAssertThrowsError(try h.wait(observe: {
            observations += 1
            return observations == 1 ? .init() : h.observation
        }, tapContinue: {
            h.stage("continue-tap"); h.now = 31; throw NativeFailure.tap
        })) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertEqual(observations, 2)
        XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, 1)
        XCTAssertTrue(h.allowance.attempted)
        XCTAssertTrue(h.subject.echoDiagnostic["input_elapsed_seconds"] is NSNull)
        h.now = 0
        XCTAssertThrowsError(try h.subject.typeTextOnce { XCTFail("Input must remain forbidden") })
        XCTAssertThrowsError(try h.wait()) { XCTAssertTrue($0 is NativeFailure) }
    }

    func testSplitFinalObservationBlocksUnknownAndDuplicateOwners() throws {
        for count in [1, 2] {
            let h = Harness(timing: .keyboardSetupThenInput)
            var observations = 0
            XCTAssertFalse(try h.poll(observe: {
                h.stage("observe")
                observations += 1
                return observations == 1 ? .init() : .init(introductionCount: count)
            }))
            XCTAssertEqual(observations, 2)
            XCTAssertFalse(h.subject.dismissedIntroduction)
            XCTAssertEqual(h.subject.diagnostic["introduction_count"] as? Int, count)
            XCTAssertEqual(h.subject.diagnostic["saw_introduction"] as? Bool, true)
            XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
            h.observation = .init(introductionCount: count)
            XCTAssertFalse(try h.poll())
            XCTAssertEqual(h.events.filter { $0 == "entry-count" }.count, 1)
            XCTAssertFalse(h.events.contains("continue-tap"))
            XCTAssertFalse(h.events.contains("unexpected-type"))
        }
    }

    func testSplitFinalObservationRunsAfterDismissalEvidenceAndDoesNotRetap() throws {
        let h = Harness(timing: .keyboardSetupThenInput)
        h.showIntroduction()
        XCTAssertFalse(try h.poll())
        h.observation = .init()
        h.afterEvidence = { [unowned h] stage in
            if stage == .dismissedAndFieldReady { h.showIntroduction() }
        }
        XCTAssertFalse(try h.poll())
        XCTAssertEqual(h.events.suffix(2), ["evidence-dismissedAndFieldReady", "observe"])
        XCTAssertFalse(h.subject.dismissedIntroduction)
        XCTAssertFalse(try h.poll())
        XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
        XCTAssertEqual(h.events.filter { $0 == "continue-tap" }.count, 1)
        XCTAssertFalse(h.events.contains("unexpected-type"))
    }

    func testSplitFinalObservationAtDeadlineCannotPublishInputOrRestart() {
        for end in [30.0, 30.001] {
            let h = Harness(timing: .keyboardSetupThenInput)
            var observations = 0
            XCTAssertThrowsError(try h.wait(observe: {
                h.stage("observe")
                observations += 1
                if observations == 2 { h.now = end }
                return .init()
            })) { XCTAssertEqual($0 as? RecoveryOCRReadinessWindow.Failure, .expired) }
            XCTAssertEqual(observations, 2)
            XCTAssertEqual(h.subject.echoDiagnostic["setup_completed"] as? Bool, false)
            XCTAssertTrue(h.subject.echoDiagnostic["input_elapsed_seconds"] is NSNull)
            let events = h.events
            h.now = 0
            XCTAssertThrowsError(try h.wait())
            XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
            XCTAssertEqual(h.events, events)
        }
    }

    func testSplitFinalObservationPreservesLateNativeError() {
        enum NativeFailure: Error { case observation }
        let h = Harness(timing: .keyboardSetupThenInput)
        var observations = 0
        XCTAssertThrowsError(try h.wait(observe: {
            h.stage("observe")
            observations += 1
            if observations == 2 { h.now = 31; throw NativeFailure.observation }
            return .init()
        })) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertEqual(observations, 2)
        XCTAssertEqual(h.subject.echoDiagnostic["setup_completed"] as? Bool, false)
        XCTAssertTrue(h.subject.echoDiagnostic["input_elapsed_seconds"] is NSNull)
        let events = h.events
        h.now = 0
        XCTAssertThrowsError(try h.wait()) { XCTAssertTrue($0 is NativeFailure) }
        XCTAssertThrowsError(try h.subject.perform { h.stage("unexpected-query") }) {
            XCTAssertTrue($0 is NativeFailure)
        }
        XCTAssertThrowsError(try h.subject.typeTextOnce { h.stage("unexpected-type") })
        XCTAssertEqual(h.events, events)
    }

    func testSharedWindowDoesNotPerformSplitFinalObservation() throws {
        enum UnexpectedObservation: Error { case repeated }
        let h = Harness()
        var observations = 0
        try h.wait(observe: {
            h.stage("observe")
            observations += 1
            if observations > 1 { throw UnexpectedObservation.repeated }
            return .init()
        })
        try h.tapField()
        XCTAssertEqual(observations, 1)
        XCTAssertEqual(h.events, ["observe", "entry-count", "field-enabled", "field-hit", "field-tap"])
        XCTAssertEqual(h.subject.echoDiagnostic["timing_mode"] as? String, "shared_ten_seconds")
    }

}
