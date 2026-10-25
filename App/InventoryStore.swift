import Foundation
import Observation
import InventoryCore

private actor InventoryDisk {
    let repository: InventoryRepository
    init(repository: InventoryRepository) { self.repository = repository }
    func load() throws -> Inventory { try repository.load() }
    func save(_ value: Inventory) throws { try repository.save(value) }
    func attach(data: Data, originalName: String, mediaType: String, kind: AttachmentKind,
                to inventory: Inventory, itemID: UUID) throws -> (inventory: Inventory, attachment: InventoryAttachment) {
        try repository.appendAttachment(data: data, originalName: originalName, mediaType: mediaType, kind: kind,
                                        to: inventory, itemID: itemID)
    }
    func data(for attachment: InventoryAttachment) throws -> Data { try repository.data(for: attachment) }
    func restore(url: URL) throws -> Inventory {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size <= InventoryLimits.maxBackupBytes else { throw InventoryUIError.tooLarge }
        return try repository.restoreBackup(Data(contentsOf: url, options: .mappedIfSafe))
    }
}

enum InventoryUIError: LocalizedError {
    case missingRecord, tooLarge, unavailable, invalidImage
    var errorDescription: String? {
        switch self {
        case .missingRecord: ServiceL10n.text("inventory.missingRecord")
        case .tooLarge: ServiceL10n.text("inventory.tooLarge")
        case .unavailable: ServiceL10n.text("inventory.unavailable")
        case .invalidImage: ServiceL10n.text("inventory.invalidImage")
        }
    }
}

@MainActor @Observable
final class InventoryStore {
    private(set) var inventory = Inventory()
    private(set) var isBusy = false
    private(set) var hasLoaded = false
    private(set) var repository: InventoryRepository?
    var errorMessage: String?
    var notice: String?
    private var disk: InventoryDisk?
    private let explicitRootURL: URL?

    init(rootURL: URL? = nil) {
        explicitRootURL = rootURL
        initializeRepository()
    }

    private func initializeRepository() {
        do {
            let root: URL
            if let explicitRootURL { root = explicitRootURL }
            else {
                let base = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
                root = base.appendingPathComponent("RoomInventory", isDirectory: true)
            }
            let repository = try InventoryRepository(rootURL: root)
            self.repository = repository
            self.disk = InventoryDisk(repository: repository)
        } catch { errorMessage = error.localizedDescription }
    }

    var roomCount: Int { inventory.homes.reduce(0) { $0 + $1.rooms.count } }
    var itemCount: Int { inventory.homes.reduce(0) { $0 + $1.rooms.reduce(0) { $0 + $1.items.count } } }
    func home(_ id: UUID) -> InventoryHome? { inventory.homes.first { $0.id == id } }
    func room(homeID: UUID, roomID: UUID) -> InventoryRoom? { home(homeID)?.rooms.first { $0.id == roomID } }
    func item(homeID: UUID, roomID: UUID, itemID: UUID) -> InventoryItem? { room(homeID: homeID, roomID: roomID)?.items.first { $0.id == itemID } }
    func canAddRoom(isPro: Bool) -> Bool { isPro || roomCount < 1 }
    func canAddItem(isPro: Bool) -> Bool { isPro || itemCount < 10 }

    func load() async {
        guard !isBusy, !hasLoaded else { return }
        if disk == nil { initializeRepository() }
        guard let disk else { errorMessage = InventoryUIError.unavailable.localizedDescription; return }
        isBusy = true
        defer { isBusy = false }
        do { inventory = try await disk.load(); hasLoaded = true }
        catch { errorMessage = error.localizedDescription }
    }

    @discardableResult
    private func commit(_ next: Inventory) async -> Bool {
        guard !isBusy, hasLoaded, let disk else { return false }
        isBusy = true
        defer { isBusy = false }
        do { try await disk.save(next); inventory = next; return true }
        catch { errorMessage = error.localizedDescription; return false }
    }

    @discardableResult
    func addHome(name: String) async -> Bool {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return false }
        var next = inventory
        next.homes.append(InventoryHome(name: name))
        return await commit(next)
    }

    @discardableResult
    func addRoom(homeID: UUID, name: String, isPro: Bool) async -> Bool {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, canAddRoom(isPro: isPro), let h = inventory.homes.firstIndex(where: { $0.id == homeID }) else { return false }
        var next = inventory
        next.homes[h].rooms.append(InventoryRoom(name: name))
        return await commit(next)
    }

    @discardableResult
    func addItem(homeID: UUID, roomID: UUID, name: String, isPro: Bool) async -> Bool {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, canAddItem(isPro: isPro), let h = inventory.homes.firstIndex(where: { $0.id == homeID }),
              let r = inventory.homes[h].rooms.firstIndex(where: { $0.id == roomID }) else { return false }
        var next = inventory
        next.homes[h].rooms[r].items.append(InventoryItem(name: name))
        return await commit(next)
    }

    @discardableResult
    func renameHome(homeID: UUID, name: String) async -> Bool {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, let h = inventory.homes.firstIndex(where: { $0.id == homeID }) else { return false }
        var next = inventory
        next.homes[h].name = name
        return await commit(next)
    }

    @discardableResult
    func renameRoom(homeID: UUID, roomID: UUID, name: String) async -> Bool {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, let h = inventory.homes.firstIndex(where: { $0.id == homeID }),
              let r = inventory.homes[h].rooms.firstIndex(where: { $0.id == roomID }) else { return false }
        var next = inventory
        next.homes[h].rooms[r].name = name
        return await commit(next)
    }

    func deleteHome(homeID: UUID) async {
        var next = inventory
        next.homes.removeAll { $0.id == homeID }
        await commit(next)
    }

    func deleteRoom(homeID: UUID, roomID: UUID) async {
        guard let h = inventory.homes.firstIndex(where: { $0.id == homeID }) else { return }
        var next = inventory
        next.homes[h].rooms.removeAll { $0.id == roomID }
        await commit(next)
    }

    @discardableResult
    func updateItem(homeID: UUID, roomID: UUID, item: InventoryItem) async -> Bool {
        guard let h = inventory.homes.firstIndex(where: { $0.id == homeID }),
              let r = inventory.homes[h].rooms.firstIndex(where: { $0.id == roomID }),
              let i = inventory.homes[h].rooms[r].items.firstIndex(where: { $0.id == item.id }) else {
            errorMessage = InventoryUIError.missingRecord.localizedDescription; return false
        }
        var next = inventory
        var updated = item
        updated.name = updated.name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !updated.name.isEmpty else { return false }
        // An editor draft must never replace attachments saved while it was open.
        updated.attachments = next.homes[h].rooms[r].items[i].attachments
        next.homes[h].rooms[r].items[i] = updated
        return await commit(next)
    }

    func deleteItem(homeID: UUID, roomID: UUID, itemID: UUID) async {
        guard let h = inventory.homes.firstIndex(where: { $0.id == homeID }),
              let r = inventory.homes[h].rooms.firstIndex(where: { $0.id == roomID }) else { return }
        var next = inventory
        next.homes[h].rooms[r].items.removeAll { $0.id == itemID }
        await commit(next)
    }

    func addAttachment(homeID: UUID, roomID: UUID, itemID: UUID, data: Data, originalName: String, mediaType: String, kind: AttachmentKind) async -> InventoryAttachment? {
        guard !isBusy, hasLoaded, let disk else { return nil }
        guard data.count <= 20_000_000 else { errorMessage = InventoryUIError.tooLarge.localizedDescription; return nil }
        guard let h = inventory.homes.firstIndex(where: { $0.id == homeID }),
              let r = inventory.homes[h].rooms.firstIndex(where: { $0.id == roomID }),
              inventory.homes[h].rooms[r].items.contains(where: { $0.id == itemID }) else {
            errorMessage = InventoryUIError.missingRecord.localizedDescription; return nil
        }
        isBusy = true
        defer { isBusy = false }
        do {
            let result = try await disk.attach(data: data, originalName: originalName, mediaType: mediaType, kind: kind,
                                               to: inventory, itemID: itemID)
            inventory = result.inventory
            return result.attachment
        } catch { errorMessage = error.localizedDescription; return nil }
    }

    func removeAttachment(homeID: UUID, roomID: UUID, itemID: UUID, attachmentID: UUID) async {
        guard let h = inventory.homes.firstIndex(where: { $0.id == homeID }),
              let r = inventory.homes[h].rooms.firstIndex(where: { $0.id == roomID }),
              let i = inventory.homes[h].rooms[r].items.firstIndex(where: { $0.id == itemID }) else { return }
        var next = inventory
        next.homes[h].rooms[r].items[i].attachments.removeAll { $0.id == attachmentID }
        await commit(next)
    }

    func attachmentData(_ attachment: InventoryAttachment) async throws -> Data {
        guard let disk else { throw InventoryUIError.unavailable }
        return try await disk.data(for: attachment)
    }

    func restore(url: URL) async {
        guard !isBusy, let disk else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            inventory = try await disk.restore(url: url)
            hasLoaded = true
            notice = ServiceL10n.text("inventory.restored")
        } catch { errorMessage = ServiceL10n.format("inventory.restoreFailed", arguments: [error.localizedDescription]) }
    }
}

extension InventoryItem {
    var missingMaterials: [String] {
        var result: [String] = []
        if !attachments.contains(where: { $0.kind == .photo }) { result.append(ServiceL10n.text("missing.photo")) }
        if !attachments.contains(where: { $0.kind == .label }) { result.append(ServiceL10n.text("missing.label")) }
        if !attachments.contains(where: { $0.kind == .receipt }) { result.append(ServiceL10n.text("missing.receipt")) }
        if model.isEmpty { result.append(ServiceL10n.text("missing.model")) }
        if serialNumber.isEmpty { result.append(ServiceL10n.text("missing.serial")) }
        if purchasePrice.isEmpty { result.append(ServiceL10n.text("missing.price")) }
        if purchaseDate.isEmpty { result.append(ServiceL10n.text("missing.date")) }
        return result
    }
}

extension AttachmentKind {
    var title: String {
        switch self { case .photo: ServiceL10n.text("attachment.photo"); case .label: ServiceL10n.text("attachment.label"); case .receipt: ServiceL10n.text("attachment.receipt") }
    }
    var symbol: String {
        switch self { case .photo: "photo"; case .label: "barcode.viewfinder"; case .receipt: "receipt" }
    }
}
