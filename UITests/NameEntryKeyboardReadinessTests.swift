import XCTest

@MainActor
final class NameEntryKeyboardReadinessTests: XCTestCase {
    @MainActor
    private final class Harness {
        var now = 0.0
        var observation = NameEntryKeyboardReadiness.Observation(entryNameCount: 1)
        var continueHittable = true
        var fieldEnabled = true
        var fieldHittable = true
        var advanceAt: [String: Double] = [:]
        var events: [String] = []
        let allowance: NameEntryKeyboardReadiness.ContinueAllowance
        lazy var subject = NameEntryKeyboardReadiness(allowance: allowance, clock: { [unowned self] in self.now })

        init(allowance: NameEntryKeyboardReadiness.ContinueAllowance = .init()) { self.allowance = allowance }
        func stage(_ name: String) { events.append(name); now += advanceAt[name, default: 0] }
        func poll() throws -> Bool {
            try subject.poll(observe: { self.stage("observe"); return self.observation },
                continueHittable: { self.stage("continue-hit"); return self.continueHittable },
                tapContinue: { self.stage("continue-tap") },
                fieldEnabled: { self.stage("field-enabled"); return self.fieldEnabled },
                fieldHittable: { self.stage("field-hit"); return self.fieldHittable },
                evidence: { self.stage("evidence-" + $0.rawValue) })
        }
        func tapField() throws { try subject.tapField { self.stage("field-tap") } }
        func showIntroduction() {
            observation = .init(entryNameCount: 1, introductionCount: 1,
                exactMarkerCount: 1, continueButtonCount: 1, continueEnabled: true)
        }
    }

    func testRecognizerRequiresExactTextAndTypedButtonWithoutCountingItsTextChild() {
        typealias Item = NameEntryKeyboardReadiness.Item
        let marker = Item(kind: .text, label: NameEntryKeyboardReadiness.introductionText, enabled: true)
        let button = Item(kind: .button, label: "Continue", enabled: true)
        let child = Item(kind: .text, label: "Continue", enabled: true)
        let exact = NameEntryKeyboardReadiness.recognize(entryNameCount: 1, introductionCount: 1,
            items: [marker, button, child])
        XCTAssertEqual(exact.exactMarkerCount, 1)
        XCTAssertEqual(exact.continueButtonCount, 1)
        XCTAssertTrue(exact.continueEnabled)
        for items in [[Item(kind: .text, label: "Different tutorial", enabled: true), button],
                      [Item(kind: .other, label: NameEntryKeyboardReadiness.introductionText, enabled: true), button]] {
            XCTAssertEqual(NameEntryKeyboardReadiness.recognize(entryNameCount: 1, introductionCount: 1,
                items: items).exactMarkerCount, 0)
        }
        XCTAssertEqual(NameEntryKeyboardReadiness.recognize(entryNameCount: 1, introductionCount: 1,
            items: [marker, child]).continueButtonCount, 0)
        XCTAssertEqual(NameEntryKeyboardReadiness.recognize(entryNameCount: 1, introductionCount: 1,
            items: [marker, Item(kind: .button, label: "Continue elsewhere", enabled: true)]).continueButtonCount, 0)
        let duplicates = NameEntryKeyboardReadiness.recognize(entryNameCount: 1, introductionCount: 1,
            items: [marker, marker, button, button])
        XCTAssertEqual(duplicates.exactMarkerCount, 2)
        XCTAssertEqual(duplicates.continueButtonCount, 2)
        XCTAssertFalse(duplicates.continueEnabled)
    }

    func testAbsentTutorialRequiresLiveFieldReadinessAndOneRealTap() throws {
        let h = Harness()
        XCTAssertTrue(try h.poll())
        try h.tapField()
        XCTAssertEqual(h.events, ["observe", "field-enabled", "field-hit", "field-tap"])
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
        XCTAssertFalse(h.events.contains("field-enabled"))
        h.observation = .init(entryNameCount: 1)
        XCTAssertTrue(try h.poll())
        try h.tapField()
        XCTAssertTrue(h.subject.dismissedIntroduction)
        XCTAssertEqual(h.events.filter { $0 == "field-tap" }.count, 1)
        XCTAssertEqual(h.events.filter { $0.hasPrefix("evidence-") },
            ["evidence-beforeContinue", "evidence-dismissedAndFieldReady"])
    }

    func testMissingWrongDuplicateOrDisabledEvidenceCannotAuthorizeContinue() throws {
        for kind in 0..<9 {
            let h = Harness(); h.showIntroduction()
            switch kind {
            case 0: h.observation.entryNameCount = 0
            case 1: h.observation.entryNameCount = 2
            case 2: h.observation.introductionCount = 2
            case 3: h.observation.exactMarkerCount = 0 // Includes wrong text.
            case 4: h.observation.exactMarkerCount = 2
            case 5: h.observation.continueButtonCount = 0 // Includes wrong label/type.
            case 6: h.observation.continueButtonCount = 2
            case 7: h.observation.continueEnabled = false
            default: h.continueHittable = false
            }
            XCTAssertFalse(try h.poll(), "case \(kind)")
            XCTAssertThrowsError(try h.tapField())
            XCTAssertFalse(h.events.contains("continue-tap"))
            XCTAssertFalse(h.events.contains("field-tap"))
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
            h.observation = .init(entryNameCount: 1)
            h.fieldEnabled = !disabled
            h.fieldHittable = disabled
            XCTAssertFalse(try h.poll())
            XCTAssertThrowsError(try h.tapField())
        }
    }

    func testLateFieldStagesCannotAuthorizeTap() {
        for stage in ["field-enabled", "field-hit"] {
            let h = Harness(); h.advanceAt[stage] = 10
            XCTAssertThrowsError(try h.poll())
            XCTAssertThrowsError(try h.tapField())
            XCTAssertFalse(h.events.contains("field-tap"))
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
            return observations == 1 ? introduction : .init(entryNameCount: 1)
        }, continueHittable: { h.stage("continue-hit"); return true },
        tapContinue: { h.stage("continue-tap") },
        fieldEnabled: { h.stage("field-enabled"); return true },
        fieldHittable: { h.stage("field-hit"); return true },
        tapField: { h.stage("field-tap") }, evidence: { h.stage("evidence-" + $0.rawValue) })
        XCTAssertEqual(observations, 2)
        XCTAssertEqual(h.events, ["observe", "continue-hit", "evidence-beforeContinue", "continue-tap",
            "observe", "field-enabled", "field-hit", "evidence-dismissedAndFieldReady", "field-tap"])
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
        }, fieldEnabled: { h.stage("unexpected-field-enabled"); return true },
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

}
