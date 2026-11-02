import XCTest
import InventoryCore
@testable import RoomInventory

final class LocalizationTests: XCTestCase {
    func testAppContainsBothLanguagesAndLocalizedCameraPermission() throws {
        XCTAssertTrue(Bundle.main.localizations.contains("en"))
        XCTAssertTrue(Bundle.main.localizations.contains("ru"))
        for language in ["en", "ru"] {
            let path = try XCTUnwrap(Bundle.main.path(forResource: language, ofType: "lproj"))
            let bundle = try XCTUnwrap(Bundle(path: path))
            let permission = bundle.localizedString(forKey: "NSCameraUsageDescription", value: nil, table: "InfoPlist")
            XCTAssertNotEqual(permission, "NSCameraUsageDescription")
            XCTAssertTrue(permission.contains(language == "ru" ? "Снимайте" : "Photograph"))
            for table in ["UI", "Export", "Services"] {
                XCTAssertNotNil(bundle.url(forResource: table, withExtension: "strings"), "Missing \(language)/\(table)")
            }
        }
    }

    func testRussianGrammarUsesLanguageWithUSNumberRegion() {
        let expected = ["0 комнат", "1 комната", "2 комнаты", "5 комнат", "21 комната"]
        for (count, value) in zip([0, 1, 2, 5, 21], expected) {
            XCTAssertEqual(InventoryLocalization.plural("count.rooms", count: count, table: "UI", language: "ru", locale: Locale(identifier: "en_US")), value)
        }
        let english = InventoryLocalization.plural("count.rooms", count: 2, table: "UI", language: "en", locale: Locale(identifier: "ru_RU"))
        XCTAssertEqual(english, "2 rooms")
        XCTAssertEqual(InventoryLocalization.text("Cancel", table: "UI", language: "fr"), "Cancel")
    }

    func testCivilDayDisplayIsRegionalAndDoesNotRollOverOrChangeStorage() {
        let raw = "2026-10-21"
        XCTAssertEqual(InventoryDisplay.purchaseDate(raw, locale: Locale(identifier: "en_US")), "Oct 21, 2026")
        XCTAssertTrue(InventoryDisplay.purchaseDate(raw, locale: Locale(identifier: "ru_RU")).contains("21 окт."))
        XCTAssertEqual(raw, "2026-10-21")
        for invalid in ["2026-02-30", "2025-02-29", "2026-13-01", "03/04/2026", "owner date", ""] {
            XCTAssertEqual(InventoryDisplay.purchaseDate(invalid), invalid)
        }
        XCTAssertNotNil(InventoryDisplay.civilDate("2024-02-29"))
    }

    func testCurrencyFormattingRequiresAnExplicitUnambiguousCurrency() {
        let us = Locale(identifier: "en_US")
        XCTAssertEqual(InventoryDisplay.purchasePrice("USD 1,299.00", locale: us), "$1,299.00")
        XCTAssertEqual(InventoryDisplay.purchasePrice("USD 1299,00", locale: us), "$1,299.00")
        XCTAssertTrue(InventoryDisplay.purchasePrice("JPY 1.23", locale: us).contains("1.23"))
        let russian = InventoryDisplay.purchasePrice("USD 1299.00", locale: Locale(identifier: "ru_RU"))
        XCTAssertTrue(russian.contains("299,00"))
        XCTAssertTrue(russian.contains("$"))
        for raw in ["$1299.00", "USD 1,299", "USD 12.345", "USD 12.34 extra", "My cost", "USD 1234567890123456.78", ""] {
            XCTAssertEqual(InventoryDisplay.purchasePrice(raw, locale: us), raw)
        }
    }
}
