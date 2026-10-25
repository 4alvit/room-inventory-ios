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
        tap(app.buttons["Таблица предметов · CSV"])
        XCTAssertTrue(app.otherElements["ActivityListView"].waitForExistence(timeout: 15) || app.buttons["Close"].exists || app.buttons["Закрыть"].exists)
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
        XCTAssertTrue(element.waitForExistence(timeout: 10), file: file, line: line)
        XCTAssertTrue(element.isHittable, file: file, line: line)
        element.tap()
    }

    private func enterName(_ value: String, app: XCUIApplication) {
        let field = app.textFields["entry.name"]
        tap(field)
        field.typeText(value)
        tap(app.buttons["entry.save"])
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: field)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 10), .completed)
    }

    private func openRecord(_ value: String, app: XCUIApplication) {
        tap(app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", value)).firstMatch)
        XCTAssertTrue(app.navigationBars[value].waitForExistence(timeout: 10))
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
