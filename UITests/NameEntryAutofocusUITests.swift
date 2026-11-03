import XCTest

@MainActor
final class NameEntryAutofocusUITests: XCTestCase {
    private let keyboardIntroductionAllowance = NameEntryKeyboardReadiness.ContinueAllowance()

    func testSuccessiveNameSheetsRetainTypedNamesAfterRelaunch() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launchEnvironment["UITEST_RUN_ID"] = UUID().uuidString
        addTeardownBlock { @MainActor [self] in
            if (testRun?.failureCount ?? 0) + (testRun?.unexpectedExceptionCount ?? 0) > 0 {
                keepEvidence("name-entry-failure", app: app)
            }
            app.terminate()
        }
        app.launch()

        let names = ["Autofocus Test Home", "Autofocus Test Room", "Autofocus Test Item"]
        let actions = ["inventory.addFirstHome", "Add a room", "Add an item"]
        for (action, name) in zip(actions, names) {
            tap(app.buttons[action])
            let observation = try AutofocusedNameEntry.type(name, in: app,
                allowance: keyboardIntroductionAllowance, evidence: { stage in
                    let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                    screenshot.name = "name-entry-keyboard-introduction-" + stage.rawValue
                    screenshot.lifetime = .keepAlways
                    self.add(screenshot)
                })
            XCTAssertTrue(observation.before.isEmpty || observation.before == observation.placeholder)
            XCTAssertEqual(observation.after, name)
            tap(app.buttons["entry.save"])
            XCTAssertTrue(try ElementDismissalReadiness().waitForDismissal {
                app.textFields.matching(identifier: "entry.name").count
            })
            openRecord(name, app: app)
        }

        // Keep the same namespace and load saved data through the real UI.
        app.terminate()
        app.launch()
        for (index, name) in names.enumerated() {
            openRecord(name, app: app)
            keepEvidence("name-entry-persisted-\(index + 1)", app: app)
        }
    }

    private func openRecord(_ name: String, app: XCUIApplication) {
        let rows = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", name))
        XCTAssertTrue(rows.firstMatch.waitForExistence(timeout: 10))
        XCTAssertEqual(rows.count, 1)
        tap(rows.element(boundBy: 0))
        // A prefix-matching list row alone is not proof of the exact saved name.
        XCTAssertTrue(app.navigationBars[name].waitForExistence(timeout: 10))
    }

    private func tap(_ element: XCUIElement) {
        XCTAssertTrue(element.waitForExistence(timeout: 10))
        let ready = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "hittable == true AND enabled == true"), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 10), .completed)
        element.tap()
    }

    private func keepEvidence(_ name: String, app: XCUIApplication) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let accessibility = XCTAttachment(string: app.debugDescription)
        accessibility.name = name + "-accessibility"
        accessibility.lifetime = .keepAlways
        add(accessibility)
    }
}
