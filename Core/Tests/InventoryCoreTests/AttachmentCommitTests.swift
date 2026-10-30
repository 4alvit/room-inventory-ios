import Darwin
import Foundation
import XCTest
@testable import InventoryCore

final class AttachmentCommitTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    }

    override func tearDownWithError() throws {
        if let root {
            try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: root.path)
            try? FileManager.default.removeItem(at: root)
        }
    }

    private func fixture(items: [InventoryItem]) -> Inventory {
        Inventory(homes: [InventoryHome(name: "Synthetic home", rooms: [InventoryRoom(name: "Room", items: items)])])
    }

    private func assets() throws -> [String] {
        try FileManager.default.contentsOfDirectory(atPath: root.appendingPathComponent("assets").path).sorted()
    }

    private func append(_ repository: InventoryRepository, to inventory: Inventory, itemID: UUID,
                        name: String = "synthetic.png", data: Data = Data("synthetic original".utf8)) throws
        -> (inventory: Inventory, attachment: InventoryAttachment) {
        try repository.appendAttachment(data: data, originalName: name, mediaType: "image/png", kind: .photo,
                                        to: inventory, itemID: itemID)
    }

    func testFailedAttachmentCommitDoesNotLeakOriginalsAcrossRetries() throws {
        let repository = try InventoryRepository(rootURL: root)
        let items = (0..<63).map {
            InventoryItem(name: "Synthetic item \($0)", notes: String(repeating: "x", count: InventoryLimits.maxTextBytes))
        }
        let original = fixture(items: items)
        try repository.save(original)
        let before = try Data(contentsOf: root.appendingPathComponent("inventory.json"))
        let priorAssets = try assets()
        for _ in 0..<3 {
            XCTAssertThrowsError(try append(repository, to: original, itemID: items[0].id,
                                            name: String(repeating: "a", count: InventoryLimits.maxTextBytes))) {
                XCTAssertEqual($0 as? InventoryError, .limitExceeded("4 MiB of inventory text"))
            }
        }
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("inventory.json")), before)
        XCTAssertEqual(try assets(), priorAssets, "Rejected retries must not consume storage")
        XCTAssertEqual(try InventoryRepository(rootURL: root).load(), original)
    }

    func testAppendCommitsOriginalAndSurvivesReloadAndBackup() throws {
        let repository = try InventoryRepository(rootURL: root)
        let item = InventoryItem(name: "Synthetic camera")
        let original = fixture(items: [item])
        try repository.save(original)
        let result = try append(repository, to: original, itemID: item.id)
        var expected = original
        expected.homes[0].rooms[0].items[0].attachments = [result.attachment]
        XCTAssertEqual(result.inventory, expected)
        let reopened = try InventoryRepository(rootURL: root)
        XCTAssertEqual(try reopened.load(), expected)
        XCTAssertEqual(try reopened.data(for: result.attachment), Data("synthetic original".utf8))
        XCTAssertEqual(try assets(), [result.attachment.fileName])
        XCTAssertEqual(try reopened.restoreBackup(reopened.exportBackup(expected)), expected)
    }

    func testUnknownItemDoesNotCreateAnOriginalOrChangeManifest() throws {
        let repository = try InventoryRepository(rootURL: root)
        let original = fixture(items: [InventoryItem(name: "Existing item")])
        try repository.save(original)
        let before = try Data(contentsOf: root.appendingPathComponent("inventory.json"))
        XCTAssertThrowsError(try append(repository, to: original, itemID: UUID())) {
            XCTAssertEqual($0 as? InventoryError, .missingItem)
        }
        XCTAssertEqual(try assets(), [])
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("inventory.json")), before)
    }

    func testManifestWriteFailureRemovesOnlyNewOriginal() throws {
        guard geteuid() != 0 else { throw XCTSkip("Requires ordinary filesystem permissions") }
        let repository = try InventoryRepository(rootURL: root)
        let retainedBytes = Data("Previously committed and subsequently removed".utf8)
        let retained = try repository.importAttachment(data: retainedBytes, originalName: "retained.png",
                                                       mediaType: "image/png", kind: .photo)
        let existingBytes = Data("Existing referenced original".utf8)
        let existing = try repository.importAttachment(data: existingBytes, originalName: "existing.png",
                                                       mediaType: "image/png", kind: .photo)
        let item = InventoryItem(name: "Existing item", attachments: [existing, retained])
        var original = fixture(items: [item])
        try repository.save(original)
        original.homes[0].rooms[0].items[0].attachments.removeLast()
        try repository.save(original)
        let before = try Data(contentsOf: root.appendingPathComponent("inventory.json"))
        let priorAssets = try assets()

        // The assets directory remains writable, but creating the manifest temp file
        // in root must fail after the new original has been created and synced.
        try FileManager.default.setAttributes([.posixPermissions: 0o500], ofItemAtPath: root.path)
        for _ in 0..<3 {
            XCTAssertThrowsError(try append(repository, to: original, itemID: item.id)) {
                XCTAssertEqual($0 as? InventoryError, .storage("creating an inventory file"))
            }
        }
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: root.path)
        XCTAssertEqual(try assets(), priorAssets)
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("inventory.json")), before)
        XCTAssertEqual(try repository.data(for: retained), retainedBytes)
        XCTAssertEqual(try repository.data(for: existing), existingBytes)
        XCTAssertEqual(try InventoryRepository(rootURL: root).load(), original)
        XCTAssertFalse(try FileManager.default.contentsOfDirectory(atPath: root.path).contains { $0.hasPrefix(".manifest-") })
    }

    func testAggregateLimitRejectsBeforeCreatingAnotherOriginal() throws {
        let repository = try InventoryRepository(rootURL: root)
        let item = InventoryItem(name: "Existing item")
        var original = fixture(items: [item])
        // The repository supports 25 MiB originals, independently of the capture UI's 20 MB limit.
        for count in [25, 25, 25, 5] {
            let attachment = try repository.importAttachment(data: Data(repeating: 1, count: count * 1_024 * 1_024),
                                                             originalName: "synthetic.png", mediaType: "image/png", kind: .photo)
            original.homes[0].rooms[0].items[0].attachments.append(attachment)
        }
        try repository.save(original)
        let priorAssets = try assets()
        let before = try Data(contentsOf: root.appendingPathComponent("inventory.json"))
        XCTAssertThrowsError(try append(repository, to: original, itemID: item.id, data: Data([1]))) {
            XCTAssertEqual($0 as? InventoryError, .limitExceeded("80 MiB of originals per inventory"))
        }
        XCTAssertEqual(try assets(), priorAssets)
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("inventory.json")), before)
    }
}
