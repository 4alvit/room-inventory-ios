import Foundation

/// Formats values for display only. Stored strings and exported machine data stay unchanged.
enum InventoryDisplay {
    static func civilDate(_ raw: String) -> Date? {
        guard raw.range(of: #"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"#, options: .regularExpression) != nil else { return nil }
        let parts = raw.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let components = DateComponents(year: parts[0], month: parts[1], day: parts[2])
        guard let date = calendar.date(from: components),
              calendar.dateComponents([.year, .month, .day], from: date) == components else { return nil }
        return date
    }

    static func purchaseDate(_ raw: String, locale: Locale = .current) -> String {
        guard let date = civilDate(raw) else { return raw }
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateStyle = .medium
        formatter.timeStyle = .none
        return formatter.string(from: date)
    }

    static func purchasePrice(_ raw: String, locale: Locale = .current) -> String {
        // A currency symbol alone can be ambiguous ($, for example). Only an explicit
        // ISO currency code and a complete, unambiguous amount can be reformatted.
        let pattern = #"^\s*(?:([A-Z]{3})\s*([0-9][0-9., \u00A0\u202F]*)|([0-9][0-9., \u00A0\u202F]*)\s*([A-Z]{3}))\s*$"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: raw, range: NSRange(raw.startIndex..., in: raw)) else { return raw }
        func group(_ n: Int) -> String? { Range(match.range(at: n), in: raw).map { String(raw[$0]) } }
        guard let code = group(1) ?? group(4), Locale.commonISOCurrencyCodes.contains(code),
              let amount = (group(2) ?? group(3))?.trimmingCharacters(in: .whitespaces),
              amount.filter(\.isNumber).count <= 15,
              amount.range(of: #"^(?:[0-9]+(?:[.,][0-9]{2})?|[0-9]{1,3}(?:,[0-9]{3})+\.[0-9]{2}|[0-9]{1,3}(?:\.[0-9]{3})+,[0-9]{2}|[0-9]{1,3}(?:[ \u00A0\u202F][0-9]{3})+,[0-9]{2})$"#, options: .regularExpression) != nil else { return raw }
        var canonical = amount.filter { !$0.isWhitespace }
        if let last = canonical.lastIndex(where: { $0 == "." || $0 == "," }) {
            let fraction = canonical[canonical.index(after: last)...]
            let integer = canonical[..<last].filter(\.isNumber)
            canonical = integer + "." + fraction
        }
        guard let value = Decimal(string: canonical, locale: Locale(identifier: "en_US_POSIX")) else { return raw }
        let formatter = NumberFormatter()
        formatter.locale = locale
        formatter.numberStyle = .currency
        formatter.currencyCode = code
        if canonical.contains(".") {
            // Preserve authored cents even for currencies whose usual display has none.
            formatter.minimumFractionDigits = max(formatter.minimumFractionDigits, 2)
            formatter.maximumFractionDigits = max(formatter.maximumFractionDigits, 2)
        }
        return formatter.string(from: value as NSDecimalNumber) ?? raw
    }
}
