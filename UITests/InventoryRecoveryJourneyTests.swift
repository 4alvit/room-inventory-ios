import XCTest
import UIKit

/// Dedicated clean-Simulator test. Seed only SyntheticRecoveryReceipt.png into
/// Photos before opting in; all inventory creation and file operations use UI.
@MainActor
final class InventoryRecoveryJourneyTests: XCTestCase {
    private var evidence: RecoveryJourneyEvidence?
    private var bridge: RecoveryJourneyBridge?
    private var application: XCUIApplication?
    private var activeRunID = ""
    private var completed = false

    private func finishEvidence() throws {
        if let evidence, let application {
            defer { application.terminate() }
            let failures = (testRun?.failureCount ?? 1) + (testRun?.unexpectedExceptionCount ?? 0)
            if failures > 0 { evidence.recordIssue("XCTest recorded \(failures) failure(s)") }
            try evidence.finish(completed: completed && failures == 0, runID: activeRunID, app: application, test: self)
        }
    }

    func testPhotosOCRExportRestoreIntoFreshNamespace() throws {
        let environment = ProcessInfo.processInfo.environment
        try XCTSkipUnless(environment["RUN_INVENTORY_RECOVERY_JOURNEY"] == "1",
                          "Requires an explicitly allocated clean Simulator containing only the synthetic receipt in Photos.")
        executionTimeAllowance = 360
        continueAfterFailure = false
        let journeyID = try requiredUUID("RECOVERY_JOURNEY_RUN_ID", environment)
        let sourceID = try requiredUUID("RECOVERY_SOURCE_RUN_ID", environment)
        let targetID = try requiredUUID("RECOVERY_TARGET_RUN_ID", environment)
        guard Set([journeyID, sourceID, targetID]).count == 3 else {
            throw RecoveryJourneyFailure.assertion("distinct configured UUIDs", "duplicate", "three distinct UUIDs")
        }
        let suffix = String(journeyID.prefix(8))
        let names = ["home_name": "Recovery Home \(suffix)", "room_name": "Recovery Room \(suffix)",
                     "item_name": "Recovery Item \(suffix)", "notes": "Recovery receipt QA"]
        let ledger = RecoveryJourneyEvidence(journeyID: journeyID, sourceID: sourceID, targetID: targetID, expected: names)
        evidence = ledger
        let app = XCUIApplication()
        application = app
        // Async teardown crosses to this class's MainActor explicitly and also
        // runs after XCTest failures that can bypass a Swift defer statement.
        addTeardownBlock { [self] in try await finishEvidence() }
        bridge = try RecoveryJourneyBridge(journeyID: journeyID, sourceID: sourceID, targetID: targetID)
        app.launchArguments = ["--ui-testing", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
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
        let observedPurpose = (purpose.value as? String) ?? purpose.label
        try ledger.require("Receipt purpose selected", observedPurpose.contains("Receipt"))
        try tap(element("import.photos", app), app: app)
        // The runner must provide a dedicated library with this one fixture.
        // Reject an unexpected visible asset inventory instead of guessing.
        let photoPredicate = NSPredicate(format: "label BEGINSWITH[c] %@", "Photo,")
        let photos = app.images.matching(photoPredicate)
        try ledger.require("seeded photo appears", photos.firstMatch.waitForExistence(timeout: 10))
        try ledger.require("exactly one seeded photo", actual: String(photos.count), expected: "1")
        let photoLabel = photos.firstMatch.label
        ledger.capture("recovery-photos-picker-before-selection", app: app, test: self)
        try tap(photos.firstMatch, app: app)
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
            try tap(app.switches["ocr.select.\(key)"], app: app, scroll: true)
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
        try tap(confirmation.buttons["restore.confirm"], app: app)
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

    private func backToDashboard(_ app: XCUIApplication) throws {
        for _ in 0..<3 {
            if app.navigationBars["Room Inventory"].exists { return }
            try tap(app.navigationBars.buttons.element(boundBy: 0), app: app)
        }
        try ledger.require("returned to dashboard", app.navigationBars["Room Inventory"].waitForExistence(timeout: 5))
    }

    private func selectExport(_ id: String, app: XCUIApplication) throws {
        try tap(app.buttons["inventory.exportMenu"], app: app)
        let action = app.buttons[id]
        for _ in 0..<5 {
            if action.exists && action.isHittable { try tap(action, app: app); return }
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
        let observedFolder = app.navigationBars[folder].staticTexts[folder].label
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
        if app.navigationBars[folder].exists {
            try ledger.require("existing target folder expected", !create)
            return
        }
        let localTitle = UIDevice.current.userInterfaceIdiom == .pad ? "On My iPad" : "On My iPhone"
        for _ in 0..<5 {
            if app.navigationBars[localTitle].exists { break }
            let local = fileItem(localTitle, app: app)
            if local.exists && local.isHittable { try tap(local, app: app); continue }
            let browse = app.buttons["Browse"]
            if browse.exists && browse.isHittable { try tap(browse, app: app); continue }
            let back = app.navigationBars.buttons.matching(NSPredicate(format: "label == 'Back' OR label == 'Locations' OR label == 'Browse'")).firstMatch
            try tap(back, app: app)
        }
        try ledger.require("local Files location selected", app.navigationBars[localTitle].exists)
        if create {
            try ledger.require("run folder does not already exist", !fileItem(folder, app: app).exists)
            let more = app.buttons.matching(NSPredicate(format: "label == 'More' OR label == 'More Actions'")).firstMatch
            try tap(more, app: app)
            try tap(app.buttons["New Folder"], app: app)
            let field = app.alerts.textFields.firstMatch
            try tap(field, app: app)
            let previous = field.value as? String ?? ""
            field.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
            field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: previous.count) + folder)
            try ledger.require("folder name entered", actual: field.value as? String ?? "", expected: folder)
            let createButton = app.alerts.buttons.matching(NSPredicate(format: "label == 'Done' OR label == 'Create'")).firstMatch
            try tap(createButton, app: app)
        }
        if !app.navigationBars[folder].exists { try tap(fileItem(folder, app: app), app: app, scroll: true) }
        try ledger.require("run folder opened", app.navigationBars[folder].waitForExistence(timeout: 5))
    }

    private func fileItem(_ name: String, app: XCUIApplication) -> XCUIElement {
        let predicate = NSPredicate(format: "label == %@ OR label BEGINSWITH %@ OR label BEGINSWITH %@", name, name + ".", name + ",")
        return app.descendants(matching: .any).matching(predicate).firstMatch
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
