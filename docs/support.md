# Support and recovery

Report reproducible issues at
[4alvit/room-inventory-ios issues](https://github.com/4alvit/room-inventory-ios/issues).
Include app version/source SHA, iOS version, device or Simulator model, the action
that failed and the exact non-sensitive error message. Use synthetic examples.
Public issues are visible to everyone; never upload a real home inventory, receipt,
backup, credential or private document. No response-time guarantee is offered for
the development preview.

## Restore a saved backup

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

Limits: 25 MiB per stored original, 80 MiB of originals per inventory, 128 MiB per
backup, 4 MiB of inventory JSON, and 64 KiB per text field. A large backup can use
more memory than its on-disk size. Imports through the capture UI can have a smaller
limit. These storage limits apply to Pro as well as Free.

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

Use Restore Purchases with the same Apple Account after reinstalling or changing
devices. Pending transactions must finish through Apple's purchase approval flow.
Cancellation leaves the inventory unchanged. A refunded or revoked entitlement
can remove permission to add beyond the Free limits; existing records and basic
exports remain accessible. Store availability and price depend on the production
product configuration. The included USD 19.99 StoreKit configuration is only a test.

## Capture and OCR

Retake blurred labels in good lighting and inspect recognized text before applying
it. OCR can confuse letters, digits, dates and prices. Suggestions are not confirmed
facts and do not establish ownership, value, insurance coverage or payment.
