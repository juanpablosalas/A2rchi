# Change: Move metadata catalog storage to Postgres

## Why
Metadata for ingested resources is currently stored in a local SQLite catalog
(`catalog.sqlite`). This makes it harder to share catalog state across
containers and to manage backups alongside other deployment data. Moving the
catalog to Postgres aligns metadata storage with existing services and improves
operational consistency.

## What Changes
- Introduce a Postgres-backed catalog table for resource metadata.
- Update catalog read/write paths to use Postgres as the source of truth.
- Deprecate the SQLite catalog (`catalog.sqlite`) without migrating old entries.
- Keep the CatalogService API stable for callers (uploader, vectorstore,
  integrations).

## Impact
- Affected code: `src/data_manager/collectors/utils/index_utils.py`,
  `src/data_manager/collectors/persistence.py`,
  `src/data_manager/vectorstore/manager.py`,
  `src/interfaces/uploader_app/app.py`,
  `src/interfaces/redmine_mailer_integration/redmine.py`.
- Deployment: Postgres becomes required for catalog operations; existing
  deployments start storing new metadata in Postgres without migrating legacy
  SQLite data. The CLI already auto-enables the Postgres service for deployments.
