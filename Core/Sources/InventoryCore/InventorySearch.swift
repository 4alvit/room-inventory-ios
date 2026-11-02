import Foundation

public struct InventorySearchResult: Equatable, Sendable, Identifiable {
    public let homeID: UUID
    public let homeName: String
    public let roomID: UUID
    public let roomName: String
    public let item: InventoryItem
    public var id: UUID { item.id }
}

extension Inventory {
    /// Search saved text on this device. All words must match the same item's
    /// details or location; results retain their original navigation identities.
    public func searchItems(_ query: String) -> [InventorySearchResult] {
        let words = query.split(whereSeparator: { $0.isWhitespace }).map(String.init)
        guard !words.isEmpty else { return [] }
        var results: [InventorySearchResult] = []
        for home in homes {
            for room in home.rooms {
                for item in room.items {
                    let fields = [item.name, item.model, item.serialNumber, item.notes, home.name, room.name]
                    let matches = words.allSatisfy { word in
                        fields.contains { field in
                            field.range(of: word, options: [.caseInsensitive, .diacriticInsensitive]) != nil
                        }
                    }
                    if matches {
                        results.append(InventorySearchResult(homeID: home.id, homeName: home.name,
                                                             roomID: room.id, roomName: room.name, item: item))
                    }
                }
            }
        }
        return results
    }
}
