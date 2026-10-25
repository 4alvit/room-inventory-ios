import XCTest
import UIKit

@MainActor
final class PrivacySupportUITests: XCTestCase {
    func testEnglishLocalPrivacyPageAndOptionalLinks() {
        verifyPage(russian: false)
    }

    func testRussianLocalPrivacyPageAndOptionalLinks() {
        verifyPage(russian: true)
    }

    func testRussianPrivacyPageAtMaximumDynamicType() {
        verifyPage(russian: true, maximumDynamicType: true)
    }

    private func verifyPage(russian: Bool, maximumDynamicType: Bool = false) {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "-AppleLanguages", russian ? "(ru-RU,en-US)" : "(en-GB,ru-RU)", "-AppleLocale", "en_US"]
        if maximumDynamicType {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        }
        app.launchEnvironment["UITEST_RUN_ID"] = UUID().uuidString
        app.launch()
        defer { app.terminate() }
        let evidencePrefix = "privacy-\(russian ? "ru" : "en")\(maximumDynamicType ? "-AXXXL" : "")"
        defer { keepEvidence(evidencePrefix + "-final", app: app) }

        let addHome = app.buttons["inventory.addFirstHome"]
        XCTAssertTrue(addHome.waitForExistence(timeout: 10), "Expected a fresh isolated inventory")
        XCTAssertEqual(addHome.label, russian ? "Добавить первый дом" : "Add your first home")
        let entry = app.buttons["inventory.privacySupport"]
        XCTAssertEqual(entry.label, russian ? "Конфиденциальность и поддержка" : "Privacy and support")
        tap(entry)
        let content = element("privacy.content", in: app)
        XCTAssertTrue(content.waitForExistence(timeout: 10))
        XCTAssertTrue(app.navigationBars[russian ? "Данные и помощь" : "Privacy & support"].exists)

        let sections = [
            ("intro", "without internet access or Pro", "без интернета и без Pro"),
            ("storage", "local sandbox", "хранятся локально"),
            ("capture", "Suggestions start unselected", "Предложения изначально не выбраны"),
            ("sharing", "exports are not encrypted", "не зашифрованы"),
            ("deletion", "Unlinked original files are retained", "Оригиналы без ссылок остаются"),
            ("apple", "restores Pro access, not your inventory", "доступ к Pro, а не вашу опись"),
            ("limits", "128 MiB", "128 МиБ"),
            ("recovery", "Restore replaces the active inventory", "Восстановление заменяет текущую опись"),
            ("support", "Never upload private inventories", "Никогда не публикуйте личные описи")
        ]
        for (id, english, translated) in sections {
            let body = element("privacy.\(id).body", in: app)
            reveal(body, in: content, app: app, requiresHitTarget: false)
            XCTAssertTrue(body.label.contains(russian ? translated : english), "Missing localized \(id) explanation")
            if id == "intro" || id == "support" {
                keepEvidence(evidencePrefix + "-" + id, app: app)
            }
        }

        // Inspect link labels and reachable hit targets without following them.
        // No purchases or connectivity changes are part of this test.
        let links = [
            ("policy", "Preview privacy document", "Документ о конфиденциальности: превью"),
            ("support", "Preview support document", "Документ поддержки: превью"),
            ("issues", "Open public GitHub issues", "Открыть публичные GitHub Issues"),
            ("apple", "Apple: App Store & Privacy (English)", "Apple: App Store и конфиденциальность (англ.)"),
            ("github", "GitHub privacy statement (English)", "Заявление GitHub о конфиденциальности (англ.)")
        ]
        for (id, english, translated) in links {
            let link = element("privacy.link.\(id)", in: app)
            reveal(link, in: content, app: app, requiresHitTarget: true)
            XCTAssertEqual(link.label, russian ? translated : english)
            XCTAssertTrue(link.isEnabled)
            keepEvidence(evidencePrefix + "-link-" + id, app: app)
        }
        let footerStart = russian ? "Ссылки открываются в браузере только после нажатия" : "These links open your browser only when tapped"
        let footer = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", footerStart)).firstMatch
        reveal(footer, in: content, app: app, requiresHitTarget: false)
        XCTAssertTrue(footer.label.contains(russian ? "Весь текст выше доступен офлайн" : "All information above remains available offline"))
        keepEvidence(evidencePrefix + "-links-footer", app: app)
        XCTAssertEqual(app.state, .runningForeground)
        let done = app.buttons["privacy.done"]
        XCTAssertEqual(done.label, russian ? "Готово" : "Done")
        tap(done)
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: content)
        XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 10), .completed)
        XCTAssertTrue(entry.isHittable, "The dashboard must remain reachable after dismissal")
        XCTAssertTrue(addHome.exists, "Reading privacy information must not create inventory records")
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func reveal(_ element: XCUIElement, in content: XCUIElement, app: XCUIApplication,
                        requiresHitTarget: Bool, file: StaticString = #filePath, line: UInt = #line) {
        // Lists create rows lazily. Long accessibility-sized paragraphs can be
        // taller than the screen, so visibility must not require their midpoint
        // to be hittable. Interactive links do require a real hit target.
        for _ in 0..<50 {
            let viewport = content.frame.intersection(app.frame).insetBy(dx: 8, dy: 30)
            if element.exists {
                let visible = element.frame.intersection(viewport)
                if !visible.isNull && visible.width > 0 && visible.height >= 24 && (!requiresHitTarget || element.isHittable) {
                    return
                }
            }
            XCTAssertFalse(viewport.isEmpty, "Privacy list has no visible scroll area", file: file, line: line)
            let origin = app.coordinate(withNormalizedOffset: .zero)
            let start = origin.withOffset(CGVector(dx: viewport.midX, dy: viewport.minY + viewport.height * 0.72))
            let end = origin.withOffset(CGVector(dx: viewport.midX, dy: viewport.minY + viewport.height * 0.28))
            start.press(forDuration: 0.05, thenDragTo: end)
        }
        keepEvidence("privacy-unreachable-" + element.identifier, app: app)
        XCTFail("Privacy content did not become reachable: \(element.identifier)", file: file, line: line)
    }

    private func tap(_ element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(element.waitForExistence(timeout: 10), file: file, line: line)
        XCTAssertTrue(element.isHittable, file: file, line: line)
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
