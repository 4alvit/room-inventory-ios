import XCTest
@testable import InventoryCore

final class InventoryReportOptionsTests: XCTestCase {
    func testSelectionAndFieldOmissionDoNotChangeSourceOrIdentities() {
        let attachment = InventoryAttachment(originalName: "private-receipt.png")
        let item = InventoryItem(name: "Monitor", model: "Model 42", serialNumber: "PRIVATE-SERIAL",
                                 purchasePrice: "USD 99", purchaseDate: "2026-10-21", notes: "PRIVATE-NOTE", attachments: [attachment])
        let selected = InventoryRoom(name: "Office", items: [item])
        let excluded = InventoryRoom(name: "Private room", items: [InventoryItem(name: "Excluded item")])
        let inventory = Inventory(homes: [InventoryHome(name: "Home", rooms: [selected, excluded]),
                                         InventoryHome(name: "Other home", rooms: [InventoryRoom(name: "Other room")])])
        var options = InventoryReportOptions(roomIDs: [selected.id])
        options.includeSerialNumbers = false
        options.includePurchaseDetails = false
        options.includeNotes = false
        options.includeAttachmentList = false
        let result = options.applying(to: inventory)
        XCTAssertEqual(result.homes.count, 1)
        XCTAssertEqual(result.homes.first?.id, inventory.homes.first?.id)
        XCTAssertEqual(result.homes.first?.rooms.map(\.id), [selected.id])
        var expected = item
        expected.serialNumber = ""; expected.purchasePrice = ""; expected.purchaseDate = ""
        expected.notes = ""; expected.attachments = []
        XCTAssertEqual(result.homes.first?.rooms.first?.items, [expected])
        XCTAssertEqual(inventory.homes.first?.rooms.first?.items, [item])
        XCTAssertEqual(inventory.homes.count, 2)
    }

    func testDefaultFieldsAndUnknownOrEmptySelection() {
        let room = InventoryRoom(name: "Office", items: [InventoryItem(name: "Lamp", serialNumber: "ABC")])
        let inventory = Inventory(homes: [InventoryHome(name: "Home", rooms: [room])])
        XCTAssertEqual(InventoryReportOptions(roomIDs: [room.id]).applying(to: inventory), inventory)
        XCTAssertTrue(InventoryReportOptions(roomIDs: []).applying(to: inventory).homes.isEmpty)
        XCTAssertTrue(InventoryReportOptions(roomIDs: [UUID()]).applying(to: inventory).homes.isEmpty)
    }
}
