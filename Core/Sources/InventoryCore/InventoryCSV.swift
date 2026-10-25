import Foundation

public enum InventoryCSV {
    public static let maximumOutputBytes = 16 * 1_024 * 1_024

    /// UTF-8 CSV with CRLF rows. Each item has one row per original, or one blank
    /// attachment row. Relative `originals/<item UUID>/…` paths match the ZIP
    /// export package, independently of the repository's private storage layout.
    /// Throws before exceeding 16 MiB, including escaping and line terminators.
    public static func render(_ inventory: Inventory) throws -> String {
        try render(inventory, headings: headers, kindLabel: { $0.rawValue })
    }

    /// Human-readable companion export. User values, IDs, paths and stored dates
    /// remain verbatim; only column headings and attachment kind captions change.
    public static func renderLocalized(_ inventory: Inventory, language: String? = nil, locale: Locale = .current) throws -> String {
        let headings = headers.map { InventoryLocalization.text("csv." + $0, table: "Core", bundle: .module, language: language) }
        return try render(inventory, headings: headings, kindLabel: {
            InventoryLocalization.text("kind." + $0.rawValue, table: "Core", bundle: .module, language: language)
        })
    }

    private static let headers = [
            "home_id", "home", "room_id", "room", "item_id", "item", "model", "serial_number",
            "purchase_price", "purchase_date", "notes", "attachment_id", "attachment_kind",
            "attachment_path", "original_name", "media_type", "sha256"
    ]

    private static func render(_ inventory: Inventory, headings: [String], kindLabel: (AttachmentKind) -> String) throws -> String {
        var writer = Writer()
        try writer.appendRow(headings)
        for home in inventory.homes {
            for room in home.rooms {
                for item in room.items {
                    let common = [
                        home.id.uuidString, home.name, room.id.uuidString, room.name, item.id.uuidString,
                        item.name, item.model, item.serialNumber, item.purchasePrice, item.purchaseDate, item.notes
                    ]
                    if item.attachments.isEmpty {
                        try writer.appendRow(common + Array(repeating: "", count: 6))
                    } else {
                        for attachment in item.attachments {
                            try writer.appendRow(common + [
                                attachment.id.uuidString, kindLabel(attachment.kind), "originals/\(item.id.uuidString)/\(attachment.fileName)",
                                attachment.originalName, attachment.mediaType, attachment.sha256
                            ])
                        }
                    }
                }
            }
        }
        return writer.output
    }

    private static func needsFormulaPrefix(_ value: String) -> Bool {
        // Spreadsheet importers can ignore leading whitespace/control characters
        // before recognizing a formula. Prefix at the very beginning, before quoting.
        let significant = value.unicodeScalars.drop(while: {
            CharacterSet.whitespacesAndNewlines.contains($0) || CharacterSet.controlCharacters.contains($0)
                || $0.value == 0xFEFF
        })
        let startsWithFormula = significant.first.map { "=+-@".unicodeScalars.contains($0) } ?? false
        let startsWithControl = value.unicodeScalars.first.map { CharacterSet.controlCharacters.contains($0) } ?? false
        return startsWithFormula || startsWithControl
    }

    private struct Writer {
        private(set) var output = ""
        private var byteCount = 0

        mutating func appendRow(_ values: [String]) throws {
            for (index, value) in values.enumerated() {
                if index > 0 { try appendLiteral(",") }
                try appendEscaped(value)
            }
            try appendLiteral("\r\n")
        }

        private mutating func appendLiteral(_ value: String) throws {
            let count = value.utf8.count
            try requireCapacity(count)
            output.append(value)
            byteCount += count
        }

        private mutating func appendEscaped(_ value: String) throws {
            // Reject even a single oversized field before allocating its escaped
            // copy. Counting raw bytes first also bounds the arithmetic below.
            let rawBytes = value.utf8.count
            try requireCapacity(rawBytes)
            let prefix = needsFormulaPrefix(value)
            let quoteCount = value.utf8.reduce(into: 0) { count, byte in
                if byte == 0x22 { count += 1 }
            }
            let escapedBytes = rawBytes + quoteCount + 2 + (prefix ? 1 : 0)
            try requireCapacity(escapedBytes)
            output.append("\"")
            if prefix { output.append("'") }
            output.append(value.replacingOccurrences(of: "\"", with: "\"\""))
            output.append("\"")
            byteCount += escapedBytes
        }

        private func requireCapacity(_ additionalBytes: Int) throws {
            guard additionalBytes <= maximumOutputBytes - byteCount else {
                throw InventoryError.limitExceeded("16 MiB per CSV export")
            }
        }
    }
}
