import Foundation

public struct Inventory: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public var homes: [InventoryHome]

    public init(schemaVersion: Int = 1, homes: [InventoryHome] = []) {
        self.schemaVersion = schemaVersion
        self.homes = homes
    }
}

public struct InventoryHome: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var name: String
    public var rooms: [InventoryRoom]

    public init(id: UUID = UUID(), name: String = "", rooms: [InventoryRoom] = []) {
        self.id = id
        self.name = name
        self.rooms = rooms
    }
}

public struct InventoryRoom: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var name: String
    public var items: [InventoryItem]

    public init(id: UUID = UUID(), name: String = "", items: [InventoryItem] = []) {
        self.id = id
        self.name = name
        self.items = items
    }
}

public struct InventoryItem: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var name: String
    public var model: String
    public var serialNumber: String
    public var purchasePrice: String
    public var purchaseDate: String
    public var notes: String
    public var attachments: [InventoryAttachment]

    public init(
        id: UUID = UUID(), name: String = "", model: String = "",
        serialNumber: String = "", purchasePrice: String = "", purchaseDate: String = "",
        notes: String = "", attachments: [InventoryAttachment] = []
    ) {
        self.id = id
        self.name = name
        self.model = model
        self.serialNumber = serialNumber
        self.purchasePrice = purchasePrice
        self.purchaseDate = purchaseDate
        self.notes = notes
        self.attachments = attachments
    }
}

public enum AttachmentKind: String, Codable, CaseIterable, Sendable {
    case photo, label, receipt
}

public struct InventoryAttachment: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var kind: AttachmentKind
    public var fileName: String
    public var originalName: String
    public var mediaType: String
    public var sha256: String

    public init(
        id: UUID = UUID(), kind: AttachmentKind = .photo, fileName: String = "",
        originalName: String = "", mediaType: String = "", sha256: String = ""
    ) {
        self.id = id
        self.kind = kind
        self.fileName = fileName
        self.originalName = originalName
        self.mediaType = mediaType
        self.sha256 = sha256
    }
}
