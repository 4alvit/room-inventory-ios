import Foundation
import XCTest

/// Handles only the observed system keyboard introduction. Autofocus may use a
/// separate setup allowance; the default keeps Localization's shared ten seconds.
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

    struct FieldItem {
        let isTextField: Bool
        let identifier: String
        let enabled: Bool
        let placeholder: String?
    }

    struct FieldObservation {
        var count = 0
        var onlyField: FieldItem?
    }

    static let fieldSnapshotNodeLimit = 1024

    enum Failure: Error { case notReady }
    enum EvidenceStage: String { case beforeContinue, dismissedAndFieldReady }
    enum Timing { case sharedTenSeconds, keyboardSetupThenInput }

    // Cache only samples already requested by the deadline engine. Diagnostics
    // must not query the UI or advance an injected clock.
    private final class Clock {
        let read: () -> TimeInterval
        var latest = 0.0
        init(_ read: @escaping () -> TimeInterval) { self.read = read }
        func now() -> TimeInterval { latest = read(); return latest }
    }

    private let clock: Clock
    private let timing: Timing
    private let setupWindow: RecoveryOCRReadinessWindow
    private let setupStartedAt: TimeInterval
    private var inputWindow: RecoveryOCRReadinessWindow?
    private var inputStartedAt: TimeInterval?
    private var setupWaitStarted = false
    private var setupCompleted = false
    private var polling = false
    private var terminalError: Error?
    private var inputAttempted = false
    private var window: RecoveryOCRReadinessWindow { inputWindow ?? setupWindow }
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

    init(allowance: ContinueAllowance, timing: Timing = .sharedTenSeconds,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.allowance = allowance
        self.timing = timing
        let sampledClock = Clock(clock)
        self.clock = sampledClock
        setupWindow = RecoveryOCRReadinessWindow(
            timeout: timing == .keyboardSetupThenInput ? 30 : 10, clock: sampledClock.now)
        setupStartedAt = sampledClock.latest
    }

    func perform<Value>(_ operation: () throws -> Value) throws -> Value {
        if let terminalError { throw terminalError }
        do { return try window.perform(operation) }
        catch { retainFailure(error); throw error }
    }

    /// Inventory one immutable application snapshot; never resolve the field
    /// again merely to read attributes already present in that snapshot.
    func captureNameField<Node>(snapshot: () throws -> Node,
                                children: (Node) -> [Node],
                                attributes: (Node) -> FieldItem) throws -> FieldObservation {
        var pending = [try perform(snapshot)]
        var visited = 0
        var result = FieldObservation()
        while let node = pending.popLast() {
            let item = try perform { attributes(node) }
            visited += 1
            if item.isTextField && item.identifier == "entry.name" {
                result.count += 1
                result.onlyField = result.count == 1 ? item : nil
            }
            let descendants = try perform { children(node) }
            try perform {
                guard descendants.count <= Self.fieldSnapshotNodeLimit - visited - pending.count else {
                    throw Failure.notReady
                }
            }
            pending.append(contentsOf: descendants)
        }
        return result
    }

    private func retainFailure(_ error: Error) {
        guard terminalError == nil else { return }
        // A throwing native call skips the window's postcheck. Capture its end
        // for diagnostics only; the original error remains authoritative.
        _ = clock.now()
        terminalError = error
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
        if let terminalError { throw terminalError }
        guard inputWindow == nil, !polling else { throw Failure.notReady }
        polling = true
        defer { polling = false }
        fieldReady = false
        self.entryNameCount = nil
        self.fieldEnabled = nil
        self.fieldHittable = nil
        let observation = try perform(observe)
        self.observation = observation
        sawIntroduction = sawIntroduction || observation.introductionCount > 0
        if observation.introductionCount != 0 {
            try handleIntroduction(observation, continueHittable: continueHittable,
                tapContinue: tapContinue, evidence: evidence)
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
        if timing == .keyboardSetupThenInput {
            // Cold keyboard initialization can present its introduction while
            // the field's native readiness queries are running. Do not start
            // the input window using the absence observed before those queries.
            let finalObservation = try perform(observe)
            self.observation = finalObservation
            sawIntroduction = sawIntroduction || finalObservation.introductionCount > 0
            guard finalObservation.introductionCount == 0 else {
                dismissedIntroduction = false
                try handleIntroduction(finalObservation, continueHittable: continueHittable,
                    tapContinue: tapContinue, evidence: evidence)
                return false
            }
        }
        fieldReady = true
        return true
    }

    private func handleIntroduction(_ observation: Observation,
                                    continueHittable: () throws -> Bool,
                                    tapContinue: () throws -> Void,
                                    evidence: (EvidenceStage) throws -> Void) throws {
        guard observation.introductionCount == 1,
              observation.exactMarkerCount == 1,
              observation.continueButtonCount == 1,
              observation.continueEnabled,
              !allowance.attempted else { return }
        guard try perform(continueHittable) else { return }
        // Evidence is optional near the deadline and cannot renew it.
        if try window.remaining() > 2 { try perform { try evidence(.beforeContinue) } }
        try perform {
            allowance.attempted = true
            continueAttempted = true
            try tapContinue()
        }
    }

    func tapField(_ action: () throws -> Void) throws {
        guard timing == .sharedTenSeconds, fieldReady, !fieldTapAttempted else { throw Failure.notReady }
        try perform {
            fieldTapAttempted = true
            try action()
        }
    }

    /// Only this completed wait may activate the autofocus input window. A
    /// successful individual poll cannot renew the setup allowance or admit input.
    func waitForField(observe: @escaping () throws -> Observation,
                      continueHittable: @escaping () throws -> Bool,
                      tapContinue: @escaping () throws -> Void,
                      entryNameCount: @escaping () throws -> Int,
                      fieldEnabled: @escaping () throws -> Bool,
                      fieldHittable: @escaping () throws -> Bool,
                      evidence: @escaping (EvidenceStage) throws -> Void) throws {
        if let terminalError { throw terminalError }
        guard !setupWaitStarted, !polling else { throw Failure.notReady }
        setupWaitStarted = true
        do {
            try waitUntil {
                try self.poll(observe: observe, continueHittable: continueHittable,
                    tapContinue: tapContinue, entryNameCount: entryNameCount, fieldEnabled: fieldEnabled,
                    fieldHittable: fieldHittable, evidence: evidence)
            }
            guard fieldReady else { throw Failure.notReady }
            if timing == .keyboardSetupThenInput {
                // Construct exactly once, then check that the complete handoff
                // still falls within setup's deadline before publishing it.
                let (candidate, startedAt) = try setupWindow.perform {
                    let candidate = RecoveryOCRReadinessWindow(clock: self.clock.now)
                    return (candidate, self.clock.latest)
                }
                inputStartedAt = startedAt
                inputWindow = candidate
            }
            setupCompleted = true
        } catch {
            retainFailure(error)
            throw error
        }
    }

    func typeTextOnce(_ action: () throws -> Void) throws {
        guard fieldReady, !inputAttempted,
              timing == .sharedTenSeconds || inputWindow != nil else { throw Failure.notReady }
        try perform {
            inputAttempted = true
            try action()
        }
    }

    /// Input has already happened once. Only read its echo, using the remainder
    /// of its ten seconds; nil and partial values do not authorize progress.
    func waitForExactValue(_ expected: String, read: @escaping () throws -> String?) throws -> String {
        guard fieldReady, !echoWaitStarted,
              timing == .sharedTenSeconds || (inputWindow != nil && inputAttempted) else { throw Failure.notReady }
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
        if let terminalError { throw terminalError }
        do {
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
        } catch {
            retainFailure(error)
            throw error
        }
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
        let record: [String: Any] = ["schema_version": 1,
         "allowance_seconds": 10,
         "echo_wait_started": echoWaitStarted,
         "timely_observation_count": echoObservationCount,
         "matched": echoMatched,
         "mismatch_observed": echoMismatchObserved,
         "last_mismatching_value": lastEchoMismatch.map { $0 as Any } ?? NSNull(),
         "last_mismatching_value_truncated": lastEchoMismatchTruncated]
        return timingDiagnostic.merging(record) { _, value in value }
    }

    var diagnostic: [String: Any] {
        let record: [String: Any] = ["owner_identifier": Self.introductionID,
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
        return timingDiagnostic.merging(record) { _, value in value }
    }

    private var timingDiagnostic: [String: Any] {
        func elapsed(from start: TimeInterval, to end: TimeInterval) -> Any {
            let value = end - start
            return value.isFinite && value >= 0 ? value as Any : NSNull()
        }
        return ["timing_mode": timing == .keyboardSetupThenInput ? "keyboard_setup_then_input" : "shared_ten_seconds",
                "active_phase": inputWindow != nil ? "input" : "setup",
                "setup_allowance_seconds": timing == .keyboardSetupThenInput ? 30 : 10,
                "input_allowance_seconds": 10,
                "setup_elapsed_seconds": elapsed(from: setupStartedAt, to: inputStartedAt ?? clock.latest),
                "input_elapsed_seconds": inputStartedAt.map { elapsed(from: $0, to: clock.latest) } ?? NSNull(),
                "setup_completed": setupCompleted,
                "input_attempted_once": inputAttempted]
    }
}
