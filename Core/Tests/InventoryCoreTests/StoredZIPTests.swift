import Foundation
import XCTest
@testable import InventoryCore

final class StoredZIPTests: XCTestCase {
    func testStandardCRCVector() { XCTAssertEqual(StoredZIP.crc32(Data("123456789".utf8)), 0xCBF43926) }
    func testRefusesTraversalAndAbsolutePaths() {
        for path in ["../secret", "/absolute", "a/../b", "a//b", "a\\b", "C:secret", "a\u{0}b"] {
            XCTAssertThrowsError(try StoredZIP.encode(entries: [.init(path: path, data: Data())]))
        }
    }
    func testRefusesDuplicateNames() {
        XCTAssertThrowsError(try StoredZIP.encode(entries: [.init(path: "one", data: Data()), .init(path: "one", data: Data())]))
    }
    func testEmptyArchiveAndDeterminism() throws {
        let empty = try StoredZIP.encode(entries: [])
        XCTAssertEqual(empty.count, 22)
        XCTAssertEqual(Array(empty.prefix(4)), [0x50, 0x4b, 0x05, 0x06])
        let entries = [StoredZIP.Entry(path: "originals/чек.txt", data: Data("receipt".utf8))]
        XCTAssertEqual(try StoredZIP.encode(entries: entries), try StoredZIP.encode(entries: entries))
        XCTAssertEqual(Array(try StoredZIP.encode(entries: entries).prefix(4)), [0x50, 0x4b, 0x03, 0x04])
    }
}
