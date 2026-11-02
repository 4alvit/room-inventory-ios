import Foundation
import InventoryCore

struct ExportL10n: Sendable {
    let language: String
    let locale: Locale

    init(language: String? = nil, locale: Locale = .current) {
        self.language = InventoryLocalization.preferredLanguage(bundle: .main, language: language)
        self.locale = locale
    }

    func text(_ key: String) -> String {
        InventoryLocalization.text(key, table: "Export", bundle: .main, language: language)
    }

    func format(_ key: String, _ arguments: CVarArg...) -> String {
        InventoryLocalization.format(key, arguments: arguments, table: "Export", bundle: .main, language: language, locale: locale)
    }

    func number(_ value: Int) -> String {
        let formatter = NumberFormatter()
        formatter.locale = locale
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: value)) ?? String(value)
    }
}
