import CryptoKit
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
    private var filesCaptureStages: [String] = []

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

    /// Two bounded observations in the owned runner, independent of xcresult.
    /// The host binds these run IDs to its pinned source and verifies every byte.
    func captureFirstFilesTap(_ stage: String, localTitle: String,
                              target: XCUIElement, app: XCUIApplication) {
        // Diagnostic failures never enter the acceptance ledger or escape to
        // the caller. The original tap remains outside this nonthrowing boundary.
        do {
            try writeFirstFilesTap(stage, localTitle: localTitle, target: target, app: app)
        } catch {
            let label = stage == "before" ? "before" : stage == "after" ? "after" : "invalid"
            print("ROOM_FILES_CAPTURE_V1 \(label) incomplete")
        }
    }

    private func writeFirstFilesTap(_ stage: String, localTitle: String,
                                    target: XCUIElement, app: XCUIApplication) throws {
        let expected = filesCaptureStages.isEmpty ? "before" : "after"
        guard filesCaptureStages.count < 2, stage == expected,
              Bundle.main.bundleIdentifier == "com.alvit.roominventory.uitests.xctrunner",
              let deviceID = ProcessInfo.processInfo.environment["RECOVERY_SIMULATOR_UDID"],
              UUID(uuidString: deviceID)?.uuidString == deviceID else {
            throw RecoveryJourneyFailure.assertion("Files capture identity/order", stage, expected)
        }
        let root = try FileManager.default.url(for: .documentDirectory, in: .userDomainMask,
                                               appropriateFor: nil, create: false)
            .appendingPathComponent("RecoveryFilesFirstTap-" + journeyID, isDirectory: true)
        if stage == "before" {
            guard !FileManager.default.fileExists(atPath: root.path) else {
                throw RecoveryJourneyFailure.assertion("fresh Files capture directory", "exists", "absent")
            }
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
        }
        let png = XCUIScreen.main.screenshot().pngRepresentation
        guard !png.isEmpty, png.count <= 2 * 1_024 * 1_024 else {
            throw RecoveryJourneyFailure.assertion("Files PNG byte bound", String(png.count), "1...2097152")
        }
        let query = app.descendants(matching: .any).matching(NSPredicate(
            format: "label == %@ OR label BEGINSWITH %@ OR label BEGINSWITH %@",
            localTitle, localTitle + ".", localTitle + ","))
        guard query.count <= 16, app.navigationBars.count <= 8 else {
            throw RecoveryJourneyFailure.assertion("Files AX element bound", "exceeded", "16 matches / 8 bars")
        }
        func describe(_ element: XCUIElement) -> [String: Any] {
            guard element.exists else { return ["exists": false] }
            let frame = element.frame
            return ["type": element.elementType.rawValue, "identifier": element.identifier,
                    "label": element.label, "exists": element.exists,
                    "hittable": element.isHittable, "enabled": element.isEnabled,
                    "frame": [frame.origin.x, frame.origin.y, frame.size.width, frame.size.height]]
        }
        let identity: [String: Any] = ["schema_version": 1, "stage": stage,
            "journey_run_id": journeyID, "source_run_id": sourceID,
            "target_run_id": targetID, "simulator_udid": deviceID]
        var observation = identity
        observation["local_title"] = localTitle
        observation["selected_target"] = describe(target)
        observation["matches"] = query.allElementsBoundByIndex.map(describe)
        observation["navigation_bars"] = app.navigationBars.allElementsBoundByIndex.map(describe)
        // Full indentation preserves ancestors and bar children/titles; individual
        // query matches above also expose the actual selector's ambiguity.
        observation["hierarchy"] = app.debugDescription
        let ax = try JSONSerialization.data(withJSONObject: observation, options: [.sortedKeys])
        guard ax.count <= 256 * 1_024 else {
            throw RecoveryJourneyFailure.assertion("Files AX byte bound", String(ax.count), "262144")
        }
        var receipt = identity
        var entries: [[String: Any]] = []
        for (name, data) in [(stage + ".png", png), (stage + "-ax.json", ax)] {
            let url = root.appendingPathComponent(name)
            try data.write(to: url, options: [.withoutOverwriting])
            let handle = try FileHandle(forWritingTo: url)
            defer { try? handle.close() }
            try handle.synchronize()
            entries.append(["name": name, "bytes": data.count,
                "sha256": SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()])
        }
        receipt["files"] = entries
        let data = try JSONSerialization.data(withJSONObject: receipt, options: [.sortedKeys])
        guard data.count <= 16_384 else {
            throw RecoveryJourneyFailure.assertion("Files receipt byte bound", String(data.count), "16384")
        }
        // Publish the receipt only after its bytes are synchronized. Any earlier
        // IO error leaves a missing receipt or unexpected pending file, so the
        // host's exact-file-set check cannot accept an incomplete stage.
        let pending = root.appendingPathComponent(stage + ".pending")
        try data.write(to: pending, options: [.withoutOverwriting])
        let handle = try FileHandle(forWritingTo: pending)
        defer { try? handle.close() }
        try handle.synchronize()
        try FileManager.default.moveItem(at: pending, to: root.appendingPathComponent(stage + ".json"))
        filesCaptureStages.append(stage)
    }

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
