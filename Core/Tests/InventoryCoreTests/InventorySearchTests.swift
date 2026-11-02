import XCTest
@testable import InventoryCore

final class InventorySearchTests: XCTestCase {
    func testFindsModelSerialAndNotesAcrossHomesWithoutChangingInventory() {
        let monitor = InventoryItem(name: "Monitor", model: "DISPLAY-42", serialNumber: "SN-007", notes: "Blue stand")
        let office = InventoryRoom(name: "Office", items: [monitor])
        let home = InventoryHome(name: "Main home", rooms: [office])
        let other = InventoryHome(name: "Apartment", rooms: [InventoryRoom(name: "Kitchen", items: [InventoryItem(name: "Kettle")])])
        let inventory = Inventory(homes: [other, home])
        let original = inventory

        for query in ["display-42", "sn-007", "blue", "office monitor", "MAIN display", " \n office\tSN-007  "] {
            let result = inventory.searchItems(query)
            XCTAssertEqual(result.map(\.id), [monitor.id], query)
            XCTAssertEqual(result.first?.homeID, home.id)
            XCTAssertEqual(result.first?.roomID, office.id)
            XCTAssertEqual(result.first?.homeName, "Main home")
            XCTAssertEqual(result.first?.roomName, "Office")
            XCTAssertEqual(result.first?.item, monitor)
        }
        XCTAssertEqual(inventory, original)
    }

    func testMatchesRussianAndAccentsWithoutRequiringExactCase() {
        let items = [InventoryItem(name: "Серебряный чайник"), InventoryItem(name: "Café lamp")]
        let inventory = Inventory(homes: [InventoryHome(rooms: [InventoryRoom(items: items)])])
        XCTAssertEqual(inventory.searchItems("ЧАЙНИК").map(\.id), [items[0].id])
        XCTAssertEqual(inventory.searchItems("CAFE").map(\.id), [items[1].id])
    }

    func testDuplicateNamesRetainDistinctLocationsAndInventoryOrder() {
        let firstItem = InventoryItem(name: "Monitor")
        let secondItem = InventoryItem(name: "Monitor")
        let firstRoom = InventoryRoom(name: "Office", items: [firstItem])
        let secondRoom = InventoryRoom(name: "Bedroom", items: [secondItem])
        let firstHome = InventoryHome(name: "Home", rooms: [firstRoom])
        let secondHome = InventoryHome(name: "Apartment", rooms: [secondRoom])
        let result = Inventory(homes: [firstHome, secondHome]).searchItems("monitor")
        XCTAssertEqual(result.map(\.id), [firstItem.id, secondItem.id])
        XCTAssertEqual(result.map(\.homeID), [firstHome.id, secondHome.id])
        XCTAssertEqual(result.map(\.roomID), [firstRoom.id, secondRoom.id])
    }

    func testEmptyAndUnmatchedQueriesDoNotReturnUnrelatedItems() {
        let inventory = Inventory(homes: [InventoryHome(name: "Home", rooms: [
            InventoryRoom(name: "Office", items: [InventoryItem(name: "Monitor")]),
            InventoryRoom(name: "Kitchen", items: [InventoryItem(name: "Kettle")])
        ])])
        for query in ["", " \n\t ", "missing", "kitchen monitor", "monitor kettle"] {
            XCTAssertTrue(inventory.searchItems(query).isEmpty, query)
        }
        XCTAssertTrue(Inventory().searchItems("monitor").isEmpty)
    }
}
