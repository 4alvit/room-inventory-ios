import Foundation

/// A bounded, uncompressed ZIP writer. Filenames are UTF-8 relative paths.
/// No archives are read or extracted by this type.
public enum StoredZIP {
    public struct Entry: Sendable {
        public let path: String
        public let data: Data
        public init(path: String, data: Data) { self.path = path; self.data = data }
    }
    public enum ArchiveError: Error, Equatable {
        case invalidPath, duplicatePath, tooLarge
    }
    public static let maximumArchiveBytes = 128 * 1024 * 1024
    private static let crcTable: [UInt32] = (0..<256).map { value in
        var crc = UInt32(value)
        for _ in 0..<8 { crc = (crc & 1) == 1 ? (crc >> 1) ^ 0xEDB88320 : crc >> 1 }
        return crc
    }
    public static func crc32(_ data: Data) -> UInt32 {
        var crc: UInt32 = 0xFFFFFFFF
        for byte in data { crc = (crc >> 8) ^ crcTable[Int((crc ^ UInt32(byte)) & 0xFF)] }
        return crc ^ 0xFFFFFFFF
    }
    public static func encode(entries: [Entry]) throws -> Data {
        guard entries.count <= Int(UInt16.max) else { throw ArchiveError.tooLarge }
        var names = Set<String>()
        var estimated = 22
        for entry in entries {
            let parts = entry.path.split(separator: "/", omittingEmptySubsequences: false)
            guard !entry.path.isEmpty, !entry.path.contains("\\"), !entry.path.contains(":"),
                  !entry.path.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
                  parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }),
                  entry.path.utf8.count <= Int(UInt16.max) else { throw ArchiveError.invalidPath }
            guard names.insert(entry.path).inserted else { throw ArchiveError.duplicatePath }
            guard entry.data.count <= maximumArchiveBytes else { throw ArchiveError.tooLarge }
            estimated += entry.data.count + entry.path.utf8.count * 2 + 76
            guard estimated <= maximumArchiveBytes else { throw ArchiveError.tooLarge }
        }
        var out = Data(), central = Data()
        out.reserveCapacity(estimated)
        for entry in entries {
            let filename = Data(entry.path.utf8), crc = crc32(entry.data)
            let count = UInt32(entry.data.count), offset = UInt32(out.count)
            out.appendLE(UInt32(0x04034B50)); out.appendLE(UInt16(20))
            out.appendLE(UInt16(0x0800)); out.appendLE(UInt16(0)) // UTF-8, stored
            out.appendLE(UInt16(0)); out.appendLE(UInt16(33)) // deterministic 1980-01-01
            out.appendLE(crc); out.appendLE(count); out.appendLE(count)
            out.appendLE(UInt16(filename.count)); out.appendLE(UInt16(0))
            out.append(filename); out.append(entry.data)
            central.appendLE(UInt32(0x02014B50)); central.appendLE(UInt16(20)); central.appendLE(UInt16(20))
            central.appendLE(UInt16(0x0800)); central.appendLE(UInt16(0))
            central.appendLE(UInt16(0)); central.appendLE(UInt16(33))
            central.appendLE(crc); central.appendLE(count); central.appendLE(count)
            central.appendLE(UInt16(filename.count)); central.appendLE(UInt16(0)); central.appendLE(UInt16(0))
            central.appendLE(UInt16(0)); central.appendLE(UInt16(0)); central.appendLE(UInt32(0)); central.appendLE(offset)
            central.append(filename)
        }
        let start = UInt32(out.count)
        out.append(central)
        out.appendLE(UInt32(0x06054B50)); out.appendLE(UInt16(0)); out.appendLE(UInt16(0))
        out.appendLE(UInt16(entries.count)); out.appendLE(UInt16(entries.count))
        out.appendLE(UInt32(central.count)); out.appendLE(start); out.appendLE(UInt16(0))
        return out
    }
}

private extension Data {
    mutating func appendLE<T: FixedWidthInteger>(_ value: T) {
        var little = value.littleEndian
        Swift.withUnsafeBytes(of: &little) { append(contentsOf: $0) }
    }
}
