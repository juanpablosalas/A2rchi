## ADDED Requirements
### Requirement: Postgres metadata catalog
The system SHALL store resource metadata in Postgres and use it for catalog read
and write operations.

#### Scenario: Resource upsert stored in Postgres
- **WHEN** a resource is persisted with metadata
- **THEN** the metadata row is written to the Postgres catalog table
- **AND** subsequent reads return the stored metadata

### Requirement: SQLite catalog deprecation
The system SHALL treat `catalog.sqlite` as deprecated and SHALL NOT import its
rows into Postgres.

#### Scenario: SQLite catalog present on startup
- **WHEN** `catalog.sqlite` exists alongside an empty Postgres catalog
- **THEN** no metadata is imported from SQLite
- **AND** new metadata is written only to Postgres

### Requirement: Catalog API compatibility
The system SHALL preserve the `CatalogService` public API for existing callers.

#### Scenario: Existing callers continue to query metadata
- **WHEN** services request metadata via CatalogService methods
- **THEN** the calls succeed without call-site changes
