import Foundation
import InventoryCore

/// Explicit table lookup also localizes strings passed through dynamic state.
enum ServiceL10n {
    static func text(_ key: String, language: String? = nil) -> String {
        InventoryLocalization.text(key, table: "Services", bundle: .main, language: language)
    }

    static func format(_ key: String, arguments: [CVarArg], language: String? = nil, locale: Locale = .current) -> String {
        InventoryLocalization.format(key, arguments: arguments, table: "Services", bundle: .main, language: language, locale: locale)
    }

    static func plural(_ key: String, count: Int, language: String? = nil, locale: Locale = .current) -> String {
        InventoryLocalization.plural(key, count: count, table: "Services", bundle: .main, language: language, locale: locale)
    }
}
