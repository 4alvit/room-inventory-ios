import Foundation
import XCTest
@testable import InventoryCore

final class InventoryLocalizationTests: XCTestCase {
    private func fixture() throws -> (Bundle, URL) {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".bundle")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let info: [String: Any] = ["CFBundleIdentifier": UUID().uuidString, "CFBundleDevelopmentRegion": "en", "CFBundleLocalizations": ["en", "ru"]]
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0).write(to: root.appendingPathComponent("Info.plist"))
        let strings = [
            "en": "\"greeting\" = \"Hello\";\n\"englishOnly\" = \"English fallback\";\n\"item.one\" = \"%@ item\";\n\"item.other\" = \"%@ items\";\n\"fallbackItem.other\" = \"%@ fallback items\";",
            "ru": "\"greeting\" = \"Здравствуйте\";\n\"item.one\" = \"%@ вещь\";\n\"item.few\" = \"%@ вещи\";\n\"item.many\" = \"%@ вещей\";\n\"item.other\" = \"%@ вещи\";"
        ]
        for (language, content) in strings {
            let path = root.appendingPathComponent(language + ".lproj")
            try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true)
            try Data(content.utf8).write(to: path.appendingPathComponent("Test.strings"))
        }
        return (try XCTUnwrap(Bundle(path: root.path)), root)
    }

    func testOrderedSystemPreferencesAndEnglishFallback() {
        for (preferences, expected) in [
            (["ru-RU", "en-US"], "ru"), (["en-GB", "ru-RU"], "en"),
            (["fr-FR", "ru-RU", "en-US"], "ru"), (["fr-FR"], "en"), ([], "en")
        ] {
            XCTAssertEqual(InventoryLocalization.preferredLanguage(preferences: preferences, bundle: .module), expected, preferences.joined(separator: ","))
        }
    }

    func testExplicitRegionalLanguageAndMissingTranslationFallback() throws {
        let (bundle, root) = try fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertEqual(InventoryLocalization.text("greeting", table: "Test", bundle: bundle, language: "ru-RU"), "Здравствуйте")
        XCTAssertEqual(InventoryLocalization.text("greeting", table: "Test", bundle: bundle, language: "fr-FR"), "Hello")
        XCTAssertEqual(InventoryLocalization.text("englishOnly", table: "Test", bundle: bundle, language: "ru"), "English fallback")
        XCTAssertEqual(InventoryLocalization.text("unknown", table: "Test", bundle: bundle, language: "ru"), "unknown")
        XCTAssertEqual(InventoryLocalization.plural("fallbackItem", count: 5, table: "Test", bundle: bundle, language: "ru"), "5 fallback items")
    }

    func testRussianPluralGrammarIsIndependentFromUSNumberLocale() throws {
        let (bundle, root) = try fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        let expectations = [(0, "0 вещей"), (1, "1 вещь"), (2, "2 вещи"), (5, "5 вещей"), (21, "21 вещь"), (11, "11 вещей"), (12, "12 вещей"), (22, "22 вещи"), (1_001, "1,001 вещь")]
        for (count, expected) in expectations {
            XCTAssertEqual(InventoryLocalization.plural("item", count: count, table: "Test", bundle: bundle, language: "ru", locale: Locale(identifier: "en_US")), expected)
        }
    }

    func testEnglishPluralFormsAndRussianNumericFormatting() throws {
        let (bundle, root) = try fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        for count in [0, 1, 2, 5, 21] {
            XCTAssertEqual(InventoryLocalization.plural("item", count: count, table: "Test", bundle: bundle, language: "en", locale: Locale(identifier: "en_US")), "\(count) " + (count == 1 ? "item" : "items"))
        }
        let locale = Locale(identifier: "ru_RU")
        let expectedNumber = InventoryLocalization.number(1_001, locale: locale)
        XCTAssertFalse(expectedNumber.contains(","))
        XCTAssertEqual(InventoryLocalization.plural("item", count: 1_001, table: "Test", bundle: bundle, language: "en", locale: locale), expectedNumber + " items")
        XCTAssertEqual(InventoryLocalization.pluralCategory(Int.min, language: "ru"), "many")
        XCTAssertEqual(InventoryLocalization.pluralCategory(-21, language: "ru"), "one")
    }

    func testCoreCatalogParityAndFormatArguments() throws {
        func catalog(_ language: String) throws -> [String: String] {
            let directory = try XCTUnwrap(Bundle.module.path(forResource: language, ofType: "lproj"))
            let data = try Data(contentsOf: URL(fileURLWithPath: directory).appendingPathComponent("Core.strings"))
            return try XCTUnwrap(PropertyListSerialization.propertyList(from: data, format: nil) as? [String: String])
        }
        let english = try catalog("en"), russian = try catalog("ru")
        XCTAssertEqual(Set(english.keys), Set(russian.keys))
        XCTAssertGreaterThan(english.count, 50)
        for key in english.keys {
            XCTAssertFalse(try XCTUnwrap(russian[key]).isEmpty, key)
            XCTAssertEqual(english[key]!.components(separatedBy: "%@").count, russian[key]!.components(separatedBy: "%@").count, key)
        }
    }

    func testEveryCoreErrorAndNestedTokenHasRussianTextWithoutChangingRawValues() {
        let sentinel = "Raw-original-Файл.png"
        let errors: [InventoryError] = [.unsupportedSchema(3), .invalidManifest, .invalidBackup, .duplicateIdentifier, .unsafePath, .unsupportedMediaType("image/alien"), .missingItem, .missingAttachment(sentinel), .checksumMismatch(sentinel), .attachmentConflict(sentinel)]
        for error in errors {
            let ru = error.localizedDescription(language: "ru", locale: Locale(identifier: "en_US"))
            XCTAssertNotEqual(ru, error.localizedDescription(language: "en"), String(describing: error))
            XCTAssertNil(ru.range(of: "error."))
        }
        XCTAssertTrue(InventoryError.missingAttachment(sentinel).localizedDescription(language: "ru").contains(sentinel))
        let limits = ["128 MiB per backup", "4 MiB of inventory text", "100 homes", "1,000 rooms", "10,000 items", "5,000 originals", "64 KiB per text field", "25 MiB per original", "80 MiB of originals per inventory", "16 MiB per CSV export", "originals must not be empty", "4 MiB per stored file", "25 MiB per stored file"]
        for value in limits {
            let error = InventoryError.limitExceeded(value)
            XCTAssertEqual(error, .limitExceeded(value))
            XCTAssertFalse(error.localizedDescription(language: "ru", locale: Locale(identifier: "en_US")).contains(value), value)
            XCTAssertTrue(error.localizedDescription(language: "en", locale: Locale(identifier: "en_US")).contains(value), value)
        }
        let operations = ["installing restored originals", "committing restored inventory", "checking a restored original name", "allocating a restored original name", "opening the inventory lock", "locking the inventory", "creating the inventory folder", "checking the inventory file", "reading an inventory file", "creating an inventory file", "writing an inventory file", "saving an inventory file", "committing the inventory"]
        for operation in operations {
            XCTAssertFalse(InventoryError.storage(operation).localizedDescription(language: "ru").contains(operation), operation)
            XCTAssertTrue(InventoryError.storage(operation).localizedDescription(language: "en").contains(operation), operation)
        }
    }

    func testLocalizedCSVRetainsRawValuesPathsAndFormulaProtection() throws {
        let attachment = InventoryAttachment(kind: .receipt, fileName: "original.png", originalName: "Исходный файл.png", mediaType: "image/png", sha256: "sha-value")
        let item = InventoryItem(name: "=1+1", model: "Original Model", serialNumber: "SN-RAW", purchasePrice: "USD 1,299.00", purchaseDate: "2026-10-21", notes: "User русский text", attachments: [attachment])
        let inventory = Inventory(homes: [.init(name: "User Home", rooms: [.init(name: "User Room", items: [item])])])
        let before = try InventoryCSV.render(inventory)
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        let encoded = try encoder.encode(inventory)
        let localized = try InventoryCSV.renderLocalized(inventory, language: "ru", locale: Locale(identifier: "en_US"))
        XCTAssertTrue(localized.hasPrefix("\"ID дома\",\"Дом\""))
        for raw in ["'" + item.name, item.model, item.serialNumber, item.purchasePrice, item.purchaseDate, item.notes, attachment.originalName, "originals/\(item.id.uuidString)/original.png", "sha-value"] {
            XCTAssertTrue(localized.contains(raw), raw)
        }
        XCTAssertTrue(localized.contains("\"Чек\""))
        XCTAssertTrue(before.contains("\"receipt\""))
        XCTAssertEqual(try InventoryCSV.render(inventory), before)
        XCTAssertEqual(try encoder.encode(inventory), encoded)
        XCTAssertEqual(try InventoryCSV.renderLocalized(inventory, language: "fr"), try InventoryCSV.renderLocalized(inventory, language: "en"))
    }
}
