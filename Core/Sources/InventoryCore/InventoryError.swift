import Foundation

/// Resource limits apply to both ordinary saves and untrusted backup imports.
public enum InventoryLimits {
    public static let maxAttachmentBytes = 25 * 1_024 * 1_024
    public static let maxTotalAttachmentBytes = 80 * 1_024 * 1_024
    public static let maxManifestBytes = 4 * 1_024 * 1_024
    public static let maxBackupBytes = 128 * 1_024 * 1_024
    public static let maxTextBytes = 64 * 1_024
    public static let maxHomes = 100
    public static let maxRooms = 1_000
    public static let maxItems = 10_000
    public static let maxAttachments = 5_000
}

public enum InventoryError: Error, Equatable, Sendable, LocalizedError {
    case unsupportedSchema(Int)
    case invalidManifest
    case invalidBackup
    case limitExceeded(String)
    case duplicateIdentifier
    case unsafePath
    case unsupportedMediaType(String)
    case missingItem
    case missingAttachment(String)
    case checksumMismatch(String)
    case attachmentConflict(String)
    case storage(String)

    public var errorDescription: String? { localizedDescription() }

    public func localizedDescription(language: String? = nil, locale: Locale = .current) -> String {
        func text(_ key: String) -> String {
            InventoryLocalization.text(key, table: "Core", bundle: .module, language: language)
        }
        func format(_ key: String, _ arguments: CVarArg...) -> String {
            InventoryLocalization.format(key, arguments: arguments, table: "Core", bundle: .module, language: language, locale: locale)
        }
        switch self {
        case .unsupportedSchema(let version):
            return format("error.unsupportedSchema", InventoryLocalization.number(version, locale: locale))
        case .invalidManifest: return text("error.invalidManifest")
        case .invalidBackup: return text("error.invalidBackup")
        case .limitExceeded(let limit):
            return format("error.limitExceeded", localizedLimit(limit, language: language, locale: locale))
        case .duplicateIdentifier: return text("error.duplicateIdentifier")
        case .unsafePath: return text("error.unsafePath")
        case .unsupportedMediaType(let type): return format("error.unsupportedMediaType", type)
        case .missingItem: return text("error.missingItem")
        case .missingAttachment(let name): return format("error.missingAttachment", name)
        case .checksumMismatch(let name): return format("error.checksumMismatch", name)
        case .attachmentConflict(let name): return format("error.attachmentConflict", name)
        case .storage(let operation):
            return format("error.storage", localizedOperation(operation, language: language))
        }
    }

    private func localizedLimit(_ value: String, language: String?, locale: Locale) -> String {
        let limits: [String: (String, Int)] = [
            "128 MiB per backup": ("limit.backup", 128),
            "4 MiB of inventory text": ("limit.manifest", 4),
            "100 homes": ("limit.homes", 100),
            "1,000 rooms": ("limit.rooms", 1_000),
            "10,000 items": ("limit.items", 10_000),
            "5,000 originals": ("limit.originals", 5_000),
            "64 KiB per text field": ("limit.textField", 64),
            "25 MiB per original": ("limit.original", 25),
            "80 MiB of originals per inventory": ("limit.allOriginals", 80),
            "16 MiB per CSV export": ("limit.csv", 16)
        ]
        if let (key, count) = limits[value] {
            return InventoryLocalization.format(key, arguments: [InventoryLocalization.number(count, locale: locale)], table: "Core", bundle: .module, language: language, locale: locale)
        }
        if value == "originals must not be empty" {
            return InventoryLocalization.text("limit.emptyOriginal", table: "Core", bundle: .module, language: language)
        }
        let suffix = " MiB per stored file"
        if value.hasSuffix(suffix), let count = Int(value.dropLast(suffix.count)) {
            return InventoryLocalization.format("limit.storedFile", arguments: [InventoryLocalization.number(count, locale: locale)], table: "Core", bundle: .module, language: language, locale: locale)
        }
        // Associated values remain compatible. Unknown details belong to the caller.
        return value
    }

    private func localizedOperation(_ value: String, language: String?) -> String {
        let operations = [
            "installing restored originals": "operation.installingRestoredOriginals",
            "committing restored inventory": "operation.committingRestoredInventory",
            "checking a restored original name": "operation.checkingRestoredName",
            "allocating a restored original name": "operation.allocatingRestoredName",
            "opening the inventory lock": "operation.openingLock",
            "locking the inventory": "operation.locking",
            "creating the inventory folder": "operation.creatingFolder",
            "checking the inventory file": "operation.checkingFile",
            "reading an inventory file": "operation.readingFile",
            "creating an inventory file": "operation.creatingFile",
            "writing an inventory file": "operation.writingFile",
            "saving an inventory file": "operation.savingFile",
            "committing the inventory": "operation.committingInventory"
        ]
        guard let key = operations[value] else { return value }
        return InventoryLocalization.text(key, table: "Core", bundle: .module, language: language)
    }
}
