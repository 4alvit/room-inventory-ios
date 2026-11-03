import XCTest
import UIKit

/// Dedicated controller-owned Simulator test. The runner seeds the exact bundled
/// receipt into Photos and isolates it before inventory and file operations use UI.
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
                          "Requires a fresh controller-owned Simulator for the exact synthetic Photos receipt.")
        executionTimeAllowance = 720
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
            try typeIntoEmptyField(app.textFields["itemEditor.\(field)"], value: initial[field]!, app: app)
        }
        try tap(app.buttons["itemEditor.save"], app: app)
        try waitForDismissal(app.buttons.matching(identifier: "itemEditor.save"))
        try checkpoint("item_before_ocr", observations: readItem(initial, app: app), app: app)
        try closeItemEditor(app)

        try tap(app.buttons["item.addAttachment"], app: app, scroll: true)
        try tap(app.buttons["import.purpose"], app: app)
        try tap(app.buttons["Receipt"], app: app)
        let purpose = app.buttons["import.purpose"]
        let selectionDeadline = ProcessInfo.processInfo.systemUptime + 10
        var observedPurpose = "<no timely string value>"
        var purposeSnapshotError: String?
        // Reuse one typed snapshot per poll for the assertion and its evidence.
        // A slow native query may outlive the wait, but cannot authorize a late
        // success. Failure reporting must not resolve the purpose control again.
        let selectedReceipt = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard ProcessInfo.processInfo.systemUptime < selectionDeadline else { return false }
            do {
                let snapshot = try purpose.snapshot()
                purposeSnapshotError = nil
                let value = snapshot.value as? String
                guard ProcessInfo.processInfo.systemUptime < selectionDeadline else { return false }
                observedPurpose = value ?? "<missing string value>"
                return observedPurpose == "Receipt"
            } catch {
                purposeSnapshotError = String(describing: error)
                return false
            }
        }, object: nil)
        let selectionSettled = XCTWaiter.wait(for: [selectedReceipt],
            timeout: max(0, selectionDeadline - ProcessInfo.processInfo.systemUptime))
        let selectionWasTimely = ProcessInfo.processInfo.systemUptime < selectionDeadline
        if selectionSettled != .completed || !selectionWasTimely || observedPurpose != "Receipt" {
            let actual = "value=\(observedPurpose); wait=\(selectionSettled); timely=\(selectionWasTimely); snapshot_error=\(purposeSnapshotError ?? "<none>")"
            try ledger.require("Receipt purpose selected", actual: actual,
                               expected: "exact Receipt value within the selection wait")
        }
        try ledger.require("Receipt purpose selected", actual: observedPurpose, expected: "Receipt")
        try tap(app.buttons["import.photos"], app: app)
        let photosAppearance = RecoveryPhotosAppearanceWindow()
        // PhotoKit verified the original and isolated this owned library before
        // scenario actions. Still reject any unexpected picker representation.
        let photoPredicate = NSPredicate(format: "label BEGINSWITH[c] %@", "Photo,")
        let photos = app.images.matching(photoPredicate)
        let photoAppeared = try photosAppearance.waitForProbe {
            photos.firstMatch.exists
        }
        try ledger.require("seeded photo appears", photoAppeared)
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
        try waitForDismissal(app.buttons.matching(identifier: "ocr.apply"))

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
        try waitForDismissal(app.textFields.matching(identifier: "entry.name"))
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
            let field = app.textFields["itemEditor.\(key)"]
            try reveal(field, app: app)
            let value = field.value as? String ?? ""
            try ledger.require("stored raw \(key)", actual: value, expected: expected[key]!)
            result[key] = value
        }
        return result
    }

    private func closeItemEditor(_ app: XCUIApplication) throws {
        try tap(app.buttons["itemEditor.cancel"], app: app)
        try waitForDismissal(app.buttons.matching(identifier: "itemEditor.cancel"))
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
        let window = RecoveryOCRReadinessWindow()
        typealias Node = (element: any XCUIElementSnapshot, form: (any XCUIElementSnapshot)?, inToolbar: Bool)
        typealias Observation = (snapshot: any XCUIElementSnapshot, nodes: [Node], switches: [Node], navigation: [Node])
        func observeForm() throws -> Observation {
            let snapshot = try app.snapshot()
            _ = try window.remaining()
            var pending: [Node] = [(snapshot, nil, false)]
            var nodes: [Node] = []
            while let next = pending.popLast() {
                _ = try window.remaining()
                guard nodes.count < 10_000 else {
                    throw RecoveryJourneyFailure.assertion("OCR geometry node bound", "exceeded", "10000 nodes")
                }
                let form = next.element.elementType == .collectionView ? next.element : next.form
                let inToolbar = next.inToolbar || next.element.elementType == .toolbar
                nodes.append((next.element, form, inToolbar))
                pending.append(contentsOf: next.element.children.reversed().map { ($0, form, inToolbar) })
            }
            let switches = nodes.filter { $0.element.elementType == .switch && $0.element.identifier == "ocr.select.\(id)" }
            let navigation = nodes.filter { $0.element.elementType == .navigationBar }.filter {
                [$0.element.identifier, $0.element.title, $0.element.label,
                 $0.element.placeholderValue ?? "", $0.element.value as? String ?? ""].contains("Review recognized text")
            }
            return (snapshot, nodes, switches, navigation)
        }
        var observation: Observation?
        var observationError: Error?
        var observedState = "<no timely observation>"
        // A live four-property predicate resolves the same switch repeatedly.
        // Read state once from the snapshot also used for geometry, then make
        // only the separate hit test that a snapshot cannot provide.
        let readinessResult = try window.waitForProbe {
            if observation != nil || observationError != nil { return true }
            do {
                observation = try window.probe(snapshot: observeForm, stateReady: { candidate in
                    let targets = candidate.switches
                    guard targets.count <= 1, candidate.navigation.count <= 1 else {
                        throw RecoveryJourneyFailure.assertion("OCR \(id) unique form target",
                            "switches=\(targets.count), navigation=\(candidate.navigation.count)", "one of each")
                    }
                    let target = targets.first
                    let value = target?.element.value as? String
                    let enabled = target?.element.isEnabled == true
                    observedState = "switches=\(targets.count); enabled=\(enabled); value=\(value ?? "<missing>")"
                    return target?.form != nil && candidate.navigation.count == 1 && enabled && value == "0"
                }, hittable: {
                    let hittable = toggle.isHittable
                    observedState += "; hittable=\(hittable)"
                    return hittable
                })
                return observation != nil
            } catch {
                // End the wait without another snapshot; retain this error in
                // the diagnostic before any observation can authorize a tap.
                observationError = error
                return true
            }
        }
        let timely = (try? window.remaining()) != nil
        if readinessResult != .completed || !timely || observation == nil || observationError != nil {
            throw RecoveryJourneyFailure.assertion("OCR \(id) readiness",
                "\(observedState); wait=\(readinessResult); timely=\(timely); observation_error=\(observationError.map { String(describing: $0) } ?? "<none>")",
                "one enabled, unselected, hittable switch within 10 seconds")
        }
        try ledger.require("OCR \(id) starts unselected and interactive", readinessResult == .completed && observation != nil)
        guard let observation else {
            throw RecoveryJourneyFailure.assertion("OCR \(id) readiness observation", "missing", "completed")
        }
        // The visible label is separate from the native switch, whose frame
        // must stay narrow in this fixed English fixture. Let XCTest choose its
        // native hit point. Never retry a toggle: a second tap can undo a delayed
        // first activation and hide a real interaction failure.
        let (snapshot, nodes, switches, navigation) = observation
        try ledger.require("OCR \(id) visible form is identifiable", switches.count == 1
            && switches.first?.form != nil && navigation.count == 1)
        guard let target = switches.first, let form = target.form, let navigation = navigation.first else {
            throw RecoveryJourneyFailure.assertion("OCR form geometry", "missing", "identified")
        }
        let frame = target.element.frame
        let center = CGPoint(x: frame.midX, y: frame.midY)
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
        // entire switch frame must be in this OCR form, below its navigation
        // bar, and outside keyboards, tab bars and toolbar buttons. SwiftUI can
        // expose a transparent, full-screen Toolbar container with no controls;
        // that semantic container's bounds do not describe a painted obstruction.
        let covered = chrome.contains { !$0.element.frame.isEmpty && $0.element.frame.intersects(frame) }
        let checks = ["switch_size": frame.width >= 40 && frame.width <= 80 && frame.height >= 20,
                      "inside_form": !viewport.isNull && !viewport.isEmpty && viewport.contains(frame),
                      "below_navigation": frame.minY > navigation.element.frame.maxY,
                      "outside_chrome": !covered,
                      "no_alert": !nodes.contains { $0.element.elementType == .alert }]
        func rectangle(_ frame: CGRect) -> [CGFloat] { [frame.minX, frame.minY, frame.width, frame.height] }
        let geometry: [String: Any] = ["field": id, "basis": "single_application_snapshot",
            "activation": "native_switch_tap", "checked_region": "entire_switch_frame",
            "center": [center.x, center.y], "switch": rectangle(frame), "form_viewport": rectangle(viewport),
            "navigation": rectangle(navigation.element.frame), "checks": checks,
            "chrome": chrome.map { ["type": $0.element.elementType.rawValue, "frame": rectangle($0.element.frame)] },
            "toolbar_containers": toolbars.map { rectangle($0.element.frame) }]
        if let data = try? JSONSerialization.data(withJSONObject: geometry, options: [.sortedKeys]),
           data.count <= 16_384, let text = String(data: data, encoding: .utf8) {
            print("ROOM_OCR_TAP_GEOMETRY " + text)
        }
        try ledger.require("OCR \(id) entire switch is unobscured", checks.values.allSatisfy { $0 })
        _ = try window.remaining() // Geometry and evidence cannot authorize a late tap.
        toggle.tap()
        let selectionWindow = RecoveryOCRSelectionWindow()
        var selectionObservation: RecoveryOCRSelectionWindow.Observation?
        var selectionError: Error?
        func observeSelection() -> Bool {
            if selectionObservation?.selected == true || selectionError != nil { return true }
            do {
                selectionObservation = try selectionWindow.observe(identifier: "ocr.select.\(id)",
                    snapshot: { try app.snapshot() }, children: { $0.children },
                    isSwitch: { $0.elementType == .switch }, identifierOf: { $0.identifier },
                    value: { $0.value as? String })
                return selectionObservation?.selected == true
            } catch {
                selectionError = error
                return true
            }
        }
        // Probe immediately: XCTest's first predicate poll can spend a second
        // of this allowance before starting an already slow remote query.
        var selectionResult: XCTWaiter.Result?
        if !observeSelection() {
            let selected = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                observeSelection()
            }, object: nil)
            do {
                selectionResult = XCTWaiter.wait(for: [selected], timeout: try selectionWindow.remaining())
            } catch {
                selectionError = error
            }
        }
        let selectionTimely = (try? selectionWindow.remaining()) != nil
        guard selectionTimely, selectionError == nil, selectionObservation?.selected == true,
              selectionResult == nil || selectionResult == .completed else {
            let observed = "matches=\(selectionObservation?.matches ?? 0); value=\(selectionObservation?.value ?? "<missing>"); wait=\(selectionResult.map { String(describing: $0) } ?? "immediate"); timely=\(selectionTimely); error=\(selectionError.map { String(describing: $0) } ?? "<none>")"
            throw RecoveryJourneyFailure.assertion("OCR \(id) selected after one activation", observed,
                "one selected target switch observed within 10 seconds")
        }
        try ledger.require("OCR \(id) selected after one activation", selectionObservation?.selected == true)
        try ledger.require("OCR \(id) selected value", actual: selectionObservation?.value ?? "", expected: "1")
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
        let saveButtons = app.buttons.matching(identifier: "Save")
        let saveButton = saveButtons.element
        try ledger.require("Files save dialog presented", saveButton.waitForExistence(timeout: 10))
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
        guard let homeName = ledger.expected["home_name"] else {
            throw RecoveryJourneyFailure.assertion("export return home", "missing", "run-bound home")
        }
        try tap(saveButton, app: app)
        let returning = ExportReturnReadiness(homeName: homeName)
        var returnSucceeded = false
        do {
            defer {
                var record = returning.diagnostic
                record["role"] = role.rawValue
                record["result"] = returnSucceeded ? "returned" : "failed"
                if let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]),
                   data.count <= 4_096, let text = String(data: data, encoding: .utf8) {
                    print("ROOM_EXPORT_RETURN_V2 " + text)
                }
            }
            // Each probe takes one immutable app snapshot. Remote Files nodes may
            // be omitted, so their absence is never our return condition. Unique
            // positive anchors identify the screen; the run-bound home also
            // needs current native hittability. firstMatch avoids exhaustive
            // remote traversal after snapshot uniqueness checks;
            // these observations are sequential, not an atomic hierarchy snapshot.
            let home = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", homeName + ", ")).firstMatch
            let close = app.navigationBars.matching(identifier: "UIActivityContentView").buttons
                .matching(NSPredicate(format: "identifier == %@ AND label == %@", "header.closeButton", "Close"))
                .firstMatch
            returnSucceeded = try returning.waitForReturn(observe: {
                let root = try app.snapshot()
                var nodes: [ExportReturnReadiness.Element] = []
                var pending = root.children.reversed().map { ($0, Optional<Int>.none) }
                while let (node, parent) = pending.popLast() {
                    guard nodes.count < 10_000 else { throw ExportReturnReadiness.Failure.invalidObservation }
                    let kind: ExportReturnReadiness.Kind
                    switch node.elementType {
                    case .button: kind = .button
                    case .staticText: kind = .text
                    case .navigationBar: kind = .navigationBar
                    case .alert: kind = .alert
                    default: kind = .other
                    }
                    let index = nodes.count
                    nodes.append(.init(kind: kind, identifier: node.identifier, label: node.label,
                                       enabled: node.isEnabled, frame: node.frame, parent: parent))
                    pending.append(contentsOf: node.children.reversed().map { ($0, Optional(index)) })
                }
                return .init(frame: root.frame, elements: nodes)
            }, isHittable: { target in
                switch target {
                case .home: return home.isHittable
                case .shareClose: return close.isHittable
                }
            }, close: { close.tap() })
        }
        try ledger.require("sheet dismissed", returnSucceeded)
        try ledger.require("export returned to dashboard", returnSucceeded)
        try bridge.synchronize(role: role, phase: .after, test: self)
        try checkpoint(checkpointName, observations: ["save_name": observedName, "folder": observedFolder], app: app)
    }

    private func enterFilesFolder(_ folder: String, create: Bool, app: XCUIApplication) throws {
        let localTitle = UIDevice.current.userInterfaceIdiom == .pad ? "On My iPad" : "On My iPhone"
        // A cold document service can still be starting after the presentation
        // tap returns. An empty sheet is not evidence that Back is the next step.
        var state = try waitForFilesNavigationState(folder, localTitle: localTitle,
                                                    app: app, initial: true)
        var navigationActions = 0
        navigation: while true {
            switch state {
            case .targetFolder:
                try ledger.require("existing target folder expected", !create)
                return
            case .localRoot:
                break navigation
            case .localEntry, .browse, .back:
                guard navigationActions < 5 else {
                    throw RecoveryJourneyFailure.assertion("bounded Files navigation", "exhausted", "local location within five actions")
                }
            }
            switch state {
            case .localEntry:
                let local = fileItem(localTitle, app: app)
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
            case .browse:
                try tap(app.buttons["Browse"], app: app)
            case .back:
                try tap(filesBackButton(app: app), app: app)
            case .targetFolder, .localRoot:
                throw RecoveryJourneyFailure.assertion("Files navigation action", "folder state", "navigation control")
            }
            navigationActions += 1
            state = try waitForFilesNavigationState(folder, localTitle: localTitle,
                                                   app: app, initial: false)
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
                let dismissal = ElementDismissalReadiness()
                try ledger.require("sheet dismissed", try dismissal.waitForDismissal { inlineFields.count })
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

    private func filesBackButton(app: XCUIApplication) -> XCUIElement {
        app.navigationBars.buttons.matching(NSPredicate(
            format: "label == 'Back' OR label == 'Locations' OR label == 'Browse'")).firstMatch
    }

    private func waitForFilesNavigationState(_ folder: String, localTitle: String,
                                            app: XCUIApplication, initial: Bool) throws -> FilesNavigationReadiness.State {
        let allowance: TimeInterval = initial ? 30 : 10
        let readiness = FilesNavigationReadiness(timeout: allowance)
        let began = ProcessInfo.processInfo.systemUptime
        var selected: FilesNavigationReadiness.State?
        defer {
            let record: [String: Any] = [
                "schema_version": 1, "phase": initial ? "presentation" : "navigation",
                "allowance_seconds": allowance,
                "elapsed_seconds": ProcessInfo.processInfo.systemUptime - began,
                "result": selected == nil ? "failed" : "ready",
                "state": selected.map { String(describing: $0) } as Any? ?? NSNull()
            ]
            if let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]),
               data.count <= 4_096, let text = String(data: data, encoding: .utf8) {
                print("ROOM_FILES_NAVIGATION_V1 \(text)")
            }
        }
        func interactive(_ element: XCUIElement) throws -> Bool {
            guard try readiness.perform({ element.exists }) else { return false }
            guard try readiness.perform({ element.isEnabled }) else { return false }
            return try readiness.perform { element.isHittable }
        }
        func folderOpen(_ title: String) throws -> Bool {
            let titles = filesFolderTitles(title, app: app)
            let count = try readiness.perform { titles.count }
            guard count <= 1 else {
                throw RecoveryJourneyFailure.assertion("unique Files folder title", String(count), "at most one: \(title)")
            }
            guard count == 1 else { return false }
            return try interactive(titles.element(boundBy: 0))
        }
        let state = try readiness.waitForState {
            // Live queries include the remote document service. app.snapshot()
            // alone can omit its controls and cannot prove that it is absent.
            if try folderOpen(folder) { return .targetFolder }
            if try folderOpen(localTitle) { return .localRoot }
            if try interactive(self.fileItem(localTitle, app: app)) { return .localEntry }
            if try interactive(app.buttons["Browse"]) { return .browse }
            if try interactive(self.filesBackButton(app: app)) { return .back }
            return nil
        }
        selected = state
        return state
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

    private func waitForDismissal(_ query: XCUIElementQuery) throws {
        let dismissal = ElementDismissalReadiness()
        try ledger.require("sheet dismissed", try dismissal.waitForDismissal { query.count })
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
