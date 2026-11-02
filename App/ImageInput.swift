import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import CoreTransferable

enum ImageInputError: Error, Equatable, LocalizedError {
    case fileTooLarge, unsupportedType, invalidMetadata, dimensionsTooLarge, cannotDecode

    var errorDescription: String? {
        switch self {
        case .fileTooLarge: ServiceL10n.text("image.tooLarge")
        case .unsupportedType: ServiceL10n.text("image.unsupported")
        case .invalidMetadata: ServiceL10n.text("image.invalidMetadata")
        case .dimensionsTooLarge: ServiceL10n.text("image.dimensionsTooLarge")
        case .cannotDecode: ServiceL10n.text("image.cannotDecode")
        }
    }
}

/// Bounds compressed inputs before asking ImageIO to decode any pixels.
/// This also applies to originals supplied by a restored backup.
enum ImageInput {
    static let maximumBytes = 20_000_000
    static let maximumDimension = 16_384
    static let maximumPixels = 64_000_000

    struct Metadata: Equatable, Sendable {
        let width: Int
        let height: Int
        let mediaType: String
        let fileExtension: String
    }

    /// Photos must provide a file, not an unbounded in-memory Data representation.
    /// Read while the importing closure still owns the provider's temporary URL.
    struct TransferredImage: Transferable {
        let data: Data

        static var transferRepresentation: some TransferRepresentation {
            FileRepresentation(importedContentType: .image) { received in
                Self(data: try readFile(received.file))
            }
        }
    }

    static func readFile(_ url: URL) throws -> Data {
        try Task.checkCancellation()
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let properties = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
        guard properties.isRegularFile == true else { throw ImageInputError.invalidMetadata }
        guard (properties.fileSize ?? 0) <= maximumBytes else { throw ImageInputError.fileTooLarge }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var data = Data()
        while true {
            try Task.checkCancellation()
            guard let chunk = try handle.read(upToCount: 65_536), !chunk.isEmpty else { break }
            // Check each chunk as a provider may change the file after preflight.
            guard chunk.count <= maximumBytes - data.count else { throw ImageInputError.fileTooLarge }
            data.append(chunk)
        }
        return data
    }

    static func validateForImport(_ data: Data) async throws {
        try Task.checkCancellation()
        let worker = Task.detached(priority: .userInitiated) {
            try Task.checkCancellation()
            _ = try thumbnail(data, maxDimension: 64)
            try Task.checkCancellation()
        }
        try await withTaskCancellationHandler {
            try await worker.value
            try Task.checkCancellation()
        } onCancel: {
            worker.cancel()
        }
    }

    static func inspect(_ data: Data) throws -> Metadata {
        guard data.count <= maximumBytes else { throw ImageInputError.fileTooLarge }
        guard !data.isEmpty,
              let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              CGImageSourceGetStatus(source) == .statusComplete,
              CGImageSourceGetCount(source) > 0,
              CGImageSourceGetStatusAtIndex(source, 0) == .statusComplete else { throw ImageInputError.invalidMetadata }
        guard let typeIdentifier = CGImageSourceGetType(source),
              let type = UTType(typeIdentifier as String),
              [UTType.jpeg, .png, .heic, .heif].contains(where: { type.conforms(to: $0) }) else { throw ImageInputError.unsupportedType }
        guard let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, [kCGImageSourceShouldCache: false] as CFDictionary) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? NSNumber,
              let height = properties[kCGImagePropertyPixelHeight] as? NSNumber else { throw ImageInputError.invalidMetadata }
        let dimensions = try validateDimensions(width: width.doubleValue, height: height.doubleValue)
        return Metadata(width: dimensions.width, height: dimensions.height, mediaType: type.preferredMIMEType ?? "image/jpeg", fileExtension: type.preferredFilenameExtension ?? "jpg")
    }

    /// Validate before converting to Int or multiplying, so hostile metadata
    /// cannot overflow an integer or request an unreasonable pixel buffer.
    static func validateDimensions(width: Double, height: Double) throws -> (width: Int, height: Int) {
        guard width.isFinite, height.isFinite, width > 0, height > 0,
              width.rounded(.towardZero) == width, height.rounded(.towardZero) == height else { throw ImageInputError.invalidMetadata }
        guard width <= Double(maximumDimension), height <= Double(maximumDimension),
              width * height <= Double(maximumPixels) else { throw ImageInputError.dimensionsTooLarge }
        return (Int(width), Int(height))
    }

    static func thumbnail(_ data: Data, maxDimension: Int) throws -> CGImage {
        _ = try inspect(data)
        guard maxDimension > 0, maxDimension <= 3_000,
              let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceShouldCacheImmediately: true,
                kCGImageSourceThumbnailMaxPixelSize: maxDimension
              ] as CFDictionary) else { throw ImageInputError.cannotDecode }
        return image
    }
}
