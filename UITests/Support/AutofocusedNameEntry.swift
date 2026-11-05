import XCTest

/// Only for a newly presented, empty NameEntrySheet, which focuses its own field.
/// The exact keyboard introduction, readiness, one native input and its echo
/// use bounded setup (30 seconds), then one ten-second input/echo window.
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
        let introductions = app.otherElements.matching(identifier: NameEntryKeyboardReadiness.introductionID)
        // Count and snapshot recognition below establish uniqueness before use.
        // Stop resolution at that known owner/button instead of indexing all matches.
        let introduction = introductions.firstMatch
        let continueButton = introduction.buttons
            .matching(NSPredicate(format: "label == %@", "Continue")).firstMatch
        var placeholder: String?
        var fieldObservation: NameEntryKeyboardReadiness.FieldObservation?
        var stage = "keyboard_setup"
        do {
            try readiness.waitForField(observe: {
                var state = NameEntryKeyboardReadiness.Observation()
                state.introductionCount = try readiness.perform { introductions.count }
                guard state.introductionCount == 1 else { return state }
                // Use the same exact owner/marker/button recognition as Localization.
                // A root application snapshot can omit this keyboard sibling.
                let root = try readiness.perform { try introduction.snapshot() }
                guard root.elementType == .other,
                      root.identifier == NameEntryKeyboardReadiness.introductionID else { return state }
                var pending: [any XCUIElementSnapshot] = [root]
                var nodes: [any XCUIElementSnapshot] = []
                while let node = pending.popLast() {
                    _ = try readiness.perform { () }
                    guard nodes.count < 256 else { throw NameEntryKeyboardReadiness.Failure.notReady }
                    nodes.append(node)
                    pending.append(contentsOf: node.children)
                }
                return NameEntryKeyboardReadiness.recognize(introductionCount: state.introductionCount,
                    items: nodes.map { node in
                        let kind: NameEntryKeyboardReadiness.Item.Kind = node.elementType == .button ? .button
                            : node.elementType == .staticText ? .text : .other
                        return .init(kind: kind, label: node.label, enabled: node.isEnabled)
                    })
            }, continueHittable: { continueButton.isHittable }, tapContinue: { continueButton.tap() },
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
            }, fieldHittable: { fields.element.isHittable }, evidence: evidence)
            // Empty controls may expose nil. Preserve the original live-value
            // normalization only before input; nil is never a successful typed echo.
            stage = "initial_value"
            let before = try readiness.perform { fields.element.value as? String ?? "" }
            try readiness.perform { try recordInitial(before, placeholder) }
            guard before.isEmpty || before == placeholder else { throw Failure.notEmpty }
            stage = "input"
            try readiness.typeTextOnce { fields.element.typeText(value) }
            stage = "echo"
            let after = try readiness.waitForExactValue(value) { fields.element.value as? String }
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
