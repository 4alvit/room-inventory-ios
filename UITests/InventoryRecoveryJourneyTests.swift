import XCTest
import UIKit

/// Dedicated controller-owned Simulator test. Seed SyntheticRecoveryReceipt.png;
/// the runner verifies/isolates it before all inventory and file operations use UI.
@MainActor
final class InventoryRecoveryJourneyTests: XCTestCase {
    private var evidence: RecoveryJourneyEvidence?
    private var bridge: RecoveryJourneyBridge?
    private var application: XCUIApplication?
    private var activeRunID = ""
    private var completed = false
    private var firstFilesTapCaptured = false

    private func finishEvidence() throws {
        defer { application?.terminate() }
        if let evidence, let application {
            let failures = (testRun?.failureCount ?? 1) + (testRun?.unexpectedExceptionCount ?? 0)
            if failures > 0 { evidence.recordIssue("XCTest recorded \(failures) failure(s)") }
            try evidence.finish(completed: completed && failures == 0, runID: activeRunID, app: application, test: self)
        }
    }

    func testPhotosOCRExportRestoreIntoFreshNamespace() throws {
        let environment = ProcessInfo.processInfo.environment
        try XCTSkipUnless(environment["RUN_INVENTORY_RECOVERY_JOURNEY"] == "1",
                          "Requires a fresh controller-owned Simulator seeded with the synthetic receipt in Photos.")
        executionTimeAllowance = 360
        continueAfterFailure = false
        let journeyID = try requiredUUID("RECOVERY_JOURNEY_RUN_ID", environment)
        let sourceID = try requiredUUID("RECOVERY_SOURCE_RUN_ID", environment)
        let targetID = try requiredUUID("RECOVERY_TARGET_RUN_ID", environment)
        guard Set([journeyID, sourceID, targetID]).count == 3 else {
            throw RecoveryJourneyFailure.assertion("distinct configured UUIDs", "duplicate", "three distinct UUIDs")
        }
        let deviceID = try requiredUUID("RECOVERY_SIMULATOR_UDID", environment)
        let startupBridge = try RecoveryJourneyBridge(journeyID: journeyID, sourceID: sourceID,
                                                       targetID: targetID, deviceID: deviceID)
        let app = XCUIApplication()
        application = app
        // Cleanup also covers an installation-only launch that fails before the
        // evidence ledger or final host acknowledgement exists.
        addTeardownBlock { @MainActor [self] () async throws in try finishEvidence() }
        app.launchArguments = ["--ui-testing", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        // First AUT launch may replace its preinstalled Simulator container.
        // Use only the distinct journey UUID; source/target data remain absent.
        app.launchEnvironment["UITEST_RUN_ID"] = journeyID
        app.launch()
        guard app.state == .runningForeground else {
            throw RecoveryJourneyFailure.assertion("installation launch", String(app.state.rawValue), "foreground")
        }
        app.terminate()
        guard app.state == .notRunning else {
            throw RecoveryJourneyFailure.assertion("installation termination", String(app.state.rawValue), "not running")
        }
        // The host now verifies the empty installation namespace and pins the
        // final containers once, before either scenario namespace is launched.
        try startupBridge.synchronizeInstallation(test: self)
        try startupBridge.isolatePhotosFixture(test: self)
        bridge = startupBridge
        let suffix = String(journeyID.prefix(8))
        let names = ["home_name": "Recovery Home \(suffix)", "room_name": "Recovery Room \(suffix)",
                     "item_name": "Recovery Item \(suffix)", "notes": "Recovery receipt QA"]
        let ledger = RecoveryJourneyEvidence(journeyID: journeyID, sourceID: sourceID, targetID: targetID, expected: names)
        evidence = ledger
        activeRunID = sourceID
        app.launchEnvironment["UITEST_RUN_ID"] = sourceID
        app.launch()

        try checkpoint("source_empty_free", observations: emptyAndFree(app), app: app)
        try tap(app.buttons["inventory.addFirstHome"], app: app, scroll: true)
        try enterName(names["home_name"]!, app: app)
        try openRecord(names["home_name"]!, app: app)
        try tap(app.buttons["Add a room"], app: app, scroll: true)
        try enterName(names["room_name"]!, app: app)
        try openRecord(names["room_name"]!, app: app)
        try tap(app.buttons["Add an item"], app: app, scroll: true)
        try enterName(names["item_name"]!, app: app)
        try openRecord(names["item_name"]!, app: app)
        try tap(app.buttons["item.editDetails"], app: app, scroll: true)
        let initial = ["model": "BEFORE-MODEL", "serial": "KEEP-SERIAL", "price": "USD 1.00",
                       "date": "2025-01-01", "notes": names["notes"]!]
        for field in ["model", "serial", "price", "date", "notes"] {
            try typeIntoEmptyField(element("itemEditor.\(field)", app), value: initial[field]!, app: app)
        }
        try tap(app.buttons["itemEditor.save"], app: app)
        try waitForDismissal(app.buttons["itemEditor.save"])
        try checkpoint("item_before_ocr", observations: readItem(initial, app: app), app: app)
        try closeItemEditor(app)

        try tap(app.buttons["item.addAttachment"], app: app, scroll: true)
        try tap(element("import.purpose", app), app: app)
        try tap(app.buttons["Receipt"], app: app)
        let purpose = element("import.purpose", app)
        let selectedReceipt = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == true AND value == %@", "Receipt"), object: purpose)
        let selectionSettled = XCTWaiter.wait(for: [selectedReceipt], timeout: 10)
        let purposeValue = purpose.value
        let observedPurpose = purposeValue as? String ?? "<missing string value>"
        if selectionSettled != .completed || observedPurpose != "Receipt" {
            let actual = "value=\(String(describing: purposeValue)); label=\(purpose.label); wait=\(selectionSettled)"
            try ledger.require("Receipt purpose selected", actual: actual,
                               expected: "exact Receipt value within the selection wait")
        }
        try ledger.require("Receipt purpose selected", actual: observedPurpose, expected: "Receipt")
        try tap(element("import.photos", app), app: app)
        // PhotoKit verified the original and isolated this owned library before
        // scenario actions. Still reject any unexpected picker representation.
        let photoPredicate = NSPredicate(format: "label BEGINSWITH[c] %@", "Photo,")
        let photos = app.images.matching(photoPredicate)
        try ledger.require("seeded photo appears", photos.firstMatch.waitForExistence(timeout: 10))
        ledger.capture("recovery-photos-picker-before-selection", app: app, test: self)
        try ledger.require("exactly one seeded photo", actual: String(photos.count), expected: "1")
        let photoLabel = photos.firstMatch.label
        ledger.capturePhotosSelection("before", fixtureIsolated: bridge != nil,
                                      app: app)
        do {
            try tap(photos.firstMatch, app: app)
        } catch {
            ledger.capturePhotosSelection("after", fixtureIsolated: bridge != nil,
                                          app: app, failure: error)
            throw error
        }
        ledger.capturePhotosSelection("after", fixtureIsolated: bridge != nil,
                                      app: app)
        // Some supported picker versions expose Add for single selection;
        // others immediately deliver the sole selected image.
        if app.buttons["Add"].exists && app.buttons["Add"].isHittable {
            try tap(app.buttons["Add"], app: app)
        }
        try ledger.require("real OCR review presented", app.navigationBars["Review recognized text"].waitForExistence(timeout: 20))
        try checkpoint("photos_receipt_selected", observations: ["purpose": observedPurpose, "photo_label": photoLabel], app: app)
        let ocr = try readOCR(selected: [], expectedPrice: nil, app: app)
        let actualPrice = ocr["price"]!
        try ledger.require("Apply disabled before explicit selection", !app.buttons["ocr.apply"].isEnabled)
        try checkpoint("ocr_review_unselected", observations: ocr, app: app)
        for key in ["model", "purchasePrice"] {
            try selectOCRField(key, app: app)
        }
        let selectedOCR = try readOCR(selected: ["model", "price"], expectedPrice: actualPrice, app: app)
        try ledger.require("Apply exactly two fields", actual: app.buttons["ocr.apply"].label, expected: "Apply 2")
        try checkpoint("ocr_selection_model_price", observations: selectedOCR, app: app)
        try tap(app.buttons["ocr.apply"], app: app)
        try waitForDismissal(app.buttons["ocr.apply"])

        let recovered = ["model": "VISTA-420", "serial": "KEEP-SERIAL", "price": actualPrice,
                         "date": "2025-01-01", "notes": names["notes"]!]
        try checkpoint("source_item_after_ocr", observations: readItem(recovered, app: app), app: app)
        try closeItemEditor(app)
        try backToDashboard(app)
        try checkpoint("source_free", observations: freeStatus(app), app: app)
        let folder = "Recovery-\(journeyID)"
        try saveExport("export.package", baseName: "source-\(journeyID)", folder: folder, createFolder: true,
                       role: .sourceZIP, checkpointName: "source_zip_saved", app: app)
        try saveExport("export.backup", baseName: "backup-\(journeyID)", folder: folder, createFolder: false,
                       role: .backup, checkpointName: "backup_saved", app: app)

        app.terminate()
        activeRunID = targetID
        app.launchEnvironment["UITEST_RUN_ID"] = targetID
        app.launch()
        try checkpoint("target_empty_free", observations: emptyAndFree(app), app: app)
        try selectExport("export.restore", app: app)
        try enterFilesFolder(folder, create: false, app: app)
        let backup = fileItem("backup-\(journeyID)", app: app)
        try tap(backup, app: app, scroll: true)
        let confirmation = app.alerts["Replace the current inventory?"]
        try ledger.require("replacement warning presented", confirmation.waitForExistence(timeout: 10))
        let warning = confirmation.staticTexts["Replace the current inventory?"].label
        try ledger.require("actual replacement warning", actual: warning, expected: "Replace the current inventory?")
        try checkpoint("restore_confirmation", observations: ["warning": warning], app: app)
        try tap(restoreConfirmationButton(in: confirmation), app: app)
        let restored = app.alerts["Inventory restored"]
        try ledger.require("restore succeeded", restored.waitForExistence(timeout: 15))
        try tap(restored.buttons["OK"], app: app)
        try openItem(names, app: app)
        try checkpoint("target_restored", observations: readItem(recovered, app: app), app: app)
        try closeItemEditor(app)

        app.terminate()
        app.launch() // Same target namespace: verifies persisted restoration.
        try openItem(names, app: app)
        try checkpoint("target_relaunched", observations: readItem(recovered, app: app), app: app)
        try closeItemEditor(app)
        let attachments = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "item.attachment."))
        try ledger.require("one restored receipt", attachments.firstMatch.waitForExistence(timeout: 10))
        try ledger.require("attachment count", actual: String(attachments.count), expected: "1")
        try tap(attachments.firstMatch, app: app, scroll: true)
        let image = app.images["attachment.originalImage"]
        try ledger.require("original decoded into preview", image.waitForExistence(timeout: 10))
        try ledger.require("preview is Receipt", actual: image.label, expected: "Receipt")
        try ledger.require("preview has visible pixels", !image.frame.intersection(app.frame).isEmpty)
        let originalName = element("attachment.originalName", app).label
        try ledger.require("original PNG filename is visible", !originalName.isEmpty && originalName.lowercased().hasSuffix(".png"))
        try checkpoint("original_preview", observations: ["original_name": originalName, "image_label": image.label], app: app)
        try tap(app.navigationBars["Receipt"].buttons["Done"], app: app)
        try backToDashboard(app)
        try saveExport("export.package", baseName: "recovered-\(journeyID)", folder: folder, createFolder: false,
                       role: .targetZIP, checkpointName: "recovered_zip_saved", app: app)
        try checkpoint("target_free", observations: freeStatus(app), app: app)
        try ledger.require("app remains foreground", app.state == .runningForeground)
        guard let bridge else {
            throw RecoveryJourneyFailure.assertion("runner bridge", "missing", "initialized")
        }
        try bridge.requireComplete()
        try checkpoint("complete", observations: ["app_state": String(app.state.rawValue)], app: app)
        completed = true
    }

    private var ledger: RecoveryJourneyEvidence { evidence! }

    private func requiredUUID(_ key: String, _ environment: [String: String]) throws -> String {
        guard let raw = environment[key], let uuid = UUID(uuidString: raw) else {
            throw RecoveryJourneyFailure.assertion(key, "missing or invalid", "explicit UUID")
        }
        return uuid.uuidString
    }

    private func element(_ id: String, _ app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private func checkpoint(_ name: String, observations: [String: String], app: XCUIApplication) throws {
        try ledger.checkpoint(name, runID: activeRunID, observations: observations, app: app, test: self)
    }

    private func emptyAndFree(_ app: XCUIApplication) throws -> [String: String] {
        try ledger.require("dashboard present", app.navigationBars["Room Inventory"].waitForExistence(timeout: 10))
        let empty = app.buttons["inventory.addFirstHome"]
        try reveal(empty, app: app)
        let label = empty.label
        try ledger.require("empty inventory action", actual: label, expected: "Add your first home")
        try ledger.require("empty inventory loaded", empty.isEnabled)
        var result = try freeStatus(app)
        result["empty_label"] = label
        return result
    }

    private func freeStatus(_ app: XCUIApplication) throws -> [String: String] {
        let status = app.buttons["inventory.proStatus"]
        try reveal(status, app: app)
        let label = status.label
        try ledger.require("Free UI status", actual: label, expected: "Explore Pro")
        return ["free_label": label]
    }

    private func enterName(_ value: String, app: XCUIApplication) throws {
        let field = app.textFields["entry.name"]
        try typeIntoEmptyField(field, value: value, app: app)
        try tap(app.buttons["entry.save"], app: app)
        try waitForDismissal(field)
    }

    private func openRecord(_ name: String, app: XCUIApplication) throws {
        let row = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", name)).firstMatch
        try tap(row, app: app, scroll: true)
        try ledger.require("opened \(name)", app.navigationBars[name].waitForExistence(timeout: 10))
    }

    private func openItem(_ names: [String: String], app: XCUIApplication) throws {
        for key in ["home_name", "room_name", "item_name"] { try openRecord(names[key]!, app: app) }
    }

    private func typeIntoEmptyField(_ field: XCUIElement, value: String, app: XCUIApplication) throws {
        try tap(field, app: app, scroll: true)
        let before = field.value as? String ?? ""
        try ledger.require("field initially empty", before.isEmpty || before == field.placeholderValue)
        field.typeText(value)
        try ledger.require("typed value retained", actual: field.value as? String ?? "", expected: value)
    }

    private func readItem(_ expected: [String: String], app: XCUIApplication) throws -> [String: String] {
        try tap(app.buttons["item.editDetails"], app: app, scroll: true)
        var result: [String: String] = [:]
        for key in ["model", "serial", "price", "date", "notes"] {
            let field = element("itemEditor.\(key)", app)
            try reveal(field, app: app)
            let value = field.value as? String ?? ""
            try ledger.require("stored raw \(key)", actual: value, expected: expected[key]!)
            result[key] = value
        }
        return result
    }

    private func closeItemEditor(_ app: XCUIApplication) throws {
        try tap(app.buttons["itemEditor.cancel"], app: app)
        try waitForDismissal(app.buttons["itemEditor.cancel"])
    }

    private func readOCR(selected: Set<String>, expectedPrice: String?, app: XCUIApplication) throws -> [String: String] {
        let fields = [("model", "model", "VISTA-420"), ("serial", "serialNumber", "QA-2026-0042"),
                      ("price", "purchasePrice", expectedPrice ?? ""), ("date", "purchaseDate", "2026-10-20")]
        var result: [String: String] = [:]
        for (key, id, expected) in fields {
            let field = app.textFields["ocr.value.\(id)"]
            try reveal(field, app: app)
            let value = field.value as? String ?? ""
            if key == "price" && expectedPrice == nil {
                try ledger.require("OCR price is the exact supported receipt amount", ["USD149.50", "USD 149.50"].contains(value))
            } else {
                try ledger.require("actual Vision \(key)", actual: value, expected: expected)
            }
            let toggle = app.switches["ocr.select.\(id)"]
            try reveal(toggle, app: app)
            let state = toggle.value as? String ?? ""
            try ledger.require("OCR selection \(key)", actual: state, expected: selected.contains(key) ? "1" : "0")
            result[key] = value
            result["selected.\(key)"] = state
        }
        return result
    }

    private func selectOCRField(_ id: String, app: XCUIApplication) throws {
        let toggle = app.switches["ocr.select.\(id)"]
        try reveal(toggle, app: app)
        let ready = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == true AND hittable == true AND enabled == true AND value == %@", "0"),
            object: toggle)
        try ledger.require("OCR \(id) starts unselected and interactive", XCTWaiter.wait(for: [ready], timeout: 10) == .completed)
        // A SwiftUI labeled switch can expose the whole row as its frame.
        // This English-only journey activates the trailing switch itself, not
        // the center of that label/row. Never retry a toggle: a second tap can
        // undo a delayed first activation and hide a real interaction failure.
        let snapshot = try app.snapshot()
        typealias Node = (element: any XCUIElementSnapshot, form: (any XCUIElementSnapshot)?, inToolbar: Bool)
        var pending: [Node] = [(snapshot, nil, false)]
        var nodes: [Node] = []
        while let next = pending.popLast() {
            guard nodes.count < 10_000 else {
                throw RecoveryJourneyFailure.assertion("OCR geometry node bound", "exceeded", "10000 nodes")
            }
            let form = next.element.elementType == .collectionView ? next.element : next.form
            let inToolbar = next.inToolbar || next.element.elementType == .toolbar
            nodes.append((next.element, form, inToolbar))
            pending.append(contentsOf: next.element.children.reversed().map { ($0, form, inToolbar) })
        }
        let switches = nodes.filter { $0.element.elementType == .switch && $0.element.identifier == "ocr.select.\(id)" }
        let navigationBars = nodes.filter { $0.element.elementType == .navigationBar }
        let navigation = navigationBars.filter {
            [$0.element.identifier, $0.element.title, $0.element.label,
             $0.element.placeholderValue ?? "", $0.element.value as? String ?? ""].contains("Review recognized text")
        }
        try ledger.require("OCR \(id) visible form is identifiable", switches.count == 1
            && switches.first?.form != nil && navigation.count == 1)
        guard let target = switches.first, let form = target.form, let navigation = navigation.first else {
            throw RecoveryJourneyFailure.assertion("OCR form geometry", "missing", "identified")
        }
        let frame = target.element.frame
        let point = CGPoint(x: frame.maxX - 20, y: frame.midY)
        let viewport = form.frame.intersection(snapshot.frame).insetBy(dx: 2, dy: 2)
        let chrome = nodes.filter {
            [.navigationBar, .tabBar, .keyboard].contains($0.element.elementType)
                || ($0.inToolbar && $0.element.elementType == .button)
        }
        let toolbars = nodes.filter { $0.element.elementType == .toolbar }
        guard chrome.count <= 64, toolbars.count <= 16 else {
            throw RecoveryJourneyFailure.assertion("OCR geometry chrome bound", "exceeded", "64 controls / 16 toolbars")
        }
        // Hittable alone proves only that some point can receive input. The
        // actual trailing point must be in this OCR form, below its navigation
        // bar, and outside keyboards, tab bars and toolbar buttons. SwiftUI can
        // expose a transparent, full-screen Toolbar container with no controls;
        // that semantic container's bounds do not describe a painted obstruction.
        let covered = chrome.contains { !$0.element.frame.isEmpty && $0.element.frame.contains(point) }
        let checks = ["switch_size": frame.width >= 40 && frame.height >= 20,
                      "inside_form": !viewport.isNull && !viewport.isEmpty && viewport.contains(point),
                      "below_navigation": point.y > navigation.element.frame.maxY,
                      "outside_chrome": !covered,
                      "no_alert": !nodes.contains { $0.element.elementType == .alert }]
        func rectangle(_ frame: CGRect) -> [CGFloat] { [frame.minX, frame.minY, frame.width, frame.height] }
        let geometry: [String: Any] = ["field": id, "basis": "single_application_snapshot",
            "point": [point.x, point.y], "switch": rectangle(frame), "form_viewport": rectangle(viewport),
            "navigation": rectangle(navigation.element.frame), "checks": checks,
            "chrome": chrome.map { ["type": $0.element.elementType.rawValue, "frame": rectangle($0.element.frame)] },
            "toolbar_containers": toolbars.map { rectangle($0.element.frame) }]
        if let data = try? JSONSerialization.data(withJSONObject: geometry, options: [.sortedKeys]),
           data.count <= 16_384, let text = String(data: data, encoding: .utf8) {
            print("ROOM_OCR_TAP_GEOMETRY " + text)
        }
        try ledger.require("OCR \(id) switch point is unobscured", checks.values.allSatisfy { $0 })
        app.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: point.x - snapshot.frame.minX, dy: point.y - snapshot.frame.minY)).tap()
        let selected = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == true AND value == %@", "1"), object: toggle)
        try ledger.require("OCR \(id) selected after one activation", XCTWaiter.wait(for: [selected], timeout: 10) == .completed)
        try ledger.require("OCR \(id) selected value", actual: toggle.value as? String ?? "", expected: "1")
    }

    private func backToDashboard(_ app: XCUIApplication) throws {
        for _ in 0..<3 {
            if app.navigationBars["Room Inventory"].exists { return }
            try tap(app.navigationBars.buttons.element(boundBy: 0), app: app)
        }
        try ledger.require("returned to dashboard", app.navigationBars["Room Inventory"].waitForExistence(timeout: 5))
    }

    private func selectExport(_ id: String, app: XCUIApplication) throws {
        // Native Menu rows can omit SwiftUI accessibility identifiers. This
        // English-only journey selects one exact, visible action title instead.
        let titles = ["export.package": "Inventory package · ZIP",
                      "export.backup": "Restorable backup + originals",
                      "export.restore": "Restore a backup"]
        guard let title = titles[id] else {
            throw RecoveryJourneyFailure.assertion("known export action", id, "package, backup or restore")
        }
        try tap(app.buttons["inventory.exportMenu"], app: app)
        let actions = app.buttons.matching(NSPredicate(format: "label == %@", title))
        for _ in 0..<5 {
            let count = actions.count
            try ledger.require("export action is unambiguous: \(id)", count <= 1)
            if count == 1 {
                let action = actions.element(boundBy: 0)
                if action.isHittable { try tap(action, app: app); return }
            }
            let anchors = ["Restore a backup", "Restorable backup + originals", "Item table · CSV", "Report · PDF", "Inventory package · ZIP"]
            guard let anchor = anchors.map({ app.buttons[$0] }).first(where: { $0.exists && $0.isHittable }) else { break }
            let point = anchor.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            point.press(forDuration: 0.05, thenDragTo: point.withOffset(CGVector(dx: 0, dy: -110)))
        }
        try ledger.require("export action reachable: \(id)", false)
    }

    private func saveExport(_ action: String, baseName: String, folder: String, createFolder: Bool,
                            role: RecoveryJourneyBridge.Role, checkpointName: String, app: XCUIApplication) throws {
        guard let bridge else {
            throw RecoveryJourneyFailure.assertion("runner bridge", "missing", "initialized")
        }
        try bridge.synchronize(role: role, phase: .before, test: self)
        try selectExport(action, app: app)
        let saveToFiles = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Save to Files")).firstMatch
        if !saveToFiles.waitForExistence(timeout: 10) { try reveal(saveToFiles, app: app) }
        try tap(saveToFiles, app: app, scroll: true)
        try ledger.require("Files save dialog presented", app.buttons["Save"].waitForExistence(timeout: 10))
        try enterFilesFolder(folder, create: createFolder, app: app)
        let filename = app.textFields.firstMatch
        try tap(filename, app: app)
        let existingName = filename.value as? String ?? ""
        try ledger.require("export filename editable", !existingName.isEmpty)
        filename.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
        filename.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: existingName.count) + baseName)
        let observedName = filename.value as? String ?? ""
        try ledger.require("unique export base name", actual: observedName, expected: baseName)
        let observedTitle = filesFolderTitles(folder, app: app).element(boundBy: 0).label
        let actionsSuffix = ", Actions Menu"
        let observedFolder = observedTitle.hasSuffix(actionsSuffix)
            ? String(observedTitle.dropLast(actionsSuffix.count)) : observedTitle
        try ledger.require("unique export folder", actual: observedFolder, expected: folder)
        ledger.capture("recovery-\(checkpointName)-save-dialog", app: app, test: self)
        try tap(app.buttons["Save"], app: app)
        try waitForDismissal(app.buttons["Save"])
        if app.buttons["Close"].exists && app.buttons["Close"].isHittable { try tap(app.buttons["Close"], app: app) }
        try ledger.require("export returned to dashboard", app.buttons["inventory.exportMenu"].isHittable)
        try bridge.synchronize(role: role, phase: .after, test: self)
        try checkpoint(checkpointName, observations: ["save_name": observedName, "folder": observedFolder], app: app)
    }

    private func enterFilesFolder(_ folder: String, create: Bool, app: XCUIApplication) throws {
        if try filesFolderIsOpen(folder, app: app) {
            try ledger.require("existing target folder expected", !create)
            return
        }
        let localTitle = UIDevice.current.userInterfaceIdiom == .pad ? "On My iPad" : "On My iPhone"
        for _ in 0..<5 {
            if try filesFolderIsOpen(localTitle, app: app) { break }
            let local = fileItem(localTitle, app: app)
            if local.exists && local.isHittable {
                if !firstFilesTapCaptured {
                    firstFilesTapCaptured = true
                    ledger.captureFirstFilesTap("before", localTitle: localTitle, app: app)
                    // Keep the diagnostic pair when tap readiness throws; the
                    // nonthrowing capture preserves the original failure.
                    defer {
                        ledger.captureFirstFilesTap("after", localTitle: localTitle, app: app)
                    }
                    try tap(local, app: app)
                } else {
                    try tap(local, app: app)
                }
                continue
            }
            let browse = app.buttons["Browse"]
            if browse.exists && browse.isHittable { try tap(browse, app: app); continue }
            let back = app.navigationBars.buttons.matching(NSPredicate(format: "label == 'Back' OR label == 'Locations' OR label == 'Browse'")).firstMatch
            try tap(back, app: app)
        }
        try ledger.require("local Files location selected", filesFolderIsOpen(localTitle, app: app))
        if create {
            try ledger.require("run folder does not already exist", !fileItem(folder, app: app).exists)
            let more = app.buttons.matching(NSPredicate(format: "label == 'More' OR label == 'More Actions'")).firstMatch
            try tap(more, app: app)
            try tap(app.buttons["New Folder"], app: app)
            let inlineFields = app.textViews.matching(identifier: "DOC.inlineRenameField")
            let inline = inlineFields.element(boundBy: 0)
            if inline.waitForExistence(timeout: 5) {
                try ledger.require("unique inline folder editor", inlineFields.count == 1)
                try ledger.require("inline folder editor ready", inline.isHittable && inline.isEnabled)
                let previous = inline.value as? String ?? ""
                try ledger.require("inline default folder name present", !previous.isEmpty && previous.count <= 255)
                // New Folder focuses and selects its inline name. Type directly
                // so another tap cannot collapse the selection into the name.
                inline.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: previous.count) + folder)
                try ledger.require("folder name entered", actual: inline.value as? String ?? "", expected: folder)
                let done = app.keyboards.buttons.matching(identifier: "Done")
                try ledger.require("unique folder keyboard Done", done.count == 1)
                try tap(done.element(boundBy: 0), app: app)
                try waitForDismissal(inline)
            } else {
                let field = app.alerts.textFields.firstMatch
                try ledger.require("folder alert field appeared", field.waitForExistence(timeout: 10))
                try ledger.require("unique folder alert field", app.alerts.textFields.count == 1)
                try tap(field, app: app)
                let previous = field.value as? String ?? ""
                field.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
                field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: previous.count) + folder)
                try ledger.require("folder name entered", actual: field.value as? String ?? "", expected: folder)
                let createButton = app.alerts.buttons.matching(NSPredicate(format: "label == 'Done' OR label == 'Create'")).firstMatch
                try tap(createButton, app: app)
            }
        }
        if try !filesFolderIsOpen(folder, app: app) { try tap(fileItem(folder, app: app), app: app, scroll: true) }
        try ledger.require("run folder title appeared", filesFolderTitles(folder, app: app).element(boundBy: 0).waitForExistence(timeout: 5))
        try ledger.require("run folder opened", filesFolderIsOpen(folder, app: app))
    }

    private func filesFolderTitles(_ title: String, app: XCUIApplication) -> XCUIElementQuery {
        // Local storage uses a static title; a folder title can be a menu button.
        // Direct children avoid counting a button's own title a second time.
        app.navigationBars.children(matching: .any).matching(NSPredicate(
            format: "(elementType == %d AND label == %@) OR (elementType == %d AND label == %@)",
            XCUIElement.ElementType.staticText.rawValue, title,
            XCUIElement.ElementType.button.rawValue, title + ", Actions Menu"))
    }

    private func filesFolderIsOpen(_ title: String, app: XCUIApplication) throws -> Bool {
        let titles = filesFolderTitles(title, app: app)
        let count = titles.count
        guard count <= 1 else {
            throw RecoveryJourneyFailure.assertion("unique Files folder title", String(count), "at most one: \(title)")
        }
        return count == 1 && titles.element(boundBy: 0).isHittable
    }

    private func fileItem(_ name: String, app: XCUIApplication) -> XCUIElement {
        let predicate = NSPredicate(format: "label == %@ OR label BEGINSWITH %@ OR label BEGINSWITH %@", name, name + ".", name + ",")
        return app.descendants(matching: .any).matching(predicate).firstMatch
    }

    private func restoreConfirmationButton(in alert: XCUIElement) throws -> XCUIElement {
        let matches = alert.buttons.matching(identifier: "restore.confirm")
        try ledger.require("Restore button appeared", matches.firstMatch.waitForExistence(timeout: 10))
        let count = matches.count
        try ledger.require("bounded Restore button representation", (1...2).contains(count))
        let outer = matches.element(boundBy: 0)
        try ledger.require("Restore button label", actual: outer.label, expected: "Restore backup")
        let nested = outer.buttons.matching(identifier: "restore.confirm")
        try ledger.require("Restore duplicate is nested", nested.count == count - 1)
        let target = count == 2 ? nested.element(boundBy: 0) : outer
        try ledger.require("Restore target label", actual: target.label, expected: "Restore backup")
        let outerFrame = outer.frame
        try ledger.require("Restore button has visible bounds", !outerFrame.isEmpty)
        try ledger.require("Restore target shares wrapper bounds", target.frame == outerFrame)
        // Some runtimes expose an inaccessible wrapper with the same identifier.
        // The real leaf still passes the normal enabled/hittable wait before tap.
        return target
    }

    private func tap(_ target: XCUIElement, app: XCUIApplication, scroll: Bool = false) throws {
        if scroll { try reveal(target, app: app) }
        if !target.exists { try ledger.require("control exists", target.waitForExistence(timeout: 10)) }
        if !target.isHittable || !target.isEnabled {
            let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "hittable == true AND enabled == true"), object: target)
            try ledger.require("control interactive", XCTWaiter.wait(for: [ready], timeout: 10) == .completed)
        }
        target.tap()
    }

    private func waitForDismissal(_ target: XCUIElement) throws {
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: target)
        try ledger.require("sheet dismissed", XCTWaiter.wait(for: [gone], timeout: 10) == .completed)
    }

    private func reveal(_ target: XCUIElement, app: XCUIApplication) throws {
        if target.exists && target.isHittable { return }
        // Bound both directions; Forms and lazy Lists may reset on sheet entry.
        for down in [false, true, false] {
            for _ in 0..<5 {
                if target.exists && target.isHittable { return }
                let content = app.collectionViews.allElementsBoundByIndex.last ?? app.scrollViews.allElementsBoundByIndex.last ?? app
                let frame = content.frame.intersection(app.frame)
                let bottom = min(frame.maxY - 30, app.keyboards.firstMatch.exists ? app.keyboards.firstMatch.frame.minY - 65 : frame.maxY - 30)
                let top = frame.minY + 90
                try ledger.require("visible scroll area", bottom > top)
                let origin = app.coordinate(withNormalizedOffset: .zero)
                let high = origin.withOffset(CGVector(dx: frame.midX, dy: top + (bottom - top) * 0.2))
                let low = origin.withOffset(CGVector(dx: frame.midX, dy: top + (bottom - top) * 0.8))
                if down { high.press(forDuration: 0.05, thenDragTo: low) }
                else { low.press(forDuration: 0.05, thenDragTo: high) }
            }
        }
        try ledger.require("control reachable by bounded scrolling", target.exists && target.isHittable)
    }
}
