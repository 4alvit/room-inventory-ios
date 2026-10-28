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
        let beforeShareCount = shareControllers.count
        if beforeShareCount != 0 { keepShareFailureEvidence(app: app) }
        XCTAssertEqual(beforeShareCount, 0, "A share controller must not preexist the CSV action")
        tap(app.buttons["Таблица предметов · CSV"])
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard shareControllers.count == 1 else { return false }
            let controller = shareControllers.element(boundBy: 0)
            return controller.exists && controller.isHittable
        }, object: nil)
        let sharePresented = XCTWaiter.wait(for: [ready], timeout: 15) == .completed
        if !sharePresented { keepShareFailureEvidence(app: app) }
        XCTAssertTrue(sharePresented, "Expected exactly one visible, hittable real CSV share controller")
        keepEvidence("ru-csv-share", app: app)
        app.terminate()
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
