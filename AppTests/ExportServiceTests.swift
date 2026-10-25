import XCTest
import InventoryCore
import PDFKit
@testable import RoomInventory

final class ExportServiceTests: XCTestCase {
    func testValidInventoryWithExcessiveLineBreaksCannotProduceUnboundedPDF() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let repository = try InventoryRepository(rootURL: root)
        let inventory = Inventory(homes: [.init(name: "Synthetic home", rooms: [.init(name: "Office", items: [
            .init(name: "Long note", notes: String(repeating: "\n", count: 30_000) + "TAIL")
        ])])])
        // This is accepted by ordinary storage limits, not an impossible model.
        try repository.save(inventory)
        do {
            let url = try await ExportService.pdfURL(inventory: inventory)
            defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
            let pdf = try XCTUnwrap(PDFDocument(url: url))
            XCTFail("Expected a bounded export error; produced \(pdf.pageCount) pages")
        } catch {
            XCTAssertEqual(error as? PDFExportError, .pageLimitExceeded)
        }
        do {
            let url = try await ExportService.bundleURL(inventory: inventory, repository: repository)
            defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
            XCTFail("ZIP must not publish a partial PDF")
        } catch {
            XCTAssertEqual(error as? PDFExportError, .pageLimitExceeded)
        }
        XCTAssertEqual(try repository.load(), inventory)
    }

    func testCustomPDFExcludesUnselectedRoomsAndPrivateFields() async throws {
        let item = InventoryItem(name: "Selected desk", model: "Public model", serialNumber: "SECRET-SERIAL",
                                 purchasePrice: "SECRET-PRICE", purchaseDate: "SECRET-DATE", notes: "SECRET-NOTE",
                                 attachments: [.init(originalName: "SECRET-ATTACHMENT")])
        let room = InventoryRoom(name: "Selected room", items: [item])
        let inventory = Inventory(homes: [.init(name: "Home", rooms: [room, .init(name: "SECRET-ROOM", items: [.init(name: "SECRET-ITEM")])])])
        var options = InventoryReportOptions(roomIDs: [room.id])
        options.includeSerialNumbers = false
        options.includePurchaseDetails = false
        options.includeNotes = false
        options.includeAttachmentList = false
        let url = try await ExportService.pdfURL(inventory: options.applying(to: inventory))
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let pdf = try XCTUnwrap(PDFDocument(url: url))
        let text = (0..<pdf.pageCount).compactMap { pdf.page(at: $0)?.string }.joined(separator: "\n")
        XCTAssertTrue(text.contains("Selected desk"))
        XCTAssertTrue(text.contains("Public model"))
        XCTAssertFalse(text.contains("SECRET"))
        XCTAssertFalse(text.contains("originals/"))
        XCTAssertEqual(inventory.homes.first?.rooms.first?.items.first, item)
    }

    func testPDFSpansPagesWithoutLosingLongNotes() async throws {
        let note = String(repeating: "Synthetic inventory note with a serial label. ", count: 450) + "END-OF-NOTE"
        let inventory = Inventory(homes: [.init(name: "Test home", rooms: [.init(name: "Office", items: [.init(name: "Test display", notes: note)])])])
        let url = try await ExportService.pdfURL(inventory: inventory)
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let pdf = try XCTUnwrap(PDFDocument(url: url))
        XCTAssertGreaterThan(pdf.pageCount, 1)
        let text = (0..<pdf.pageCount).compactMap { pdf.page(at: $0)?.string }.joined(separator: "\n")
        XCTAssertTrue(text.contains("END-OF-NOTE"))
        XCTAssertTrue(text.contains("Test display"))
    }

    func testBackupExportContainsOriginalAndRestoresExactly() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = try InventoryRepository(rootURL: root.appendingPathComponent("source"))
        let attachment = try source.importAttachment(data: Data("synthetic original".utf8), originalName: "Synthetic receipt.png", mediaType: "image/png", kind: .receipt)
        let inventory = Inventory(homes: [.init(name: "Test home", rooms: [.init(name: "Office", items: [.init(name: "Test display", attachments: [attachment])])])])
        try source.save(inventory)
        let url = try await ExportService.backupURL(inventory: inventory, repository: source)
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let target = try InventoryRepository(rootURL: root.appendingPathComponent("target"))
        XCTAssertEqual(try target.restoreBackup(Data(contentsOf: url)), inventory)
        XCTAssertEqual(try target.data(for: attachment), Data("synthetic original".utf8))
    }

    func testZIPUsesCSVPathsAndPreservesOriginalBytes() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let repository = try InventoryRepository(rootURL: root)
        let bytes = Data("original synthetic bytes".utf8)
        let attachment = try repository.importAttachment(data: bytes, originalName: "Receipt, №1.png", mediaType: "image/png", kind: .receipt)
        let item = InventoryItem(name: "Test", attachments: [attachment])
        let inventory = Inventory(homes: [.init(name: "Test home", rooms: [.init(name: "Office", items: [item])])])
        try repository.save(inventory)
        let url = try await ExportService.bundleURL(inventory: inventory, repository: repository)
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let archive = try Data(contentsOf: url)
        // Read local stored entries independently of our encoder; sizes are little-endian.
        func u16(_ i: Int) -> Int { Int(archive[i]) | Int(archive[i+1]) << 8 }
        func u32(_ i: Int) -> Int { u16(i) | u16(i+2) << 16 }
        var offset = 0
        var files: [String: Data] = [:]
        while offset + 30 <= archive.count && u32(offset) == 0x04034b50 {
            XCTAssertEqual(u16(offset+8), 0)
            let size = u32(offset+18), nameSize = u16(offset+26), extraSize = u16(offset+28)
            let dataStart = offset+30+nameSize+extraSize
            guard dataStart+size <= archive.count else { XCTFail("Truncated ZIP entry"); return }
            let name = try XCTUnwrap(String(data: archive[(offset+30)..<(offset+30+nameSize)], encoding: .utf8))
            files[name] = archive[dataStart..<(dataStart+size)]
            offset = dataStart+size
        }
        let path = "originals/\(item.id.uuidString)/\(attachment.fileName)"
        XCTAssertEqual(files[path], bytes)
        let csv = try XCTUnwrap(String(data: try XCTUnwrap(files["Inventory.csv"]), encoding: .utf8))
        XCTAssertTrue(csv.contains(path))
        XCTAssertNotNil(files["Inventory.pdf"])
    }
    func testRussianPDFCaptionsUseRussianWhileAmountsFollowUSRegion() async throws {
        let item = InventoryItem(name: "USER-NAME", model: "USER-MODEL", serialNumber: "USER-SERIAL", purchasePrice: "USD 1299.00", purchaseDate: "2026-10-21", notes: "USER-NOTES", attachments: [.init(kind: .receipt, originalName: "USER-ORIGINAL.png")])
        let inventory = Inventory(homes: [.init(name: "USER-HOME", rooms: [.init(name: "USER-ROOM", items: [item])])])
        let before = try JSONEncoder().encode(inventory)
        let url = try await ExportService.pdfURL(inventory: inventory, language: "ru", locale: Locale(identifier: "en_US"))
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let pdf = try XCTUnwrap(PDFDocument(url: url))
        let text = (0..<pdf.pageCount).compactMap { pdf.page(at: $0)?.string }.joined(separator: "\n")
        let attachment = XCTAttachment(data: try Data(contentsOf: url), uniformTypeIdentifier: "com.adobe.pdf")
        attachment.name = "Russian-inventory-report"
        attachment.lifetime = .keepAlways
        add(attachment)
        for value in ["Ваше имущество", "Модель", "Серийный номер", "Цена покупки", "Дата покупки", "Заметки", "Чек", "USER-NAME", "USER-MODEL", "USER-SERIAL", "USER-NOTES", "USER-ORIGINAL.png", "$1,299.00", "Oct 21, 2026"] {
            XCTAssertTrue(text.contains(value), "PDF missing: " + value + "\nExtracted text: " + text)
        }
        XCTAssertEqual(try JSONDecoder().decode(Inventory.self, from: before), inventory)
        let csvURL = try await ExportService.csvURL(inventory: inventory, language: "ru", locale: Locale(identifier: "en_US"))
        defer { try? FileManager.default.removeItem(at: csvURL.deletingLastPathComponent()) }
        let csv = try String(contentsOf: csvURL, encoding: .utf8)
        XCTAssertTrue(csv.contains("Модель"))
        XCTAssertTrue(csv.contains("USD 1299.00"))
        XCTAssertTrue(csv.contains("2026-10-21"))
        XCTAssertTrue(csv.contains("USER-ORIGINAL.png"))
    }

}
