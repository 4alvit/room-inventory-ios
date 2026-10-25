# Privacy — development preview

Last updated: 2026-10-21. This statement describes the code in this repository.
Review it against the shipped build and App Store Connect disclosures before release.

Room Inventory keeps item descriptions, amounts, serial numbers, notes, selected
photos, labels and receipt images in the app's local sandbox. OCR uses Apple's
on-device Vision framework. The application has no mandatory account, application
server, advertising SDK, analytics SDK or developer-operated cloud sync. Inventory
content is not sent to the developer by these features.

Apple handles StoreKit product availability, purchases and purchase restoration.
The application uses verified StoreKit transactions to determine Pro access. Apple
can process purchase information under its own terms. Local StoreKit test purchases
are simulations; they do not establish production sales.

Camera access is requested when taking photos. The photo picker supplies items the
user selects. The app does not need unrestricted access to the whole photo library.
Files import/export and sharing use user-selected locations or recipients. A cloud
Files provider, shared destination, Photos or operating-system/device backup can
retain copies according to its settings; this app does not control those services.

PDF, CSV, ZIP and `.roominventory` exports are not encrypted. Stored images can
include embedded metadata such as capture date or location. The app preserves the
bytes received during import rather than stripping metadata. Files imports retain
the selected file. Photos supplies its current representation, which may include
edits or provider conversion; the app requests current encoding where possible.
Camera capture creates a JPEG. These paths do not guarantee an untouched camera
asset or preservation of all its original metadata. Choose recipients and storage
locations accordingly. Temporary exported copies are retained briefly in the app
sandbox; old export folders are cleaned opportunistically on later exports.

Deleting an item removes it from the active inventory, but this preview retains
unreferenced original files internally to avoid deleting data still needed by an
older manifest or interrupted restore. There is no automatic original-file garbage
collection. Uninstalling the app removes its device sandbox; independently exported
copies and operating-system/cloud backups must be managed separately. Back up any
data you want to retain before uninstalling.

The implementation uses platform sandboxing and iOS Data Protection, not a separate
encrypted vault or a promise of end-to-end encrypted backup. Public support is at
[GitHub issues](https://github.com/4alvit/room-inventory-ios/issues). Do not attach
private inventories, receipts, serial numbers, photos or backups to a public issue.
