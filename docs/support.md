# Support and recovery

[Русский](support.ru.md) · [Privacy](privacy.md)

Report reproducible issues at
[4alvit/room-inventory-ios issues](https://github.com/4alvit/room-inventory-ios/issues).
Include app version (and source SHA if available), iOS version, device or Simulator
model, the action that failed and the exact non-sensitive error message. Use synthetic examples.
Public issues are visible to everyone; never upload a real home inventory, receipt,
backup, credential or private document. No response-time guarantee is offered for
the development preview.

## Restore a saved backup

To save a restorable copy, use **Export and backup → Restorable backup + originals**.
It contains the current inventory and its linked originals. Previously removed
records and file links are not included. The backup is not encrypted; choose a
safe storage location and manage any cloud or shared copies separately.

Open Room Inventory, return to its main screen, and choose **Export and backup →
Restore a backup**. Select the `.roominventory` file in Files and review the
replacement warning before confirming. Export the current inventory first if you
need to keep it. Cancelling leaves the current inventory unchanged.

Opening a backup directly from Files is not supported. The app deliberately does
not register as a file editor or an Open In destination. A PDF report or report ZIP
cannot restore the inventory; use a `.roominventory` backup with originals.

## Storage errors

If storage is full or unavailable, free space and retry. A failed save should not
replace the previous saved inventory; avoid repeatedly adding the same item before
checking its current state. Restore stages the incoming content before committing.
Keep the original backup and do not uninstall the app as the first recovery step.

Limits: 25 MiB per stored original, 80 MiB of originals linked to the current
inventory, 128 MiB per backup, 4 MiB of inventory JSON, and 64 KiB per text field. A large backup can use
more memory than its on-disk size. These storage limits apply to Pro as well as Free.

The image capture/import UI accepts JPEG, PNG and HEIC/HEIF images up to 20 MB
(20,000,000 bytes), 64 megapixels and 16,384 pixels on either side. Image preview
and OCR use these same image limits. Import an image of a PDF receipt rather than
the PDF itself.

Deleting records or attachment links does not delete their original files from
device storage: the app retains them internally for recovery, without automatic cleanup or
an in-app recovery browser. Retained originals and temporary exports can make
device storage use exceed 80 MiB. Save a usable backup before removing records or
uninstalling; a new backup includes only originals still linked to the inventory.

PDF reports are limited to 500 pages. If a report exceeds this limit, no partial
PDF or ZIP is exported. Reduce long notes, select fewer rooms in a custom report,
or export a restorable backup. Your saved inventory is unchanged.

A damaged inventory manifest can be replaced by restoring a known-good
`.roominventory` backup. Missing and damaged regular originals can also be restored.
If a generated original filename already exists with different bytes, restoration
preserves that file and gives the recovered attachment a fresh ID and filename.
The home, room and item identities remain unchanged. Unsafe symlink collisions
are rejected; preserve the affected storage for inspection rather than editing
links or filenames by hand. Do not uninstall until a usable backup exists and any
recoverable data has been preserved.

An unsupported backup version requires a compatible newer app. A report ZIP is
not a restorable backup: export `.roominventory` specifically for restoration.
Backups must contain exactly their referenced originals; changing file names or
JSON by hand can break integrity checks and associations.

## Purchases

After reinstalling or changing devices, open the Pro screen and use **Restore
purchases** with the same Apple Account. Restoring a purchase restores Pro access, not inventory data; restore a
saved `.roominventory` backup separately for your records and images.
Pending transactions must finish through Apple's purchase approval flow.
Cancellation leaves the inventory unchanged. A refunded or revoked entitlement
can remove permission to add beyond the Free limits. Free allows one room and
10 items across all homes. Viewing and editing existing records, restoring backups,
and basic PDF, CSV, ZIP and backup exports remain available without Pro, subject
to the same storage limits.

Pro is designed as one purchase, not a subscription. It enables additional rooms
and items, importing up to 10 images together for one item, and custom PDF reports.
Apple handles payment; review the local price in Apple's purchase confirmation.
Store availability and price depend on the production product configuration.
The included StoreKit test configuration simulates purchases and is not a live
price or evidence that the product is available for sale.

## Capture and OCR

OCR runs on the device. Retake blurred labels in good lighting and inspect
recognized text before applying it. Suggestions start unselected; choose only
values you want to replace in the item. OCR can confuse letters, digits, dates and
prices. Suggestions are not confirmed facts and do not establish ownership,
value, insurance coverage or payment.
