import Foundation
import XCTest
@testable import InventoryCore

final class InventoryCSVTests: XCTestCase {
    private func csv(name: String = "Camera", notes: String = "", attachments: [InventoryAttachment] = []) throws -> String {
        try InventoryCSV.render(Inventory(homes: [InventoryHome(name: "Home", rooms: [InventoryRoom(name: "Room", items: [
            InventoryItem(name: name, notes: notes, attachments: attachments)
        ])])]))
    }

    func testQuotesCommasAndNewlinesAreEscaped() throws {
        let output = try csv(name: "Camera, \"wide\"", notes: "line one\nline two")
        XCTAssertTrue(output.contains("\"Camera, \"\"wide\"\"\""))
        XCTAssertTrue(output.contains("\"line one\nline two\""))
        XCTAssertTrue(output.hasSuffix("\r\n"))
    }

    func testFormulaPrefixesAreNeutralizedIncludingWhitespaceAndControls() throws {
        for input in ["=1+1", "+SUM(1,2)", "-1+2", "@SUM(A1)", "  =1+1", "\t=1+1", "\r=1+1", "\u{FEFF}=1+1", "\u{0000}=1+1"] {
            XCTAssertTrue(try csv(name: input).contains("\"'" + input + "\""), "Unprotected input: \(input)")
        }
        XCTAssertTrue(try csv(name: "Ordinary").contains("\"Ordinary\""))
        XCTAssertFalse(try csv(name: "Ordinary").contains("\"'Ordinary\""))
    }

    func testEveryAttachmentRowRetainsStableAssociation() throws {
        let first = InventoryAttachment(kind: .photo, fileName: "first.jpg", originalName: "=malicious.jpg", mediaType: "image/jpeg", sha256: "abc")
        let second = InventoryAttachment(kind: .receipt, fileName: "second.pdf", mediaType: "application/pdf", sha256: "def")
        let output = try csv(attachments: [first, second])
        let lines = output.components(separatedBy: "\r\n").filter { !$0.isEmpty }
        XCTAssertEqual(lines.count, 3)
        let itemID = lines[1].components(separatedBy: ",")[4].trimmingCharacters(in: CharacterSet(charactersIn: "\""))
        XCTAssertTrue(lines[1].contains(first.id.uuidString))
        XCTAssertEqual(lines[1].components(separatedBy: ",")[13], "\"originals/\(itemID)/first.jpg\"")
        XCTAssertTrue(lines[1].contains("\"'=malicious.jpg\""))
        XCTAssertTrue(lines[2].contains(second.id.uuidString))
        XCTAssertEqual(lines[2].components(separatedBy: ",")[13], "\"originals/\(itemID)/second.pdf\"")
        XCTAssertEqual(lines[1].components(separatedBy: ",")[4], lines[2].components(separatedBy: ",")[4])
    }

    func testAttachmentPathsMatchZIPEntriesAndIncludeOwningItem() throws {
        let first = InventoryItem(name: "Camera", attachments: [
            InventoryAttachment(kind: .photo, fileName: "first.jpg", originalName: "first.jpg", mediaType: "image/jpeg")
        ])
        let second = InventoryItem(name: "Lamp", attachments: [
            InventoryAttachment(kind: .receipt, fileName: "second.pdf", originalName: "second.pdf", mediaType: "application/pdf")
        ])
        let inventory = Inventory(homes: [InventoryHome(name: "Synthetic home", rooms: [InventoryRoom(name: "Room", items: [first, second])])])
        let output = try InventoryCSV.render(inventory)
        let paths = output.components(separatedBy: "\r\n").dropFirst().filter { !$0.isEmpty }.map {
            $0.components(separatedBy: ",")[13].trimmingCharacters(in: CharacterSet(charactersIn: "\""))
        }
        let expected = ["originals/\(first.id.uuidString)/first.jpg", "originals/\(second.id.uuidString)/second.pdf"]
        XCTAssertEqual(paths, expected)
        let zip = try StoredZIP.encode(entries: expected.map { StoredZIP.Entry(path: $0, data: Data("synthetic original".utf8)) })
        for path in paths {
            XCTAssertNotNil(zip.range(of: Data(path.utf8)), "CSV references a file absent from the companion ZIP")
        }
        XCTAssertFalse(output.contains("assets/"))
    }

    func testItemWithoutOriginalStillHasARowAndEmptyInventoryHasHeader() throws {
        XCTAssertEqual(try csv().components(separatedBy: "\r\n").filter { !$0.isEmpty }.count, 2)
        let empty = try InventoryCSV.render(Inventory())
        XCTAssertEqual(empty.components(separatedBy: "\r\n").filter { !$0.isEmpty }.count, 1)
        XCTAssertTrue(empty.contains("attachment_path"))
    }

    func testAllowedMetadataCannotAmplifyIntoAnUnboundedCSV() throws {
        let notes = String(repeating: "n", count: InventoryLimits.maxTextBytes)
        let attachments = (0..<InventoryLimits.maxAttachments).map { _ in
            let id = UUID()
            return InventoryAttachment(id: id, fileName: "\(id.uuidString.lowercased()).png",
                                       originalName: "synthetic.png", mediaType: "image/png",
                                       sha256: String(repeating: "0", count: 64))
        }
        let inventory = Inventory(homes: [InventoryHome(rooms: [InventoryRoom(items: [
            InventoryItem(name: "Synthetic item", notes: notes, attachments: attachments)
        ])])])
        XCTAssertLessThan(try JSONEncoder().encode(inventory).count, InventoryLimits.maxManifestBytes)
        XCTAssertEqual(notes.utf8.count, InventoryLimits.maxTextBytes)
        XCTAssertThrowsError(try InventoryCSV.render(inventory)) {
            XCTAssertEqual($0 as? InventoryError, .limitExceeded("16 MiB per CSV export"))
        }
    }

    func testEscapedQuotesAndMultibyteTextCountTowardTheByteBudget() throws {
        let attachments = (0..<256).map { _ in InventoryAttachment(fileName: "synthetic.png") }
        for notes in [String(repeating: "\"", count: 64 * 1_024), String(repeating: "😀", count: 16 * 1_024)] {
            XCTAssertEqual(notes.utf8.count, InventoryLimits.maxTextBytes)
            XCTAssertThrowsError(try csv(notes: notes, attachments: attachments)) {
                XCTAssertEqual($0 as? InventoryError, .limitExceeded("16 MiB per CSV export"))
            }
        }
    }

    func testOrdinaryCSVRemainsByteForByteCompatible() throws {
        let homeID = UUID(uuidString: "00000000-0000-0000-0000-000000000001")!
        let roomID = UUID(uuidString: "00000000-0000-0000-0000-000000000002")!
        let itemID = UUID(uuidString: "00000000-0000-0000-0000-000000000003")!
        let inventory = Inventory(homes: [InventoryHome(id: homeID, name: "Home", rooms: [
            InventoryRoom(id: roomID, name: "Room", items: [InventoryItem(id: itemID, name: "Camera")])
        ])])
        let expected = "\"home_id\",\"home\",\"room_id\",\"room\",\"item_id\",\"item\",\"model\",\"serial_number\",\"purchase_price\",\"purchase_date\",\"notes\",\"attachment_id\",\"attachment_kind\",\"attachment_path\",\"original_name\",\"media_type\",\"sha256\"\r\n"
            + "\"\(homeID.uuidString)\",\"Home\",\"\(roomID.uuidString)\",\"Room\",\"\(itemID.uuidString)\",\"Camera\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\",\"\"\r\n"
        XCTAssertEqual(try InventoryCSV.render(inventory), expected)
    }
}
