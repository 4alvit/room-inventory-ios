# App Store submission copy — Room Inventory

Prepared **2026-10-25** for **English (U.S., en-US)** and **Russian (ru)**. Product baseline: [`68041c3f1f1c70f4c07207f443dd636a141f5f65`](https://github.com/4alvit/room-inventory-ios/commit/68041c3f1f1c70f4c07207f443dd636a141f5f65), version `0.1.0`. This is editable submission material; no listing, IAP, upload or release is created by this document.

Batch image import and custom PDF options are implemented in this baseline and are included in the copy below. Use the copy only for a signed candidate with the same verified behavior. Name availability and App Store Connect app/product registration remain owner checks.

## Source baseline and release boundary

[Hosted run 40154440680](https://github.com/4alvit/room-inventory-ios/actions/runs/40154440680) passed all eight jobs for the baseline: **263 tooling, 46 Core, 57 app tests (including four StoreKit tests), and three UI tests passed**. The iPad-only UI test was the single expected skip. The retained xcresult establishes iPhone 17 Pro / iOS 26.2 (23C54); the compile SDK was 18.5. The tested PR merge tree matched the signed source head.

This is Simulator evidence. A GitHub unsigned Simulator ZIP cannot be installed on a physical iPhone or submitted to App Store Connect. A signed Release archive, physical-device behavior, fresh signed-device Sandbox purchases and restoration, production product configuration, TestFlight and App Review remain separate gates. The existing green local StoreKit tests do not establish a production price or a sale. See [device handoff](device-release.md) and [release checklist](release-checklist.md).

## Field limits and counting

Apple references checked on **2026-10-25**:

- [App information](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information): name 2–30 characters; subtitle at most 30 characters.
- [Platform version information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information): promotional text at most 170 characters; plain-text description at most 4000 characters; keywords at most **100 bytes**, with each keyword longer than two characters; App Review Notes at most **4000 bytes**. App Review notes are one submission field, not separate localized product-page fields: choose one language below, do not concatenate both.
- [In-App Purchase information](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information): internal reference name at most 64 characters; product ID at most 100; localized display name 2–30; localized description at most 45; IAP Review Notes at most **4000 characters**. IAP notes are also alternatives, not two blocks to concatenate.

Counts below include spaces, punctuation and internal paragraph breaks, but exclude Markdown fences and the newline after each field. Character counts use Unicode code points (`len(text)`); byte counts use UTF-8 (`len(text.encode("utf-8"))`). All fields are NFC-normalized and contain no emoji or combining sequences. Apple labels the two byte limits as bytes; UTF-8 is the encoding measured here. Recount after any edit and recheck the live form before submission.

## English (U.S.) product page

### Name

<!-- metadata:en-US:name -->
Count: **14 / 30 characters; 14 UTF-8 bytes**.

```text
Room Inventory
```

### Subtitle

<!-- metadata:en-US:subtitle -->
Count: **28 / 30 characters; 28 UTF-8 bytes**.

```text
Photos, receipts and records
```

### Keywords

<!-- metadata:en-US:keywords -->
Count: **91 / 100 UTF-8 bytes; 91 characters**.

```text
home,belongings,serial,organizer,moving,backup,property,checklist,documents,pdf,csv,offline
```

### Promotional text

<!-- metadata:en-US:promotional_text -->
Count: **147 / 170 characters; 147 UTF-8 bytes**.

```text
Photograph your belongings, keep receipts and serial numbers together, and make useful exports. Pro adds batch image import and custom PDF reports.
```

### Description

<!-- metadata:en-US:description -->
Count: **2975 / 4000 characters; 2975 UTF-8 bytes**.

```text
Make a clear record of your belongings, one room at a time. Room Inventory keeps item photos, labels, receipt images and purchase details together so you can find them when you need them.

BUILD YOUR INVENTORY
Create homes and rooms, then add your belongings. Take a photo or select JPEG, PNG or HEIC images from Photos or Files. Record model and serial numbers, purchase amounts and dates, and notes. Suggested next steps help you spot missing details.

CHECK RECOGNIZED TEXT
Text recognition runs on your device. Review suggestions from labels and receipts, select the values you want, then confirm before they update an item. English and Russian interfaces and recognition labels are supported. Recognition can make mistakes; your confirmation stays in control.

START FREE, ADD PRO WHEN YOU NEED IT
Free includes one room and ten items in total across all homes, with one image imported at a time. An optional, one-time Pro purchase adds more rooms and items within the app's limits, import of up to ten images at once into the same item, and custom PDF reports. Batch images share the chosen purpose; they do not create separate items or apply OCR automatically.

With a custom PDF, choose rooms and include or omit serial numbers, purchase details, notes, and attachment names and paths. These choices change the exported PDF only, not your saved records. PDF reports do not embed the image files.

Viewing, editing, deletion, standard exports and backup restoration remain available without Pro, including after an entitlement is revoked. Restore purchases through the App Store. Pro is not a subscription.

KEEP A PORTABLE COPY
Export a PDF report, a CSV table or a ZIP containing the report, CSV tables and saved original files with their item associations. A separate .roominventory backup restores the inventory and originals in the app. The report ZIP is not a restorable backup.

LOCAL STORAGE AND CLEAR LIMITS
No app account is required. Inventory content stays in the app's local storage unless you share it or it is copied by device backups. Cloud locations you choose in Files follow their own settings.

All plans share an 80 MiB limit for originals linked to the active inventory. Other global limits are 100 homes, 1,000 rooms, 10,000 items and 5,000 originals; storage and text limits may be reached first. Pro does not remove these limits. Removed originals remain in local recovery storage until the app is deleted and may use additional device space.

Exports and backups are not encrypted. Images may retain dates or location metadata. Files imports preserve the selected bytes; Photos supplies its current representation, which may include edits or conversions. Camera capture saves a JPEG. The untouched camera asset and all original metadata are not guaranteed. Manage shared copies and device backups separately.

Room Inventory records information you provide. It does not automatically value property or guarantee insurance coverage or payment.
```

## Русская страница приложения

### Name

<!-- metadata:ru:name -->
Count: **14 / 30 characters; 14 UTF-8 bytes**.

```text
Room Inventory
```

### Subtitle

<!-- metadata:ru:subtitle -->
Count: **29 / 30 characters; 52 UTF-8 bytes**.

```text
Фото, чеки и сведения о вещах
```

### Keywords

<!-- metadata:ru:keywords -->
Count: **85 / 100 UTF-8 bytes; 49 characters**.

```text
вещи,дом,опись,имущество,переезд,серийный,pdf,csv
```

### Promotional text

<!-- metadata:ru:promotional_text -->
Count: **141 / 170 characters; 252 UTF-8 bytes**.

```text
Храните фото вещей, чеки и серийные номера вместе. Создавайте отчёты и резервные копии. С Pro — групповой импорт изображений и настройка PDF.
```

### Description

<!-- metadata:ru:description -->
Count: **3155 / 4000 characters; 5702 UTF-8 bytes**.

```text
Соберите понятную опись вещей по комнатам. Room Inventory хранит вместе фотографии предметов, маркировку, изображения чеков и сведения о покупке, чтобы нужную запись было легко найти.

СОЗДАЙТЕ ОПИСЬ
Добавляйте дома, комнаты и предметы. Снимайте камерой или выбирайте изображения JPEG, PNG и HEIC из «Фото» и «Файлов». Записывайте модель, серийный номер, стоимость и дату покупки, заметки. Подсказки помогут заметить недостающие сведения.

ПРОВЕРЯЙТЕ РАСПОЗНАННЫЙ ТЕКСТ
Текст распознаётся на устройстве. Проверьте значения с маркировки или чека, выберите нужные и подтвердите изменения. Пока вы не подтвердите выбор, сведения о предмете не изменятся. Интерфейс и распознавание подписей полей поддерживают русский и английский языки. При распознавании возможны ошибки.

НАЧНИТЕ БЕСПЛАТНО
Бесплатная версия включает одну комнату и десять предметов суммарно во всех домах, а изображения импортируются по одному. Необязательная разовая покупка Pro позволяет добавлять больше комнат и предметов в пределах лимитов приложения, импортировать до десяти изображений за раз для одного предмета и настраивать PDF.

Все изображения в группе получают выбранное назначение и прикрепляются к одному предмету. Отдельные предметы для них не создаются, автоматического распознавания всей группы нет.

В настраиваемом PDF можно выбрать комнаты, включить или убрать серийные номера, сведения о покупке, заметки, имена и пути вложений. Эти настройки меняют только новый PDF, а не сохранённые записи. Файлы изображений в PDF не встраиваются.

Просмотр, редактирование, удаление, обычный экспорт и восстановление резервных копий доступны без Pro, в том числе после отзыва покупки. Покупки можно восстановить через App Store. Pro не является подпиской.

СОХРАНЯЙТЕ КОПИИ
Экспортируйте PDF, таблицу CSV или ZIP с отчётом, таблицами и сохранёнными оригиналами, связанными с предметами. Отдельная резервная копия .roominventory восстанавливает записи и оригиналы в приложении. ZIP с отчётом не подходит для восстановления.

ЛОКАЛЬНОЕ ХРАНЕНИЕ И ЛИМИТЫ
Учётная запись приложения не нужна. Содержимое хранится локально, пока вы не поделитесь им или оно не попадёт в резервную копию устройства. Облачные хранилища, выбранные в «Файлах», используют собственные настройки.

Во всех версиях действует лимит 80 МиБ оригиналов, связанных с текущими записями. Другие общие лимиты: 100 домов, 1000 комнат, 10 000 предметов и 5000 оригиналов. Ограничения объёма файлов и текста могут быть достигнуты раньше. Pro не снимает эти лимиты. Удалённые оригиналы остаются в локальном хранилище восстановления до удаления приложения и могут занимать дополнительное место.

Экспорт и резервные копии не зашифрованы. В изображениях могут остаться дата съёмки и геолокация. Импорт из «Файлов» сохраняет выбранные байты. «Фото» передаёт текущую версию, иногда с изменениями или преобразованием формата. Камера сохраняет JPEG. Неизменённый исходник камеры и все его метаданные не гарантируются. Управляйте отправленными копиями и резервными копиями устройства отдельно.

Приложение записывает введённые вами сведения. Оно не оценивает имущество автоматически и не гарантирует страховое покрытие или выплату.
```

## Non-consumable IAP

Type: **Non-consumable**. The product grants Pro without a subscription or trial. The local StoreKit price is a test fixture; no numeric price from it is included here. Confirm actual storefront availability and localized `Product.displayPrice` in the signed candidate after configuring App Store Connect. Do not publish a test price or present a simulated purchase as a real transaction.

### Internal IAP reference name

<!-- metadata:shared:iap_reference_name -->
Count: **18 / 64 characters; 18 UTF-8 bytes**.

```text
Room Inventory Pro
```

### IAP product ID

<!-- metadata:shared:iap_product_id -->
Count: **27 / 100 characters; 27 UTF-8 bytes**.

```text
com.alvit.roominventory.pro
```

## English (U.S.) IAP

### Localized IAP display name

<!-- metadata:en-US:iap_display_name -->
Count: **18 / 30 characters; 18 UTF-8 bytes**.

```text
Room Inventory Pro
```

### Localized IAP description

<!-- metadata:en-US:iap_description -->
Count: **44 / 45 characters; 44 UTF-8 bytes**.

```text
More rooms, batch import and report options.
```

### IAP Review Notes

<!-- metadata:en-US:iap_review_notes -->
Count: **730 / 4000 characters; 730 UTF-8 bytes**.

```text
Room Inventory Pro is a non-consumable one-time upgrade, product ID com.alvit.roominventory.pro. Open Explore Pro, reach a Free quota, or select Custom PDF report to see the offer. It adds more rooms/items within global limits, up to ten images per batch for the same item, and custom PDF room/detail options. Free is one room and ten items globally. The 80 MiB active-originals limit and other storage/structural caps also apply to Pro. Restore purchases is on the offer screen. Pending/cancelled purchases do not unlock; revocation retains existing records and standard exports. No subscription or trial. Price comes from StoreKit; no fixed price is asserted here. Supply the actual candidate's IAP review screenshot separately.
```

## Русская локализация IAP

### Localized IAP display name

<!-- metadata:ru:iap_display_name -->
Count: **18 / 30 characters; 18 UTF-8 bytes**.

```text
Room Inventory Pro
```

### Localized IAP description

<!-- metadata:ru:iap_description -->
Count: **45 / 45 characters; 80 UTF-8 bytes**.

```text
Больше комнат, пакетный импорт, настройка PDF
```

### IAP Review Notes

<!-- metadata:ru:iap_review_notes -->
Count: **751 / 4000 characters; 1299 UTF-8 bytes**.

```text
Room Inventory Pro — разовая покупка (non-consumable) com.alvit.roominventory.pro, не подписка. Предложение открывается через «Подробнее о Pro», при достижении бесплатной квоты или выборе настраиваемого PDF. Pro добавляет больше комнат/предметов в пределах общих лимитов, импорт до десяти изображений для одного предмета и выбор комнат/полей PDF. Бесплатно доступны одна комната и десять предметов суммарно. Лимит 80 МиБ связанных оригиналов и другие ограничения действуют и с Pro. На экране есть «Восстановить покупки». Отменённая или ожидающая покупка не открывает Pro. Отзыв покупки сохраняет записи и обычный экспорт. Пробного периода нет. Цена загружается из StoreKit. Отдельно приложите снимок предложения из фактической сборки для проверки IAP.
```

## App Review instructions

For the configured signed candidate: **app sign-in required — No**. Do not supply invented demo credentials. Apple purchase authentication is separate. Real App Review contact name, email and phone must be supplied by the owner. Use one of the following notes fields after the signed-device/Sandbox gates pass; attach actual candidate screenshots and synthetic examples separately.

## English (U.S.) — review

### App Review Notes

<!-- metadata:en-US:app_review_notes -->
Count: **2725 / 4000 UTF-8 bytes; 2725 characters**.

```text
Room Inventory is a local inventory utility. No app account, login, invitation or developer server is required. Apple purchase authentication is separate; no developer-issued credentials are needed.

Suggested review path (English UI):
1. Add Demo Home, an Office room and a Demo Camera item. Add a photo or document image; choose Item photo, Model / serial label, or Receipt. Camera, Photos and Files accept JPEG/PNG/HEIC images, not PDF documents.
2. Import a synthetic label or receipt. A single label/receipt opens text review after saving; alternatively long-press an attachment and choose Recognize text. OCR runs on-device. Suggestions start unselected; select values and use Apply to confirm changes.
3. Free allows one room and ten items globally across all homes. Add beyond a quota or open Explore Pro to see the offer. Product com.alvit.roominventory.pro is non-consumable; price is loaded from StoreKit. Restore purchases is on the Pro screen.
4. With Pro, select up to ten images in Photos or Files for one existing item. All use the selected purpose. Import results show saved/failed images; retry affects failed images only. No item-per-image creation or automatic batch OCR is performed.
5. Open Export and backup. Standard PDF/CSV/ZIP and the separate .roominventory backup remain available without Pro. Restore via Restore a backup inside the app; direct opening from Files is not supported. Restore replaces the active inventory after confirmation; an invalid backup retains it.
6. With Pro, open Custom PDF report. Select rooms and toggle serial numbers, purchase prices/dates, notes, and attachment names/paths. These options affect this PDF only. The PDF does not embed image files.
7. Existing records, editing, deletion, standard exports and backup restoration remain available after Pro revocation. Pending or cancelled purchases do not unlock Pro. No subscription or trial is offered.

Limits apply to Free and Pro: 80 MiB of linked originals per active inventory; globally 100 homes, 1,000 rooms, 10,000 items and 5,000 originals. Capture imports: 20 MB, 64 megapixels, 16,384 pixels per side. Storage: 25 MiB per original, 4 MiB inventory text, 64 KiB per field. Backups/report ZIPs: 128 MiB; CSV: 16 MiB; PDF: 500 pages. Smaller limits can be reached first; oversized operations fail rather than truncate.

Exports/backups are not encrypted. Files preserves imported bytes; Photos may supply edits/conversions, and camera capture creates JPEG. Images may contain date/location metadata. Removed originals are retained locally until app deletion and can use extra storage. Device backups and selected cloud Files providers may retain copies. There is no automatic valuation or insurance decision.
```

## Русский — review

### App Review Notes

<!-- metadata:ru:app_review_notes -->
Count: **3592 / 4000 UTF-8 bytes; 2040 characters**.

```text
Room Inventory не требует учётной записи или сервера разработчика. Авторизация покупки Apple выполняется отдельно.

1. Добавьте дом «Пример», комнату «Кабинет» и предмет «Камера». Прикрепите тестовое изображение JPEG/PNG/HEIC из камеры, «Фото» или «Файлов». PDF не импортируется.
2. Одиночная маркировка или чек открывает проверку текста; также можно удерживать вложение и выбрать «Распознать текст». Распознавание локальное. Значения изначально не выбраны и меняют запись только после выбора и подтверждения.
3. Бесплатно: одна комната и десять предметов суммарно во всех домах. Превышение лимита или «Подробнее о Pro» открывает предложение. com.alvit.roominventory.pro — разовая покупка, не подписка. Цена поступает из StoreKit; доступна кнопка «Восстановить покупки».
4. Pro: до десяти изображений из «Фото»/«Файлов» для одного предмета с общим назначением. Результаты показывают ошибки; повторяются только неудачные импорты. Предметы не создаются автоматически, группового распознавания нет.
5. «Экспорт и резервная копия»: обычные PDF/CSV/ZIP и копия .roominventory доступны без Pro. Восстановление запускается внутри приложения и заменяет записи после подтверждения; неверная копия их сохраняет.
6. «Настраиваемый отчёт PDF · Pro»: выбор комнат, серийных номеров, покупки, заметок, имён/путей вложений. Меняется только PDF; изображения не встраиваются.

После отзыва Pro записи, редактирование, удаление, обычный экспорт и восстановление доступны. Ожидающая или отменённая покупка не активирует Pro. Пробного периода нет.

Для всех версий: 80 МиБ связанных оригиналов; всего до 100 домов, 1000 комнат, 10 000 предметов, 5000 оригиналов. Импорт: 20 МБ, 64 Мп, сторона 16 384 пикселя. Меньший лимит может сработать раньше.

Экспорт и копии не зашифрованы. В изображениях возможны метаданные. «Фото» может передать изменённую версию, камера создаёт JPEG. Удалённые оригиналы остаются до удаления приложения и занимают дополнительное место. Копии устройства и облачных провайдеров управляются отдельно. Автооценки и страховых решений нет.
```

## Product and storage facts to preserve in every locale

The Free quota is **one room and ten items across the entire active inventory**, not per home. Pro adds room/item capacity, up to ten selected images per batch for one existing item, and custom PDF options. Each batch uses one attachment purpose. A batch does not create separate items or automatically recognize all images. Failed images may be retried without resaving successful ones.

Custom PDF options select rooms and control serial numbers, purchase prices/dates, notes and attachment names/paths. They change only the new PDF; they do not redact stored data or other export formats. PDF reports do not embed image files. Basic PDF/CSV/ZIP and restorable backup export/restore remain available without Pro, including for an inventory above Free quotas after revocation. Restoring an app backup does not restore an Apple purchase entitlement.

Independent limits apply to both Free and Pro; reaching any one stops the operation:

- Across the active inventory: **100 homes, 1000 rooms, 10,000 items, 5000 originals, 80 MiB of linked original bytes**.
- Stored data: **25 MiB per original, 4 MiB of inventory text, 64 KiB per text field**. Current capture/import UI is narrower: **20 MB (20,000,000 bytes), 64 megapixels and 16,384 pixels per side**, JPEG/PNG/HEIC only.
- Output: **128 MiB per backup/report ZIP, 16 MiB per CSV, 500 PDF pages**. Oversized operations fail rather than silently truncate; smaller file/text limits can apply before the structural caps.
- Removed originals remain in local recovery storage until app deletion. They can use extra device storage beyond the active inventory's 80 MiB. Exported copies and operating-system/cloud backups must be managed separately.

No app account or developer server is required. OCR is on-device and suggested field changes require explicit selection and confirmation. Exports and backups are **not encrypted**. Files preserves selected bytes; Photos can supply an edited/converted representation, and camera capture creates JPEG. The app does not promise an untouched camera asset, stripped metadata, unlimited storage, hosted sync, automatic valuation or insurance approval.

Source anchors: [Free quotas](../App/InventoryStore.swift), [batch import](../App/BatchImageImport.swift), [attachment UI](../App/Views/AttachImageSheet.swift), [report controls](../App/Views/CustomReportSheet.swift), [report projection](../Core/Sources/InventoryCore/InventoryReportOptions.swift), [global limits](../Core/Sources/InventoryCore/InventoryError.swift), [image limits](../App/ImageInput.swift), [exports](../App/ExportService.swift), [StoreKit](../App/ProStore.swift), [localization](localization.md), [privacy](privacy.md) and [recovery/support](support.md).

## Screenshot handoff

Capture the actual candidate in each language using one consistent synthetic inventory: Demo Home / Office / Demo Camera, Desk Lamp, Monitor and Headphones; Russian equivalents may be used. Mark the sample receipt SAMPLE / ОБРАЗЕЦ, use invented serial numbers and amounts, and include no household photos, addresses or private documents.

1. Finished room with recognizable items: the main task.
2. Item photo, label, receipt and confirmed model/serial/purchase details.
3. Text review with unselected/selectable suggestions and the confirmation action. The original image is in the separate attachment preview, not on this review screen.
4. Suggested missing details, shown as optional guidance.
5. Up to ten selected images for the same item and the real batch-result screen.
6. Custom PDF room/detail controls, followed by the matching generated output.
7. Standard exports and the separate restorable backup flow; do not imply that the report ZIP restores the app.
8. Actual Pro offer with Restore purchases. Any visible price must be the verified localized StoreKit value for that candidate/storefront; keep simulated-price screenshots internal.

The [screenshot candidate set](app-store/screenshots/README.md) contains seven real captures with EN/RU iPhone and 13-inch iPad coverage. Its manifest retains source SHA, build, device/runtime, locale, dimensions and raw/candidate hashes. Select the strongest accurate set for the final signed build. These Simulator assets do not establish upload acceptance or physical-device accessibility validation; no selected image shows simulated IAP pricing.

## Public repository candidates and final URL gates

The review branch provides the following candidate document locations in the public repository. These are changeable review URLs; the acceptance report records their unauthenticated response and exact committed-content URLs after push. They are not a claim that App Store Connect has accepted them or that `main` already contains this version.

- [Privacy policy candidate — English](https://github.com/4alvit/room-inventory-ios/blob/feat/initial-public-preview-20261024/docs/privacy.md)
- [Privacy policy candidate — Russian](https://github.com/4alvit/room-inventory-ios/blob/feat/initial-public-preview-20261024/docs/privacy.ru.md)
- [Support candidate — English](https://github.com/4alvit/room-inventory-ios/blob/feat/initial-public-preview-20261024/docs/support.md)
- [Support candidate — Russian](https://github.com/4alvit/room-inventory-ios/blob/feat/initial-public-preview-20261024/docs/support.ru.md)
- [Public issue channel](https://github.com/4alvit/room-inventory-ios/issues): only non-sensitive reports; never post receipts, personal inventory or identity/payment information.

The owner must still confirm the final Privacy Policy URL, final Support URL and actual support contact information. Stable `main` document URLs depend on the reviewed PR being merged and its contents being verified. A separate marketing URL is not supplied.

Apple's [app-information reference](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information) requires a privacy policy URL for iOS; its [version-information reference](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information) requires a support URL leading to actual contact information. Repository issue links do not supply a person's email, phone or legal identity. No personal contact details have been invented here.

## Remaining owner and submission gates

- Select the exact signed Release archive/source/build, confirm enrolled team ownership of `com.alvit.roominventory` and registration/type of `com.alvit.roominventory.pro`.
- Validate the signed candidate on supported physical iPhone/iPad devices, and record fresh-install Sandbox purchase, cancellation, pending approval, restoration and revocation behavior. Check retained records/basic exports without Pro, offline access, camera/Photos/Files permissions, OCR confirmation, interrupted imports, low storage and corrupt backups. Do not substitute Simulator or unsigned-device compilation evidence for these gates.
- Confirm the actual localized StoreKit price and product availability; prepare real IAP review screenshots. No numeric production price, trial, Family Sharing entitlement or revenue is asserted by this copy.
- Owner selects the App Store primary language, the app-level download price and country/region availability separately from IAP pricing/availability, and the release setting: manual, automatic after approval, or automatic no earlier than an owner-selected date. These choices remain unset in this draft.
- Supply developer/seller identity, SKU, copyright owner/year, review/support contact details and any required owner-managed agreements. Category suggestions remain Productivity (primary) and Utilities (optional secondary); the owner chooses the actual classification.
- Review final App Privacy, age-rating, content-rights and encryption/export questionnaire answers against the shipped binary and dependencies. This document supplies no fabricated legal answers or compliance attestation. Use the build-matched privacy/support text and verified public URLs.
- Review final EN/RU copy and screenshots, upload through the authorized Apple workflow, and separately confirm TestFlight, App Review and storefront availability. Current source and CI evidence establish none of those external states.
