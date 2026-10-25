# App Store submission draft — Room Inventory

Prepared 2026-10-21 for **English (U.S.)**. This is editable submission copy, not a submitted listing or a release-readiness declaration. Source baseline: `f09740524197889086519c99fa526859a22f5404`, plus the working tree inspected on this date. No App Store account, HCP, GitHub account or signing checks were made for this draft.

The baseline copy below describes the current product. **Pro batch image import and report options are required candidate scope under implementation and still need validation.** Do not advertise those features until the exact release build supports and passes them; use the conditional copy below only after that gate. Reconcile this draft with the final source SHA, UI labels, privacy text and actual purchase configuration before submission.

## App identity and placement

- Proposed App Store name: Room Inventory. Name availability has not been checked or reserved.
- Bundle ID in the Xcode project: `com.alvit.roominventory`. Confirm it against the registered app and uploaded build; this draft does not establish ownership.
- Minimum target: iOS 17. The project supports iPhone and iPad; retain both only after final layout and device validation.
- Primary category suggestion: **Productivity**, because the core task is organizing records and producing reusable exports. Secondary suggestion: **Utilities**, if selected by the owner. These are editorial suggestions, not an Apple classification or ranking claim.
- Developer/seller name, SKU, copyright owner/year, App Review contact details and age-rating questionnaire: **owner input required**. No personal contact data or fabricated answers are supplied here.

Apple documents 30-character name/subtitle limits in [App information](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information). Promotional text is limited to 170 characters, description to 4,000, and keywords to **100 UTF-8 bytes**, according to [Platform version information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information). Counts below were computed with Python `len(value)` and `len(value.encode("utf-8"))`; code-fence markers and the presentation newline after each value are excluded. Description and review-note paragraph breaks are included.

## Baseline product-page copy

### Name

Count: **14 / 30 characters**.

```text
Room Inventory
```

### Subtitle

Count: **28 / 30 characters**.

```text
Photos, receipts and records
```

### Keywords

Count: **91 / 100 UTF-8 bytes**.

```text
home,belongings,serial,organizer,moving,backup,property,checklist,documents,pdf,csv,offline
```

### Promotional text

Count: **132 / 170 characters**.

```text
Photograph your belongings, review text from labels and receipts, and keep a portable inventory with local storage and easy exports.
```

### Description

Count: **2106 / 4000 characters**.

```text
Make a clear record of your belongings, one room at a time. Room Inventory brings item photos, label details and receipt images together so you can find them when you need them.

BUILD YOUR INVENTORY
Create a home and room, then add your belongings. Take a photo or select an image from Photos or Files. Keep the model, serial number, purchase amount, purchase date and notes with each item.

REVIEW RECOGNIZED TEXT
Text recognition runs on your device. Review suggestions from labels and receipts, select the values you want, and confirm before they update an item. Reminders help you spot missing photos, receipts and details.

KEEP A PORTABLE COPY
Export a PDF report, CSV table or ZIP package containing your original files and their item associations. Save a separate .roominventory backup to restore your inventory and originals inside the app.

START FREE
Free includes one room and ten items across all homes. An optional, one-time Pro purchase allows more rooms and items within the app's storage limits. Viewing, editing, basic exports and backup restoration remain available without Pro. Purchases can be restored through the App Store.

LOCAL STORAGE
No app account is required. The app keeps inventory content on your device and does not send it to an app server. Device backups and any cloud locations you choose in Files may retain copies under their own settings.

Current inventories support up to 80 MiB of original files, including with Pro. Exports and backups are not encrypted. Stored images may contain capture dates or location. Files imports preserve the selected bytes; Photos supplies its current representation, which may include edits or conversions. Camera capture saves a JPEG. An untouched camera asset and all its original metadata are not guaranteed. Choose where you store and share them. Originals removed from item records remain in local recovery storage until the app is deleted; manage exported copies and device backups separately.

Room Inventory records information you provide. It does not automatically value property or guarantee insurance coverage or payment.
```

## Non-consumable in-app purchase

Type: **Non-consumable**, not a subscription. The local StoreKit configuration uses a USD 19.99 test price; that is a simulation, not a verified production price or sale. Configure the actual storefront availability and price in App Store Connect, then verify the localized price in the signed build. Do not place the test price in public copy or synthetic purchase screenshots.

The 30-character localized display-name and 45-character description limits, plus internal reference-name and product-ID constraints, are documented in [In-App Purchase information](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information).

### Internal reference name

Count: **18 / 64 characters**.

```text
Room Inventory Pro
```

### Product ID

Count: **27 / 100 characters**.

```text
com.alvit.roominventory.pro
```

### Localized display name

Count: **18 / 30 characters**.

```text
Room Inventory Pro
```

### Baseline localized description

Count: **39 / 45 characters**.

```text
More rooms and items. One-time upgrade.
```

### Conditional Pro copy — not yet approved for submission

Only after batch import and report options pass on the exact release build, replace the START FREE paragraph in the description with this paragraph. Confirm the actual batch cap and available report controls first; this copy makes no unlimited-import or unlimited-storage promise.

### Candidate replacement paragraph

Count: **335 characters**.

```text
Free includes one room and ten items across all homes. An optional, one-time Pro purchase adds more rooms and items, batch import of selected images, and report options within the app's storage limits. Viewing, editing, basic exports and backup restoration remain available without Pro. Purchases can be restored through the App Store.
```

Full description with this replacement: **2157 / 4,000 characters**.

### Candidate localized IAP description

Count: **44 / 45 characters**.

```text
More rooms, batch import and report options.
```

Before using the candidate paragraph, record evidence for: bounded multi-image selection and limits; per-image error handling; cancellation/interruption; correct item-to-image associations; Pro purchase/restore/revocation behavior; actual report controls; and continued access to basic exports without Pro. Do not add unsupported options such as automatic estimates, 3D scans, family sharing, hosted sync or PDF-document import to this copy.

## App Review notes

The following text is for a configured, signed candidate. Keep it in draft until the payment and device gates below pass. Update step numbers and exact labels if the final UI changes. App sign-in required: **No**. Apple purchase authentication is separate. Enter the real review contact in App Store Connect; do not invent demo credentials.

### Review notes draft

Count: **2677 characters**.

```text
Room Inventory is a local inventory utility. No app account, login, invitation or developer server is required. Purchases use Apple's standard StoreKit flow; no developer-issued test credentials are needed.

Suggested review path:
1. Launch the app, add a home called Demo Home, add a room called Office, and add an item called Demo Camera.
2. Open the item and choose Add photo or document image. Take a photo, select an image from Photos, or import an image from Files. Choose Item photo, Model / serial label, or Receipt as appropriate. The current capture UI accepts JPEG, PNG and HEIC images, not PDF documents.
3. Use a clear synthetic label or receipt image. Open Recognize text, review the suggestions, select the values to use, and tap Apply. OCR runs on-device. Suggestions start unselected and do not update item fields without confirmation.
4. Return to the main screen and open Export and backup. Try the PDF report, CSV table, original-file ZIP package and separate restorable .roominventory backup. Use the system share sheet to save to Files. To restore, use Export and backup > Restore a backup inside the app. Opening the backup directly from Files is not supported. Restore replaces the active inventory after confirmation.
5. Free access allows one room and ten items in total across all homes. Attempting to add beyond this opens the Pro offer. Pro uses the non-consumable product com.alvit.roominventory.pro. The price comes from StoreKit. Use Restore purchases in the Pro screen to restore an existing entitlement.
6. Viewing, editing, deletion, basic exports and backup restoration remain available without an active Pro entitlement. A pending or cancelled purchase does not unlock Pro. Existing records remain available after revocation.

There is no automatic property valuation or insurance coverage/payment decision. The app stores user-entered information and images. Stored images can retain metadata. Files imports preserve the selected bytes. Photos supplies its current representation, which may include edits or conversion, and camera capture creates a JPEG; preservation of an untouched camera asset and all its original metadata is not guaranteed. Exports and backups are not encrypted. Device backups and user-selected Files providers may retain copies. Removed originals remain in local recovery storage until the app is deleted.

The active inventory supports up to 80 MiB of originals, including with Pro. Capture imports are limited to 20 MB, 64 megapixels and 16,384 pixels per side. PDF reports are limited to 500 pages, CSV exports to 16 MiB and backups to 128 MiB; oversized operations return an error rather than truncated content.
```

If candidate Pro features ship, add their verified navigation steps and concrete limits to these review notes. For batch import, state whether images attach to the selected item or create separate items, matching the implementation. For report options, list only the controls actually exposed. Attach synthetic label/receipt examples and a real IAP review screenshot when preparing the submission; none are created or attached by this document.

## Screenshot shot list

Capture the actual final build with synthetic data. Proposed dataset: **Demo Home → Office** with **Demo Camera**, **Desk Lamp**, **Monitor** and **Headphones**. Use a printed label such as `Model: DEMO-C100 / Serial: DEMO-000123`, a receipt visibly marked `SAMPLE`, and invented amounts and dates. No household photos, addresses, real receipts or real serial numbers. Maintain one consistent inventory across the set.

1. **Know what you have.** Room screen with the four sample items and their file/detail counts. Show a finished small room, not a first-launch blank state. First screenshot communicates the central task.
2. **Keep the details together.** Demo Camera detail with a photo, label and receipt image plus confirmed model, serial and user-entered amount. No automatic-value badge or insurance endorsement.
3. **Check the text before saving.** Actual **Review recognized text** screen with readable text and a candidate value from the synthetic image. The original image is available in the separate attachment preview, not on this review screen. Show the selection controls and Apply action; do not imply perfect OCR.
4. **See what is still missing.** An item with clear suggested next steps. Capture reminders as optional guidance, not insurance requirements.
5. **Export a useful record.** Actual **Export and backup** menu or in-app/system preview of the generated PDF. Caption may say **PDF, CSV and original files**. Verify the displayed report and ZIP/CSV paths correspond to the same synthetic inventory.
6. **Keep a restorable copy.** In-app backup/restore flow with the `.roominventory` selection and confirmation visible. Avoid implying that a report ZIP restores the app or that backups sync automatically.
7. **One purchase, more room.** Actual Pro screen after production product configuration. Any shown price must be the real localized StoreKit value for the captured storefront. Show the restore-purchases path and the absence of a subscription. Until price loading is validated, this shot is internal-only.
8. **Candidate only: Add several images.** Capture the real bounded Pro batch selector/progress/result after validation. Display the actual cap and per-image outcomes if the UI exposes them. Do not mock an unimplemented workflow.
9. **Candidate only: Choose your report.** Capture the final Pro report-options screen and matching output after validation. Captions must name only verified options.

Use the strongest six or seven baseline shots; add candidate shots only when the features ship. Capture readable iPhone and iPad compositions separately rather than stretching one layout. Retain raw captures, source SHA, build/version, simulator or device model, runtime, locale, appearance and pixel dimensions as release evidence.

As checked on 2026-10-21, Apple's [Screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications) require an iPhone Dynamic Island medium-display set and, for iPad support, a 13-inch iPad set. Concrete capture targets accepted by that reference are **1206 × 2622** portrait for the iPhone set and **2064 × 2752** portrait (or **2752 × 2064** landscape) for the iPad set. Use a simulator/device that naturally produces the selected size, verify actual pixels and omit alpha/transparency. Recheck requirements in App Store Connect at upload; this is not evidence that any screenshots have been captured or accepted.

## Privacy and support URL gate

- **Privacy Policy URL: UNSET — submission gate.** Publish the final, build-matched privacy statement and verify the exact public HTTPS page opens without sign-in. Source draft: [privacy.md](privacy.md).
- **Support URL: UNSET — submission gate.** Publish a reachable page with actual support contact information and the recovery instructions. Source draft: [support.md](support.md). Apple's [Platform version information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information) describes the support-contact requirement. Existing repository references to GitHub issues are not a verified live support destination in this draft; public reachability was not checked here.
- **Marketing URL: not proposed.** Supply one only if an actual product page is published and checked. Do not paste an illustrative or anticipated URL into App Store Connect.
- Public copy must match actual local storage, on-device OCR, Apple-handled purchases, user-selected sharing, retained removed originals, imported bytes, possible image metadata and the Photos/camera representation limits. Do not claim an encrypted vault, zero metadata, automatic deletion of all copies, or private-by-default behavior of external Files providers.
- The current privacy manifest declares no collected-data entries and no tracking; source inspection also shows no app server or analytics/advertising SDK. These are inputs for the owner to review against the final binary and dependencies, **not a completed App Privacy questionnaire or a legal/compliance attestation**. Review required-reason API declarations and actual purchase behavior before submitting disclosures.

## Unresolved submission gates

- [ ] Final batch import and report-option implementation passes; choose baseline or conditional copy accordingly and reconcile README/product docs. The README describes the implemented candidate features; final runtime acceptance is still required.
- [ ] Exact candidate SHA, version/build and archive selected; current repository/unsigned Simulator artifacts do not constitute a device submission.
- [ ] Cold-install StoreKit tests are reproducible. The current README records a fresh-Simulator purchase-routing failure on Xcode 27.0 / iOS 27.0; a pass on a previously used simulator does not close it. Validate purchase, cancellation, pending approval, restore, refund/revocation and offline access on the intended signed sandbox/TestFlight build.
- [ ] Existing inventory, basic exports and restore remain usable without Pro, including an inventory above Free quotas after revocation. The 80 MiB inventory-originals limit is shown before purchase and matches store copy.
- [ ] Camera permissions, denied access, selected-image import, OCR confirmation, background interruption, low storage, corrupt backup handling, iPhone/iPad layouts and accessibility are exercised on the release build and supported physical devices.
- [ ] Baseline and any candidate screenshots are captured from the actual build; IAP review screenshot and any review attachments contain synthetic data only.
- [ ] Public privacy/support URLs and real contact details are supplied and verified; final App Privacy, age-rating and encryption/export questions are reviewed by the owner from actual behavior.
- [ ] The owner supplies the enrolled Developer team, app/product registration and valid signing setup. Any required legal, paid-app, banking or tax agreements are completed by an authorized human. This draft neither accepts them nor asserts compliance.
- [ ] Final localized store price, product ID/type and availability are confirmed; upload, TestFlight acceptance, App Review and actual storefront availability are verified separately before claiming a release or revenue.

This draft creates no external listing, product, purchase, support page or release.
