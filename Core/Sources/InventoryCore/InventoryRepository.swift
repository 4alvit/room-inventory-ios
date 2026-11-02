import CryptoKit
import Darwin
import Foundation

/// A local, synchronous repository. Perform large operations away from the main actor.
/// All disk operations are serialized, including between instances using the same root.
/// Assets are immutable and never removed automatically, so an interrupted operation
/// cannot remove an original referenced by the last committed manifest.
public final class InventoryRepository: @unchecked Sendable {
    public let rootURL: URL
    private let lock = NSRecursiveLock()
    private var assetsURL: URL { rootURL.appendingPathComponent("assets", isDirectory: true) }
    private var manifestURL: URL { rootURL.appendingPathComponent("inventory.json") }

    public init(rootURL: URL) throws {
        guard rootURL.isFileURL else { throw InventoryError.unsafePath }
        self.rootURL = rootURL.standardizedFileURL
        try withStorageLock { }
    }

    public func load() throws -> Inventory {
        try withStorageLock {
            guard let bytes = try readFile(manifestURL, limit: InventoryLimits.maxManifestBytes) else {
                return Inventory()
            }
            let inventory = try decodeInventory(bytes)
            let attachments = try validate(inventory)
            try verifyStoredAttachments(attachments)
            return inventory
        }
    }

    public func save(_ inventory: Inventory) throws {
        try withStorageLock {
            let attachments = try validate(inventory)
            let bytes = try encodeInventory(inventory)
            try verifyStoredAttachments(attachments)
            try replaceManifest(bytes)
        }
    }

    public func importAttachment(
        data: Data, originalName: String, mediaType: String, kind: AttachmentKind
    ) throws -> InventoryAttachment {
        try withStorageLock {
            let attachment = try makeAttachment(data: data, originalName: originalName, mediaType: mediaType, kind: kind)
            try writeNewFile(data, to: assetsURL.appendingPathComponent(attachment.fileName))
            return attachment
        }
    }

    /// Commits an original and its item reference together. Failed attempts remove
    /// only their own newly created file; prior and unreferenced originals remain.
    /// The caller must serialize read/modify/save sequences for its inventory snapshot.
    public func appendAttachment(
        data: Data, originalName: String, mediaType: String, kind: AttachmentKind,
        to inventory: Inventory, itemID: UUID
    ) throws -> (inventory: Inventory, attachment: InventoryAttachment) {
        try withStorageLock {
            let existing = try validate(inventory)
            var destination: (home: Int, room: Int, item: Int)?
            for h in inventory.homes.indices {
                for r in inventory.homes[h].rooms.indices {
                    if let i = inventory.homes[h].rooms[r].items.firstIndex(where: { $0.id == itemID }) {
                        destination = (h, r, i)
                    }
                }
            }
            guard let destination else { throw InventoryError.missingItem }
            let attachment = try makeAttachment(data: data, originalName: originalName, mediaType: mediaType, kind: kind)
            var next = inventory
            next.homes[destination.home].rooms[destination.room].items[destination.item].attachments.append(attachment)
            _ = try validate(next)
            let manifest = try encodeInventory(next)
            // Check every prior original and the aggregate limit before creating a file.
            var total = data.count
            for previous in existing {
                total += try readAttachment(previous).count
                try validateTotalSize(total)
            }
            let asset = assetsURL.appendingPathComponent(attachment.fileName)
            // O_EXCL means this call owns the path only after creation succeeds.
            try writeNewFile(data, to: asset)
            do {
                try replaceManifest(manifest)
            } catch {
                try? FileManager.default.removeItem(at: asset)
                syncDirectory(assetsURL)
                throw error
            }
            // No throwing operations after the atomic manifest commit.
            return (next, attachment)
        }
    }

    public func data(for attachment: InventoryAttachment) throws -> Data {
        try withStorageLock { try readAttachment(attachment) }
    }

    public func exportBackup(_ inventory: Inventory) throws -> Data {
        try withStorageLock {
            let attachments = try validate(inventory)
            _ = try encodeInventory(inventory)
            var files: [String: Data] = [:]
            var total = 0
            for attachment in attachments {
                let bytes = try readAttachment(attachment)
                total += bytes.count
                try validateTotalSize(total)
                files[attachment.fileName] = bytes
            }
            let backup = Backup(format: Self.backupFormat, version: 1, inventory: inventory, files: files)
            let bytes: Data
            do { bytes = try Self.encoder().encode(backup) }
            catch { throw InventoryError.invalidBackup }
            guard bytes.count <= InventoryLimits.maxBackupBytes else {
                throw InventoryError.limitExceeded("128 MiB per backup")
            }
            return bytes
        }
    }

    /// Fully validate and stage the backup before an atomic manifest replacement.
    /// Existing assets are retained. Failed restores leave the prior manifest intact.
    public func restoreBackup(_ data: Data) throws -> Inventory {
        try withStorageLock {
            guard data.count <= InventoryLimits.maxBackupBytes else {
                throw InventoryError.limitExceeded("128 MiB per backup")
            }
            let header: BackupHeader
            do { header = try JSONDecoder().decode(BackupHeader.self, from: data) }
            catch { throw InventoryError.invalidBackup }
            guard header.format == Self.backupFormat else { throw InventoryError.invalidBackup }
            guard header.version == 1 else { throw InventoryError.unsupportedSchema(header.version) }
            // Check the embedded schema before decoding fields from a future version.
            guard header.inventory.schemaVersion == 1 else {
                throw InventoryError.unsupportedSchema(header.inventory.schemaVersion)
            }
            let backup: Backup
            do { backup = try JSONDecoder().decode(Backup.self, from: data) }
            catch { throw InventoryError.invalidBackup }
            let attachments = try validate(backup.inventory)
            _ = try encodeInventory(backup.inventory)
            let expectedNames = Set(attachments.map(\.fileName))
            guard Set(backup.files.keys) == expectedNames else { throw InventoryError.invalidBackup }
            var total = 0
            var collisions = Set<UUID>()
            for attachment in attachments {
                guard let bytes = backup.files[attachment.fileName] else { throw InventoryError.invalidBackup }
                try validateAttachmentSize(bytes.count)
                total += bytes.count
                try validateTotalSize(total)
                guard checksum(bytes) == attachment.sha256 else {
                    throw InventoryError.checksumMismatch(attachment.fileName)
                }
                // A damaged current original must not prevent recovery from a
                // known-good backup. Preserve its bytes and give the restored
                // original a fresh identity instead of overwriting that file.
                do {
                    if let existing = try readFile(
                        assetsURL.appendingPathComponent(attachment.fileName),
                        limit: InventoryLimits.maxAttachmentBytes
                    ), checksum(existing) != attachment.sha256 {
                        collisions.insert(attachment.id)
                    }
                } catch InventoryError.limitExceeded {
                    // readFile already established a regular, non-symlink file.
                    // Oversized damaged bytes need not be loaded to preserve them.
                    collisions.insert(attachment.id)
                }
            }

            var restored = backup.inventory
            var files = backup.files
            var reservedIDs = Set(attachments.map(\.id))
            for home in restored.homes {
                reservedIDs.insert(home.id)
                for room in home.rooms {
                    reservedIDs.insert(room.id)
                    for item in room.items { reservedIDs.insert(item.id) }
                }
            }
            for h in restored.homes.indices {
                for r in restored.homes[h].rooms.indices {
                    for i in restored.homes[h].rooms[r].items.indices {
                        for a in restored.homes[h].rooms[r].items[i].attachments.indices {
                            var attachment = restored.homes[h].rooms[r].items[i].attachments[a]
                            guard collisions.contains(attachment.id) else { continue }
                            let oldName = attachment.fileName
                            let identity = try unusedAttachmentIdentity(
                                mediaType: attachment.mediaType, excluding: &reservedIDs
                            )
                            attachment.id = identity.id
                            attachment.fileName = identity.fileName
                            restored.homes[h].rooms[r].items[i].attachments[a] = attachment
                            files[attachment.fileName] = files.removeValue(forKey: oldName)
                        }
                    }
                }
            }
            let restoredAttachments = try validate(restored)
            let manifest = try encodeInventory(restored)

            let staging = rootURL.appendingPathComponent(".restore-\(UUID().uuidString)", isDirectory: true)
            try createPrivateDirectory(staging)
            defer { try? FileManager.default.removeItem(at: staging) }
            for attachment in restoredAttachments {
                try writeNewFile(files[attachment.fileName]!, to: staging.appendingPathComponent(attachment.fileName))
            }
            let stagedManifest = staging.appendingPathComponent("inventory.json")
            try writeNewFile(manifest, to: stagedManifest)

            var promoted: [URL] = []
            do {
                for attachment in restoredAttachments {
                    let destination = assetsURL.appendingPathComponent(attachment.fileName)
                    // The storage lock prevents other repository instances from writing
                    // during promotion. link() itself also refuses to overwrite a file.
                    let source = staging.appendingPathComponent(attachment.fileName)
                    if Darwin.link(source.path, destination.path) == 0 {
                        promoted.append(destination)
                    } else if errno != EEXIST {
                        throw InventoryError.storage("installing restored originals")
                    } else {
                        _ = try readAttachment(attachment)
                    }
                }
                // Flush the directory entries before making the manifest refer to them.
                syncDirectory(assetsURL)
                try ensureRegularFileIfPresent(manifestURL)
                guard Darwin.rename(stagedManifest.path, manifestURL.path) == 0 else {
                    throw InventoryError.storage("committing restored inventory")
                }
                // No throwing operations after commit: callers must not mistake a
                // committed restore for a failure and retry it with stale UI state.
                syncDirectory(rootURL)
                return restored
            } catch {
                for url in promoted { try? FileManager.default.removeItem(at: url) }
                throw error
            }
        }
    }

    private static let backupFormat = "com.alvit.roominventory.backup"

    private struct SchemaHeader: Decodable { let schemaVersion: Int }
    private struct BackupHeader: Decodable {
        let format: String
        let version: Int
        let inventory: SchemaHeader
    }
    private struct Backup: Codable {
        let format: String
        let version: Int
        let inventory: Inventory
        let files: [String: Data]
    }

    private static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }

    private func decodeInventory(_ bytes: Data) throws -> Inventory {
        let schema: SchemaHeader
        do { schema = try JSONDecoder().decode(SchemaHeader.self, from: bytes) }
        catch { throw InventoryError.invalidManifest }
        guard schema.schemaVersion == 1 else { throw InventoryError.unsupportedSchema(schema.schemaVersion) }
        do { return try JSONDecoder().decode(Inventory.self, from: bytes) }
        catch { throw InventoryError.invalidManifest }
    }

    private func encodeInventory(_ inventory: Inventory) throws -> Data {
        let bytes: Data
        do { bytes = try Self.encoder().encode(inventory) }
        catch { throw InventoryError.invalidManifest }
        guard bytes.count <= InventoryLimits.maxManifestBytes else {
            throw InventoryError.limitExceeded("4 MiB of inventory text")
        }
        return bytes
    }

    private func validate(_ inventory: Inventory) throws -> [InventoryAttachment] {
        guard inventory.schemaVersion == 1 else { throw InventoryError.unsupportedSchema(inventory.schemaVersion) }
        guard inventory.homes.count <= InventoryLimits.maxHomes else {
            throw InventoryError.limitExceeded("100 homes")
        }
        var ids = Set<UUID>()
        var names = Set<String>()
        var attachments: [InventoryAttachment] = []
        var roomCount = 0
        var itemCount = 0
        func addID(_ id: UUID) throws {
            guard ids.insert(id).inserted else { throw InventoryError.duplicateIdentifier }
        }
        for home in inventory.homes {
            try addID(home.id)
            try validateText(home.name)
            roomCount += home.rooms.count
            guard roomCount <= InventoryLimits.maxRooms else { throw InventoryError.limitExceeded("1,000 rooms") }
            for room in home.rooms {
                try addID(room.id)
                try validateText(room.name)
                itemCount += room.items.count
                guard itemCount <= InventoryLimits.maxItems else { throw InventoryError.limitExceeded("10,000 items") }
                for item in room.items {
                    try addID(item.id)
                    for text in [item.name, item.model, item.serialNumber, item.purchasePrice, item.purchaseDate, item.notes] {
                        try validateText(text)
                    }
                    guard attachments.count + item.attachments.count <= InventoryLimits.maxAttachments else {
                        throw InventoryError.limitExceeded("5,000 originals")
                    }
                    for attachment in item.attachments {
                        try addID(attachment.id)
                        try validateAttachment(attachment)
                        guard names.insert(attachment.fileName).inserted else { throw InventoryError.duplicateIdentifier }
                        attachments.append(attachment)
                    }
                }
            }
        }
        return attachments
    }

    private func validateAttachment(_ attachment: InventoryAttachment) throws {
        let ext = try fileExtension(for: attachment.mediaType)
        guard attachment.fileName == "\(attachment.id.uuidString.lowercased()).\(ext)" else {
            throw InventoryError.unsafePath
        }
        guard attachment.sha256.utf8.count == 64,
              attachment.sha256.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else {
            throw InventoryError.checksumMismatch(attachment.fileName)
        }
        try validateText(attachment.originalName)
    }

    private func fileExtension(for type: String) throws -> String {
        switch type {
        case "image/jpeg": return "jpg"
        case "image/png": return "png"
        case "image/heic": return "heic"
        case "image/heif": return "heif"
        case "application/pdf": return "pdf"
        default: throw InventoryError.unsupportedMediaType(type)
        }
    }

    private func validateText(_ text: String) throws {
        guard text.utf8.count <= InventoryLimits.maxTextBytes else {
            throw InventoryError.limitExceeded("64 KiB per text field")
        }
    }

    private func validateAttachmentSize(_ count: Int) throws {
        guard count > 0 else { throw InventoryError.limitExceeded("originals must not be empty") }
        guard count <= InventoryLimits.maxAttachmentBytes else {
            throw InventoryError.limitExceeded("25 MiB per original")
        }
    }

    private func validateTotalSize(_ total: Int) throws {
        guard total <= InventoryLimits.maxTotalAttachmentBytes else {
            throw InventoryError.limitExceeded("80 MiB of originals per inventory")
        }
    }

    private func checksum(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func makeAttachment(
        data: Data, originalName: String, mediaType: String, kind: AttachmentKind
    ) throws -> InventoryAttachment {
        try validateAttachmentSize(data.count)
        try validateText(originalName)
        let ext = try fileExtension(for: mediaType)
        let id = UUID()
        return InventoryAttachment(
            id: id, kind: kind, fileName: "\(id.uuidString.lowercased()).\(ext)",
            originalName: originalName, mediaType: mediaType, sha256: checksum(data)
        )
    }

    private func unusedAttachmentIdentity(
        mediaType: String, excluding reservedIDs: inout Set<UUID>
    ) throws -> (id: UUID, fileName: String) {
        let ext = try fileExtension(for: mediaType)
        for _ in 0..<128 {
            let id = UUID()
            guard reservedIDs.insert(id).inserted else { continue }
            let name = "\(id.uuidString.lowercased()).\(ext)"
            var info = stat()
            if lstat(assetsURL.appendingPathComponent(name).path, &info) == 0 { continue }
            guard errno == ENOENT else { throw InventoryError.storage("checking a restored original name") }
            return (id, name)
        }
        throw InventoryError.storage("allocating a restored original name")
    }

    private func readAttachment(_ attachment: InventoryAttachment) throws -> Data {
        try validateAttachment(attachment)
        guard let bytes = try readFile(
            assetsURL.appendingPathComponent(attachment.fileName), limit: InventoryLimits.maxAttachmentBytes
        ) else { throw InventoryError.missingAttachment(attachment.fileName) }
        try validateAttachmentSize(bytes.count)
        guard checksum(bytes) == attachment.sha256 else { throw InventoryError.checksumMismatch(attachment.fileName) }
        return bytes
    }

    private func verifyStoredAttachments(_ attachments: [InventoryAttachment]) throws {
        var total = 0
        for attachment in attachments {
            total += try readAttachment(attachment).count
            try validateTotalSize(total)
        }
    }

    private func withStorageLock<T>(_ operation: () throws -> T) throws -> T {
        lock.lock()
        defer { lock.unlock() }
        try createPrivateDirectory(rootURL)
        try createPrivateDirectory(assetsURL)
        let lockURL = rootURL.appendingPathComponent(".repository.lock")
        let descriptor = Darwin.open(lockURL.path, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw InventoryError.storage("opening the inventory lock") }
        defer { Darwin.close(descriptor) }
        var info = stat()
        guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG else {
            throw InventoryError.unsafePath
        }
        while flock(descriptor, LOCK_EX) != 0 {
            if errno != EINTR { throw InventoryError.storage("locking the inventory") }
        }
        defer { flock(descriptor, LOCK_UN) }
        // Recheck after taking the cross-instance lock.
        try ensureDirectory(rootURL)
        try ensureDirectory(assetsURL)
        return try operation()
    }

    private func createPrivateDirectory(_ url: URL) throws {
        do {
            try FileManager.default.createDirectory(
                at: url, withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
        } catch { throw InventoryError.storage("creating the inventory folder") }
        try ensureDirectory(url)
    }

    private func ensureDirectory(_ url: URL) throws {
        var info = stat()
        guard lstat(url.path, &info) == 0, (info.st_mode & S_IFMT) == S_IFDIR else {
            throw InventoryError.unsafePath
        }
    }

    private func ensureRegularFileIfPresent(_ url: URL) throws {
        var info = stat()
        if lstat(url.path, &info) != 0 {
            if errno == ENOENT { return }
            throw InventoryError.storage("checking the inventory file")
        }
        guard (info.st_mode & S_IFMT) == S_IFREG else { throw InventoryError.unsafePath }
    }

    private func readFile(_ url: URL, limit: Int) throws -> Data? {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
        if descriptor < 0 {
            if errno == ENOENT { return nil }
            if errno == ELOOP { throw InventoryError.unsafePath }
            throw InventoryError.storage("reading an inventory file")
        }
        defer { Darwin.close(descriptor) }
        var info = stat()
        guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG else {
            throw InventoryError.unsafePath
        }
        guard info.st_size >= 0, info.st_size <= limit else {
            throw InventoryError.limitExceeded("\(limit / 1_024 / 1_024) MiB per stored file")
        }
        var result = Data()
        result.reserveCapacity(Int(info.st_size))
        var buffer = [UInt8](repeating: 0, count: 64 * 1_024)
        while true {
            let count = buffer.withUnsafeMutableBytes { bytes in
                Darwin.read(descriptor, bytes.baseAddress!, bytes.count)
            }
            if count < 0 {
                if errno == EINTR { continue }
                throw InventoryError.storage("reading an inventory file")
            }
            if count == 0 { return result }
            guard result.count + count <= limit else {
                throw InventoryError.limitExceeded("\(limit / 1_024 / 1_024) MiB per stored file")
            }
            result.append(buffer, count: count)
        }
    }

    private func writeNewFile(_ data: Data, to url: URL) throws {
        let descriptor = Darwin.open(url.path, O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW | O_CLOEXEC, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw InventoryError.storage("creating an inventory file") }
        var finished = false
        defer {
            Darwin.close(descriptor)
            if !finished { try? FileManager.default.removeItem(at: url) }
        }
        try data.withUnsafeBytes { buffer in
            var offset = 0
            while offset < buffer.count {
                let count = Darwin.write(descriptor, buffer.baseAddress!.advanced(by: offset), buffer.count - offset)
                if count < 0 {
                    if errno == EINTR { continue }
                    throw InventoryError.storage("writing an inventory file")
                }
                guard count > 0 else { throw InventoryError.storage("writing an inventory file") }
                offset += count
            }
        }
        guard fsync(descriptor) == 0 else { throw InventoryError.storage("saving an inventory file") }
        finished = true
    }

    private func replaceManifest(_ bytes: Data) throws {
        let temporary = rootURL.appendingPathComponent(".manifest-\(UUID().uuidString).tmp")
        try writeNewFile(bytes, to: temporary)
        defer { try? FileManager.default.removeItem(at: temporary) }
        try ensureRegularFileIfPresent(manifestURL)
        syncDirectory(assetsURL)
        guard Darwin.rename(temporary.path, manifestURL.path) == 0 else {
            throw InventoryError.storage("committing the inventory")
        }
        syncDirectory(rootURL)
    }

    private func syncDirectory(_ url: URL) {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        if descriptor >= 0 {
            _ = fsync(descriptor)
            Darwin.close(descriptor)
        }
    }
}
