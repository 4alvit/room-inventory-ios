# Architecture and data contract

Room Inventory is a native SwiftUI iOS 17+ app with a local Swift package,
`InventoryCore`. It requires no account or application server. Fixtures and public
screenshots use synthetic content. The non-consumable product ID is configured by
`ProProductID` and initially equals `com.alvit.roominventory.pro`.

## Models and persistence

All models are `Codable`, `Equatable` and `Sendable`. Homes, rooms, items and
attachments carry UUID identities. Initializers create IDs for new records;
synthesized decoding requires saved IDs and never replaces missing identities.

An inventory contains homes, rooms and items. Each item contains a name, model,
serial number, purchase amount/date, notes and original attachments. Attachments
carry a kind (`photo`, `label`, `receipt`), generated filename, original display
name, MIME type and SHA-256. User-supplied names are never filesystem paths.

`InventoryRepository` exposes synchronous throwing operations:

```swift
init(rootURL: URL) throws
func load() throws -> Inventory
func save(_ inventory: Inventory) throws
func importAttachment(data: Data, originalName: String, mediaType: String, kind: AttachmentKind) throws -> InventoryAttachment
func data(for attachment: InventoryAttachment) throws -> Data
func exportBackup(_ inventory: Inventory) throws -> Data
func restoreBackup(_ data: Data) throws -> Inventory
```

The UI serializes mutations through `InventoryStore` and a private disk actor.
The repository adds per-instance and filesystem locks. A read-modify-save sequence
across arbitrary repository callers is not itself a transaction. The application
publishes a changed inventory only after persistence succeeds.

Restore validates and stages files before an atomic manifest switch. Different
bytes at an existing original's filename are retained; only that restored
attachment receives a fresh ID/filename. Old and unreferenced originals remain on
disk. See [the format, limits and recovery rules](../Core/README.md).

## Batch import

Pro can select up to ten images for one item. Files are loaded and saved in order;
successful files stay attached if another file fails. Retry operates only on failed
entries. Free retains single-image import. Batch import does not create new items
or apply OCR automatically; each saved label or receipt can be opened for explicit
recognition and review.

## Export

`InventoryCSV.render(_:) throws` produces escaped UTF-8 CSV with formula defense, record
identities and item-to-original associations. It stops before the rendered output exceeds
16 MiB instead of silently truncating records. The backup remains available for larger
text projections. PDF rendering stops before page 501, returning an explicit
error and discarding partial renderer output. This also prevents a report ZIP
from containing a truncated PDF. A single export actor serializes
heavy rendering, reads and encoding away from the main actor. The facade is async:

```swift
static func csvURL(inventory: Inventory) async throws -> URL
static func pdfURL(inventory: Inventory) async throws -> URL
static func backupURL(inventory: Inventory, repository: InventoryRepository) async throws -> URL
static func bundleURL(inventory: Inventory, repository: InventoryRepository) async throws -> URL
```

ZIP packages contain PDF, CSV and byte-exact originals at
`originals/<item UUID>/<generated filename>`. PDF and CSV record the same paths.
The separate `.roominventory` JSON/base64 backup restores records and originals.
Neither format is encrypted. Originals retain their metadata. Export copies live
in the app's temporary directory; older export directories are eligible for
cleanup after 24 hours or by the operating system.

## Purchases and capture

`ProStore` derives access exclusively from verified StoreKit 2 non-consumable
transactions with the configured product ID. Free additions are limited to one
room and ten items globally. Existing viewing, editing, deletion, export, backup
and restore remain available without Pro. Larger restored libraries are preserved;
only new additions are restricted. Storage limits still apply to Pro.

OCR runs on-device. Candidates start unselected and require explicit review and
application; existing values are shown before replacement. The original is saved
before recognition and remains available if recognition fails. Capture currently
accepts images; direct PDF receipt import is not part of the current UI.

### Custom PDF projection

`InventoryReportOptions` filters rooms and optional detail fields in a value copy
of the inventory. It does not save or delete anything. The PDF renderer receives
only this projection, so excluded serials, purchase details, notes and attachment
paths are not merely hidden by layout. Room names, item names and models remain
included. Basic all-inventory exports remain available without Pro.
