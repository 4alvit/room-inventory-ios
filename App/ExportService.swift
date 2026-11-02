import Foundation
import InventoryCore
import UIKit

enum PDFExportError: Error, Equatable, LocalizedError {
    case pageLimitExceeded

    var errorDescription: String? {
        ExportL10n().text("pdf.limit")
    }
}

enum ExportService {
    static let maximumPDFPages = 500
    private static let worker = ExportWorker()
    static func csvURL(inventory: Inventory, language: String? = nil, locale: Locale = .current) async throws -> URL {
        try await worker.csvURL(inventory: inventory, l10n: ExportL10n(language: language, locale: locale))
    }
    static func pdfURL(inventory: Inventory, language: String? = nil, locale: Locale = .current) async throws -> URL {
        try await worker.pdfURL(inventory: inventory, l10n: ExportL10n(language: language, locale: locale))
    }
    static func backupURL(inventory: Inventory, repository: InventoryRepository) async throws -> URL {
        try await worker.backupURL(inventory: inventory, repository: repository)
    }
    static func bundleURL(inventory: Inventory, repository: InventoryRepository, language: String? = nil, locale: Locale = .current) async throws -> URL {
        try await worker.bundleURL(inventory: inventory, repository: repository, l10n: ExportL10n(language: language, locale: locale))
    }
}

// Serializes the memory-heavy jobs away from the UI executor.
private actor ExportWorker {
    func csvURL(inventory: Inventory, l10n: ExportL10n) throws -> URL {
        try write(Data(try InventoryCSV.renderLocalized(inventory, language: l10n.language, locale: l10n.locale).utf8), named: "Inventory-localized.csv")
    }
    func pdfURL(inventory: Inventory, l10n: ExportL10n) throws -> URL {
        try write(try pdfData(inventory, l10n: l10n), named: "Inventory.pdf")
    }
    func backupURL(inventory: Inventory, repository: InventoryRepository) throws -> URL {
        try write(repository.exportBackup(inventory), named: "Inventory.roominventory")
    }
    func bundleURL(inventory: Inventory, repository: InventoryRepository, l10n: ExportL10n) throws -> URL {
        var entries: [StoredZIP.Entry] = [
            .init(path: "Inventory.csv", data: Data(try InventoryCSV.render(inventory).utf8)),
            .init(path: "Inventory-localized.csv", data: Data(try InventoryCSV.renderLocalized(inventory, language: l10n.language, locale: l10n.locale).utf8)),
            .init(path: "Inventory.pdf", data: try pdfData(inventory, l10n: l10n)),
            .init(path: "README.txt", data: Data(l10n.text("zip.readme").utf8))
        ]
        for home in inventory.homes { for room in home.rooms { for item in room.items {
            for attachment in item.attachments {
                entries.append(.init(path: "originals/\(item.id.uuidString)/\(attachment.fileName)", data: try repository.data(for: attachment)))
            }
        } } }
        return try write(StoredZIP.encode(entries: entries), named: "Inventory-package.zip")
    }

    private func write(_ data: Data, named name: String) throws -> URL {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("InventoryExports", isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        // Only our old export directories are eligible; never delete selected originals.
        let threshold = Date().addingTimeInterval(-86_400)
        for url in (try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: [.creationDateKey], options: [.skipsHiddenFiles])) ?? [] {
            if let date = try? url.resourceValues(forKeys: [.creationDateKey]).creationDate, date < threshold {
                try? fm.removeItem(at: url)
            }
        }
        let directory = root.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent(name)
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        return url
    }

    private func reportFont(size: CGFloat, bold: Bool = false) -> UIFont {
        // SF's PDF subset maps Cyrillic к to Latin kra (U+0138) on iOS 27.
        // Arial preserves searchable/copyable Unicode in English/Russian reports.
        UIFont(name: bold ? "Arial-BoldMT" : "ArialMT", size: size)
            ?? (bold ? UIFont.boldSystemFont(ofSize: size) : UIFont.systemFont(ofSize: size))
    }

    private func pdfData(_ inventory: Inventory, l10n: ExportL10n) throws -> Data {
        let page = CGRect(x: 0, y: 0, width: 595.2, height: 841.8)
        let renderer = UIGraphicsPDFRenderer(bounds: page)
        var renderingError: Error?
        let data = renderer.pdfData { context in
            let inset: CGFloat = 40, width = page.width - 80
            var y: CGFloat = 0, pageNumber = 0
            func newPage() throws {
                guard pageNumber < ExportService.maximumPDFPages else { throw PDFExportError.pageLimitExceeded }
                context.beginPage(); pageNumber += 1; y = 68
                ("ROOM INVENTORY" as NSString).draw(at: CGPoint(x: inset, y: 26), withAttributes: [.font: reportFont(size: 11, bold: true), .foregroundColor: UIColor.systemTeal])
                (l10n.format("pdf.footer", l10n.number(pageNumber)) as NSString).draw(at: CGPoint(x: inset, y: page.height - 28), withAttributes: [.font: reportFont(size: 9), .foregroundColor: UIColor.darkGray])
            }
            func text(_ value: String, size: CGFloat = 11, bold: Bool = false) throws {
                let font = reportFont(size: size, bold: bold)
                let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: UIColor.black]
                let leading = size * 1.45
                // Prefer word boundaries; fall back to characters for long serials and paths.
                for paragraph in value.components(separatedBy: .newlines) {
                    var line = ""
                    for character in paragraph {
                        let next = line + String(character)
                        if !line.isEmpty && (next as NSString).size(withAttributes: attrs).width > width {
                            let remainder: String
                            if let boundary = line.lastIndex(where: { $0.isWhitespace }),
                               line[..<boundary].contains(where: { !$0.isWhitespace }) {
                                remainder = String(line[line.index(after: boundary)...]) + String(character)
                                line = String(line[...boundary])
                            } else {
                                remainder = String(character)
                            }
                            if y + leading > page.height - 46 { try newPage() }
                            (line as NSString).draw(at: CGPoint(x: inset, y: y), withAttributes: attrs)
                            y += leading; line = remainder
                        } else { line = next }
                    }
                    if y + leading > page.height - 46 { try newPage() }
                    (line as NSString).draw(at: CGPoint(x: inset, y: y), withAttributes: attrs)
                    y += leading
                }
                y += 5
            }
            do {
                try newPage()
                try text(l10n.text("pdf.title"), size: 23, bold: true)
                try text(l10n.text("pdf.disclaimer"))
                for home in inventory.homes {
                    try text(home.name.isEmpty ? l10n.text("home") : home.name, size: 19, bold: true)
                    for room in home.rooms {
                        try text(room.name.isEmpty ? l10n.text("room") : room.name, size: 16, bold: true)
                        for item in room.items {
                            if y > page.height - 160 { try newPage() }
                            try text(item.name.isEmpty ? l10n.text("item") : item.name, size: 13, bold: true)
                            try text(l10n.format("item.id", item.id.uuidString), size: 8)
                            for (label, value) in [("model", item.model), ("serial", item.serialNumber), ("price", InventoryDisplay.purchasePrice(item.purchasePrice, locale: l10n.locale)), ("date", InventoryDisplay.purchaseDate(item.purchaseDate, locale: l10n.locale)), ("notes", item.notes)] where !value.isEmpty {
                                try text(l10n.format("field.value", l10n.text(label), value))
                            }
                            for attachment in item.attachments {
                                try text("\(l10n.text(attachment.kind.rawValue)): \(attachment.originalName)\noriginals/\(item.id.uuidString)/\(attachment.fileName)", size: 8)
                            }
                            y += 8
                        }
                    }
                }
                if inventory.homes.isEmpty { try text(l10n.text("empty")) }
            } catch { renderingError = error }
        }
        // The renderer closure cannot throw. Discard its partial data on failure;
        // neither the standalone PDF nor the ZIP may publish a truncated report.
        if let renderingError { throw renderingError }
        return data
    }
}
