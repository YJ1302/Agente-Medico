# EXCEL IMPORT WORKFLOW — UPeU Internado 360 (Batch 2F)

Safe, human-confirmed bulk import from Excel. **No file is ever imported
automatically.**

## Supported files

`.xlsx` and `.xlsm` only. `.xls` is not supported. Every upload is validated for
extension, MIME type, size (`IMPORT_MAX_MB`, default 8 MB), workbook readability,
malformed workbook and duplicate sheet names (`app/services/excel_reader.py`).
Uploaded files are stored **outside** `app/static` (`var/imports/`) and deleted
after import unless `IMPORT_RETAIN_FILES` is enabled.

## Workflow

```
Upload → Select sheet → Detect headers → Map columns → Validate (dry-run)
       → Preview + warnings/errors → Choose mode → Confirm → Import (transactional) → Result
```

Each step is a POST + CSRF-protected route; the batch advances through statuses
`uploaded → mapped → validated → confirmed | partial | cancelled | failed`.

## Import modes

| Mode | Behaviour |
|------|-----------|
| `create_only` | Create new rows; a row matching an existing record is an **error**. |
| `update_existing` | Update matched rows; a row with no match is **skipped**. |
| `skip_duplicates` | Create new rows; matched rows are **skipped**. |
| `valid_only` | Upsert the valid rows; invalid rows are skipped (**partial**). |
| `all_or_nothing` | If **any** row has an error, the whole import is cancelled (rollback). |

## Safety guarantees

- **Transactional**: an import writes all rows in a single commit; `all_or_nothing`
  writes nothing when any error exists.
- **Reuses existing services**: validation reuses the authoritative per-entity
  service validators and the rotation conflict engine — business rules are never
  bypassed (DECISIONS_LOG D-029).
- **Stale-confirmation guard**: the confirmation is rejected if the file or mapping
  changed since validation (a SHA-256 of file + sheet + mapping is compared).
- **Duplicate confirmation prevented**: only a `validated` batch can be confirmed.
- **Idempotent re-import**: `skip_duplicates` / `update_existing` re-runs create no
  duplicates.
- **Row limit**: `IMPORT_MAX_ROWS` (default 2000) bounds processing; read-only
  streaming avoids loading huge files fully into memory.
- **Downloadable error report**: `GET /imports/{id}/errors.xlsx`.

## Pages

Import center, new-import, sheet selector, column mapping, preview + validation
summary, confirm, result, history, batch detail, and the error-report download.
Counts shown: total, valid, warnings, errors, created, updated, skipped, failed.

## Profiles

Students, sedes, tutors, coordinators, rotations, grade components — see
`IMPORT_PROFILE_CATALOG.md`.

## Known limitations

- No `.xls` (legacy) support.
- Cross-sheet consistency (e.g. a student present in one sheet but not another) is
  detected within grade imports per sheet, not across a whole workbook.
- No background/async processing; imports run inline within the request.
