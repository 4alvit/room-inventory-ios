import XCTest

@MainActor
final class NameEntryKeyboardReadinessTests: XCTestCase {
    @MainActor
    private final class Harness {
        var now = 0.0
        var observation = NameEntryKeyboardReadiness.Observation()
        var entryNameCount = 1
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
                entryNameCount: { self.stage("entry-count"); return self.entryNameCount },
                fieldEnabled: { self.stage("field-enabled"); return self.fieldEnabled },
                fieldHittable: { self.stage("field-hit"); return self.fieldHittable },
                evidence: { self.stage("evidence-" + $0.rawValue) })
        }
        func tapField() throws { try subject.tapField { self.stage("field-tap") } }
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

}
