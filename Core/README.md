# InventoryCore

Swift 6 package for iOS 17+ and macOS 13+. Run `swift test` in this directory.
There are no network dependencies. All test data is synthetic.

## Persistence and recovery

`InventoryRepository` is a synchronous, thread-safe API. Move heavy work off the
main actor. An instance lock plus a filesystem advisory lock serializes operations
from all cooperating repository instances that use the same root. Read/modify/save
is not one transaction: the application must serialize those sequences itself.

The root has an atomic `inventory.json`, immutable originals in `assets/`, and
`.repository.lock`. Filenames are generated from attachment UUIDs and an allowlisted
media type extension. SHA-256 is checked on every original read and before save,
load, export, or restore. Symlink originals, symlink manifests, paths containing
traversal, duplicate identities, missing originals, and future schema versions are
rejected. Missing manifests create an empty in-memory inventory; malformed manifests
raise an error and are never silently reset. `save` can deliberately replace a
corrupt manifest after the application has obtained a known-good inventory.

Restore validates the entire envelope, inventory, exact original-file set, sizes,
and checksums before writing. It stages all originals and the new manifest, promotes
originals without overwriting existing files, then atomically replaces the manifest.
A failed commit removes only originals introduced by that attempt. Old originals
are never automatically removed. Files and directory entries are flushed before
commit where supported; directory flushes are best-effort. Process interruption may
leave harmless temporary directories or unreferenced originals; none are treated as
the active inventory. This release deliberately avoids automatic orphan cleanup.
If an existing regular original has different bytes under the same generated
filename, restore preserves that file and gives only the recovered attachment a
fresh UUID and generated filename. Home, room, and item identities remain unchanged.
The restored manifest and subsequent backups reference the recovered bytes; the
damaged original stays available on disk for inspection. Non-conflicting restores
preserve all identities exactly. Symlink collisions are still rejected. A known-good
backup can therefore recover both a corrupt manifest and damaged regular originals
in place without overwriting prior bytes.

Explicit orphan cleanup is not exposed yet: attachment import and manifest save
are separate operations, so a reference scan alone could mistake an in-flight
import for garbage. A future cleanup transaction must first stop new import/save
work, wait for pending imports to finish or cancel, lock storage, load and verify
the committed manifest, and retain every referenced file and pending import lease.
It must then recheck the manifest generation before removing only regular files
from the reviewed candidate set. Age thresholds alone cannot provide that safety.

The app uses `appendAttachment` to commit a new original and its item reference
under one storage lock. It validates the destination, resulting manifest and total
original size before writing. If the manifest commit fails, it removes only the
original created by that call, so rejected retries do not accumulate new files.
Previously committed originals remain retained even after removal from an item.
The lower-level `importAttachment` API still creates a retained original separately
from `save`; callers needing the combined operation should use `appendAttachment`.

Filesystem permissions are owner-only (directories `0700`, files `0600`). This is
not application-level encryption: iOS sandbox and system Data Protection apply.
Backup files contain ordinary JSON and base64-encoded original data, not encryption;
users should share them only with intended recipients.

## Portable `.roominventory` backup, version 1

JSON object: `format: "com.alvit.roominventory.backup"`, `version: 1`,
`inventory: <Inventory schemaVersion 1>`, and `files: {"<generated filename>":
"<base64 original bytes>"}`. The backup has exactly one `files` member per referenced
attachment, with no extra files. Original names are metadata, never filesystem paths.
The same generated names appear in CSV as `originals/<item UUID>/<filename>`,
matching the ZIP package so exports retain the full item-to-original association.

Limits are exposed in `InventoryLimits`: 25 MiB per original, 80 MiB of originals
per inventory, 4 MiB of manifest JSON, 128 MiB per encoded backup, 64 KiB per text
field, 100 homes, 1,000 rooms, 10,000 items, and 5,000 attachments. Free/Pro product
limits are separate application policy. Restore does not impose Free limits.
Supported original MIME types: JPEG, PNG, HEIC, HEIF, and PDF. The repository verifies
integrity and bounded storage; it does not certify that bytes are a valid image or PDF.
Decoders must still handle malformed content safely. Backup parsing is bounded by
encoded file size, but may temporarily use several times that size in memory; callers
must serialize exports/restores and enforce the file-size limit before loading an
external backup into memory.

CSV rendering is incremental and throws if the output would exceed 16 MiB.
The budget includes UTF-8, quote escaping, formula-defense prefixes and row separators.
No partial table is returned. A repeated attachment table can exceed this limit
even when its source manifest fits; the restorable backup remains available.

CSV uses UTF-8 with quoted fields and CRLF row endings, doubles embedded quotation
marks, and prefixes formula-looking fields (including leading whitespace/control
characters) with an apostrophe. Every item has at least one row; each original adds
its own row with stable home, room, item, and attachment IDs. Formula defense can
alter a value's spreadsheet display; original values remain in the backup.
