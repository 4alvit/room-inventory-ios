import XCTest

/// Only for a newly presented, empty NameEntrySheet, which focuses its own field.
/// The exact keyboard introduction, readiness, one native input and its echo
/// share one ten-second window. The field itself is never tapped.
@MainActor
enum AutofocusedNameEntry {
    struct Observation {
        let before: String
        let placeholder: String?
        let after: String
    }

    enum Failure: Error {
        case unexpectedField, missingValue, notEmpty, valueNotRetained
    }

    @discardableResult
    static func type(_ value: String, in app: XCUIApplication,
                     allowance: NameEntryKeyboardReadiness.ContinueAllowance,
                     evidence: @escaping (NameEntryKeyboardReadiness.EvidenceStage) throws -> Void,
                     recordInitial: @escaping (String, String?) throws -> Void = { _, _ in },
                     recordTyped: @escaping (String) throws -> Void = { _ in }) throws -> Observation {
        let readiness = NameEntryKeyboardReadiness(allowance: allowance)
        let fields = app.textFields.matching(identifier: "entry.name")
        let field = fields.element(boundBy: 0)
        let introductions = app.otherElements.matching(identifier: NameEntryKeyboardReadiness.introductionID)
        let continueButton = introductions.element(boundBy: 0).buttons
            .matching(NSPredicate(format: "label == %@", "Continue")).element(boundBy: 0)
        var placeholder: String?
        try readiness.waitForField(observe: {
            var state = NameEntryKeyboardReadiness.Observation()
            state.introductionCount = try readiness.perform { introductions.count }
            guard state.introductionCount == 1 else { return state }
            // Use the same exact owner/marker/button recognition as Localization.
            // A root application snapshot can omit this keyboard sibling.
            let root = try readiness.perform { try introductions.element(boundBy: 0).snapshot() }
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
        entryNameCount: { fields.count }, fieldEnabled: {
            let snapshot = try field.snapshot()
            guard snapshot.elementType == .textField, snapshot.identifier == "entry.name" else {
                throw Failure.unexpectedField
            }
            placeholder = snapshot.placeholderValue
            return snapshot.isEnabled
        }, fieldHittable: { field.isHittable }, evidence: evidence)
        // Empty controls may expose nil. Preserve the original live-value
        // normalization only before input; nil is never a successful typed echo.
        let before = try readiness.perform { field.value as? String ?? "" }
        try readiness.perform { try recordInitial(before, placeholder) }
        guard before.isEmpty || before == placeholder else { throw Failure.notEmpty }
        try readiness.perform { field.typeText(value) }
        guard let after = try readiness.perform({ field.value as? String }) else {
            throw Failure.missingValue
        }
        try readiness.perform { try recordTyped(after) }
        guard after == value else { throw Failure.valueNotRetained }
        return Observation(before: before, placeholder: placeholder, after: after)
    }
}
