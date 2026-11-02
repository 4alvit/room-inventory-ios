import Foundation
import XCTest
@testable import InventoryCore

final class InventoryRepositoryTests: XCTestCase {
    private var temporary: URL!

    override func setUpWithError() throws {
        temporary = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let temporary { try? FileManager.default.removeItem(at: temporary) }
    }

    private func repository(_ name: String = "store") throws -> InventoryRepository {
        try InventoryRepository(rootURL: temporary.appendingPathComponent(name, isDirectory: true))
    }

    private func fixture(_ attachment: InventoryAttachment? = nil, name: String = "Camera") -> Inventory {
        Inventory(homes: [InventoryHome(name: "Synthetic Home", rooms: [InventoryRoom(name: "Studio", items: [
            InventoryItem(name: name, model: "Example 100", serialNumber: "SYNTHETIC-001", purchasePrice: "19.99",
                          purchaseDate: "2026-10-20", notes: "Synthetic fixture only", attachments: attachment.map { [$0] } ?? [])
        ])])])
    }

    private func importFixture(_ repo: InventoryRepository) throws -> InventoryAttachment {
        try repo.importAttachment(data: Data("synthetic original".utf8), originalName: "receipt.png", mediaType: "image/png", kind: .receipt)
    }

    private func editedBackup(_ data: Data, edit: (inout [String: Any]) -> Void) throws -> Data {
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        edit(&object)
        return try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }

    func testFreshRepositoryAndPublicDefaults() throws {
        XCTAssertEqual(try repository().load(), Inventory())
        XCTAssertEqual(InventoryItem().attachments, [])
        XCTAssertEqual(InventoryItem().notes, "")
        XCTAssertEqual(InventoryHome().rooms, [])
    }

    func testSaveLoadAndPortableBackupRoundTrip() throws {
        let source = try repository()
        let attachment = try importFixture(source)
        let expected = fixture(attachment)
        try source.save(expected)
        XCTAssertEqual(try source.load(), expected)
        let backup = try source.exportBackup(expected)
        let destination = try repository("restored")
        XCTAssertEqual(try destination.restoreBackup(backup), expected)
        XCTAssertEqual(try destination.load(), expected)
        XCTAssertEqual(try destination.data(for: attachment), Data("synthetic original".utf8))
        // All file data remains outside the ordinary inventory JSON.
        let manifest = try String(contentsOf: source.rootURL.appendingPathComponent("inventory.json"), encoding: .utf8)
        XCTAssertFalse(manifest.contains(Data("synthetic original".utf8).base64EncodedString()))
        XCTAssertEqual(try destination.exportBackup(expected), backup)
    }

    func testSaveReplacesManifestAtomicallyAndRetainsUnreferencedOriginals() throws {
        let repo = try repository()
        let attachment = try importFixture(repo)
        try repo.save(fixture(attachment))
        let replacement = fixture(name: "New synthetic item")
        try repo.save(replacement)
        XCTAssertEqual(try repo.load(), replacement)
        XCTAssertEqual(try repo.data(for: attachment), Data("synthetic original".utf8))
        let contents = try FileManager.default.contentsOfDirectory(atPath: repo.rootURL.path)
        XCTAssertFalse(contents.contains(where: { $0.hasPrefix(".manifest-") }))
    }

    func testBadAttachmentCannotReplaceSavedInventory() throws {
        let repo = try repository()
        let attachment = try importFixture(repo)
        let original = fixture(attachment)
        try repo.save(original)
        var invalid = attachment
        invalid.sha256 = String(repeating: "0", count: 64)
        XCTAssertThrowsError(try repo.save(fixture(invalid))) { error in
            XCTAssertEqual(error as? InventoryError, .checksumMismatch(attachment.fileName))
        }
        XCTAssertEqual(try repo.load(), original)
    }

    func testTraversalRejectedForDirectReadSaveAndRestore() throws {
        let repo = try repository()
        var attachment = try importFixture(repo)
        let good = fixture(attachment)
        try repo.save(good)
        attachment.fileName = "../outside.png"
        XCTAssertThrowsError(try repo.data(for: attachment)) { XCTAssertEqual($0 as? InventoryError, .unsafePath) }
        XCTAssertThrowsError(try repo.save(fixture(attachment))) { XCTAssertEqual($0 as? InventoryError, .unsafePath) }
        let maliciousInventory = fixture(attachment)
        let invalid = try JSONSerialization.data(withJSONObject: [
            "format": "com.alvit.roominventory.backup", "version": 1,
            "inventory": JSONSerialization.jsonObject(with: JSONEncoder().encode(maliciousInventory)),
            "files": [attachment.fileName: Data("synthetic original".utf8).base64EncodedString()]
        ])
        XCTAssertThrowsError(try repo.restoreBackup(invalid)) { XCTAssertEqual($0 as? InventoryError, .unsafePath) }
        XCTAssertEqual(try repo.load(), good)
        XCTAssertFalse(FileManager.default.fileExists(atPath: temporary.appendingPathComponent("outside.png").path))
    }

    func testUnsupportedInventoryAndBackupVersionsDoNotReplaceCurrentData() throws {
        let repo = try repository()
        let expected = fixture()
        try repo.save(expected)
        let backup = try repo.exportBackup(expected)
        var future = expected
        future.schemaVersion = 99
        XCTAssertThrowsError(try repo.save(future)) { XCTAssertEqual($0 as? InventoryError, .unsupportedSchema(99)) }
        let futureBackup = try editedBackup(backup) { $0["version"] = 99 }
        XCTAssertThrowsError(try repo.restoreBackup(futureBackup)) { XCTAssertEqual($0 as? InventoryError, .unsupportedSchema(99)) }
        let futureInventory = try editedBackup(backup) {
            $0["inventory"] = ["schemaVersion": 99]
        }
        XCTAssertThrowsError(try repo.restoreBackup(futureInventory)) { XCTAssertEqual($0 as? InventoryError, .unsupportedSchema(99)) }
        XCTAssertEqual(try repo.load(), expected)
    }

    func testCorruptManifestNeverSilentlyResetsData() throws {
        let repo = try repository()
        let file = repo.rootURL.appendingPathComponent("inventory.json")
        let corrupt = Data("{broken".utf8)
        try corrupt.write(to: file)
        XCTAssertThrowsError(try repo.load()) { XCTAssertEqual($0 as? InventoryError, .invalidManifest) }
        XCTAssertEqual(try Data(contentsOf: file), corrupt)
        try Data("{\"schemaVersion\":99}".utf8).write(to: file)
        XCTAssertThrowsError(try repo.load()) { XCTAssertEqual($0 as? InventoryError, .unsupportedSchema(99)) }
    }

    func testBackupMissingExtraAndCorruptFilesAreNonDestructive() throws {
        let repo = try repository()
        let attachment = try importFixture(repo)
        let expected = fixture(attachment)
        try repo.save(expected)
        let originalManifest = try Data(contentsOf: repo.rootURL.appendingPathComponent("inventory.json"))
        let backup = try repo.exportBackup(expected)
        let missing = try editedBackup(backup) { $0["files"] = [:] }
        let extra = try editedBackup(backup) {
            var files = $0["files"] as! [String: Any]
            files["../../unrequested"] = "dGVzdA=="
            $0["files"] = files
        }
        let damaged = try editedBackup(backup) { $0["files"] = [attachment.fileName: Data("different".utf8).base64EncodedString()] }
        let invalidBase64 = try editedBackup(backup) { $0["files"] = [attachment.fileName: "%%invalid%%"] }
        for invalid in [missing, extra, damaged, invalidBase64, Data("not JSON".utf8)] {
            XCTAssertThrowsError(try repo.restoreBackup(invalid))
            XCTAssertEqual(try Data(contentsOf: repo.rootURL.appendingPathComponent("inventory.json")), originalManifest)
            XCTAssertEqual(try repo.load(), expected)
        }
        XCTAssertFalse(try FileManager.default.contentsOfDirectory(atPath: repo.rootURL.path).contains(where: { $0.hasPrefix(".restore-") }))
    }

    func testTamperedAndMissingStoredAssetsAreReported() throws {
        let repo = try repository()
        let attachment = try importFixture(repo)
        let expected = fixture(attachment)
        try repo.save(expected)
        let asset = repo.rootURL.appendingPathComponent("assets").appendingPathComponent(attachment.fileName)
        try Data("damaged".utf8).write(to: asset)
        XCTAssertThrowsError(try repo.load()) { XCTAssertEqual($0 as? InventoryError, .checksumMismatch(attachment.fileName)) }
        XCTAssertThrowsError(try repo.exportBackup(expected))
        try FileManager.default.removeItem(at: asset)
        XCTAssertThrowsError(try repo.data(for: attachment)) { XCTAssertEqual($0 as? InventoryError, .missingAttachment(attachment.fileName)) }
    }

    func testRestoreRemapsCollisionAndPreservesExistingOriginal() throws {
        let source = try repository("source")
        let destination = try repository("destination")
        let attachment = try importFixture(source)
        let incoming = fixture(attachment)
        let original = fixture(name: "Destination")
        try destination.save(original)
        let collision = destination.rootURL.appendingPathComponent("assets").appendingPathComponent(attachment.fileName)
        let priorBytes = Data("different original must survive".utf8)
        try priorBytes.write(to: collision)
        let restored = try destination.restoreBackup(source.exportBackup(incoming))
        let remapped = try XCTUnwrap(restored.homes.first?.rooms.first?.items.first?.attachments.first)
        XCTAssertNotEqual(remapped.id, attachment.id)
        XCTAssertNotEqual(remapped.fileName, attachment.fileName)
        var expected = incoming
        expected.homes[0].rooms[0].items[0].attachments[0] = remapped
        XCTAssertEqual(restored, expected)
        XCTAssertEqual(try destination.load(), expected)
        XCTAssertEqual(try destination.data(for: remapped), Data("synthetic original".utf8))
        XCTAssertEqual(try Data(contentsOf: collision), priorBytes)
    }

    func testKnownGoodBackupRecoversDamagedOriginalAndOnlyRemapsCollision() throws {
        let repo = try repository()
        let damaged = try importFixture(repo)
        let intact = try importFixture(repo)
        var expected = fixture(damaged)
        expected.homes[0].rooms[0].items[0].attachments.append(intact)
        try repo.save(expected)
        let backup = try repo.exportBackup(expected)
        let path = repo.rootURL.appendingPathComponent("assets").appendingPathComponent(damaged.fileName)
        let damagedBytes = Data("damaged original retained for inspection".utf8)
        try damagedBytes.write(to: path)
        XCTAssertThrowsError(try repo.load())

        let manifestURL = repo.rootURL.appendingPathComponent("inventory.json")
        let previousManifest = try Data(contentsOf: manifestURL)
        let invalid = try editedBackup(backup) {
            $0["files"] = [damaged.fileName: Data("invalid backup bytes".utf8).base64EncodedString()]
        }
        XCTAssertThrowsError(try repo.restoreBackup(invalid))
        XCTAssertEqual(try Data(contentsOf: manifestURL), previousManifest)
        XCTAssertEqual(try Data(contentsOf: path), damagedBytes)

        let restored = try repo.restoreBackup(backup)
        let recovered = restored.homes[0].rooms[0].items[0].attachments[0]
        XCTAssertNotEqual(recovered.id, damaged.id)
        var remappedExpected = expected
        remappedExpected.homes[0].rooms[0].items[0].attachments[0] = recovered
        XCTAssertEqual(restored, remappedExpected, "Only the conflicting attachment identity may change")
        XCTAssertEqual(try repo.load(), remappedExpected)
        XCTAssertEqual(try repo.data(for: recovered), Data("synthetic original".utf8))
        XCTAssertEqual(try repo.data(for: intact), Data("synthetic original".utf8))
        XCTAssertEqual(try Data(contentsOf: path), damagedBytes)

        let nextBackup = try repo.exportBackup(restored)
        XCTAssertEqual(try repository("roundtrip").restoreBackup(nextBackup), restored)
        XCTAssertEqual(try repo.restoreBackup(nextBackup), restored, "Non-conflicting restore stays exact")
    }

    func testDamagedOversizedOriginalCanBeRecoveredWithoutOverwritingIt() throws {
        let repo = try repository()
        let attachment = try importFixture(repo)
        let expected = fixture(attachment)
        try repo.save(expected)
        let backup = try repo.exportBackup(expected)
        let path = repo.rootURL.appendingPathComponent("assets").appendingPathComponent(attachment.fileName)
        let handle = try FileHandle(forWritingTo: path)
        try handle.truncate(atOffset: UInt64(InventoryLimits.maxAttachmentBytes + 1))
        try handle.close()
        let restored = try repo.restoreBackup(backup)
        XCTAssertEqual(try repo.load(), restored)
        XCTAssertNotEqual(restored.homes[0].rooms[0].items[0].attachments[0].id, attachment.id)
        XCTAssertEqual(try path.resourceValues(forKeys: [.fileSizeKey]).fileSize, InventoryLimits.maxAttachmentBytes + 1)
    }

    func testRestoreStillRejectsSymlinkCollisionWithoutChangingCurrentManifest() throws {
        let source = try repository("source")
        let destination = try repository("destination")
        let attachment = try importFixture(source)
        let incoming = fixture(attachment)
        let current = fixture(name: "Existing inventory")
        try destination.save(current)
        let preserved = temporary.appendingPathComponent("preserved.png")
        let bytes = Data("outside original".utf8)
        try bytes.write(to: preserved)
        let link = destination.rootURL.appendingPathComponent("assets").appendingPathComponent(attachment.fileName)
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: preserved)
        XCTAssertThrowsError(try destination.restoreBackup(source.exportBackup(incoming))) {
            XCTAssertEqual($0 as? InventoryError, .unsafePath)
        }
        XCTAssertEqual(try destination.load(), current)
        XCTAssertEqual(try Data(contentsOf: preserved), bytes)
    }

    func testSymlinkAssetsAndManifestAreRejectedAndFailedRestoreRollsBackPromotions() throws {
        let source = try repository("source")
        let destination = try repository("destination")
        let attachment = try importFixture(source)
        let incoming = fixture(attachment)
        let original = fixture(name: "Destination")
        try destination.save(original)
        let manifest = destination.rootURL.appendingPathComponent("inventory.json")
        let preserved = temporary.appendingPathComponent("preserved.json")
        try FileManager.default.moveItem(at: manifest, to: preserved)
        let originalBytes = try Data(contentsOf: preserved)
        try FileManager.default.createSymbolicLink(at: manifest, withDestinationURL: preserved)
        XCTAssertThrowsError(try destination.load()) { XCTAssertEqual($0 as? InventoryError, .unsafePath) }
        XCTAssertThrowsError(try destination.restoreBackup(source.exportBackup(incoming))) {
            XCTAssertEqual($0 as? InventoryError, .unsafePath)
        }
        XCTAssertEqual(try Data(contentsOf: preserved), originalBytes)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: destination.rootURL.appendingPathComponent("assets").path), [])
        XCTAssertFalse(try FileManager.default.contentsOfDirectory(atPath: destination.rootURL.path).contains(where: { $0.hasPrefix(".restore-") }))

        let sourceAsset = source.rootURL.appendingPathComponent("assets").appendingPathComponent(attachment.fileName)
        let originalAsset = temporary.appendingPathComponent("preserved.png")
        try FileManager.default.moveItem(at: sourceAsset, to: originalAsset)
        try FileManager.default.createSymbolicLink(at: sourceAsset, withDestinationURL: originalAsset)
        XCTAssertThrowsError(try source.data(for: attachment)) { XCTAssertEqual($0 as? InventoryError, .unsafePath) }
    }

    func testDuplicateIdentityIsRejected() throws {
        let repo = try repository()
        let item = InventoryItem(name: "Duplicate")
        let duplicate = Inventory(homes: [InventoryHome(rooms: [InventoryRoom(items: [item, item])])])
        XCTAssertThrowsError(try repo.save(duplicate)) { XCTAssertEqual($0 as? InventoryError, .duplicateIdentifier) }
    }

    func testImportLimitsAndUnsupportedMediaType() throws {
        let repo = try repository()
        XCTAssertThrowsError(try repo.importAttachment(data: Data(), originalName: "empty.png", mediaType: "image/png", kind: .photo))
        XCTAssertThrowsError(try repo.importAttachment(data: Data([1]), originalName: "file.svg", mediaType: "image/svg+xml", kind: .photo)) {
            XCTAssertEqual($0 as? InventoryError, .unsupportedMediaType("image/svg+xml"))
        }
        XCTAssertThrowsError(try repo.importAttachment(data: Data(repeating: 0, count: InventoryLimits.maxAttachmentBytes + 1), originalName: "large.png", mediaType: "image/png", kind: .photo))
        XCTAssertThrowsError(try repo.save(fixture(name: String(repeating: "x", count: InventoryLimits.maxTextBytes + 1))))
        XCTAssertEqual(try repo.load(), Inventory())
    }

    func testRepeatedRestoreIsIdempotentAndOldOriginalsSurvive() throws {
        let source = try repository("source")
        let destination = try repository("destination")
        let incomingAttachment = try importFixture(source)
        let oldAttachment = try importFixture(destination)
        let incoming = fixture(incomingAttachment)
        try destination.save(fixture(oldAttachment))
        let backup = try source.exportBackup(incoming)
        for _ in 0..<2 { XCTAssertEqual(try destination.restoreBackup(backup), incoming) }
        XCTAssertEqual(try destination.data(for: oldAttachment), Data("synthetic original".utf8))
        XCTAssertEqual(try destination.data(for: incomingAttachment), Data("synthetic original".utf8))
    }

    func testKnownGoodBackupRecoversCorruptManifest() throws {
        let repo = try repository()
        let expected = fixture(try importFixture(repo))
        try repo.save(expected)
        let backup = try repo.exportBackup(expected)
        try Data("corrupt manifest".utf8).write(to: repo.rootURL.appendingPathComponent("inventory.json"))
        XCTAssertThrowsError(try repo.load())
        XCTAssertEqual(try repo.restoreBackup(backup), expected)
        XCTAssertEqual(try repo.load(), expected)
    }

    func testReadOnlyStorageFailureLeavesManifestUnchanged() throws {
        let repo = try repository()
        let expected = fixture()
        try repo.save(expected)
        let backup = try repo.exportBackup(fixture(name: "New item"))
        let manifest = repo.rootURL.appendingPathComponent("inventory.json")
        let bytes = try Data(contentsOf: manifest)
        try FileManager.default.setAttributes([.posixPermissions: 0o500], ofItemAtPath: repo.rootURL.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: repo.rootURL.path) }
        XCTAssertThrowsError(try repo.restoreBackup(backup))
        XCTAssertEqual(try Data(contentsOf: manifest), bytes)
    }

    func testConcurrentRepositoryInstancesProduceCompleteManifestsAndRetainAllOriginals() throws {
        let root = temporary.appendingPathComponent("shared")
        let results = ConcurrentResults()
        DispatchQueue.concurrentPerform(iterations: 16) { index in
            do {
                let repo = try InventoryRepository(rootURL: root)
                let data = Data("Synthetic original \(index)".utf8)
                let attachment = try repo.importAttachment(data: data, originalName: "test-\(index).png", mediaType: "image/png", kind: .photo)
                let snapshot = Inventory(homes: [InventoryHome(name: "Home \(index)", rooms: [InventoryRoom(items: [
                    InventoryItem(name: "Item \(index)", attachments: [attachment])
                ])])])
                try repo.save(snapshot)
                // A concurrent save can win, but a reader always sees a complete
                // validated manifest and can always read this worker's original.
                _ = try repo.load()
                guard try repo.data(for: attachment) == data else { throw InventoryError.invalidManifest }
                results.append(attachment: attachment)
            } catch { results.append(error: error) }
        }
        XCTAssertEqual(results.errors, [])
        XCTAssertEqual(results.attachments.count, 16)
        let repo = try InventoryRepository(rootURL: root)
        XCTAssertEqual(try repo.load().homes.count, 1)
        for attachment in results.attachments { XCTAssertNoThrow(try repo.data(for: attachment)) }
    }
}

private final class ConcurrentResults: @unchecked Sendable {
    private let lock = NSLock()
    private var storedErrors: [String] = []
    private var storedAttachments: [InventoryAttachment] = []
    var errors: [String] { lock.withLock { storedErrors } }
    var attachments: [InventoryAttachment] { lock.withLock { storedAttachments } }
    func append(error: Error) { lock.withLock { storedErrors.append(String(describing: error)) } }
    func append(attachment: InventoryAttachment) { lock.withLock { storedAttachments.append(attachment) } }
}
