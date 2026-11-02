# App Store screenshot candidates

Seven real Simulator captures cover English and Russian on iPhone and 13-inch
iPad. These are review candidates, not screenshots accepted or uploaded by Apple.
The owner still chooses the final storefront set after signed-build validation.

| Locale | Device | Candidates |
| --- | --- | --- |
| English (U.S.) | iPhone, 1206 × 2622 | [Inventory](en-US/iphone-01-inventory.png), [Item details](en-US/iphone-02-item.png) |
| Russian | iPhone, 1206 × 2622 | [Inventory](ru/iphone-01-inventory.png), [Item details](ru/iphone-02-item.png), [Review recognized text](ru/iphone-03-ocr.png) |
| English (U.S.) | iPad 13-inch, 2064 × 2752 | [Inventory](en-US/ipad-01-inventory.png) |
| Russian | iPad 13-inch, 2064 × 2752 | [Inventory](ru/ipad-01-inventory.png) |

The iPhone uses the existing synthetic **Originals QA / Studio / QA Desk Lamp**
inventory. The iPad uses **Demo Home / Office / Demo Camera**, entered through
the normal application UI. User-entered names are intentionally unchanged by
language selection. Item purchase amounts shown in the record are invented
fixture data, not the price of Pro. No selected image shows an IAP price.

The [manifest](manifest.json) records source commits, raw and candidate SHA-256,
dimensions, device/runtime and transformations. The Russian iPhone captures were
reused from `af4587e`; its App and Core source trees match `68041c3`. Other captures
use the accepted `68041c3` Release preview, version 0.1.0 (1). Raw images remain in
the local QA evidence; the committed PNGs remove only fully opaque alpha and
nonessential file metadata. Every RGB pixel and the sRGB color intent are
preserved. There is no resizing, generated UI, caption overlay or price overlay.

The current English OCR capture is internal-only because its real navigation
title is truncated. Previous purchase screenshots remain internal because their
prices are simulated. Historical 11-inch iPad captures do not fill the required
13-inch slot. No application code or purchase configuration was changed to make
these assets.

Checked against Apple's [screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)
on 2026-10-25: at least one and up to ten images per device size; a supported
Dynamic Island medium-display iPhone size and a 13-inch iPad size; no alpha.
All four locale/device slots above have a candidate that meets these format
checks. Recheck the actual App Store Connect upload result before submission.
