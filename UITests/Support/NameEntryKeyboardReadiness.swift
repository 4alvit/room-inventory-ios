import Foundation
import XCTest

/// Handles only the observed system keyboard introduction, inside name-entry's
/// original readiness window. It never accepts an unrelated alert or Continue.
@MainActor
final class NameEntryKeyboardReadiness {
    static let introductionID = "UIContinuousPathIntroductionView"
    static let introductionText = "Speed up your typing by sliding your finger across the letters to compose a word."

    final class ContinueAllowance {
        fileprivate(set) var attempted = false
    }

    struct Observation {
        var introductionCount = 0
        var exactMarkerCount = 0
        var continueButtonCount = 0
        var continueEnabled = false
    }

    struct Item {
        enum Kind { case text, button, other }
        let kind: Kind
        let label: String
        let enabled: Bool
    }

    static func recognize(introductionCount: Int, items: [Item]) -> Observation {
        let buttons = items.filter { $0.kind == .button && $0.label == "Continue" }
        return Observation(introductionCount: introductionCount,
            exactMarkerCount: items.filter { $0.kind == .text && $0.label == introductionText }.count,
            continueButtonCount: buttons.count,
            continueEnabled: buttons.count == 1 && buttons[0].enabled)
    }

    enum Failure: Error { case notReady }
    enum EvidenceStage: String { case beforeContinue, dismissedAndFieldReady }

    private let window: RecoveryOCRReadinessWindow
    private let allowance: ContinueAllowance
    private(set) var observation: Observation?
    private(set) var sawIntroduction = false
    private(set) var dismissedIntroduction = false
    private(set) var continueAttempted = false
    private(set) var entryNameCount: Int?
    private(set) var fieldEnabled: Bool?
    private(set) var fieldHittable: Bool?
    private(set) var fieldTapAttempted = false
    private var fieldReady = false
    private var afterEvidenceRecorded = false
    private var echoWaitStarted = false
    private var echoMatched = false
    private var echoObservationCount = 0
    private var echoMismatchObserved = false
    private var lastEchoMismatch: String?
    private var lastEchoMismatchTruncated = false

    init(allowance: ContinueAllowance,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.allowance = allowance
        window = RecoveryOCRReadinessWindow(clock: clock)
    }

    func perform<Value>(_ operation: () throws -> Value) throws -> Value {
        try window.perform(operation)
    }

    // This is the same policy seam used by the live adapter and deterministic
    // tests. Every observation and action must return within the one deadline.
    func poll(observe: () throws -> Observation,
              continueHittable: () throws -> Bool,
              tapContinue: () throws -> Void,
              entryNameCount: () throws -> Int,
              fieldEnabled: () throws -> Bool,
              fieldHittable: () throws -> Bool,
              evidence: (EvidenceStage) throws -> Void = { _ in }) throws -> Bool {
        fieldReady = false
        self.entryNameCount = nil
        self.fieldEnabled = nil
        self.fieldHittable = nil
        let observation = try perform(observe)
        self.observation = observation
        sawIntroduction = sawIntroduction || observation.introductionCount > 0
        if observation.introductionCount != 0 {
            guard observation.introductionCount == 1,
                  observation.exactMarkerCount == 1,
                  observation.continueButtonCount == 1,
                  observation.continueEnabled,
                  !allowance.attempted else { return false }
            guard try perform(continueHittable) else { return false }
            // Evidence is optional near the deadline; it never renews it. A
            // slow screenshot still fails closed before the physical action.
            if try window.remaining() > 2 { try perform { try evidence(.beforeContinue) } }
            try perform {
                allowance.attempted = true
                continueAttempted = true
                try tapContinue()
            }
            return false // A tap is not proof that the introduction disappeared.
        }
        dismissedIntroduction = sawIntroduction && continueAttempted
        // The private enterName callsite supplies the intended interaction.
        // Resolve the field only after the exact blocking owner is absent;
        // its identity and live readiness still gate every field action.
        self.entryNameCount = try perform(entryNameCount)
        guard self.entryNameCount == 1 else { return false }
        self.fieldEnabled = try perform(fieldEnabled)
        guard self.fieldEnabled == true else { return false }
        self.fieldHittable = try perform(fieldHittable)
        guard self.fieldHittable == true else { return false }
        if try dismissedIntroduction && !afterEvidenceRecorded && window.remaining() > 2 {
            try perform { try evidence(.dismissedAndFieldReady) }
            afterEvidenceRecorded = true
        }
        fieldReady = true
        return true
    }

    func tapField(_ action: () throws -> Void) throws {
        guard fieldReady, !fieldTapAttempted else { throw Failure.notReady }
        try perform {
            fieldTapAttempted = true
            try action()
        }
    }

    /// Autofocus callers omit the field tap and keep input inside `perform`.
    func waitForField(observe: @escaping () throws -> Observation,
                      continueHittable: @escaping () throws -> Bool,
                      tapContinue: @escaping () throws -> Void,
                      entryNameCount: @escaping () throws -> Int,
                      fieldEnabled: @escaping () throws -> Bool,
                      fieldHittable: @escaping () throws -> Bool,
                      evidence: @escaping (EvidenceStage) throws -> Void) throws {
        try waitUntil {
            try self.poll(observe: observe, continueHittable: continueHittable,
                tapContinue: tapContinue, entryNameCount: entryNameCount, fieldEnabled: fieldEnabled,
                fieldHittable: fieldHittable, evidence: evidence)
        }
        guard fieldReady else { throw Failure.notReady }
    }

    /// Input has already happened once. Only read its echo, using the remainder
    /// of the original window; nil and partial values do not authorize progress.
    func waitForExactValue(_ expected: String, read: @escaping () throws -> String?) throws -> String {
        guard fieldReady, !echoWaitStarted else { throw Failure.notReady }
        echoWaitStarted = true
        var matchedValue: String?
        try waitUntil {
            let value = try self.perform(read)
            self.echoObservationCount += 1
            if value == expected {
                matchedValue = value
                return true
            }
            self.echoMismatchObserved = true
            self.lastEchoMismatch = value.map {
                var bytes = Array($0.utf8.prefix(256))
                // A valid string's byte prefix can cut only its final scalar.
                // Dropping at most three bytes avoids a replacement character.
                for _ in 0..<3 {
                    if let prefix = String(bytes: bytes, encoding: .utf8) { return prefix }
                    bytes.removeLast()
                }
                return String(decoding: bytes, as: UTF8.self)
            }
            self.lastEchoMismatchTruncated = value.map { $0.utf8.count > 256 } ?? false
            return false
        }
        guard let matchedValue else { throw Failure.notReady }
        echoMatched = true
        return matchedValue
    }

    private func waitUntil(_ probe: @escaping () throws -> Bool) throws {
        var capturedError: Error?
        let result = try window.waitForProbe {
            do {
                return try probe()
            } catch {
                capturedError = error
                return true
            }
        }
        if let capturedError { throw capturedError }
        guard result == .completed else { throw Failure.notReady }
    }

    func waitAndTapField(observe: @escaping () throws -> Observation,
                         continueHittable: @escaping () throws -> Bool,
                         tapContinue: @escaping () throws -> Void,
                         entryNameCount: @escaping () throws -> Int,
                         fieldEnabled: @escaping () throws -> Bool,
                         fieldHittable: @escaping () throws -> Bool,
                         tapField: () throws -> Void,
                         evidence: @escaping (EvidenceStage) throws -> Void) throws {
        try waitForField(observe: observe, continueHittable: continueHittable,
            tapContinue: tapContinue, entryNameCount: entryNameCount,
            fieldEnabled: fieldEnabled, fieldHittable: fieldHittable, evidence: evidence)
        try self.tapField(tapField)
    }

    /// Test-owned synthetic names only. This never queries the UI or clock.
    var echoDiagnostic: [String: Any] {
        ["schema_version": 1,
         "allowance_seconds": 10,
         "echo_wait_started": echoWaitStarted,
         "timely_observation_count": echoObservationCount,
         "matched": echoMatched,
         "mismatch_observed": echoMismatchObserved,
         "last_mismatching_value": lastEchoMismatch.map { $0 as Any } ?? NSNull(),
         "last_mismatching_value_truncated": lastEchoMismatchTruncated]
    }

    var diagnostic: [String: Any] {
        ["owner_identifier": Self.introductionID,
         "has_timely_observation": observation != nil,
         "entry_name_count": entryNameCount.map { $0 as Any } ?? NSNull(),
         "introduction_count": observation.map { $0.introductionCount as Any } ?? NSNull(),
         "exact_marker_count": observation.map { $0.exactMarkerCount as Any } ?? NSNull(),
         "continue_button_count": observation.map { $0.continueButtonCount as Any } ?? NSNull(),
         "saw_introduction": sawIntroduction,
         "continue_attempted_once": continueAttempted,
         "test_case_continue_consumed": allowance.attempted,
         "dismissed_introduction": dismissedIntroduction,
         "field_enabled": fieldEnabled.map { $0 as Any } ?? NSNull(),
         "field_hittable": fieldHittable.map { $0 as Any } ?? NSNull(),
         "field_tap_attempted": fieldTapAttempted,
         "path": sawIntroduction ? "observed_introduction" : "introduction_not_observed"]
    }
}
