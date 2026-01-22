## Context
Resource metadata is currently indexed in a local SQLite file (`catalog.sqlite`)
via `CatalogService` in `src/data_manager/collectors/utils/index_utils.py`.
Multiple services (uploader, vectorstore, integrations) read from this catalog.
The deployment already includes a Postgres service for other state, and the CLI
auto-enables Postgres for deployments.

## Goals / Non-Goals
- Goals:
  - Store catalog metadata in Postgres for shared, durable access.
  - Keep the CatalogService public API stable for callers.
- Non-Goals:
  - Change the shape of metadata fields or resource hashing.
  - Redesign the ingestion pipeline or vectorstore interfaces.

## Decisions
- Use a Postgres table mirroring the SQLite `resources` schema
  (resource_hash, path, file_name, display_name, source_type, url, ticket_id,
  suffix, size_bytes, original_path, base_path, relative_path, created_at,
  modified_at, ingested_at, extra_json, extra_text).
- Initialize schema on startup if missing, and keep indexes aligned with the
  existing SQLite schema.
- Deprecate the SQLite catalog; new metadata is stored only in Postgres.
- Use the existing Postgres service configuration from deployment configs.

## Risks / Trade-offs
- Postgres is required for catalog operations; deployments must include the
  Postgres service that the CLI already provisions.
- Existing metadata in SQLite will not be queryable unless re-ingested.

## Migration Plan
1. Create the Postgres table and indexes if missing.
2. Switch CatalogService reads/writes to Postgres.
3. Leave `catalog.sqlite` in place as a deprecated artifact (no longer updated).

## Open Questions
None.
