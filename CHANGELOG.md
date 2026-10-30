# Changelog

## Unreleased

- Build same-repository PR Simulator candidates on GitHub-hosted macOS, with verified tested-tree identity and payload provenance, without publishing a release.
- Add an offline English and Russian privacy/support page from the main screen, available without Pro. It explains local data, deletion, sharing, backups and public support, with optional links to published preview documents.

## [0.1.0] - development preview

### Added

- English and Russian UI, accessibility text, errors, permission text and report captions selected automatically from iOS language preferences.
- Russian receipt/label OCR suggestions, regional display formatting and separate translated CSV output while machine CSV and backups retain their stable formats.

- Native iOS room/item inventory with photo import, receipt/label attachments and explicit OCR review.
- Local manifests and originals with checksums, atomic saves and validated backup restore.
- PDF, CSV and original-file report packages; Free users retain viewing, basic export and restore.
- StoreKit 2 non-consumable Pro flow and a local USD 19.99 test configuration.
- Core regression tests, Simulator/app validation, CodeQL and gated unsigned preview packaging.
- Pro batch image import with per-file outcomes and retry of failed files only.
- Pro custom PDFs with room selection and optional serial numbers, purchase details, notes and attachment paths.

This entry describes development scope, not a completed App Store publication.
Production StoreKit configuration, device signing, Apple agreements, real-device
acceptance and App Review remain separate requirements.

### Fixed

- Unsigned Release previews omit build-machine paths and code-coverage data; packaging rejects app payloads that retain them.
- PDF fonts preserve exact Cyrillic text for copying and searching, including the letter к.

- Singular inventory counts and word-aware PDF line wrapping.
- Removed unsupported Open In document-editor registration; restore remains available through the in-app Files picker.
- Preview/OCR errors no longer promise that a missing or damaged original can be exported.
- Entitlement refresh ordering prevents an older scan from replacing a newer result.

### Upgrade

This is the initial development preview. Preserve a `.roominventory` backup before
changing builds or uninstalling. Storage currently permits 80 MiB of originals per
inventory. When a regular original filename has conflicting bytes, restoration
preserves the old file and remaps only the recovered attachment. Home, room and
item identities remain unchanged. Unreferenced originals are not automatically deleted.

### Security

Backups and report packages are not encrypted and can contain original photo
metadata. Share them only with intended recipients. The repository checks paths,
sizes and SHA-256 integrity and rejects symlink originals. No device-signing keys,
personal inventories or real purchase records belong in public fixtures or releases.
