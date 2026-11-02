import XCTest
import CoreGraphics
import ImageIO
@testable import RoomInventory

final class ImageInputTests: XCTestCase {
    private func tinyPNG() throws -> Data {
        let provider = try XCTUnwrap(CGDataProvider(data: Data(repeating: 255, count: 24) as CFData))
        let image = try XCTUnwrap(CGImage(width: 2, height: 3, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: 8,
                                          space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                                          provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
        let data = NSMutableData()
        let destination = try XCTUnwrap(CGImageDestinationCreateWithData(data as CFMutableData, "public.png" as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        return data as Data
    }

    func testSmallSyntheticImagePassesMetadataValidationAndDecodes() throws {
        let data = try tinyPNG()
        let metadata = try ImageInput.inspect(data)
        XCTAssertEqual(metadata.width, 2)
        XCTAssertEqual(metadata.height, 3)
        XCTAssertEqual(metadata.mediaType, "image/png")
        let thumbnail = try ImageInput.thumbnail(data, maxDimension: 64)
        XCTAssertGreaterThan(thumbnail.width, 0)
        XCTAssertGreaterThan(thumbnail.height, 0)
    }

    func testInvalidAndTruncatedInputsFailBeforeThumbnailCreation() throws {
        XCTAssertThrowsError(try ImageInput.inspect(Data()))
        XCTAssertThrowsError(try ImageInput.inspect(Data("not an image".utf8)))
        let data = try tinyPNG()
        XCTAssertThrowsError(try ImageInput.inspect(Data(data.prefix(40))))
        XCTAssertThrowsError(try ImageInput.thumbnail(Data(data.prefix(40)), maxDimension: 64))
    }

    func testMetadataBoundsRejectZeroNegativeFractionalAndNonFiniteDimensions() {
        let invalid: [(Double, Double)] = [(0, 1), (1, 0), (-1, 2), (2, -1), (1.5, 2), (.infinity, 2), (2, .nan)]
        for (width, height) in invalid {
            XCTAssertThrowsError(try ImageInput.validateDimensions(width: width, height: height)) { error in
                XCTAssertEqual(error as? ImageInputError, .invalidMetadata)
            }
        }
    }

    func testDimensionAndPixelCapsDoNotNeedLargeBuffers() throws {
        XCTAssertNoThrow(try ImageInput.validateDimensions(width: 8_000, height: 8_000))
        XCTAssertNoThrow(try ImageInput.validateDimensions(width: 16_384, height: 1))
        for (width, height) in [(16_385.0, 1.0), (1.0, 16_385.0), (8_001.0, 8_000.0), (Double.greatestFiniteMagnitude, 1.0)] {
            XCTAssertThrowsError(try ImageInput.validateDimensions(width: width, height: height)) { error in
                XCTAssertEqual(error as? ImageInputError, .dimensionsTooLarge)
            }
        }
    }

    func testTinyFileClaimingHugeImageIsRejectedWithoutPixelAllocation() throws {
        var data = try tinyPNG()
        // Only patch the PNG IHDR and its CRC. The file stays under 1 KB and
        // retains its tiny compressed image; no enormous pixel buffer exists.
        data.replaceSubrange(16..<20, with: [0, 0, 0x40, 1]) // 16,385 pixels wide
        let crc = crc32(Data(data[12..<29]))
        data.replaceSubrange(29..<33, with: [UInt8((crc >> 24) & 255), UInt8((crc >> 16) & 255), UInt8((crc >> 8) & 255), UInt8(crc & 255)])
        XCTAssertLessThan(data.count, 1_024)
        XCTAssertThrowsError(try ImageInput.inspect(data))
        XCTAssertThrowsError(try ImageInput.thumbnail(data, maxDimension: 64))
    }

    func testFileImportPreservesImageBytesAndRejectsSparseOversizedFile() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let image = try tinyPNG()
        let valid = directory.appendingPathComponent("provider-image.png")
        try image.write(to: valid)
        XCTAssertEqual(try ImageInput.readFile(valid), image)

        let oversized = directory.appendingPathComponent("oversized.png")
        XCTAssertTrue(FileManager.default.createFile(atPath: oversized.path, contents: nil))
        let handle = try FileHandle(forWritingTo: oversized)
        // Sparse file: no enormous image or in-memory Data allocation.
        try handle.truncate(atOffset: UInt64(ImageInput.maximumBytes + 1))
        try handle.close()
        XCTAssertThrowsError(try ImageInput.readFile(oversized)) { error in
            XCTAssertEqual(error as? ImageInputError, .fileTooLarge)
        }
        XCTAssertThrowsError(try ImageInput.readFile(directory)) { error in
            XCTAssertEqual(error as? ImageInputError, .invalidMetadata)
        }
    }

    func testFileImportChecksCancellationBeforeOpeningFile() async {
        let missing = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let task = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return try ImageInput.readFile(missing)
        }
        do {
            _ = try await task.value
            XCTFail("Cancelled read should not succeed")
        } catch is CancellationError { }
        catch { XCTFail("Cancellation must be checked before file access: \(error)") }
    }

    func testActualImportPreparationDecodesValidImageAndRejectsTruncatedImage() async throws {
        let image = try tinyPNG()
        try await ImageInput.validateForImport(image)
        do {
            try await ImageInput.validateForImport(Data(image.prefix(40)))
            XCTFail("Truncated image reached the end of preparation")
        } catch let error as ImageInputError {
            XCTAssertEqual(error, .invalidMetadata)
        }
        let task = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            try await ImageInput.validateForImport(image)
        }
        do {
            try await task.value
            XCTFail("Cancelled preparation should not succeed")
        } catch is CancellationError { }
    }

    private func crc32(_ data: Data) -> UInt32 {
        var value: UInt32 = 0xFFFF_FFFF
        for byte in data {
            value ^= UInt32(byte)
            for _ in 0..<8 { value = (value >> 1) ^ ((value & 1) == 1 ? 0xEDB8_8320 : 0) }
        }
        return value ^ 0xFFFF_FFFF
    }
}
