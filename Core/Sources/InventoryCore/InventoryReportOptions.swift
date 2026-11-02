import Foundation

/// A report-only projection. Applying options never changes the saved inventory.
public struct InventoryReportOptions: Equatable, Sendable {
    public var roomIDs: Set<UUID>
    public var includeSerialNumbers = true
    public var includePurchaseDetails = true
    public var includeNotes = true
    public var includeAttachmentList = true

    public init(roomIDs: Set<UUID>) { self.roomIDs = roomIDs }

    public func applying(to inventory: Inventory) -> Inventory {
        var result = inventory
        result.homes = inventory.homes.compactMap { home in
            var selected = home
            selected.rooms = home.rooms.filter { roomIDs.contains($0.id) }.map { room in
                var selectedRoom = room
                selectedRoom.items = room.items.map { item in
                    var copy = item
                    if !includeSerialNumbers { copy.serialNumber = "" }
                    if !includePurchaseDetails { copy.purchasePrice = ""; copy.purchaseDate = "" }
                    if !includeNotes { copy.notes = "" }
                    if !includeAttachmentList { copy.attachments = [] }
                    return copy
                }
                return selectedRoom
            }
            return selected.rooms.isEmpty ? nil : selected
        }
        return result
    }
}
