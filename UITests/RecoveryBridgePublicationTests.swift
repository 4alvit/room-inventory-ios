import Darwin
import Foundation
import XCTest

final class RecoveryBridgePublicationTests: XCTestCase {
    private func directory() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("RecoveryBridgePublication-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
        addTeardownBlock { try FileManager.default.removeItem(at: url) }
        return url
    }

    private func metadata(_ url: URL) throws -> stat {
        var value = stat()
        let result = url.path.withCString { Darwin.lstat($0, &value) }
        guard result == 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
        return value
    }

    func testPublishesCompleteBinaryFileWithSingleLinkAndNoTemporaryName() throws {
        let root = try directory()
        let destination = root.appendingPathComponent("photos-seed.json")
        let data = Data((0..<65_536).map { UInt8(truncatingIfNeeded: $0) })
        try RecoveryBridgePublication.publish(data, at: destination, nonce: "new")
        XCTAssertEqual(try Data(contentsOf: destination), data)
        XCTAssertEqual(try metadata(destination).st_nlink, 1)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), ["photos-seed.json"])
    }

    func testExistingFileIsPreservedAndFailedRenameRemovesOnlyOwnedTemporary() throws {
        let root = try directory()
        let destination = root.appendingPathComponent("request-01.json")
        let original = Data("previous request".utf8)
        try original.write(to: destination)
        let before = try metadata(destination)
        let unrelated = root.appendingPathComponent(".unrelated.tmp")
        try Data("keep".utf8).write(to: unrelated)
        XCTAssertThrowsError(try RecoveryBridgePublication.publish(Data("replacement".utf8),
                                                                  at: destination, nonce: "new")) { error in
            XCTAssertEqual((error as NSError).domain, NSPOSIXErrorDomain)
            XCTAssertEqual((error as NSError).code, Int(EEXIST))
        }
        XCTAssertEqual(try Data(contentsOf: destination), original)
        XCTAssertEqual(try metadata(destination).st_ino, before.st_ino)
        XCTAssertEqual(try Data(contentsOf: unrelated), Data("keep".utf8))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent(".request-01.json.new.tmp").path))
    }

    func testExistingDestinationSymlinkAndItsTargetArePreserved() throws {
        let root = try directory()
        let target = root.appendingPathComponent("original")
        try Data("keep".utf8).write(to: target)
        let destination = root.appendingPathComponent("installation-request.json")
        try FileManager.default.createSymbolicLink(at: destination, withDestinationURL: target)
        XCTAssertThrowsError(try RecoveryBridgePublication.publish(Data("replacement".utf8),
                                                                  at: destination, nonce: "new")) { error in
            XCTAssertEqual((error as NSError).code, Int(EEXIST))
        }
        XCTAssertEqual(try metadata(destination).st_mode & mode_t(S_IFMT), mode_t(S_IFLNK))
        XCTAssertEqual(try Data(contentsOf: target), Data("keep".utf8))
        XCTAssertEqual(try FileManager.default.destinationOfSymbolicLink(atPath: destination.path), target.path)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent(".installation-request.json.new.tmp").path))
    }

    func testExistingTemporaryFileIsNotRemovedOrReused() throws {
        let root = try directory()
        let destination = root.appendingPathComponent("request-02.json")
        let temporary = root.appendingPathComponent(".request-02.json.same.tmp")
        try Data("another publication".utf8).write(to: temporary)
        let before = try metadata(temporary)
        XCTAssertThrowsError(try RecoveryBridgePublication.publish(Data("new request".utf8),
                                                                  at: destination, nonce: "same"))
        XCTAssertEqual(try Data(contentsOf: temporary), Data("another publication".utf8))
        XCTAssertEqual(try metadata(temporary).st_ino, before.st_ino)
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.path))
    }

    func testExistingTemporarySymlinkIsNotFollowedOrRemoved() throws {
        let root = try directory()
        let target = root.appendingPathComponent("original")
        try Data("keep".utf8).write(to: target)
        let destination = root.appendingPathComponent("photos-isolation.json")
        let temporary = root.appendingPathComponent(".photos-isolation.json.same.tmp")
        try FileManager.default.createSymbolicLink(at: temporary, withDestinationURL: target)
        XCTAssertThrowsError(try RecoveryBridgePublication.publish(Data("new receipt".utf8),
                                                                  at: destination, nonce: "same"))
        XCTAssertEqual(try metadata(temporary).st_mode & mode_t(S_IFMT), mode_t(S_IFLNK))
        XCTAssertEqual(try Data(contentsOf: target), Data("keep".utf8))
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.path))
    }

    func testDirectoryDestinationSurvivesFailedRename() throws {
        let root = try directory()
        let destination = root.appendingPathComponent("request-03.json", isDirectory: true)
        try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: false)
        let before = try metadata(destination)
        XCTAssertThrowsError(try RecoveryBridgePublication.publish(Data("new request".utf8),
                                                                  at: destination, nonce: "new"))
        XCTAssertEqual(try metadata(destination).st_mode & mode_t(S_IFMT), mode_t(S_IFDIR))
        XCTAssertEqual(try metadata(destination).st_ino, before.st_ino)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), ["request-03.json"])
    }
}
