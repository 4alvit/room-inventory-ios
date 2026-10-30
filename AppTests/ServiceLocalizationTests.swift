import XCTest
@testable import RoomInventory

final class ServiceLocalizationTests: XCTestCase {
    func testRussianBatchGrammarIsIndependentOfUSNumberRegion() {
        let cases = [(0, "изображений"), (1, "изображение"), (2, "изображения"), (5, "изображений"), (21, "изображение")]
        for (count, noun) in cases {
            XCTAssertEqual(
                ServiceL10n.plural("batch.tooMany", count: count, language: "ru", locale: Locale(identifier: "en_US")),
                "Лимит за один раз — \(count) \(noun). Из выбранного набора ничего не импортировано."
            )
        }
        XCTAssertTrue(ServiceL10n.plural("batch.tooMany", count: 1_234, language: "ru", locale: Locale(identifier: "en_US")).contains("1,234 изображения"))
    }

    func testEnglishBatchGrammarAndFallbackPreserveExistingCopy() {
        for count in [0, 1, 2, 5, 21] {
            XCTAssertEqual(
                ServiceL10n.plural("batch.tooMany", count: count, language: "en", locale: Locale(identifier: "en_US")),
                "Choose no more than \(count) \(count == 1 ? "image" : "images") at a time. No images from this selection were imported."
            )
        }
        XCTAssertEqual(ServiceL10n.text("pro.cancelled", language: "fr"), "Purchase cancelled. Your inventory is unchanged.")
        XCTAssertEqual(ServiceL10n.text("pro.cancelled", language: "ru"), "Покупка отменена. Опись не изменилась.")
    }

    func testRestoreErrorKeepsUnderlyingDetailVerbatim() {
        let detail = "Receipt 100% — пользовательское имя.png"
        XCTAssertEqual(
            ServiceL10n.format("inventory.restoreFailed", arguments: [detail], language: "ru", locale: Locale(identifier: "en_US")),
            "Не удалось восстановить резервную копию. Текущая опись сохранена.\n\n" + detail
        )
    }
}
