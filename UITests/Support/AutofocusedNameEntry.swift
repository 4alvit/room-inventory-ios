import XCTest

/// Only for a newly presented, empty NameEntrySheet, which focuses its own field.
/// The exact keyboard introduction, readiness, one native input and its echo
/// use bounded setup (30 seconds), then one ten-second input/echo window.
/// Late introduction handling shares the same input deadline and Continue allowance.
/// The field itself is never tapped.
@MainActor
enum AutofocusedNameEntry {
    struct Observation {
        let before: String
        let placeholder: String?
        let after: String
    }

    enum Failure: Error {
        case unexpectedField, notEmpty, valueNotRetained
    }

    @discardableResult
    static func type(_ value: String, in app: XCUIApplication,
                     allowance: NameEntryKeyboardReadiness.ContinueAllowance,
                     evidence: @escaping (NameEntryKeyboardReadiness.EvidenceStage) throws -> Void,
                     recordInitial: @escaping (String, String?) throws -> Void = { _, _ in },
                     recordTyped: @escaping (String) throws -> Void = { _ in }) throws -> Observation {
        let readiness = NameEntryKeyboardReadiness(allowance: allowance, timing: .keyboardSetupThenInput)
        let fields = app.textFields.matching(NSPredicate(format: "identifier == %@", "entry.name"))
        // Resolve the unique live element only inside an admitted callback:
        // even element resolution can traverse the native accessibility tree.
        let introductions = app.otherElements.matching(
            NSPredicate(format: "identifier == %@", NameEntryKeyboardReadiness.introductionID))
        var boundIntroduction: XCUIElement?
        let continueButton: () throws -> XCUIElement = {
            guard let owner = boundIntroduction else { throw Failure.unexpectedField }
            return owner.buttons.matching(NSPredicate(format: "label == %@", "Continue")).element
        }
        var placeholder: String?
        var fieldObservation: NameEntryKeyboardReadiness.FieldObservation?
        var stage = "keyboard_setup"
        let observeIntroduction: () throws -> NameEntryKeyboardReadiness.Observation = {
            boundIntroduction = nil
            // A root application snapshot can omit this keyboard sibling.
            // Enumerate exact owners once, then retain the sole bound identity
            // for its snapshot and any subsequently admitted Continue action.
            return try readiness.captureIntroduction(
                matchingElements: { introductions.allElementsBoundByAccessibilityElement },
                snapshot: { (owner: XCUIElement) throws -> any XCUIElementSnapshot in
                    boundIntroduction = owner
                    return try owner.snapshot()
                }, matchesOwner: { (node: any XCUIElementSnapshot) in
                    node.elementType == .other && node.identifier == NameEntryKeyboardReadiness.introductionID
                }, children: { (node: any XCUIElementSnapshot) in node.children },
                item: { (node: any XCUIElementSnapshot) in
                    let kind: NameEntryKeyboardReadiness.Item.Kind = node.elementType == .button ? .button
                        : node.elementType == .staticText ? .text : .other
                    return .init(kind: kind, label: node.label, enabled: node.isEnabled)
                })
        }
        do {
            try readiness.waitForField(observe: observeIntroduction,
            continueHittable: { try continueButton().isHittable }, tapContinue: { try continueButton().tap() },
            entryNameCount: {
                fieldObservation = nil
                let captured = try readiness.captureNameField(snapshot: { () throws -> any XCUIElementSnapshot in
                    let root = try app.snapshot()
                    guard root.elementType == .application else { throw Failure.unexpectedField }
                    return root
                }, children: { (node: any XCUIElementSnapshot) in node.children },
                attributes: { (node: any XCUIElementSnapshot) in
                    .init(isTextField: node.elementType == .textField, identifier: node.identifier,
                          enabled: node.isEnabled, placeholder: node.placeholderValue)
                })
                fieldObservation = captured
                return captured.count
            }, fieldEnabled: {
                guard let captured = fieldObservation, captured.count == 1,
                      let snapshot = captured.onlyField else {
                    throw Failure.unexpectedField
                }
                placeholder = snapshot.placeholder
                return snapshot.enabled
            }, fieldHittable: { try readiness.perform { fields.element }.isHittable }, keyboardCount: { app.keyboards.count },
            evidence: evidence)
            // Empty controls may expose nil. Preserve the original live-value
            // normalization only before input; nil is never a successful typed echo.
            stage = "initial_value"
            let before = try readiness.perform { try readiness.perform { fields.element }.value as? String ?? "" }
            try readiness.perform { try recordInitial(before, placeholder) }
            guard before.isEmpty || before == placeholder else { throw Failure.notEmpty }
            stage = "input"
            try readiness.typeTextOnce { try readiness.perform { fields.element }.typeText(value) }
            stage = "echo"
            let after = try readiness.waitForExactValue(value, observeIntroduction: observeIntroduction,
                continueHittable: { try continueButton().isHittable }, tapContinue: { try continueButton().tap() }) {
                try readiness.perform { fields.element }.value as? String
            }
            stage = "record_typed"
            try readiness.perform { try recordTyped(after) }
            guard after == value else { throw Failure.valueNotRetained }
            return Observation(before: before, placeholder: placeholder, after: after)
        } catch {
            var diagnostic = readiness.echoDiagnostic
            diagnostic["result"] = "failed"
            diagnostic["stage"] = stage
            if let data = try? JSONSerialization.data(withJSONObject: diagnostic, options: [.sortedKeys]),
               data.count <= 4096, let text = String(data: data, encoding: .utf8) {
                print("ROOM_NAME_ENTRY_ECHO_V1 " + text)
            }
            throw error
        }
    }
}
