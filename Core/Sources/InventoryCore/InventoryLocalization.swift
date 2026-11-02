import Foundation

/// Resolves authored text independently from the locale used to format numbers.
/// The app and package each pass their own resource bundle; user content is never a key.
public enum InventoryLocalization {
    public static let supportedLanguages = ["en", "ru"]

    public static func preferredLanguage(bundle: Bundle = .main, language: String? = nil) -> String {
        preferredLanguage(preferences: language.map { [$0] } ?? Locale.preferredLanguages, bundle: bundle)
    }

    /// The explicit preferences seam also permits tests without changing device settings.
    public static func preferredLanguage(preferences: [String], bundle: Bundle = .main) -> String {
        let available = bundle.localizations.filter { supportedLanguages.contains($0) }
        let candidates = available.isEmpty ? supportedLanguages : supportedLanguages.filter { available.contains($0) }
        return Bundle.preferredLocalizations(from: candidates, forPreferences: preferences).first
            .flatMap { supportedLanguages.contains($0) ? $0 : nil } ?? "en"
    }

    public static func text(
        _ key: String, table: String = "Localizable", bundle: Bundle = .main,
        language: String? = nil
    ) -> String {
        let selected = preferredLanguage(bundle: bundle, language: language)
        return lookup(key, table: table, bundle: bundle, language: selected)
            ?? lookup(key, table: table, bundle: bundle, language: "en") ?? key
    }

    public static func format(
        _ key: String, arguments: [CVarArg], table: String = "Localizable", bundle: Bundle = .main,
        language: String? = nil, locale: Locale = .current
    ) -> String {
        String(format: text(key, table: table, bundle: bundle, language: language), locale: locale, arguments: arguments)
    }

    /// Integer CLDR forms for the supported languages. The grammar follows the
    /// text language; only the number itself follows the user's formatting locale.
    public static func plural(
        _ key: String, count: Int, table: String = "Localizable", bundle: Bundle = .main,
        language: String? = nil, locale: Locale = .current
    ) -> String {
        let selected = preferredLanguage(bundle: bundle, language: language)
        let selectedKey = key + "." + pluralCategory(count, language: selected)
        let fallbackKey = key + "." + pluralCategory(count, language: "en")
        let template = lookup(selectedKey, table: table, bundle: bundle, language: selected)
            ?? lookup(fallbackKey, table: table, bundle: bundle, language: "en") ?? selectedKey
        return String(format: template, locale: locale, arguments: [number(count, locale: locale)])
    }

    static func number(_ value: Int, locale: Locale) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = locale
        return formatter.string(from: NSNumber(value: value)) ?? String(value)
    }

    static func pluralCategory(_ value: Int, language: String) -> String {
        let number = value.magnitude
        if language == "ru" {
            if number % 10 == 1 && number % 100 != 11 { return "one" }
            if (2...4).contains(number % 10) && !(12...14).contains(number % 100) { return "few" }
            return "many"
        }
        return number == 1 ? "one" : "other"
    }

    private static func lookup(_ key: String, table: String, bundle: Bundle, language: String) -> String? {
        guard let path = bundle.path(forResource: language, ofType: "lproj"),
              let localizedBundle = Bundle(path: path) else { return nil }
        let missing = "\u{F8FF}missing-localized-value\u{F8FF}"
        let value = localizedBundle.localizedString(forKey: key, value: missing, table: table)
        return value == missing ? nil : value
    }
}
