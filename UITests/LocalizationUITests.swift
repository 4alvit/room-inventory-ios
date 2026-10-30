import XCTest

@MainActor
final class LocalizationUITests: XCTestCase {
    func testPreferredLanguagesAtLaunch() throws {
        continueAfterFailure = false
        for (preferences, expected) in [("(ru-RU,en-US)", "Добавить первый дом"), ("(en-GB,ru-RU)", "Add your first home"), ("(fr-FR,ru-RU,en-US)", "Добавить первый дом"), ("(fr-FR)", "Add your first home")] {
            let app = application(languages: preferences)
            app.launch()
            let add = app.buttons["inventory.addFirstHome"]
            XCTAssertTrue(add.waitForExistence(timeout: 10))
            XCTAssertEqual(add.label, expected, preferences)
            keepEvidence(preferences, app: app)
            app.terminate()
        }
    }

    func testRussianCreationEditingAndCSVExportWithUSRegion() throws {
        continueAfterFailure = false
        let app = application(languages: "(ru-RU,en-US)")
        app.launch()
        tap(app.buttons["inventory.addFirstHome"])
        enterName("RU Test Home", app: app)
        openRecord("RU Test Home", app: app)
        tap(app.buttons["Добавить комнату"])
        enterName("RU Test Room", app: app)
        openRecord("RU Test Room", app: app)
        // Russian has the same label for the toolbar and the list action.
        tap(app.collectionViews.buttons["Добавить предмет"])
        enterName("RU Test Item", app: app)
        openRecord("RU Test Item", app: app)
        keepEvidence("ru-item-empty", app: app)
        tap(app.buttons["Редактировать сведения"])
        let model = app.textFields["Модель"]
        tap(model)
        model.typeText("RU-MODEL-42")
        keepEvidence("ru-item-editor", app: app)
        tap(app.navigationBars["Сведения"].buttons["Сохранить"])
        XCTAssertTrue(app.staticTexts["RU-MODEL-42"].waitForExistence(timeout: 10))
        app.terminate()
        app.launch()
        openRecord("RU Test Home", app: app)
        openRecord("RU Test Room", app: app)
        openRecord("RU Test Item", app: app)
        XCTAssertTrue(app.staticTexts["RU-MODEL-42"].waitForExistence(timeout: 10))
        for _ in 0..<3 { tap(app.navigationBars.buttons.element(boundBy: 0)) }
        tap(app.buttons["inventory.exportMenu"])
        XCTAssertTrue(app.buttons["Таблица предметов · CSV"].waitForExistence(timeout: 5))
        keepEvidence("ru-export-menu", app: app)
        let shareControllers = app.descendants(matching: .any).matching(identifier: "inventory.exportShare")
        let headers = app.navigationBars.matching(identifier: "UIActivityContentView")
        let closeButtons = app.buttons.matching(identifier: "header.closeButton")
        let beforeShareCount = shareControllers.count
        if beforeShareCount != 0 || headers.count != 0 || closeButtons.count != 0 {
            keepShareFailureEvidence(app: app)
        }
        XCTAssertEqual(beforeShareCount, 0, "A share controller must not preexist the CSV action")
        XCTAssertEqual(headers.count, 0, "A system share header must not preexist the CSV action")
        XCTAssertEqual(closeButtons.count, 0, "A system share Close must not preexist the CSV action")
        tap(app.buttons["Таблица предметов · CSV"])
        // One wall-clock budget starts after the CSV action returns. Snapshot
        // and live hit-testing time still count; diagnostics never renew it.
        let phase = CSVSharePhaseTiming(start: ProcessInfo.processInfo.systemUptime)
        var timing: [String: Any] = ["start_uptime": phase.start, "deadline_uptime": phase.deadline]
        var readyPolls = 0
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            readyPolls += 1
            guard phase.permitsAction(at: ProcessInfo.processInfo.systemUptime),
                  self.csvShareIsReady(app: app, headers: headers, closeButtons: closeButtons) else { return false }
            return phase.permitsAction(at: ProcessInfo.processInfo.systemUptime)
        }, object: nil)
        let readyResult = XCTWaiter.wait(for: [ready],
            timeout: max(0, phase.remaining(at: ProcessInfo.processInfo.systemUptime)))
        let readyFinished = ProcessInfo.processInfo.systemUptime
        timing["ready_finished_uptime"] = readyFinished
        timing["ready_waiter_result"] = String(describing: readyResult)
        timing["ready_poll_count"] = readyPolls
        let sharePresented = readyResult == .completed && phase.permitsAction(at: readyFinished)
        if !sharePresented {
            emitSharePhaseTiming(timing, result: "readiness_failed")
            keepShareFailureEvidence(app: app)
        }
        XCTAssertTrue(sharePresented, "Expected the exact CSV in one visible system share header with one interactive Close")
        guard sharePresented else { return }

        // No screenshot/debugDescription between readiness and the real Close.
        let beforeClose = ProcessInfo.processInfo.systemUptime
        timing["before_close_uptime"] = beforeClose
        guard phase.permitsAction(at: beforeClose) else {
            emitSharePhaseTiming(timing, result: "expired_before_close")
            keepShareFailureEvidence(app: app)
            XCTFail("CSV share phase expired before Close")
            return
        }
        closeButtons.element(boundBy: 0).tap()
        let afterClose = ProcessInfo.processInfo.systemUptime
        timing["after_close_uptime"] = afterClose
        var returnPolls = 0
        let returned = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            returnPolls += 1
            guard phase.permitsAction(at: ProcessInfo.processInfo.systemUptime),
                  self.inventoryHasReturned(app: app, headers: headers, closeButtons: closeButtons) else { return false }
            return phase.remaining(at: ProcessInfo.processInfo.systemUptime) >= 0
        }, object: nil)
        let returnStarted = ProcessInfo.processInfo.systemUptime
        let remaining = phase.remaining(at: returnStarted)
        let returnResult: XCTWaiter.Result? = remaining > 0
            ? XCTWaiter.wait(for: [returned], timeout: remaining) : nil
        let returnFinished = ProcessInfo.processInfo.systemUptime
        let dismissed = phase.acceptsReturn(waitStartedAt: returnStarted,
            waiterCompleted: returnResult == .completed, finishedAt: returnFinished)
        timing["return_started_uptime"] = returnStarted
        timing["return_remaining_seconds"] = remaining
        timing["return_waiter_result"] = returnResult.map { String(describing: $0) } ?? "not_started"
        timing["return_finished_uptime"] = returnFinished
        timing["return_poll_count"] = returnPolls
        emitSharePhaseTiming(timing, result: dismissed ? "returned_in_time" : "return_failed")
        if !dismissed { keepShareFailureEvidence(app: app) }
        XCTAssertTrue(dismissed, "Real CSV Close must dismiss the sheet and return to the saved inventory within the same share phase")
        guard dismissed else { return }
        // This is evidence of the returned inventory, not of an open share sheet.
        keepEvidence("ru-csv-returned", app: app)
        app.terminate()
    }

    // Keep XCTest's original matching rules and firstMatch ordering. Fresh
    // snapshots turn repeated attributes of those exact matches into local reads.
    private func csvShareIsReady(app: XCUIApplication, headers: XCUIElementQuery,
                                 closeButtons: XCUIElementQuery) -> Bool {
        guard headers.count == 1, closeButtons.count == 1 else { return false }
        let headerElement = headers.element(boundBy: 0)
        let closeElement = closeButtons.element(boundBy: 0)
        let captionElement = headerElement.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@", "Inventory-localized.csv")).firstMatch
        guard let header = try? headerElement.snapshot(),
              let close = try? closeElement.snapshot(),
              let caption = try? captionElement.snapshot() else { return false }
        let appFrame = app.frame
        return close.isEnabled && !header.frame.isEmpty && appFrame.contains(header.frame)
            && header.frame.contains(close.frame) && !caption.frame.isEmpty
            && header.frame.contains(caption.frame) && closeElement.isHittable
    }

    private func inventoryHasReturned(app: XCUIApplication, headers: XCUIElementQuery,
                                      closeButtons: XCUIElementQuery) -> Bool {
        guard headers.count == 0, closeButtons.count == 0 else { return false }
        let export = app.buttons["inventory.exportMenu"]
        let home = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "RU Test Home"))
        guard let exportSnapshot = try? export.snapshot(), exportSnapshot.isEnabled,
              home.count == 1 else { return false }
        return export.isHittable && home.element(boundBy: 0).isHittable
    }

    private func emitSharePhaseTiming(_ timing: [String: Any], result: String) {
        var record = timing
        record["category"] = "share-phase-timing"
        record["result"] = result
        guard let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]),
              data.count <= 4_096, let text = String(data: data, encoding: .utf8) else { return }
        print("ROOM_LOCALIZATION_DIAGNOSTIC " + text)
    }

    private func application(languages: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "-AppleLanguages", languages, "-AppleLocale", "en_US"]
        app.launchEnvironment["UITEST_RUN_ID"] = UUID().uuidString
        return app
    }

    private func tap(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        var observed = ["exists": false, "enabled": false, "hittable": false]
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let exists = element.exists
            let enabled = exists && element.isEnabled
            let hittable = exists && element.isHittable
            observed = ["exists": exists, "enabled": enabled, "hittable": hittable]
            return exists && enabled && hittable
        }, object: nil)
        let admitted = XCTWaiter.wait(for: [ready], timeout: 10) == .completed
        if !admitted { keepActionFailureEvidence(observed: observed, file: file, line: line) }
        XCTAssertTrue(admitted, "Expected an existing, enabled, hittable action within 10 seconds", file: file, line: line)
        guard admitted else { return }
        XCTAssertTrue(element.exists, file: file, line: line)
        XCTAssertTrue(element.isEnabled, file: file, line: line)
        XCTAssertTrue(element.isHittable, file: file, line: line)
        element.tap()
    }

    private func keepActionFailureEvidence(observed: [String: Bool], file: StaticString, line: UInt) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "ru-action-readiness-failure"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let hierarchy = XCUIApplication().debugDescription
        let count = hierarchy.unicodeScalars.count
        let headCount = min(count, 2_048)
        let tailCount = min(max(0, count - headCount), 2_048)
        let context: [String: Any] = ["phase": "action-readiness-failed",
            "caller_file": String(describing: file).split(separator: "/").last.map(String.init) ?? "unknown",
            "caller_line": line, "last_observed": observed,
            "ax_original_scalars": count, "ax_omitted_scalars": count - headCount - tailCount,
            "ax_head": String(String.UnicodeScalarView(hierarchy.unicodeScalars.prefix(headCount))),
            "ax_tail": String(String.UnicodeScalarView(hierarchy.unicodeScalars.suffix(tailCount)))]
        guard let data = try? JSONSerialization.data(withJSONObject: context, options: [.sortedKeys]),
              data.count <= 64 * 1_024, let text = String(data: data, encoding: .utf8) else {
            print("ROOM_LOCALIZATION_DIAGNOSTIC {\"phase\":\"action-readiness-failed\",\"context_omitted\":true}")
            return
        }
        let attachment = XCTAttachment(string: text)
        attachment.name = "ru-action-readiness-failure-accessibility"
        attachment.lifetime = .keepAlways
        add(attachment)
        print("ROOM_LOCALIZATION_DIAGNOSTIC {\"phase\":\"action-readiness-failed\",\"caller_line\":\(line),\"exists\":\(observed["exists"] == true),\"enabled\":\(observed["enabled"] == true),\"hittable\":\(observed["hittable"] == true),\"ax_attachment_bytes\":\(data.count)}")
    }

    private func enterName(_ value: String, app: XCUIApplication, file: StaticString = #filePath, line: UInt = #line) {
        let field = app.textFields["entry.name"]
        tap(field, file: file, line: line)
        field.typeText(value)
        tap(app.buttons["entry.save"])
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: field)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 10), .completed)
    }

    private func openRecord(_ value: String, app: XCUIApplication) {
        tap(app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", value)).firstMatch)
        XCTAssertTrue(app.navigationBars[value].waitForExistence(timeout: 10))
    }

    private func keepShareFailureEvidence(app: XCUIApplication) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "ru-csv-share-failure"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let hierarchy = app.debugDescription
        let tree = XCTAttachment(string: hierarchy)
        tree.name = "ru-csv-share-failure-accessibility"
        tree.lifetime = .keepAlways
        add(tree)
        // Export failures surface through the dashboard's real error alert.
        // Preserve that observed UI separately from bounded head/tail AX context.
        let alerts = app.alerts.debugDescription
        let prefix = "ROOM_LOCALIZATION_DIAGNOSTIC "
        var printedBytes = 0
        // Fixed-shape actual query state makes missing/duplicate/noninteractive
        // surfaces distinguishable without parsing debugDescription as a test.
        let headers = app.navigationBars.matching(identifier: "UIActivityContentView")
        let closes = app.buttons.matching(identifier: "header.closeButton")
        var state: [String: Any] = ["phase": "csv-share-assertion-failed", "category": "share-surface-state",
            "app_owned_container_count": app.descendants(matching: .any).matching(identifier: "inventory.exportShare").count,
            "system_header_count": headers.count, "system_close_count": closes.count]
        if headers.count == 1 {
            let header = headers.element(boundBy: 0)
            state["header_frame"] = String(describing: header.frame)
            state["exact_csv_caption_count"] = header.descendants(matching: .any)
                .matching(NSPredicate(format: "label == %@", "Inventory-localized.csv")).count
        }
        if closes.count == 1 {
            let close = closes.element(boundBy: 0)
            state["close_enabled"] = close.isEnabled
            state["close_hittable"] = close.isHittable
            state["close_frame"] = String(describing: close.frame)
        }
        if let data = try? JSONSerialization.data(withJSONObject: state, options: [.sortedKeys]),
           data.count <= 4 * 1_024, let json = String(data: data, encoding: .utf8) {
            print(prefix + json)
            printedBytes += prefix.utf8.count + data.count + 1
        }
        func emit(_ category: String, _ scalars: [Unicode.Scalar], originalCount: Int, offset: Int) {
            for start in stride(from: 0, to: scalars.count, by: 128) {
                let end = min(start + 128, scalars.count)
                let text = String(String.UnicodeScalarView(scalars[start..<end]))
                let record: [String: Any] = ["phase": "csv-share-assertion-failed", "category": category,
                    "scalar_offset": offset + start, "original_scalars": originalCount,
                    "selected_scalars": scalars.count, "omitted_scalars": originalCount - scalars.count,
                    "text": text]
                guard let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]),
                      data.count <= 2_800, printedBytes + prefix.utf8.count + data.count + 1 <= 63 * 1_024,
                      let json = String(data: data, encoding: .utf8) else {
                    print(prefix + "{\"phase\":\"csv-share-assertion-failed\",\"diagnostic_omitted\":true}")
                    return
                }
                print(prefix + json)
                printedBytes += prefix.utf8.count + data.count + 1
            }
        }
        let alertCount = alerts.unicodeScalars.count
        emit("actual-alerts", Array(alerts.unicodeScalars.prefix(1_024)), originalCount: alertCount, offset: 0)
        let count = hierarchy.unicodeScalars.count
        let headCount = min(count, 2_048)
        let tailCount = min(max(0, count - headCount), 2_048)
        emit("app-ax-head", Array(hierarchy.unicodeScalars.prefix(headCount)), originalCount: count, offset: 0)
        emit("app-ax-tail", Array(hierarchy.unicodeScalars.suffix(tailCount)), originalCount: count,
             offset: count - tailCount)
    }

    private func keepEvidence(_ name: String, app: XCUIApplication) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let tree = XCTAttachment(string: app.debugDescription)
        tree.name = name + "-accessibility"
        tree.lifetime = .keepAlways
        add(tree)
    }
}
