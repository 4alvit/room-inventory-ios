import XCTest

/// UI observations only. The host separately collects and hashes actual files;
/// this helper never reads an application container or seeds inventory data.
@MainActor
final class RecoveryJourneyEvidence {
    static let steps = [
        "source_empty_free", "item_before_ocr", "photos_receipt_selected",
        "ocr_review_unselected", "ocr_selection_model_price", "source_item_after_ocr",
        "source_free", "source_zip_saved", "backup_saved", "target_empty_free",
        "restore_confirmation", "target_restored", "target_relaunched", "original_preview",
        "recovered_zip_saved", "target_free", "complete"
    ]

    let journeyID: String
    let sourceID: String
    let targetID: String
    let expected: [String: String]
    private var events: [[String: Any]] = []
    private var pendingAssertions: [[String: Any]] = []
    private var issues: [String] = []
    private var outcome = "running"

    init(journeyID: String, sourceID: String, targetID: String, expected: [String: String]) {
        self.journeyID = journeyID
        self.sourceID = sourceID
        self.targetID = targetID
        self.expected = expected
    }

    func require(_ name: String, actual: String, expected: String) throws {
        let passed = actual == expected
        pendingAssertions.append(["name": name, "actual": actual, "expected": expected, "passed": passed])
        guard passed else { throw RecoveryJourneyFailure.assertion(name, actual, expected) }
    }

    func require(_ name: String, _ condition: Bool) throws {
        try require(name, actual: String(condition), expected: "true")
    }

    func recordIssue(_ description: String) { issues.append(description) }

    @discardableResult
    func capture(_ name: String, app: XCUIApplication, test: XCTestCase) -> [String: String] {
        let screenshotName = name + ".png"
        let treeName = name + "-accessibility.txt"
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = screenshotName
        screenshot.lifetime = .keepAlways
        test.add(screenshot)
        let tree = XCTAttachment(string: app.debugDescription)
        tree.name = treeName
        tree.lifetime = .keepAlways
        test.add(tree)
        return ["screenshot": screenshotName, "accessibility": treeName]
    }

    func checkpoint(_ name: String, runID: String, observations: [String: String],
                    app: XCUIApplication, test: XCTestCase) throws {
        let index = events.count
        guard index < Self.steps.count, Self.steps[index] == name else {
            throw RecoveryJourneyFailure.assertion("checkpoint order", name, Self.steps.dropFirst(index).first ?? "end")
        }
        try require("checkpoint has assertions", !pendingAssertions.isEmpty)
        let attachments = capture(String(format: "recovery-%02d-%@", index + 1, name), app: app, test: test)
        events.append(["sequence": index + 1, "name": name, "run_id": runID,
                       "observations": observations, "assertions": pendingAssertions, "attachments": attachments])
        pendingAssertions = []
        try attachJSON(name: String(format: "recovery-progress-%02d.json", index + 1), test: test)
    }

    func finish(completed: Bool, runID: String, app: XCUIApplication, test: XCTestCase) throws {
        let assertionsPassed = events.allSatisfy { event in
            (event["assertions"] as? [[String: Any]])?.allSatisfy { $0["passed"] as? Bool == true } == true
        }
        outcome = completed && issues.isEmpty && events.count == Self.steps.count && pendingAssertions.isEmpty && assertionsPassed
            ? "passed" : "failed"
        if outcome == "failed" {
            let attachments = capture("recovery-failure", app: app, test: test)
            events.append(["sequence": events.count + 1, "name": "failure", "run_id": runID,
                           "observations": ["app_state": String(app.state.rawValue)],
                           "assertions": pendingAssertions, "attachments": attachments])
        }
        try attachJSON(name: "recovery-journey-evidence.json", test: test)
    }

    private func attachJSON(name: String, test: XCTestCase) throws {
        let document: [String: Any] = [
            "schema_version": 1, "journey_run_id": journeyID,
            "source_run_id": sourceID, "target_run_id": targetID,
            "outcome": outcome, "expected": expected, "events": events, "issues": issues,
            "scope": "Observed UI journey; file bytes and hashes require separate host collection and verification."
        ]
        let data = try JSONSerialization.data(withJSONObject: document, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = name
        attachment.lifetime = .keepAlways
        test.add(attachment)
    }
}

enum RecoveryJourneyFailure: Error, CustomStringConvertible {
    case assertion(String, String, String)

    var description: String {
        switch self {
        case let .assertion(name, actual, expected): "\(name): observed \(actual), expected \(expected)"
        }
    }
}
