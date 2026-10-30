import XCTest
import InventoryCore
@testable import RoomInventory

@MainActor
final class InventoryStoreTests: XCTestCase {
    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("InventoryStoreTest-\(UUID())", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    func testFreeLimitsAreGlobalAcrossHomesAndRooms() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = InventoryStore(rootURL: directory)
        await store.load()
        await store.addHome(name: "Synthetic Home A")
        await store.addHome(name: "Synthetic Home B")
        let first = try XCTUnwrap(store.inventory.homes.first?.id)
        let second = try XCTUnwrap(store.inventory.homes.last?.id)
        let firstRoom = await store.addRoom(homeID: first, name: "Office", isPro: false)
        let deniedRoom = await store.addRoom(homeID: second, name: "Garage", isPro: false)
        XCTAssertTrue(firstRoom)
        XCTAssertFalse(deniedRoom)
        let roomID = try XCTUnwrap(store.home(first)?.rooms.first?.id)
        for index in 1...10 { await store.addItem(homeID: first, roomID: roomID, name: "Synthetic item \(index)", isPro: false) }
        let deniedItem = await store.addItem(homeID: first, roomID: roomID, name: "Eleventh item", isPro: false)
        XCTAssertFalse(deniedItem)
        XCTAssertEqual(store.itemCount, 10)
        let proRoom = await store.addRoom(homeID: second, name: "Garage", isPro: true)
        XCTAssertTrue(proRoom)
        let secondRoomID = try XCTUnwrap(store.home(second)?.rooms.first?.id)
        let stillDenied = await store.addItem(homeID: second, roomID: secondRoomID, name: "Bypass attempt", isPro: false)
        XCTAssertFalse(stillDenied)
    }

    func testCorruptManifestIsNotOverwrittenByAnAddition() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let original = Data("deliberately invalid synthetic manifest".utf8)
        let manifest = directory.appendingPathComponent("inventory.json")
        try original.write(to: manifest)
        let store = InventoryStore(rootURL: directory)
        await store.load()
        let success = await store.addHome(name: "Must not overwrite")
        XCTAssertFalse(success)
        XCTAssertFalse(store.hasLoaded)
        XCTAssertEqual(try Data(contentsOf: manifest), original)
        XCTAssertNotNil(store.errorMessage)
    }

    func testStaleEditorKeepsNewlyAttachedOriginal() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = InventoryStore(rootURL: directory)
        await store.load()
        await store.addHome(name: "Synthetic Home")
        let homeID = try XCTUnwrap(store.inventory.homes.first?.id)
        await store.addRoom(homeID: homeID, name: "Office", isPro: false)
        let roomID = try XCTUnwrap(store.home(homeID)?.rooms.first?.id)
        await store.addItem(homeID: homeID, roomID: roomID, name: "Synthetic monitor", isPro: false)
        var draft = try XCTUnwrap(store.room(homeID: homeID, roomID: roomID)?.items.first)
        let png = try XCTUnwrap(Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6tX8AAAAASUVORK5CYII="))
        let attached = await store.addAttachment(homeID: homeID, roomID: roomID, itemID: draft.id, data: png, originalName: "synthetic.png", mediaType: "image/png", kind: .photo)
        XCTAssertNotNil(attached)
        draft.model = "TEST-27"
        let saved = await store.updateItem(homeID: homeID, roomID: roomID, item: draft)
        XCTAssertTrue(saved)
        XCTAssertEqual(store.item(homeID: homeID, roomID: roomID, itemID: draft.id)?.attachments.count, 1)
        XCTAssertEqual(try store.repository?.load(), store.inventory)
    }

    func testRestoredProSizedInventoryRemainsEditableWithoutPro() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let source = try InventoryRepository(rootURL: directory.appendingPathComponent("source"))
        let inventory = Inventory(homes: [InventoryHome(name: "Synthetic home", rooms: [
            InventoryRoom(name: "Room A", items: (1...11).map { InventoryItem(name: "Synthetic item \($0)") }),
            InventoryRoom(name: "Room B")
        ])])
        let backup = directory.appendingPathComponent("sample.roominventory")
        try source.exportBackup(inventory).write(to: backup)
        let store = InventoryStore(rootURL: directory.appendingPathComponent("target"))
        await store.load()
        await store.restore(url: backup)
        XCTAssertEqual(store.roomCount, 2)
        XCTAssertEqual(store.itemCount, 11)
        XCTAssertFalse(store.canAddRoom(isPro: false))
        XCTAssertFalse(store.canAddItem(isPro: false))
        let home = try XCTUnwrap(store.inventory.homes.first)
        let room = try XCTUnwrap(home.rooms.first)
        var draft = try XCTUnwrap(room.items.first)
        draft.notes = "Still editable without Pro"
        let saved = await store.updateItem(homeID: home.id, roomID: room.id, item: draft)
        XCTAssertTrue(saved)
        XCTAssertEqual(store.item(homeID: home.id, roomID: room.id, itemID: draft.id)?.notes, draft.notes)
    }

    func testFailedRestorePreservesVisibleAndPersistedInventory() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = InventoryStore(rootURL: directory.appendingPathComponent("target"))
        await store.load()
        await store.addHome(name: "Keep this synthetic home")
        let before = store.inventory
        let bad = directory.appendingPathComponent("bad.roominventory")
        try Data("invalid backup".utf8).write(to: bad)
        await store.restore(url: bad)
        XCTAssertEqual(store.inventory, before)
        XCTAssertEqual(try store.repository?.load(), before)
        XCTAssertNotNil(store.errorMessage)
    }

    func testStorageFailureDoesNotPublishAnUnsavedAddition() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let root = directory.appendingPathComponent("repository")
        let moved = directory.appendingPathComponent("unavailable-repository")
        let store = InventoryStore(rootURL: root)
        await store.load()
        await store.addHome(name: "Already saved")
        let before = store.inventory
        try FileManager.default.moveItem(at: root, to: moved)
        try Data("synthetic storage obstruction".utf8).write(to: root)
        let saved = await store.addHome(name: "Must remain unsaved")
        XCTAssertFalse(saved)
        XCTAssertEqual(store.inventory, before)
        XCTAssertNotNil(store.errorMessage)
        XCTAssertEqual(try InventoryRepository(rootURL: moved).load(), before)
    }

    func testRejectedAttachmentRetriesDoNotLeakFilesOrChangeVisibleInventory() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let repository = try InventoryRepository(rootURL: directory)
        let items = (0..<63).map {
            InventoryItem(name: "Synthetic item \($0)", notes: String(repeating: "x", count: InventoryLimits.maxTextBytes))
        }
        let original = Inventory(homes: [InventoryHome(name: "Synthetic home", rooms: [InventoryRoom(name: "Room", items: items)])])
        try repository.save(original)
        let store = InventoryStore(rootURL: directory)
        await store.load()
        XCTAssertTrue(store.hasLoaded)
        let home = original.homes[0], room = home.rooms[0], item = room.items[0]
        let manifest = directory.appendingPathComponent("inventory.json")
        let before = try Data(contentsOf: manifest)
        for _ in 0..<3 {
            let result = await store.addAttachment(homeID: home.id, roomID: room.id, itemID: item.id,
                                                   data: Data("synthetic original".utf8),
                                                   originalName: String(repeating: "a", count: InventoryLimits.maxTextBytes),
                                                   mediaType: "image/png", kind: .photo)
            XCTAssertNil(result)
            XCTAssertFalse(store.isBusy)
        }
        XCTAssertEqual(store.inventory, original)
        XCTAssertEqual(try Data(contentsOf: manifest), before)
        XCTAssertEqual(try repository.load(), original)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: directory.appendingPathComponent("assets").path), [])
        XCTAssertEqual(store.errorMessage, InventoryError.limitExceeded("4 MiB of inventory text").localizedDescription)
    }
}
