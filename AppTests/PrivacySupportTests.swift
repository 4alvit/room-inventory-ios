import XCTest
import SwiftUI
import UIKit
import InventoryCore
@testable import RoomInventory

@MainActor
final class PrivacySupportTests: XCTestCase {
    private let sections = ["intro", "storage", "capture", "sharing", "deletion", "apple", "limits", "recovery", "support"]

    func testPrivacyTextIsPackagedInBothLanguagesWithoutFallback() throws {
        let english = try packagedStrings(language: "en")
        let russian = try packagedStrings(language: "ru")
        let keys = Set(["privacy.entry", "privacy.title", "privacy.links.title", "privacy.links.footer", "privacy.link.hint"]
            + sections.flatMap { ["privacy.\($0).title", "privacy.\($0).body"] }
            + ["policy", "support", "issues", "apple", "github"].map { "privacy.link.\($0)" })
        XCTAssertEqual(keys.count, 28)
        for (language, catalog) in [("en", english), ("ru", russian)] {
            XCTAssertEqual(Set(catalog.keys.filter { $0.hasPrefix("privacy.") }), keys, language)
            for key in keys {
                let text = try XCTUnwrap(catalog[key], "Missing packaged \(language)/\(key)")
                XCTAssertFalse(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, key)
                XCTAssertNotEqual(text, key)
                XCTAssertEqual(InventoryLocalization.text(key, table: "UI", language: language), text)
                if key.hasSuffix(".body") {
                    XCTAssertGreaterThan(text.count, 100, "A heading or placeholder is not the bundled explanation: \(key)")
                }
            }
        }
        for key in keys {
            XCTAssertNotEqual(english[key], russian[key], "Russian must not silently use English: \(key)")
        }
        XCTAssertEqual(english["Done"], "Done")
        XCTAssertEqual(russian["Done"], "Готово")
    }

    func testBundledExplanationsIncludeMaterialPrivacyAndRecoveryLimitations() throws {
        let facts: [(String, [String], [String])] = [
            ("intro", ["without internet access or Pro", "development preview"], ["без интернета и без Pro", "предварительная версия"]),
            ("storage", ["local sandbox", "no developer-operated server"], ["хранятся локально", "нет сервера разработчика"]),
            ("capture", ["on your device", "Suggestions start unselected", "metadata"], ["на устройстве", "Предложения изначально не выбраны", "метаданные"]),
            ("sharing", ["exports are not encrypted", "not scheduled deletion"], ["не зашифрованы", "не удаление по расписанию"]),
            ("deletion", ["Unlinked original files are retained", "no automatic cleanup", "80 MiB"], ["Оригиналы без ссылок остаются", "Автоматической очистки", "80 МиБ"]),
            ("apple", ["may use the network", "restores Pro access, not your inventory", "basic exports remain accessible without Pro"], ["могут использовать сеть", "доступ к Pro, а не вашу опись", "базовый экспорт доступны без Pro"]),
            ("limits", ["25 MiB", "80 MiB", "128 MiB", "500 pages", "also apply with Pro"], ["25 МиБ", "80 МиБ", "128 МиБ", "500 страниц", "действуют и с Pro"]),
            ("recovery", ["Restore replaces the active inventory", "PDF or report ZIP cannot restore", "do not uninstall"], ["Восстановление заменяет текущую опись", "PDF и ZIP с отчётом не восстанавливают", "Не начинайте восстановление с удаления"]),
            ("support", ["public and visible to everyone", "Never upload private inventories", "No confidential general-support contact"], ["публичны и видны всем", "Никогда не публикуйте личные описи", "не указан конфиденциальный канал"])
        ]
        for language in ["en", "ru"] {
            let catalog = try packagedStrings(language: language)
            for (section, english, russian) in facts {
                let key = "privacy.\(section).body"
                let text = try XCTUnwrap(catalog[key])
                for fact in (language == "ru" ? russian : english) {
                    XCTAssertTrue(text.contains(fact), "Missing \(language)/\(key) limitation: \(fact)")
                }
            }
            let footer = try XCTUnwrap(catalog["privacy.links.footer"])
            XCTAssertTrue(footer.contains(language == "ru" ? "только после нажатия" : "only when tapped"))
            XCTAssertTrue(footer.contains(language == "ru" ? "требуют интернета" : "require internet access"))
        }
    }

    func testPublicDestinationsAreHTTPSAndDocumentsUsePinnedLocalizedRevision() {
        let revision = "0d0f7eb75d8c9a9c42e3a8dc1b8d3f350b12776e"
        XCTAssertEqual(PrivacySupportLinks.revision, revision)
        for (language, suffix) in [("en", ""), ("en-GB", ""), ("ru", ".ru"), ("ru-RU", ".ru"), ("fr-FR", "")] {
            for document in PrivacySupportLinks.Document.allCases {
                let destination = PrivacySupportLinks.document(document, language: language)
                XCTAssertEqual(destination.absoluteString,
                               "https://github.com/4alvit/room-inventory-ios/blob/\(revision)/docs/\(document.rawValue)\(suffix).md",
                               language)
                assertPublicHTTPS(destination)
            }
        }
        for (destination, expected) in [
            (PrivacySupportLinks.issues, "https://github.com/4alvit/room-inventory-ios/issues"),
            (PrivacySupportLinks.apple, "https://www.apple.com/legal/privacy/data/en/app-store/"),
            (PrivacySupportLinks.github, "https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement")
        ] {
            XCTAssertEqual(destination.absoluteString, expected)
            assertPublicHTTPS(destination)
        }
    }

    func testLocalPagePresentsWithoutStoresAndDoesNotRequestAnExternalURL() async throws {
        let appeared = XCTestExpectation(description: "Standalone privacy page appeared")
        let recorder = PrivacyURLRecorder()
        // Deliberately supply neither InventoryStore nor ProStore. This checks
        // the page's dependencies, not the host app's network connectivity.
        let page = PrivacySupportView()
            .environment(\.openURL, OpenURLAction { url in
                recorder.opened.append(url)
                return .handled
            })
            .onAppear { appeared.fulfill() }
        let controller = UIHostingController(rootView: page)
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let previousKeyWindow = scene.windows.first(where: \.isKeyWindow)
        let window = UIWindow(windowScene: scene)
        window.frame = scene.coordinateSpace.bounds
        window.rootViewController = controller
        defer {
            window.isHidden = true
            window.rootViewController = nil
            previousKeyWindow?.makeKey()
        }
        window.makeKeyAndVisible()
        let result = await XCTWaiter.fulfillment(of: [appeared], timeout: 5)
        XCTAssertEqual(result, .completed)
        controller.view.layoutIfNeeded()
        XCTAssertTrue(controller.view.window === window)
        XCTAssertFalse(controller.view.bounds.isEmpty)
        XCTAssertTrue(recorder.opened.isEmpty, "Presenting local explanations must not invoke openURL")
    }

    private func packagedStrings(language: String) throws -> [String: String] {
        let directory = try XCTUnwrap(Bundle.main.url(forResource: language, withExtension: "lproj"))
        let data = try Data(contentsOf: directory.appendingPathComponent("UI.strings"))
        // Read this exact file, bypassing Bundle's language fallback.
        return try XCTUnwrap(PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: String])
    }

    private func assertPublicHTTPS(_ url: URL, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(url.scheme, "https", file: file, line: line)
        XCTAssertTrue(["github.com", "www.apple.com", "docs.github.com"].contains(url.host ?? ""), file: file, line: line)
        XCTAssertNil(url.user, file: file, line: line)
        XCTAssertNil(url.password, file: file, line: line)
        XCTAssertNil(url.query, file: file, line: line)
        XCTAssertNil(url.fragment, file: file, line: line)
    }
}

@MainActor
private final class PrivacyURLRecorder {
    var opened: [URL] = []
}
