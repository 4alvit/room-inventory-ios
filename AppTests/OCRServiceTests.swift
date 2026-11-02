import XCTest
import UIKit
@testable import RoomInventory

final class OCRServiceTests: XCTestCase {
    func testExplicitLabelFieldsProduceUnselectedSuggestions() {
        let suggestions = OCRService.candidates(in: "MODEL:XR-27\nSerial number: SN-TEST-482\nGrand Total $199.00\nPurchased 2026-10-20")
        XCTAssertEqual(suggestions.count, 4)
        XCTAssertEqual(suggestions.first(where: { $0.field == .model })?.value, "XR-27")
        XCTAssertEqual(suggestions.first(where: { $0.field == .serialNumber })?.value, "SN-TEST-482")
        XCTAssertEqual(suggestions.first(where: { $0.field == .purchasePrice })?.value, "$199.00")
        XCTAssertEqual(suggestions.first(where: { $0.field == .purchaseDate })?.value, "2026-10-20")
        XCTAssertTrue(suggestions.allSatisfy { !$0.isSelected }, "OCR values require an explicit user choice.")
    }

    func testUnlabeledTextDoesNotInventModelOrSerial() {
        let suggestions = OCRService.candidates(in: "SYNTHETIC ELECTRONICS\nABCD-4821\nBlack monitor\nModeling software")
        XCTAssertTrue(suggestions.isEmpty)
    }

    func testSerialNumberPrefixIsNotIncludedInValue() {
        let suggestions = OCRService.candidates(in: "Model number: TEST-42\nS/N:234-TEST")
        XCTAssertEqual(suggestions.first(where: { $0.field == .model })?.value, "TEST-42")
        XCTAssertEqual(suggestions.first(where: { $0.field == .serialNumber })?.value, "234-TEST")
    }

    func testAmbiguousLocalDateIsNotSilentlyInterpreted() {
        let suggestions = OCRService.candidates(in: "Date: 03/04/2026")
        XCTAssertNil(suggestions.first(where: { $0.field == .purchaseDate }))
    }

    func testSubtotalDoesNotReplaceActualTotal() {
        let suggestions = OCRService.candidates(in: "Subtotal $100.00\nTax $8.00\nTotal $108.00")
        XCTAssertEqual(suggestions.first(where: { $0.field == .purchasePrice })?.value, "$108.00")
    }

    func testEmptyLabelDoesNotConsumeNextLine() {
        let suggestions = OCRService.candidates(in: "Model:\nSerial: TEST-1")
        XCTAssertNil(suggestions.first(where: { $0.field == .model }))
        XCTAssertEqual(suggestions.first(where: { $0.field == .serialNumber })?.value, "TEST-1")
    }

    func testCompleteUSAndEuropeanAmountsPreserveTheirFormatting() {
        let cases = [
            ("Total: $1,299.00", "$1,299.00"),
            ("Total EUR 1.299,00", "EUR 1.299,00"),
            ("Grand total: $12,345,678.90", "$12,345,678.90"),
            ("Amount paid: 12.345.678,90 EUR", "12.345.678,90 EUR"),
            ("Total: USD1299.00", "USD1299.00"),
            ("Total: USD 1299.00", "USD 1299.00"),
            ("Total: 1299,00 EUR", "1299,00 EUR"),
            ("Total: £0.99", "£0.99"),
            ("Total: 12.34GBP", "12.34GBP"),
            ("\tTotal: €12,34\t", "€12,34")
        ]
        for (text, expected) in cases {
            let suggestion = OCRService.candidates(in: text).first { $0.field == .purchasePrice }
            XCTAssertEqual(suggestion?.value, expected, text)
            XCTAssertEqual(suggestion?.isSelected, false, "A recognized amount still needs review: \(text)")
        }
    }

    func testMalformedOrAmbiguousAmountTokensNeverProducePrefixes() {
        let amounts = [
            "$12.345", "$12,345", "$1,299", "EUR 1.299",
            "$1,299.001", "EUR 1.299,001", "$12,34.56", "EUR 12.34,56",
            "$1234,567.89", "EUR 1234.567,89", "$1,,299.00", "$1,299,00",
            "EUR 1.299.00", "$12.34.56", "$12.34,56", "$12.34e5",
            "$12.34USD5", "$12.34/56", "$12.34-56", "$12.34 56",
            "$12.34 USD 56", "$12.34 total", "EUR 12 99,00",
            "$-12.34", "$12.34%", "$12.34.", "$12.34,"
        ]
        for amount in amounts {
            let suggestions = OCRService.candidates(in: "Total: \(amount)")
            XCTAssertNil(suggestions.first { $0.field == .purchasePrice }, amount)
        }
    }

    func testMalformedTotalDoesNotHideLaterCompleteAmount() {
        let suggestions = OCRService.candidates(in: "Total $12.345\nGrand Total $12.35")
        XCTAssertEqual(suggestions.first { $0.field == .purchasePrice }?.value, "$12.35")
    }

    func testLongAmountIsRejectedRatherThanTruncated() {
        let amount = "$" + String(repeating: "1", count: 160) + ".00"
        let suggestions = OCRService.candidates(in: "Total \(amount)")
        XCTAssertNil(suggestions.first { $0.field == .purchasePrice })
    }
    func testRussianReceiptLabelsAndGroupedAmountsRemainExplicitSuggestions() {
        for separator in [" ", "\u{00A0}", "\u{202F}"] {
            let amount = "1" + separator + "299,00" + separator + "RUB"
            let text = "Модель: ТЕСТ-42\nСерийный номер: RU-SN-123\nИтого: " + amount + "\nДата покупки: 21.10.2026"
            let suggestions = OCRService.candidates(in: text)
            XCTAssertEqual(suggestions.count, 4, separator)
            XCTAssertEqual(suggestions.first { $0.field == .model }?.value, "ТЕСТ-42")
            XCTAssertEqual(suggestions.first { $0.field == .serialNumber }?.value, "RU-SN-123")
            XCTAssertEqual(suggestions.first { $0.field == .purchasePrice }?.value, amount)
            XCTAssertEqual(suggestions.first { $0.field == .purchaseDate }?.value, "2026-10-21")
            XCTAssertTrue(suggestions.allSatisfy { !$0.isSelected })
        }
    }

    func testRussianMalformedAmountsAndImpossibleDatesAreRejected() {
        for amount in ["1 29,00 RUB", "1 299,001 RUB", "12,34 56 RUB", "1299,00 RUB extra"] {
            XCTAssertNil(OCRService.candidates(in: "Итого: " + amount).first { $0.field == .purchasePrice })
        }
        for date in ["Дата: 30.02.2026", "Дата покупки: 29.02.2025", "Дата: 03/04/2026", "2026-02-30"] {
            XCTAssertNil(OCRService.candidates(in: date).first { $0.field == .purchaseDate })
        }
    }

    func testRecognitionLanguagePriorityUsesOnlySupportedLanguages() {
        XCTAssertEqual(OCRService.recognitionLanguages(supported: ["en-US", "ru-RU", "fr-FR"], preferences: ["ru", "de-DE"]), ["ru-RU", "en-US"])
        XCTAssertEqual(OCRService.recognitionLanguages(supported: ["en-US"], preferences: ["ru"]), ["en-US"])
    }

    func testActualVisionRecognizesSyntheticRussianReceipt() async throws {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: 1400, height: 420), format: format)
        let image = renderer.image { context in
            UIColor.white.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 1400, height: 420))
            let receipt = "Модель: TEST-42\nСерийный номер: SN-123456\nИтого: 1299,00 RUB\nДата покупки: 21.10.2026"
            (receipt as NSString).draw(in: CGRect(x: 40, y: 40, width: 1300, height: 340), withAttributes: [.font: UIFont.systemFont(ofSize: 44), .foregroundColor: UIColor.black])
        }
        let result = try await OCRService.recognize(XCTUnwrap(image.pngData()))
        XCTAssertEqual(result.suggestions.first { $0.field == .model }?.value, "TEST-42", result.text)
        XCTAssertEqual(result.suggestions.first { $0.field == .serialNumber }?.value, "SN-123456", result.text)
        XCTAssertEqual(result.suggestions.first { $0.field == .purchasePrice }?.value, "1299,00 RUB", result.text)
        XCTAssertEqual(result.suggestions.first { $0.field == .purchaseDate }?.value, "2026-10-21", result.text)
        XCTAssertTrue(result.suggestions.allSatisfy { !$0.isSelected })
    }

}
