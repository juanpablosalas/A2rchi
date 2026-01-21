# Metadata Indexing Spec: File Name First

Status: Draft

## Context

Metadata is currently split between first-class catalog columns and free-form
extras. `display_name` is a required, indexed column, but the desired behavior
is the opposite: `file_name` should be required and searchable, while
`display_name` should be optional and used only for UI visualization.

## Goals

- Require `file_name` for every resource and use it as the primary searchable
  name field.
- Keep `display_name` optional and UI-focused (no filtering/indexing).
- Centralize the list of indexed metadata keys so the catalog schema is driven
  by a single definition.

## Non-Goals

- Removing `display_name` usages from UI surfaces.
- Introducing new resource types or changing ingestion flows beyond metadata.

## Proposed Data Model

### ResourceMetadata

- Fields:
  - `file_name: str` (required, non-empty)
  - `extra: Dict[str, str]` (free-form, may include `display_name`)
- Serialization (`as_dict`):
  - Returns `{"file_name": file_name, **extra}`
- Validation:
  - `file_name` must be a non-empty string.
  - `extra` keys and values must be strings.

### Indexed Metadata Keys

Define a single constant in `a2rchi/src/data_manager/collectors/utils/metadata.py`
and use it to build the catalog schema.

Initial set:

- `file_name`
- `source_type`
- `url`
- `ticket_id`
- `suffix`
- `size_bytes`
- `original_path`
- `base_path`
- `relative_path`
- `created_at`
- `modified_at`
- `ingested_at`

Notes:
- `display_name` is intentionally not indexed.
- `path` is reserved for catalog file paths and should not be reused as
  metadata.

## Catalog Changes

### Schema

- Add a `file_name` column to the `resources` table.
- Keep the existing `display_name` column for compatibility, but treat it as a
  derived field (see below).

### Upsert Behavior

- Populate `file_name` from metadata (required).
- Don't populate display_name` column unless explicitly provided.
- Store `display_name` in `extra_json` only when explicitly provided.

### Search

- Use `file_name` as the primary name field for text search.
- Remove `display_name` from search filters (keep in `extra_text` only).

## Resource Updates

All resources should provide `file_name` explicitly and only include
`display_name` when a nicer UI label exists.

- `ScrapedResource`: `file_name = get_filename()`, optional `display_name` from
  `_format_link_display`.
- `TicketResource`: `file_name = get_filename()`, optional `display_name` from
  ticket URL or `{source_type}:{ticket_id}`.
- `LocalFileResource`: `file_name = get_filename()`, optional `display_name`
  using relative path if available.

## UI/Consumer Updates

UI surfaces should:

- Prefer `display_name` for visualization when present.
- Fall back to `file_name` when `display_name` is absent.

Key call sites:

- `a2rchi/src/interfaces/chat_app/app.py`
- `a2rchi/src/interfaces/uploader_app/app.py`
- `a2rchi/src/utils/generate_benchmark_report.py`
- `a2rchi/src/bin/service_benchmark.py`

## Migration Plan

1. Add `file_name` column to the SQLite schema with `_ensure_column`.
2. Backfill `file_name` for existing rows where it is NULL:
   - Use `basename(path)` as the default.
3. Update upsert logic to require `file_name` and leave `display_name` empty
   unless explicitly provided.

## Testing/Verification

- Unit tests for `ResourceMetadata` validation and `as_dict`.
- Catalog upsert/read tests that assert:
  - `file_name` is persisted and searchable.
  - `display_name` is optional and preferred from extras.
- UI smoke check for display name fallback behavior.

## Risks

- Existing features that filter on `display_name` may need updates to use
  `file_name` (e.g., benchmarking defaults). If needed, keep
  `display_name` as an optional filter via `extra_text` until callers are
  updated.
