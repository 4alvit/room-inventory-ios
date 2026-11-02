# Localization

Supported languages: English (`en`, development fallback) and Russian (`ru`).
`InventoryLocalization` uses native ordered language matching across all preferred
languages, with English fallback. UI text comes from the app bundle; package
errors and CSV captions come from `Bundle.module`. All `.strings` files are
compiled/copied into both Debug and Release resources. Existing user-entered
names, notes, filenames, enum keys, backup schema and StoreKit product IDs are
never translated. StoreKit prices use `Product.displayPrice` directly.

## Resources

- App `UI`: views, composed labels and accessibility text.
- App `Services`: app-authored status/errors, attachment kinds and batch limits.
- App `Export`: OCR field titles, PDF captions and ZIP README.
- App `InfoPlist`: camera permission, display name and exported type description.
- Package `Core`: storage errors and nested operations/limits, CSV headings.

Integer plural forms use explicit CLDR English/Russian rules, with overflow-safe
absolute counts. Formatted digits use the regional locale separately. This avoids
changing Russian grammar when a phone uses a US region. Missing translations fall
back to English; `scripts/verify-localizations.py` fails CI for missing keys,
duplicates and mismatched interpolation arguments.

## Display and OCR

Valid stored `YYYY-MM-DD` dates are formatted as civil days with a UTC calendar
anchor, preventing a time-zone day shift. Invalid or free-form strings are kept.
Explicit ISO currency codes and unambiguous decimal amounts are formatted using
the region; ambiguous symbols, malformed numbers and excessively precise numbers
are kept verbatim. Fractional amounts are preserved for currencies such as JPY.
No currency conversion occurs.

Vision language selection is limited to languages supported by the device, ordered
by app/system preference with English fallback and automatic language detection.
English/Russian labels, grouped amounts with ordinary/NBSP/narrow-NBSP spacing,
and valid Russian labelled `DD.MM.YYYY` dates are recognized as unselected
suggestions. Malformed amounts, impossible dates and ambiguous slash dates are
not reinterpreted.

## Export compatibility

`InventoryCSV.render` remains byte-compatible for the same inventory. The ZIP
contains that machine CSV as `Inventory.csv`, plus translated headings/kinds in
`Inventory-localized.csv`, a localized PDF and localized README. Standalone CSV
export uses `Inventory-localized.csv`. CSV values, identifiers and original-file
paths stay unchanged in both modes. PDF display captions and dates/prices use the
chosen language/region. PDF text uses the built-in Arial family: on the tested
iOS 27 runtime the SF PDF subset mapped Cyrillic к to Latin kra (U+0138),
breaking search/copy despite correct-looking glyphs. Regression tests check exact
Cyrillic captions, not visual lookalikes. Restore backups stay on schema 1 and preserve raw values.

## Verification

Run `scripts/ci.sh --static` and `swift test --package-path Core`. Hosted classes
`LocalizationTests`, `ServiceLocalizationTests`, `OCRServiceTests` and
`ExportServiceTests` verify resources, plural forms 0/1/2/5/21, RU + US region,
real Vision on a synthetic Russian receipt, PDF/CSV and data preservation.
`LocalizationUITests` launches the app with process-scoped `AppleLanguages` and
`AppleLocale`; it checks ordered preferences, English fallback, Russian create /
edit / relaunch / export. It never edits global simulator language settings.
Existing English iPad tests expect localized display dates and unchanged raw
editor input. No notification extension or notification scheduling exists here.

On a fresh Simulator, the system's first-use keyboard introduction can cover the
name form. The name-entry test recognizes its observed
`UIContinuousPathIntroductionView` container, exact introduction text and unique
Continue button within the explicit name-entry callsite. It permits one real
Continue tap per test case before querying the covered field. Only after a fresh
observation shows that the introduction is absent does it require exactly one
`entry.name` field, then check that field's live enabled and hittable state before
tapping and typing. Recognition,
optional evidence, dismissal and field-tap admission share one ten-second
monotonic window. Ambiguous or unrecognized prompts do not authorize dismissal.
Field counts remain unobserved in diagnostics until a query returns in time.
This ordering avoids a redundant field query while the introduction blocks the
form; it does not extend the deadline or change the one-second polling interval.
In the observed hosted failure, Continue returned before the deadline with too
little time for the next scheduled probe. A later screenshot showed the tutorial
gone, but did not establish when it disappeared or that the field was ready in time.
The test records whether it observed and dismissed the introduction; a run where
it never appears validates only the ordinary path. Keyboard preferences remain
unchanged, and the full create, edit, relaunch and CSV-export assertions still run.

Apple references: [bundle language matching](https://developer.apple.com/documentation/foundation/bundle/preferredlocalizations),
[Vision language detection](https://developer.apple.com/documentation/vision/vnrecognizetextrequest/automaticallydetectslanguage),
[exported file type descriptions](https://developer.apple.com/documentation/UniformTypeIdentifiers/defining-file-and-data-types-for-your-app).
