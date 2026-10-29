import XCTest
import UIKit

@MainActor
final class RoomInventoryUITests: XCTestCase {
    private let homeName = "Smoke Test Home"
    private let roomName = "Smoke Test Office"
    private let itemName = "Synthetic Monitor"
    private let modelName = "TEST-MODEL-42"

    func testSearchFindsItemByModelWithoutOpeningItsHomeOrRoom() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments += ["--ui-testing", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launchEnvironment["UITEST_RUN_ID"] = UUID().uuidString
        app.launch()
        tap(app.buttons["inventory.addFirstHome"])
        enterName(homeName, in: app)
        openRecord(homeName, in: app)
        tap(app.buttons["Add a room"])
        enterName(roomName, in: app)
        openRecord(roomName, in: app)
        tap(app.buttons["Add an item"])
        enterName(itemName, in: app)
        openRecord(itemName, in: app)
        tap(app.buttons["item.editDetails"])
        let model = app.textFields["itemEditor.model"]
        tap(model)
        model.typeText(modelName)
        tap(app.buttons["itemEditor.save"])
        XCTAssertTrue(app.staticTexts[modelName].waitForExistence(timeout: 10))
        backToDashboard(app)

        let search = app.searchFields.firstMatch
        tap(search)
        search.typeText("test-model-42")
        let result = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "inventory.searchResult.")).firstMatch
        XCTAssertTrue(result.waitForExistence(timeout: 5))
        XCTAssertTrue(result.label.contains(homeName))
        XCTAssertTrue(result.label.contains(roomName))
        tap(result)
        XCTAssertTrue(app.navigationBars[itemName].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts[modelName].exists)
    }

    func testNameEntryRequiresExplicitDiscardForAnUnsavedName() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments += ["--ui-testing", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launchEnvironment["UITEST_RUN_ID"] = UUID().uuidString
        app.launch()
        tap(app.buttons["inventory.addFirstHome"])
        let field = app.textFields["entry.name"]
        tap(field)
        field.typeText("Unsaved synthetic home")
        tap(app.buttons["entry.cancel"])
        tap(app.buttons["Keep editing"])
        XCTAssertEqual(field.value as? String, "Unsaved synthetic home")
        tap(app.buttons["entry.cancel"])
        tap(app.buttons["Discard changes"])
        XCTAssertTrue(app.buttons["inventory.addFirstHome"].waitForExistence(timeout: 5))
        XCTAssertFalse(record("Unsaved synthetic home", in: app).exists)

        tap(app.buttons["inventory.addFirstHome"])
        enterName(homeName, in: app)
        record(homeName, in: app).press(forDuration: 1.2)
        tap(app.buttons["Rename home"])
        tap(field)
        field.typeText(" changed")
        tap(app.buttons["entry.cancel"])
        tap(app.buttons["Discard changes"])
        XCTAssertTrue(record(homeName, in: app).waitForExistence(timeout: 5))
        XCTAssertFalse(record(homeName + " changed", in: app).exists)
    }

    func testIPadLandscapeAtMaximumDynamicType() throws {
        try XCTSkipUnless(UIDevice.current.userInterfaceIdiom == .pad, "This flow verifies the supported iPad layout.")
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = XCUIApplication()
        app.launchArguments += ["--ui-testing", "-AppleLanguages", "(en)", "-AppleLocale", "en_US",
                                "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        app.launchEnvironment["UITEST_RUN_ID"] = UUID().uuidString
        app.launch()
        XCTAssertGreaterThan(app.frame.width, app.frame.height)
        keepLayoutEvidence("iPad-01-Empty-inventory", app: app)

        reveal(app.buttons["inventory.addFirstHome"], in: app)
        tap(app.buttons["inventory.addFirstHome"])
        enterName(homeName, in: app)
        renameRecord(homeName, action: "Rename home", suffix: " Updated", in: app)
        openRecord(homeName + " Updated", in: app)
        reveal(app.buttons["Add a room"], in: app)
        tap(app.buttons["Add a room"])
        enterName(roomName, in: app)
        renameRecord(roomName, action: "Rename room", suffix: " Updated", in: app)
        openRecord(roomName + " Updated", in: app)
        reveal(app.buttons["Add an item"], in: app)
        tap(app.buttons["Add an item"])
        enterName(itemName, in: app)
        openRecord(itemName, in: app)

        reveal(app.buttons["Edit details"], in: app)
        tap(app.buttons["Edit details"])
        let model = app.textFields["Model"]
        reveal(model, in: app)
        tap(model)
        model.typeText(modelName)
        keepLayoutEvidence("iPad-02-Edit-with-keyboard", app: app)
        let date = app.textFields["Purchase date, YYYY-MM-DD"]
        reveal(date, in: app)
        tap(date)
        keepLayoutEvidence("iPad-03a-Empty-purchase-fields", app: app)
        date.typeText("2026-10-20")
        keepLayoutEvidence("iPad-03-Purchase-with-keyboard", app: app)
        tap(app.navigationBars["Edit item"].buttons["Save"])
        reveal(app.staticTexts[modelName], in: app)
        XCTAssertTrue(app.staticTexts[modelName].isHittable)
        keepLayoutEvidence("iPad-04-Saved-item", app: app)

        backToDashboard(app)
        tap(app.buttons["inventory.exportMenu"])
        for title in ["Inventory package · ZIP", "Report · PDF"] {
            XCTAssertTrue(app.buttons[title].waitForExistence(timeout: 5), "Missing export action: \(title)")
            XCTAssertTrue(app.buttons[title].isHittable, "Export action is unreachable: \(title)")
        }
        keepLayoutEvidence("iPad-05a-Export-menu-top", app: app)
        scrollExportMenu(from: app.buttons["Report · PDF"])
        XCTAssertTrue(app.buttons["Item table · CSV"].isHittable)
        keepLayoutEvidence("iPad-05b-Export-menu-middle", app: app)
        scrollExportMenu(from: app.buttons["Item table · CSV"])
        for title in ["Restorable backup + originals", "Restore a backup"] {
            XCTAssertTrue(app.buttons[title].waitForExistence(timeout: 5))
            XCTAssertTrue(app.buttons[title].isHittable, "Export action is unreachable: \(title)")
        }
        keepLayoutEvidence("iPad-05c-Export-menu-bottom", app: app)
        scrollExportMenu(from: app.buttons["Restorable backup + originals"], towardStart: true)
        tap(app.buttons["Item table · CSV"])
        XCTAssertTrue(app.buttons["Close"].waitForExistence(timeout: 15), "The generated CSV did not open the system share sheet")
        keepLayoutEvidence("iPad-06-CSV-share-sheet", app: app)
        tap(app.buttons["Close"])

        app.terminate()
        app.launch()
        openRecord(homeName + " Updated", in: app)
        openRecord(roomName + " Updated", in: app)
        openRecord(itemName, in: app)
        reveal(app.staticTexts[modelName], in: app)
        XCTAssertTrue(app.staticTexts[modelName].isHittable, "Edited values did not persist")
        reveal(app.staticTexts["Oct 20, 2026"], in: app)
        XCTAssertTrue(app.staticTexts["Oct 20, 2026"].isHittable, "Purchase date did not persist")
    }

    private func renameRecord(_ name: String, action: String, suffix: String, in app: XCUIApplication) {
        let row = record(name, in: app)
        reveal(row, in: app)
        row.press(forDuration: 1.2)
        tap(app.buttons[action])
        let field = app.textFields["entry.name"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        // The sheet autofocuses its populated field with the insertion point at the end.
        field.typeText(suffix)
        keepLayoutEvidence("iPad-Edit-" + action, app: app)
        tap(app.buttons["entry.save"])
        XCTAssertTrue(record(name + suffix, in: app).waitForExistence(timeout: 10))
    }

    private func reveal(_ element: XCUIElement, in app: XCUIApplication, file: StaticString = #filePath, line: UInt = #line) {
        // A presented Form is later in the hierarchy than the List behind its sheet.
        let lists = app.collectionViews.allElementsBoundByIndex
        let content = lists.last ?? app.scrollViews.allElementsBoundByIndex.last ?? app
        for scrollDown in [false, true, false] {
            for _ in 0..<6 {
                if element.exists && element.isHittable { return }
                // Form's accessibility frame can extend behind the software keyboard.
                // Keep the gesture inside the visible form, above its accessory bar.
                let frame = content.frame
                let keyboardTop = app.keyboards.firstMatch.exists ? app.keyboards.firstMatch.frame.minY - 60 : frame.maxY
                let top = frame.minY + 90
                let bottom = min(frame.maxY, keyboardTop) - 15
                let high = app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: frame.midX, dy: top + (bottom - top) * 0.2))
                let low = app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: frame.midX, dy: top + (bottom - top) * 0.8))
                if scrollDown { high.press(forDuration: 0.05, thenDragTo: low) }
                else { low.press(forDuration: 0.05, thenDragTo: high) }
            }
        }
        XCTAssertTrue(element.exists && element.isHittable, "Control cannot be reached by scrolling: \(element)", file: file, line: line)
    }

    private func keepLayoutEvidence(_ name: String, app: XCUIApplication) {
        // Capture the full screen: app.screenshot can crop a landscape window
        // incorrectly on some Simulator/XCTest combinations.
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let attachment = XCTAttachment(string: app.debugDescription)
        attachment.name = name + "-accessibility"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func scrollExportMenu(from anchor: XCUIElement, towardStart: Bool = false) {
        // Menu collection frames can include clipped content or resolve to the
        // underlying List. Use the visible row established by the preceding step;
        // asking XCTest for an offscreen menu row's hittability can itself fail.
        XCTAssertTrue(anchor.isHittable)
        let start = anchor.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        let end = start.withOffset(CGVector(dx: 0, dy: towardStart ? 120 : -120))
        start.press(forDuration: 0.05, thenDragTo: end)
    }

    func testInventoryCreationEditingExportAndRelaunch() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments += ["--ui-testing", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launchEnvironment["UITEST_RUN_ID"] = UUID().uuidString
        app.launch()

        // A unique storage namespace per test guarantees a fresh inventory
        // without clearing real app data or relying on simulator resets.
        tap(app.buttons["inventory.addFirstHome"])
        enterName(homeName, in: app)
        openRecord(homeName, in: app)
        tap(app.buttons["Add a room"])
        enterName(roomName, in: app)
        openRecord(roomName, in: app)
        tap(app.buttons["Add an item"])
        enterName(itemName, in: app)
        openRecord(itemName, in: app)

        tap(app.buttons["Edit details"])
        let model = app.textFields["Model"]
        tap(model)
        model.typeText(modelName)
        tap(app.navigationBars["Edit item"].buttons["Save"])
        XCTAssertTrue(app.staticTexts[modelName].waitForExistence(timeout: 10))
        keepScreenshot("01-Item-details", app: app)

        backToDashboard(app)
        tap(app.buttons["inventory.exportMenu"])
        for title in ["Inventory package · ZIP", "Report · PDF", "Item table · CSV", "Restorable backup + originals", "Restore a backup"] {
            XCTAssertTrue(app.buttons[title].waitForExistence(timeout: 5), "Missing export action: \(title)")
        }
        keepScreenshot("02-Export-actions", app: app)

        // Relaunch with the same run ID, so this is a real disk-persistence check.
        // Terminating also dismisses the export menu without brittle coordinates.
        app.terminate()
        app.launch()
        openRecord(homeName, in: app)
        openRecord(roomName, in: app)
        openRecord(itemName, in: app)
        XCTAssertTrue(app.staticTexts[modelName].waitForExistence(timeout: 10), "Saved model did not survive relaunch")
        backToDashboard(app)

        tap(app.buttons["Explore Pro"])
        XCTAssertTrue(app.staticTexts["Room Inventory Pro"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["One purchase, no subscription"].exists)
        XCTAssertTrue(app.buttons["Restore purchases"].exists)
        XCTAssertTrue(app.buttons["Refresh price"].exists)
        keepScreenshot("03-Pro-offer", app: app)
        tap(app.buttons["Done"])
        openRecord(homeName, in: app)
        openRecord(roomName, in: app)
        XCTAssertTrue(record(itemName, in: app).waitForExistence(timeout: 5), "Viewing Pro must not remove the existing inventory")
    }

    private func enterName(_ name: String, in app: XCUIApplication) {
        let field = app.textFields["entry.name"]
        tap(field)
        field.typeText(name)
        tap(app.buttons["entry.save"])
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: field)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 10), .completed, "Name entry did not finish saving")
    }

    private func record(_ name: String, in app: XCUIApplication) -> XCUIElement {
        // SwiftUI combines a row's title and its counts into a button label.
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", name)).firstMatch
    }

    private func openRecord(_ name: String, in app: XCUIApplication) {
        tap(record(name, in: app))
        XCTAssertTrue(app.navigationBars[name].waitForExistence(timeout: 10), "Could not open \(name)")
    }

    private func backToDashboard(_ app: XCUIApplication) {
        for _ in 0..<4 {
            if app.navigationBars["Room Inventory"].exists { return }
            tap(app.navigationBars.buttons.element(boundBy: 0))
        }
        XCTAssertTrue(app.navigationBars["Room Inventory"].waitForExistence(timeout: 5))
    }

    private func tap(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(element.waitForExistence(timeout: 10), "Expected control is missing: \(element)", file: file, line: line)
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "hittable == true AND enabled == true"), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 10), .completed, "Control did not become interactive", file: file, line: line)
        element.tap()
    }

    private func keepScreenshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
