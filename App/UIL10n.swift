import Foundation
import InventoryCore

/// UI language follows the app's supported preferred language; numeric formats
/// follow the device region independently. Never pass user content as a key.
enum UIL10n {
    static func text(_ key: String) -> String {
        InventoryLocalization.text(key, table: "UI", bundle: .main)
    }

    static func format(_ key: String, _ arguments: CVarArg...) -> String {
        InventoryLocalization.format(key, arguments: arguments, table: "UI", bundle: .main, locale: .current)
    }

    static func number(_ value: Int) -> String {
        let formatter = NumberFormatter()
        formatter.locale = .current
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: value)) ?? String(value)
    }

    static func count(_ key: String, _ count: Int) -> String {
        InventoryLocalization.plural(key, count: count, table: "UI", bundle: .main, locale: .current)
    }
}
