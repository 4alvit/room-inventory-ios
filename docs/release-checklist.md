# Application release checklist

Record evidence against an exact source SHA and candidate tag. Unchecked items are
requirements, not implied passes. A successful compile or source archive is not
evidence that UI, purchases or physical devices passed acceptance.

## GitHub development preview

- [ ] Source metadata and vendored release/workflow contracts pass.
- [ ] Core tests pass, including round-trip backup, unsafe paths, corruption, failed restore, CSV safety and concurrency.
- [ ] Generic iOS Simulator Release build succeeds without signing.
- [ ] App unit/UI tests pass on a named iPhone Simulator/runtime; preserve the result bundle.
- [ ] Capture/import, explicit OCR review, missing-material states and navigation are exercised with synthetic data.
- [ ] Export PDF/CSV/ZIP contents are inspected; all original links identify the right item/file.
- [ ] Free limits apply across all homes; existing records/exports/restore remain accessible without Pro.
- [ ] StoreKit tests cover verified purchase, cancellation, pending, restore, refund/revocation and offline behavior.
- [ ] Failed save/restore and insufficient-space errors preserve previous data; interruption and recovery behavior are documented.
- [ ] Supported iOS languages, English fallback, plural forms, regional formats, localized OCR/export, and Release localization resources are checked.
- [ ] Dynamic Type, VoiceOver labels/order, contrast and empty/error/loading states are checked.
- [ ] Independent code/security review findings are fixed or explicitly tracked with release impact.
- [ ] Hosted CI gate and CodeQL pass for the exact published source SHA.
- [ ] Build source and unsigned Simulator packages from a clean checkout; verify SHA256SUMS and inspect the extracted preview.
- [ ] Release notes state storage/recovery limitations and identify the artifact as unsigned Simulator preview.
- [ ] Configure the repository release environment/permissions and enable candidate publication only after the workflows are ready.
- [ ] Publish an honest GitHub prerelease through the gated pipeline; do not label it an App Store release.

## RC and stable source/Simulator acceptance

- [ ] The exact RC artifacts have been installed/exercised on supported Simulators.
- [ ] No unresolved release-blocking correctness, privacy or data-loss issues remain.
- [ ] The source SHA, tag, test runtime and reviewer evidence are recorded.
- [ ] Promote the verified RC through the protected release environment without replacing payload bytes.

## Device distribution and App Store release — separate work

- [ ] The owner provides an enrolled Apple Developer team and valid signing configuration.
- [ ] An authorized human completes any Apple legal, paid-app, banking and tax agreements.
- [ ] Configure App Store Connect app identity and the non-consumable product; verify real localized storefront prices.
- [ ] Test signed builds on physical iPhone/iPad devices, including permissions, camera, low storage, interruption, offline restart and large inventories.
- [ ] Validate StoreKit sandbox/TestFlight purchase, restoration and revocation paths independently of local `.storekit` simulations.
- [ ] Confirm privacy manifest/API reasons and App Privacy disclosures against the release binary.
- [ ] Publish reachable privacy/support pages and complete app icon, screenshots, accessibility and store metadata review.
- [ ] Verify bundled EN/RU privacy/support reading without Pro, review it against the signed build, and replace preview links with verified final policy/support destinations when operator/contact details are complete.
- [ ] Create a signed archive with the team's credentials, validate/export it in Xcode and upload through authorized App Store tooling.
- [ ] Complete TestFlight acceptance and Apple's review; confirm actual storefront availability before claiming release or sales.

Do not put signing keys, provisioning profiles, personal test data, Terraform state,
private machine logs or internal harness traces in the public repository or release.
