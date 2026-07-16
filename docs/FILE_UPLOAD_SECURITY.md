# FILE UPLOAD SECURITY — UPeU Internado 360 (Batch 2E)

Local, offline secure attachment support for documents and incidents. Implemented
in `app/services/attachment_service.py`, backed by the polymorphic `attachments`
table.

## Allowed file types

PDF, DOCX, XLSX, XLSM, PNG, JPG/JPEG. Every other extension is rejected.

## Validation pipeline (all must pass)

1. **Extension whitelist** — the basename extension must be one of the allowed set.
2. **MIME agreement** — the declared `Content-Type` must be an accepted MIME for
   that extension.
3. **Size limit** — configurable via `settings.attachment_max_mb` (default 10 MB);
   empty files are rejected.
4. **Magic-byte sniff** — the file's leading bytes must match the extension family
   (`%PDF`, PNG signature, JPEG `FF D8 FF`, ZIP `PK` for Office formats). A renamed
   executable therefore fails even if extension and MIME are spoofed.

## Storage & access

- The **original filename is never trusted**: only its basename is stored for
  display; the on-disk name is a server-generated UUID (`<uuid>.<ext>`).
- Files are stored **outside** `app/static` (`settings.attachment_storage_dir`,
  default `var/attachments`) — there are **no public direct URLs**.
- Downloads go only through an **authorized route** that first re-checks view
  scope on the owning document/incident, then streams the file with
  `Content-Disposition: attachment`. Uploaded files are **never executed**.
- **Path traversal is impossible**: the stored path is resolved and verified to be
  inside the storage root before any read/write; only the basename is ever used.

## Deletion rules

- An attachment may be deleted **while the owner is a draft** (document) or **not
  terminal** (incident) by an authorized editor.
- On a **locked** (non-draft / closed) owner, only an **Administrator** may delete
  it, and only with a **documented reason** (audited).
- Deletion is a soft delete (the row is retained for history); the physical file
  is best-effort removed.

## Auditing

Every upload / download / delete is audited:
`upload_document_attachment`, `download_document_attachment`,
`delete_document_attachment`, `upload_incident_attachment`,
`download_incident_attachment`, `delete_incident_attachment`. Audit details store
only metadata (attachment id, original filename, size, MIME) — never file contents.

## Privacy

- A visible privacy warning is shown before every upload: **do not attach clinical
  histories or patient-identifying data.**
- Confidential body text and internal notes are never placed in audit summaries,
  notifications or dashboard snippets.
- Institutional legal/privacy review is required before production use.

## Configuration

```
ATTACHMENT_MAX_MB=10
ATTACHMENT_STORAGE_DIR=var/attachments   # relative to project root; outside static
```
