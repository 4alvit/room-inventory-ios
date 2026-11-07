import Foundation
import XCTest
import UIKit

/// Black-box exercise of the preinstalled, unchanged published Release app.
/// No application target/dependency, @testable import, seed, reset or Pro override.
@MainActor
final class RCArtifactAcceptanceTests: XCTestCase {
    private struct Failure: Error { let message: String }
    private let introduction = NameEntryKeyboardReadiness.ContinueAllowance()
    private var steps: [String] = []
    private var runID = ""
    private var directory: URL!
    private var names: [String: String] = [:]
    private var cancelled = 0
    private var restored = 0
    private let arguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]

    func testPublishedRC() throws {
        continueAfterFailure = false
        guard let raw = ProcessInfo.processInfo.environment["RC_ACCEPTANCE_ID"],
              let id = UUID(uuidString: raw), id.uuidString == raw else {
            throw Failure(message: "Missing canonical execution UUID")
        }
        runID = raw
        names = ["home": "RC Home " + String(raw.prefix(8)), "room": "RC Room " + String(raw.prefix(8)),
                 "item": "RC Item " + String(raw.prefix(8))]
        directory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("RC-" + runID, isDirectory: true)
        try require(!FileManager.default.fileExists(atPath: directory.path), "Fresh evidence directory required")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        let app = XCUIApplication(bundleIdentifier: "com.alvit.roominventory")
        app.launchArguments = arguments
        app.launchEnvironment = [:]
        defer { app.terminate() }
        do {
            app.launch()
            try ready(app.buttons.matching(identifier: "inventory.addFirstHome"))
            try checkpoint("fresh-launch", app)
            for (key, action) in [("home", "inventory.addFirstHome"), ("room", "Add a room"), ("item", "Add an item")] {
                try tap(app.buttons.matching(identifier: action))
                let value = names[key]!
                let result = try AutofocusedNameEntry.type(value, in: app, allowance: introduction,
                    evidence: { stage in try self.capture("keyboard-" + stage.rawValue, app) })
                try require(result.after == value, "Exact newly entered name")
                try tap(app.buttons.matching(identifier: "entry.save"))
                try openRecord(value, app)
            }
            try checkpoint("created-records", app)
            try edit(notes: "RC saved notes", populate: true, app)
            try checkpoint("edited-record", app)
            app.terminate(); app.launch()
            try openItem(app)
            try inspectDetails(notes: "RC saved notes", app)
            try checkpoint("cold-relaunch", app)
            try dashboard(app)
            for (kind, title) in [("csv", "Item table · CSV"), ("pdf", "Report · PDF"),
                                  ("package", "Inventory package · ZIP"), ("backup", "Restorable backup + originals")] {
                try export(title, baseName: kind + "-" + runID, create: kind == "csv", app)
                try checkpoint("saved-" + kind, app)
            }
            // A real selected backup reaches confirmation; cancellation preserves data.
            try selectBackup(app)
            try tap(app.alerts.matching(identifier: "Replace the current inventory?").buttons.matching(identifier: "Cancel"))
            cancelled += 1
            try openItem(app); try inspectDetails(notes: "RC saved notes", app)
            try dashboard(app)
            try export("Restorable backup + originals", baseName: "cancel-backup-" + runID, create: false, app)
            try openItem(app)
            try checkpoint("restore-cancelled", app)
            try edit(notes: "RC MUTATED " + runID, populate: false, app)
            app.terminate(); app.launch()
            try openItem(app)
            try inspectDetails(notes: "RC MUTATED " + runID, app)
            try checkpoint("mutated-record", app)
            try dashboard(app); try selectBackup(app)
            let alert = app.alerts["Replace the current inventory?"]
            let candidates = alert.buttons.matching(identifier: "restore.confirm")
            // SwiftUI can expose the action as an outer wrapper and one nested leaf.
            let window = FilesNavigationReadiness(timeout: 10)
            let count = try window.perform { candidates.count }
            try require((1...2).contains(count), "Exact restore action representation")
            let outer = candidates.element(boundBy: 0)
            let nested = outer.buttons.matching(identifier: "restore.confirm")
            try require(try window.perform { nested.count } == count - 1, "Only nested duplicate allowed")
            let target = count == 2 ? nested.element(boundBy: 0) : outer
            try require(try window.perform { target.label } == "Restore backup", "Exact restore label")
            let targetFrame = try window.perform { target.frame }
            let outerFrame = try window.perform { outer.frame }
            try require(!targetFrame.isEmpty && targetFrame == outerFrame, "Restore wrapper geometry")
            try require(try window.perform { target.isEnabled && target.isHittable }, "Restore ready")
            try window.perform { target.tap() }; restored += 1
            try tap(app.alerts.matching(identifier: "Inventory restored").buttons.matching(identifier: "OK"), timeout: 30)
            try checkpoint("restore-confirmed", app)
            app.terminate(); app.launch()
            try openItem(app); try inspectDetails(notes: "RC saved notes", app)
            try checkpoint("restored-relaunch", app)
            try journal(status: "complete")
        } catch {
            // The original failure remains authoritative even if evidence capture fails.
            // Signal before potentially slow screenshot/AX calls, while the AUT
            // is still alive. This marker can only request failure diagnostics.
            try? FileHandle.standardOutput.write(contentsOf:
                Data(("ROOM_RC_SAMPLE_V1 " + runID + "\n").utf8))
            // Persist the original failure before screenshot/AX diagnostics can block.
            try? journal(status: "failed", failure: String(describing: error))
            try? capture("failure", app)
            throw error
        }
    }

    private func require(_ value: Bool, _ message: String) throws {
        if !value { throw Failure(message: message) }
    }

    @discardableResult
    private func ready(_ query: XCUIElementQuery, timeout: TimeInterval = 10) throws -> XCUIElement {
        let w = FilesNavigationReadiness(timeout: timeout)
        try w.waitForTargetFolder(titleCount: { query.count },
            enabled: { query.firstMatch.isEnabled }, hittable: { query.firstMatch.isHittable })
        return query.firstMatch
    }

    private func tap(_ query: XCUIElementQuery, timeout: TimeInterval = 10) throws {
        let w = FilesNavigationReadiness(timeout: timeout)
        // Retain this probe's unique identity through the live gates and tap.
        try w.waitAndTapBoundElement(
            matchingElements: { query.allElementsBoundByAccessibilityElement },
            enabled: { $0.isEnabled }, hittable: { $0.isHittable }, tap: { $0.tap() })
    }

    private func openRecord(_ name: String, _ app: XCUIApplication) throws {
        // Reuse the existing tap10 + target10 allocation as one transition.
        // Native event delivery may itself wait for idleness; it cannot renew
        // this deadline or replace positive readiness of the exact destination.
        let window = FilesNavigationReadiness(timeout: 20)
        let rows = app.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", name, name + ", "))
        try performBoundTap(window,
            matchingElements: { rows.allElementsBoundByAccessibilityElement },
            enabled: { $0.isEnabled }, hittable: { $0.isHittable }, tap: { $0.tap() })
        let target = app.navigationBars.matching(identifier: name)
        _ = try window.waitForTargetFolder(titleCount: { target.count },
            enabled: { target.firstMatch.isEnabled }, hittable: { target.firstMatch.isHittable })
    }

    private func performBoundTap<Element>(_ window: FilesNavigationReadiness,
                                         matchingElements: @escaping () throws -> [Element],
                                         enabled: @escaping (Element) throws -> Bool,
                                         hittable: @escaping (Element) throws -> Bool,
                                         tap: @escaping (Element) throws -> Void) throws {
        var reserved: Element?
        // Consume the existing single-action admission with the exact identity.
        // This callback only reserves it; it performs no native UI action.
        try window.waitAndTapBoundElement(matchingElements: matchingElements,
            enabled: enabled, hittable: hittable, tap: { reserved = $0 })
        guard let reserved else { throw FilesNavigationReadiness.Failure.invalidSelectionCount }
        // The readiness waiter has unwound. The same absolute window still
        // rejects cancellation, expired admission, late return and native error.
        // Native synchronization is no longer interrupted by our readiness waiter;
        // a blocking action may overrun this window but can never qualify late.
        try window.perform { try tap(reserved) }
    }

    private func openItem(_ app: XCUIApplication) throws {
        for key in ["home", "room", "item"] { try openRecord(names[key]!, app) }
    }

    private func dashboard(_ app: XCUIApplication) throws {
        // Each transition is a distinct public back action with a bounded target.
        for title in [names["room"]!, names["home"]!, "Room Inventory"] {
            try tap(app.navigationBars.buttons.matching(identifier: title))
        }
        try ready(app.buttons.matching(identifier: "inventory.exportMenu"))
    }

    private func field(_ id: String, _ value: String, replace: Bool, _ app: XCUIApplication) throws {
        let query = app.textFields.matching(identifier: id)
        // At most three bounded scroll actions; never blindly repeat input.
        for _ in 0..<3 {
            if query.firstMatch.exists && query.firstMatch.isHittable { break }
            app.swipeUp()
        }
        let element = try ready(query)
        let old = element.value as? String ?? ""
        try tap(query)
        let w = FilesNavigationReadiness(timeout: 10)
        if replace {
            // Explicit select-all is a public editing action; no guessed deletion length.
            try w.perform { element.press(forDuration: 1) }
            try tap(app.menuItems.matching(identifier: "Select All"))
        }
        try w.perform { element.typeText(value) }
        try w.waitForState {
            let actual = try w.perform { element.value as? String }
            return actual == value ? .targetFolder : nil
        }
        try require(old != value || replace, "Edit must change the selected field")
    }

    private func edit(notes: String, populate: Bool, _ app: XCUIApplication) throws {
        try tap(app.buttons.matching(identifier: "item.editDetails"))
        if populate {
            for (id, value) in [("model", "RC Model"), ("serial", "RC-SERIAL-001"),
                ("price", "USD 123.45"), ("date", "2026-01-02")] {
                try field("itemEditor." + id, value, replace: false, app)
            }
        }
        try field("itemEditor.notes", notes, replace: !populate, app)
        try tap(app.buttons.matching(identifier: "itemEditor.save"))
        try ready(app.navigationBars.matching(identifier: names["item"]!))
    }

    private func inspectDetails(notes: String, _ app: XCUIApplication) throws {
        try tap(app.buttons.matching(identifier: "item.editDetails"))
        for (id, value) in [("model", "RC Model"), ("serial", "RC-SERIAL-001"),
            ("price", "USD 123.45"), ("date", "2026-01-02"), ("notes", notes)] {
            let query = app.textFields.matching(identifier: "itemEditor." + id)
            let w = FilesNavigationReadiness(timeout: 10)
            try w.waitForState {
                let n = try w.perform { query.count }
                try self.require(n <= 1, "Unique detail field")
                guard n == 1 else { return nil }
                return try w.perform { query.firstMatch.value as? String } == value ? .targetFolder : nil
            }
        }
        try tap(app.buttons.matching(identifier: "itemEditor.cancel"))
        try ready(app.navigationBars.matching(identifier: names["item"]!))
    }

    private func select(_ title: String, _ app: XCUIApplication) throws {
        try tap(app.buttons.matching(identifier: "inventory.exportMenu"))
        try tap(app.buttons.matching(NSPredicate(format: "label == %@", title)))
    }

    private func titleQuery(_ name: String, _ app: XCUIApplication) -> XCUIElementQuery {
        app.navigationBars.children(matching: .any).matching(NSPredicate(
            format: "(elementType == %d AND label == %@) OR (elementType == %d AND label == %@)",
            XCUIElement.ElementType.staticText.rawValue, name,
            XCUIElement.ElementType.button.rawValue, name + ", Actions Menu"))
    }

    private func fileRow(_ name: String, _ app: XCUIApplication) -> XCUIElementQuery {
        app.cells.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", name, name + ","))
    }

    private func filesNavigationState(_ folder: String, localTitle: String, initial: Bool,
                                      _ app: XCUIApplication) throws -> FilesNavigationReadiness.State {
        let allowance = FilesNavigationReadiness.systemProviderAllowance
        let readiness = FilesNavigationReadiness(timeout: allowance)
        let began = ProcessInfo.processInfo.systemUptime
        var selected: FilesNavigationReadiness.State?
        defer {
            let capture = readiness.navigationCaptureDiagnostics
            let record: [String: Any] = [
                "schema_version": 2, "phase": initial ? "presentation" : "navigation",
                "allowance_seconds": allowance,
                "elapsed_seconds": ProcessInfo.processInfo.systemUptime - began,
                "result": selected == nil ? "failed" : "ready",
                "state": selected.map { String(describing: $0) } as Any? ?? NSNull(),
                "query_attempts": capture.queryAttempts, "queries_completed": capture.queriesCompleted,
                "snapshot_attempts": capture.snapshotAttempts, "snapshots_completed": capture.snapshotsCompleted,
                "last_query_seconds": capture.lastQueryDuration as Any? ?? NSNull(),
                "last_query_remaining_seconds": capture.lastQueryRemainingAtStart as Any? ?? NSNull(),
                "last_snapshot_seconds": capture.lastSnapshotDuration as Any? ?? NSNull(),
                "last_snapshot_remaining_seconds": capture.lastSnapshotRemainingAtStart as Any? ?? NSNull(),
                "last_picker_count": capture.lastPickerCount as Any? ?? NSNull(),
                "last_node_count": capture.lastNodeCount, "last_stage": capture.stage
            ]
            if let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]),
               data.count <= 4_096, let text = String(data: data, encoding: .utf8) {
                print("ROOM_RC_FILES_NAVIGATION_V1 \(text)")
            }
        }
        let state = try readiness.waitForState {
            try readiness.captureNavigationState(folder: folder, localTitle: localTitle, app: app)
        }
        selected = state
        return state
    }

    private func beginFolderCreation(_ app: XCUIApplication, isPad: Bool) throws {
        let action = FilesNavigationReadiness(timeout: 10)
        let pickers = app.otherElements.matching(NSPredicate(format: "identifier == %@", FilesNavigationReadiness.pickerIdentifier))
        try performBoundTap(action, matchingElements: { () throws -> [XCUIElement] in
            let owners = try action.perform { pickers.allElementsBoundByAccessibilityElement }
            guard owners.count <= 1 else { throw FilesNavigationReadiness.Failure.invalidSelectionCount }
            guard let picker = owners.first else { return [] }
            if isPad {
                // Require positive direct creation evidence in the iPad picker.
                // Missing or ambiguous evidence never authorizes sidebar More.
                return try action.perform {
                    picker.buttons.matching(identifier: "New Folder").allElementsBoundByAccessibilityElement
                }
            }
            let bars = try action.perform {
                picker.navigationBars.matching(identifier: FilesNavigationReadiness.navigationBarIdentifier)
                    .allElementsBoundByAccessibilityElement
            }
            guard bars.count <= 1 else { throw FilesNavigationReadiness.Failure.invalidSelectionCount }
            guard let bar = bars.first else { return [] }
            return try action.perform {
                bar.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@",
                    "OverflowBarButtonItem", "More")).allElementsBoundByAccessibilityElement
            }
        }, enabled: { $0.isEnabled }, hittable: { $0.isHittable }, tap: { $0.tap() })
        if !isPad {
            // A distinct existing10s action opens creation from the positively
            // selected content overflow. It is never a fallback for the iPad.
            let menu = FilesNavigationReadiness(timeout: 10)
            let newFolder = app.buttons.matching(identifier: "New Folder")
            try performBoundTap(menu, matchingElements: { newFolder.allElementsBoundByAccessibilityElement },
                enabled: { $0.isEnabled }, hittable: { $0.isHittable }, tap: { $0.tap() })
        }
    }

    private func folder(_ create: Bool, _ app: XCUIApplication) throws {
        let local = UIDevice.current.userInterfaceIdiom == .pad ? "On My iPad" : "On My iPhone"
        let folder = "RC-" + runID
        for index in 0..<6 {
            let state = try filesNavigationState(folder, localTitle: local, initial: index == 0, app)
            if state == .targetFolder { try require(!create, "Fresh export folder required"); return }
            if state == .localRoot { break }
            try require(index < 5, "Files navigation action cap")
            let pickers = app.otherElements.matching(NSPredicate(format: "identifier == %@", FilesNavigationReadiness.pickerIdentifier))
            let target: XCUIElementQuery
            let navigationContextCount: () -> Int
            switch state {
            case .localEntry:
                let localEntry = NSPredicate(format:
                    "(elementType == %d OR elementType == %d) AND identifier != %@ AND (label == %@ OR label BEGINSWITH %@)",
                    XCUIElement.ElementType.cell.rawValue, XCUIElement.ElementType.button.rawValue,
                    "BackButton", local, local + ",")
                target = pickers.descendants(matching: .any).matching(localEntry)
                let navigationMatches = pickers.navigationBars.descendants(matching: .any).matching(localEntry)
                // A bar title is not a location action. Fail closed if the native
                // query cannot distinguish it from the observed local entry.
                navigationContextCount = { navigationMatches.count == 0 ? 1 : 0 }
            case .browse:
                target = pickers.buttons.matching(NSPredicate(format: "label == %@ OR identifier == %@", "Browse", "Browse"))
                navigationContextCount = { 1 }
            case .back:
                let bars = pickers.navigationBars.matching(NSPredicate(format: "identifier == %@", FilesNavigationReadiness.navigationBarIdentifier))
                target = bars.children(matching: .button).matching(NSPredicate(
                    format: "label == 'Back' OR label == 'Locations' OR label == 'Browse'"))
                navigationContextCount = { bars.count }
            default: throw Failure(message: "Unexpected Files state")
            }
            let action = FilesNavigationReadiness(timeout: 10)
            try action.waitAndTapFile(pickerCount: { pickers.count }, folderCount: navigationContextCount,
                fileViewCount: { 1 }, fileCount: { target.count }, enabled: { target.firstMatch.isEnabled },
                hittable: { target.firstMatch.isHittable }, tap: { target.firstMatch.tap() })
        }
        try ready(titleQuery(local, app))
        if create {
            try require(fileRow(folder, app).count == 0, "Folder already exists")
            try beginFolderCreation(app, isPad: UIDevice.current.userInterfaceIdiom == .pad)
            let inline = app.textViews.matching(identifier: "DOC.inlineRenameField")
            if inline.firstMatch.waitForExistence(timeout: 5) {
                let element = try ready(inline)
                let old = element.value as? String ?? ""
                try require(!old.isEmpty && old.count <= 255, "Initial inline folder name")
                element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: old.count) + folder)
                try require(element.value as? String == folder, "Exact folder name")
                try tap(app.keyboards.buttons.matching(identifier: "Done"))
            } else {
                let q = app.alerts.textFields
                let element = try ready(q); let old = element.value as? String ?? ""
                element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: old.count) + folder)
                try require(element.value as? String == folder, "Exact folder name")
                try tap(app.alerts.buttons.matching(NSPredicate(format: "label == 'Done' OR label == 'Create'")))
            }
            // Observe the exact remote Files owner, never a disappeared editor.
            let creation = FilesNavigationReadiness(timeout: FilesNavigationReadiness.systemProviderAllowance)
            let began = ProcessInfo.processInfo.systemUptime
            var folderReady = false
            var titleCount: Int?
            defer {
                let record: [String: Any] = [
                    "schema_version": 1, "phase": "creation", "folder": folder,
                    "allowance_seconds": FilesNavigationReadiness.systemProviderAllowance,
                    "elapsed_seconds": ProcessInfo.processInfo.systemUptime - began,
                    "result": folderReady ? "ready" : "failed",
                    "last_stage": creation.titleCaptureStage.rawValue,
                    "last_returned_title_count": titleCount as Any? ?? NSNull()
                ]
                if let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]),
                   data.count <= 4_096, let text = String(data: data, encoding: .utf8) {
                    print("ROOM_RC_FILES_CREATION_V1 \(text)")
                }
            }
            let navigationBars = app.navigationBars.matching(identifier:
                FilesNavigationReadiness.navigationBarIdentifier)
            folderReady = try creation.waitForCreatedFolderObservation(
                titleCount: {
                    let count = try creation.captureTargetFolderTitleCount(title: folder,
                        navigationBars: navigationBars)
                    titleCount = count
                    return count
                })
            try require(folderReady, "New export folder ready")
        } else {
            try tap(fileRow(folder, app)); try ready(titleQuery(folder, app))
        }
    }

    private func openExportDestination(_ app: XCUIApplication) throws {
        // One existing provider allowance covers presentation, one exact action,
        // and positive destination readiness. Neither stage renews the deadline.
        let window = FilesNavigationReadiness(timeout: FilesNavigationReadiness.systemProviderAllowance)
        let actions = app.cells.matching(NSPredicate(format: "identifier == %@ AND label == %@", "actionGroupCell", "Save to Files"))
        try performBoundTap(window, matchingElements: {
            actions.allElementsBoundByAccessibilityElement
        }, enabled: { $0.isEnabled }, hittable: { $0.isHittable }, tap: { $0.tap() })
        let save = app.buttons.matching(identifier: "Save")
        _ = try window.waitForTargetFolder(titleCount: { save.count },
                                          enabled: { save.firstMatch.isEnabled },
                                          hittable: { save.firstMatch.isHittable })
    }

    private func observeExportedFilename(_ baseName: String, _ app: XCUIApplication) throws -> String {
        // Observe the single completed input; never retype or renew this window.
        let began = ProcessInfo.processInfo.systemUptime
        let echo = FilesNavigationReadiness(timeout: FilesNavigationReadiness.systemProviderAllowance)
        var lastReturned: String?
        var readsStarted = 0
        var readsReturned = 0
        var stage = "waiting"
        var matched = false
        defer {
            let record: [String: Any] = [
                "schema_version": 1, "phase": "export_filename_echo", "expected": baseName,
                "last_returned": lastReturned.map { String($0.prefix(256)) as Any } ?? NSNull(),
                "last_returned_truncated": (lastReturned?.count ?? 0) > 256,
                "reads_started": readsStarted, "reads_returned": readsReturned, "stage": stage,
                "allowance_seconds": FilesNavigationReadiness.systemProviderAllowance,
                "elapsed_seconds": ProcessInfo.processInfo.systemUptime - began,
                "result": matched ? "matched" : "failed"
            ]
            if let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]),
               data.count <= 4_096, let text = String(data: data, encoding: .utf8) {
                print("ROOM_RC_FILES_FILENAME_ECHO_V1 \(text)")
            }
        }
        let value = try echo.waitForFilenameEcho(expected: baseName, readValue: {
            stage = "resolving_picker"
            readsStarted += 1
            let pickers = try echo.perform {
                app.otherElements.matching(NSPredicate(format: "identifier == %@", FilesNavigationReadiness.pickerIdentifier))
                    .allElementsBoundByAccessibilityElement
            }
            guard pickers.count <= 1 else { throw FilesNavigationReadiness.Failure.invalidSelectionCount }
            guard let picker = pickers.first else { return nil }
            stage = "resolving_field"
            let fields = try echo.perform {
                picker.textFields.matching(identifier: "DOCPicker.filenameTextField")
                    .allElementsBoundByAccessibilityElement
            }
            guard fields.count <= 1 else { throw FilesNavigationReadiness.Failure.invalidSelectionCount }
            guard let field = fields.first else { return nil }
            stage = "reading_value"
            let observed = try echo.perform { field.value as? String }
            lastReturned = observed
            readsReturned += 1
            stage = "value_returned"
            return observed
        })
        matched = true
        stage = "completed"
        return value
    }

    private func export(_ action: String, baseName: String, create: Bool, _ app: XCUIApplication) throws {
        try select(action, app)
        try openExportDestination(app)
        try folder(create, app)
        let q = app.textFields.matching(identifier: "DOCPicker.filenameTextField")
        let name = try ready(q)
        let old = name.value as? String ?? ""
        try require(!old.isEmpty && old.count < 256, "File name present")
        try tap(q)
        name.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap()
        name.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: old.count) + baseName)
        try require(try observeExportedFilename(baseName, app) == baseName, "Exact exported base name")
        try capture("save-" + baseName, app)
        try tap(app.buttons.matching(identifier: "Save"))
        let returning = ExportReturnReadiness(homeName: names["home"]!)
        let close = app.navigationBars.matching(identifier: "UIActivityContentView").buttons
            .matching(NSPredicate(format: "identifier == %@ AND label == %@", "header.closeButton", "Close")).firstMatch
        let returned = try returning.waitForReturn(observe: {
            let root = try app.snapshot()
            var nodes: [ExportReturnReadiness.Element] = []
            var pending = root.children.reversed().map { ($0, Optional<Int>.none) }
            while let (node, parent) = pending.popLast() {
                try self.require(nodes.count < 10_000, "Snapshot node cap")
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
            case let .home(identifier):
                return app.buttons.matching(NSPredicate(format: "identifier == %@", identifier)).element.isHittable
            case .shareClose: return close.isHittable
            }
        }, close: { close.tap() })
        try require(returned, "Positive export return")
    }

    private func selectBackup(_ app: XCUIApplication) throws {
        try select("Restore a backup", app); try folder(false, app)
        let w = FilesNavigationReadiness(timeout: FilesNavigationReadiness.systemProviderAllowance)
        let pickers = app.otherElements.matching(NSPredicate(format: "identifier == %@", FilesNavigationReadiness.pickerIdentifier))
        let filename = "backup-" + runID + ".roominventory"
        var boundFile: XCUIElement?
        func file() throws -> XCUIElement {
            guard let boundFile else { throw FilesNavigationReadiness.Failure.invalidSelectionCount }
            return boundFile
        }
        try w.waitAndTapSelection(observe: {
            boundFile = nil
            // The provider's root identifier can retain its entry-location title.
            // Prove the current folder and exact file in the same picker snapshot.
            guard let observation = try w.captureSelection(folder: "RC-" + self.runID,
                target: .backup(filename: filename), pickers: pickers) else { return nil }
            let matches = try w.perform {
                pickers.element.otherElements.matching(identifier: observation.ownerIdentifier).element
                    .collectionViews.matching(identifier: "File View").element
                    .cells.matching(identifier: filename + ", roominventory")
                    .allElementsBoundByAccessibilityElement
            }
            guard matches.count <= 1 else { throw FilesNavigationReadiness.Failure.invalidSelectionCount }
            guard let element = matches.first else { return nil }
            boundFile = element
            return observation
        }, enabled: { _ in try file().isEnabled }, hittable: { _ in try file().isHittable },
           tap: { _ in try file().tap() })
        try ready(app.alerts.matching(identifier: "Replace the current inventory?"))
    }

    private func checkpoint(_ name: String, _ app: XCUIApplication) throws {
        try capture(name, app); steps.append(name); try journal(status: "running")
    }
    private func capture(_ name: String, _ app: XCUIApplication) throws {
        let png = XCUIScreen.main.screenshot().pngRepresentation
        let ax = Data(app.debugDescription.utf8)
        try require(png.count <= 8 * 1024 * 1024 && ax.count <= 1024 * 1024, "Evidence size cap")
        for (ext, data) in [("png", png), ("txt", ax)] {
            let path = directory.appendingPathComponent(name + "." + ext)
            try require(!FileManager.default.fileExists(atPath: path.path), "Duplicate capture")
            try data.write(to: path, options: .withoutOverwriting)
        }
        let attachment = XCTAttachment(data: png, uniformTypeIdentifier: "public.png")
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
        let text = XCTAttachment(string: String(decoding: ax, as: UTF8.self))
        text.name = name + "-accessibility"; text.lifetime = .keepAlways; add(text)
    }
    private func journal(status: String, failure: String? = nil) throws {
        var value: [String: Any] = ["schema_version": 1, "run_id": runID,
            "bundle_id": "com.alvit.roominventory", "status": status, "steps": steps, "names": names,
            "aut_launch_arguments": arguments, "aut_launch_environment": [String: String](),
            "restore_cancel_count": cancelled, "restore_confirm_count": restored]
        if let failure { value["failure"] = String(failure.prefix(1024)) }
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        try require(data.count <= 64 * 1024, "Journal size cap")
        if status == "failed" {
            // Preserve the bounded journal while the runner is alive. Its data
            // container cannot be queried after the owned Simulator shuts down.
            let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
            attachment.name = "failure-journey"; attachment.lifetime = .keepAlways; add(attachment)
        }
        try data.write(to: directory.appendingPathComponent("journey.json"), options: .atomic)
    }
}
