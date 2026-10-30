import Foundation
import Vision
import ImageIO
import InventoryCore

enum OCRField: String, CaseIterable, Identifiable, Sendable {
    case model, serialNumber, purchasePrice, purchaseDate
    var id: String { rawValue }
    var title: String {
        switch self { case .model: ExportL10n().text("model"); case .serialNumber: ExportL10n().text("serial"); case .purchasePrice: ExportL10n().text("price"); case .purchaseDate: ExportL10n().text("date") }
    }
}

struct OCRSuggestion: Identifiable, Sendable {
    let field: OCRField
    var value: String
    var isSelected = false
    var id: String { field.rawValue }
}

struct OCRResult: Identifiable, Sendable {
    let id = UUID()
    let text: String
    var suggestions: [OCRSuggestion]
}

enum OCRService {
    static func recognize(_ data: Data) async throws -> OCRResult {
        try await Task.detached(priority: .userInitiated) {
            let cgImage = try ImageInput.thumbnail(data, maxDimension: 3000)
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = false
            request.automaticallyDetectsLanguage = true
            request.recognitionLanguages = recognitionLanguages(supported: try request.supportedRecognitionLanguages())
            try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
            let text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
            return OCRResult(text: text, suggestions: candidates(in: text))
        }.value
    }

    static func recognitionLanguages(supported: [String], preferences: [String] = [InventoryLocalization.preferredLanguage()] + Locale.preferredLanguages) -> [String] {
        var ordered: [String] = []
        for preference in preferences + ["en-US"] {
            let language = Locale(identifier: preference).language.languageCode?.identifier
            if let match = supported.first(where: { $0 == preference }) ?? supported.first(where: { Locale(identifier: $0).language.languageCode?.identifier == language }), !ordered.contains(match) {
                ordered.append(match)
            }
        }
        return ordered
    }

    static func candidates(in text: String) -> [OCRSuggestion] {
        func first(_ pattern: String, truncate: Bool = true) -> String? {
            guard let expression = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive, .anchorsMatchLines]),
                  let match = expression.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
                  let range = Range(match.range(at: 1), in: text) else { return nil }
            let value = text[range].trimmingCharacters(in: .whitespacesAndNewlines)
            guard !value.isEmpty, truncate || value.count <= 160 else { return nil }
            return truncate ? String(value.prefix(160)) : value
        }
        var values: [OCRField: String] = [:]
        values[.model] = first(#"^[ \t\u00A0\u202F]*(?:model(?:[ \t\u00A0\u202F]*(?:number|no\.?))?|mdl|модель)\b[ \t\u00A0\u202F]*[:#\-]?[ \t\u00A0\u202F]*([\p{L}\p{N}][^\r\n]*)$"#)
        values[.serialNumber] = first(#"^[ \t\u00A0\u202F]*(?:serial(?:[ \t\u00A0\u202F]*(?:number|no\.?))?|s/?n|серийный[ \t\u00A0\u202F]+номер|сер[ \t\u00A0\u202F]*\.[ \t\u00A0\u202F]*номер)\b[ \t\u00A0\u202F]*[:#\-]?[ \t\u00A0\u202F]*([\p{L}\p{N}][^\r\n]*)$"#)
        // Require a complete amount line so malformed grouping or extra decimal
        // digits cannot become a plausible but incorrect shorter suggestion.
        let amount = #"(?:[0-9]{1,3}(?:,[0-9]{3})+\.[0-9]{2}|[0-9]{1,3}(?:\.[0-9]{3})+,[0-9]{2}|[0-9]{1,3}(?:[ \u00A0\u202F][0-9]{3})+,[0-9]{2}|[0-9]+[.,][0-9]{2})"#
        values[.purchasePrice] = first(
            #"^[ \t\u00A0\u202F]*(?:grand[ \t\u00A0\u202F]+total|amount[ \t\u00A0\u202F]+paid|total|итого|всего|сумма)\b[ \t\u00A0\u202F]*:?[ \t\u00A0\u202F]*((?:[$€£₽]|USD|EUR|GBP|RUB)?[ \t\u00A0\u202F]*"#
                + amount + #"(?:[ \t\u00A0\u202F]*(?:USD|EUR|GBP|RUB|₽))?)[ \t\u00A0\u202F]*$"#,
            truncate: false
        )
        if let iso = first(#"\b(20[0-9]{2}-[0-9]{2}-[0-9]{2})\b"#), InventoryDisplay.civilDate(iso) != nil {
            values[.purchaseDate] = iso
        } else if let local = first(#"^[ \t\u00A0\u202F]*дата(?:[ \t\u00A0\u202F]+покупки)?[ \t\u00A0\u202F]*:?[ \t\u00A0\u202F]*([0-9]{2}\.[0-9]{2}\.20[0-9]{2})[ \t\u00A0\u202F]*$"#) {
            // A labelled Russian date has an explicit day-month-year convention.
            // Slash dates and unlabeled numeric dates remain untouched.
            let parts = local.split(separator: ".")
            let iso = "\(parts[2])-\(parts[1])-\(parts[0])"
            if InventoryDisplay.civilDate(iso) != nil { values[.purchaseDate] = iso }
        }
        return OCRField.allCases.compactMap { field in values[field].map { OCRSuggestion(field: field, value: $0) } }
    }
}
