from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras
from langchain_core.documents import Document

from src.data_manager.collectors.utils.metadata import INDEXED_METADATA_KEYS
from src.data_manager.vectorstore.loader_utils import load_doc_from_path
from src.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".pdf",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".tsv",
    ".html",
    ".htm",
    ".log",
    ".py",
    ".c",
    ".cpp",
    ".C",
    ".h",
}

_METADATA_COLUMN_MAP = {key: key for key in INDEXED_METADATA_KEYS}


@dataclass
class CatalogService:
    """Expose lightweight access to catalogued resources and metadata (Postgres)."""

    data_path: Path | str
    pg_config: Dict[str, Any]
    include_extensions: Sequence[str] = field(default_factory=lambda: sorted(DEFAULT_TEXT_EXTENSIONS))
    # in memory indices
    _file_index: Dict[str, str] = field(init=False, default_factory=dict)
    _metadata_index: Dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.data_path = Path(self.data_path)
        if self.include_extensions:
            self.include_extensions = tuple(ext.lower() for ext in self.include_extensions)
        self._validate_pg_config()
        self._init_db()
        self.refresh()

    def refresh(self) -> None:
        """Reload file and metadata indices from Postgres."""
        logger.debug("Refreshing catalog indices from Postgres")
        self._file_index = {}
        self._metadata_index = {}
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT resource_hash, path FROM resources")
                rows = cursor.fetchall()
        for row in rows:
            resource_hash = row["resource_hash"]
            stored_path = row["path"]
            self._file_index[resource_hash] = stored_path
            self._metadata_index[resource_hash] = stored_path

    @property
    def file_index(self) -> Dict[str, str]:
        return self._file_index

    @property
    def metadata_index(self) -> Dict[str, str]:
        return self._metadata_index

    def upsert_resource(
        self,
        resource_hash: str,
        path: str,
        metadata: Optional[Dict[str, str]],
    ) -> None:
        payload = metadata or {}
        file_name = payload.get("file_name") or Path(path).name
        display_name = payload.get("display_name")
        source_type = payload.get("source_type") or "unknown"
        logger.debug("Upserting resource %s (%s) -> %s", resource_hash, source_type, path)

        extra = dict(payload)
        for key in _METADATA_COLUMN_MAP:
            extra.pop(key, None)

        extra_json = json.dumps(extra, sort_keys=True)
        extra_text = _build_extra_text(payload)

        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO resources (
                        resource_hash,
                        path,
                        file_name,
                        display_name,
                        source_type,
                        url,
                        ticket_id,
                        suffix,
                        size_bytes,
                        original_path,
                        base_path,
                        relative_path,
                        created_at,
                        modified_at,
                        ingested_at,
                        extra_json,
                        extra_text
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(resource_hash) DO UPDATE SET
                        path=excluded.path,
                        file_name=excluded.file_name,
                        display_name=excluded.display_name,
                        source_type=excluded.source_type,
                        url=excluded.url,
                        ticket_id=excluded.ticket_id,
                        suffix=excluded.suffix,
                        size_bytes=excluded.size_bytes,
                        original_path=excluded.original_path,
                        base_path=excluded.base_path,
                        relative_path=excluded.relative_path,
                        created_at=excluded.created_at,
                        modified_at=excluded.modified_at,
                        ingested_at=excluded.ingested_at,
                        extra_json=excluded.extra_json,
                        extra_text=excluded.extra_text
                    """,
                    (
                        resource_hash,
                        path,
                        file_name,
                        display_name or "",
                        source_type,
                        payload.get("url"),
                        payload.get("ticket_id"),
                        payload.get("suffix"),
                        _coerce_int(payload.get("size_bytes")),
                        payload.get("original_path"),
                        payload.get("base_path"),
                        payload.get("relative_path"),
                        payload.get("created_at"),
                        payload.get("modified_at"),
                        payload.get("ingested_at"),
                        extra_json,
                        extra_text,
                    ),
                )

        self._file_index[resource_hash] = path
        self._metadata_index[resource_hash] = path

    def delete_resource(self, resource_hash: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM resources WHERE resource_hash = %s", (resource_hash,))
        self._file_index.pop(resource_hash, None)
        self._metadata_index.pop(resource_hash, None)

    def get_resource_hashes_by_metadata_filter(self, metadata_field: str, value: str) -> List[str]:
        """
        Return resource hashes whose metadata contains ``metadata_field`` equal to ``value``.
        """
        matches = self.get_metadata_by_filter(metadata_field, value=value)
        return [resource_hash for resource_hash, _ in matches]

    def get_metadata_by_filter(
        self,
        metadata_field: str,
        value: Optional[str] = None,
        metadata_keys: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Return (resource_hash, metadata) pairs whose metadata contains ``metadata_field``.

        If ``value`` is provided, only entries where ``metadata_field`` equals ``value`` are returned.
        If ``metadata_keys`` is provided, only those keys are included in the returned metadata.
        """
        if value is None and metadata_field in kwargs:
            value = kwargs[metadata_field]

        matches: List[Tuple[str, Dict[str, Any]]] = []

        column = _METADATA_COLUMN_MAP.get(metadata_field)
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if column:
                    if value is None:
                        cursor.execute(
                            f"SELECT * FROM resources WHERE {column} IS NOT NULL AND {column} != ''"
                        )
                    else:
                        cursor.execute(
                            f"SELECT * FROM resources WHERE {column} = %s",
                            (str(value),),
                        )
                else:
                    cursor.execute("SELECT * FROM resources")
                rows = cursor.fetchall()

        expected = str(value) if value is not None else None
        for row in rows:
            metadata = self._row_to_metadata(row)
            if metadata_field not in metadata:
                continue
            if expected is not None and metadata.get(metadata_field) != expected:
                continue
            if metadata_keys:
                metadata = {k: metadata[k] for k in metadata_keys if k in metadata}
            matches.append((row["resource_hash"], metadata))
        return matches

    def search_metadata(
        self,
        query: str,
        *,
        limit: Optional[int] = 5,
        filters: Optional[Dict[str, str] | List[Dict[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        if not query and not filters:
            return []

        where_clauses: List[str] = []
        params: List[object] = []

        if filters:
            filter_groups: List[Dict[str, str]] = []
            if isinstance(filters, list):
                filter_groups = [group for group in filters if isinstance(group, dict)]
            elif isinstance(filters, dict):
                filter_groups = [filters]

            if filter_groups:
                group_clauses: List[str] = []
                group_params: List[object] = []
                for group in filter_groups:
                    sub_clauses: List[str] = []
                    for key, value in group.items():
                        column = _METADATA_COLUMN_MAP.get(key)
                        if column:
                            sub_clauses.append(f"{column} = %s")
                            group_params.append(str(value))
                        else:
                            sub_clauses.append("extra_text LIKE %s")
                            group_params.append(f"%{key}:{value}%")
                    if sub_clauses:
                        group_clauses.append("(" + " AND ".join(sub_clauses) + ")")
                if group_clauses:
                    where_clauses.append("(" + " OR ".join(group_clauses) + ")")
                    params.extend(group_params)

        if query:
            like = f"%{query}%"
            where_clauses.append(
                (
                    "(file_name LIKE %s OR source_type LIKE %s OR url LIKE %s OR ticket_id LIKE %s "
                    "OR path LIKE %s OR original_path LIKE %s OR relative_path LIKE %s OR extra_text LIKE %s)"
                )
            )
            params.extend([like, like, like, like, like, like, like, like])

        sql = "SELECT * FROM resources"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        sql += " ORDER BY COALESCE(modified_at, created_at, ingested_at, '') DESC"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(int(limit))

        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            path = self._resolve_path(row["path"])
            results.append(
                {
                    "hash": row["resource_hash"],
                    "path": path,
                    "metadata": self._row_to_metadata(row),
                }
            )
        return results

    def iter_files(self) -> Iterable[Tuple[str, Path]]:
        for resource_hash, stored_path in self._file_index.items():
            path = self._resolve_path(stored_path)
            if not path.exists():
                logger.debug("File for resource hash %s not found; skipping.", resource_hash)
                continue
            if self.include_extensions and path.suffix.lower() not in self.include_extensions:
                logger.debug("File %s has excluded extension; skipping.", path)
                continue
            yield resource_hash, path

    def get_metadata_for_hash(self, hash: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM resources WHERE resource_hash = %s", (hash,)
                )
                row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_metadata(row)

    def get_filepath_for_hash(self, hash: str) -> Optional[Path]:
        stored = self._file_index.get(hash)
        if not stored:
            return None
        path = self._resolve_path(stored)
        return path if path.exists() else None

    def get_document_for_hash(self, hash: str) -> Optional[Document]:
        """
        Reconstruct a Document for the given resource hash, combining content and metadata.
        """
        path = self.get_filepath_for_hash(hash)
        if not path:
            return None
        doc = load_doc_from_path(path)
        metadata = self.get_metadata_for_hash(hash)
        if doc and metadata:
            doc.metadata.update(metadata)
        return doc

    @classmethod
    def load_sources_catalog(
        cls,
        data_path: Path | str,
        pg_config: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Convenience helper that returns the resource index mapping with absolute paths.
        """
        base_path = Path(data_path)

        with psycopg2.connect(**pg_config) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT resource_hash, path FROM resources")
                rows = cursor.fetchall()

        resolved: Dict[str, str] = {}
        for row in rows:
            stored_path = row["path"]
            path = Path(stored_path)
            if not path.is_absolute():
                path = (base_path / path).resolve()
            resolved[row["resource_hash"]] = str(path)
        return resolved

    def _init_db(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS resources (
                        resource_hash TEXT PRIMARY KEY,
                        path TEXT NOT NULL,
                        file_name TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        url TEXT,
                        ticket_id TEXT,
                        suffix TEXT,
                        size_bytes BIGINT,
                        original_path TEXT,
                        base_path TEXT,
                        relative_path TEXT,
                        created_at TEXT,
                        modified_at TEXT,
                        ingested_at TEXT,
                        extra_json TEXT NOT NULL,
                        extra_text TEXT
                    )
                    """
                )
                self._ensure_column(cursor, "file_name", "TEXT")
                self._ensure_column(cursor, "extra_text", "TEXT")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_resources_source_type ON resources(source_type)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_resources_url ON resources(url)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_resources_ticket_id ON resources(ticket_id)"
                )
                self._backfill_file_names(cursor)

    def _connect(self) -> psycopg2.extensions.connection:
        return psycopg2.connect(**self.pg_config)

    def _ensure_column(self, cursor: psycopg2.extensions.cursor, column: str, column_type: str) -> None:
        cursor.execute(f"ALTER TABLE resources ADD COLUMN IF NOT EXISTS {column} {column_type}")

    def _backfill_file_names(self, cursor: psycopg2.extensions.cursor) -> None:
        cursor.execute(
            "SELECT resource_hash, path, file_name FROM resources WHERE file_name IS NULL OR file_name = ''"
        )
        rows = cursor.fetchall()
        for row in rows:
            stored_path = row[1]
            if not stored_path:
                continue
            file_name = Path(stored_path).name
            if not file_name:
                continue
            cursor.execute(
                "UPDATE resources SET file_name = %s WHERE resource_hash = %s",
                (file_name, row[0]),
            )

    def _resolve_path(self, stored_path: str) -> Path:
        path = Path(stored_path)
        if not path.is_absolute():
            path = (self.data_path / path).resolve()
        return path

    def _row_to_metadata(self, row: Dict[str, Any]) -> Dict[str, str]:
        data = dict(row)
        metadata: Dict[str, str] = {}

        extra_json = data.get("extra_json") or "{}"
        try:
            extra = json.loads(extra_json) or {}
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse extra_json for %s: %s", data.get("resource_hash"), exc)
            extra = {}

        if isinstance(extra, dict):
            for key, value in extra.items():
                if value is None:
                    continue
                metadata[str(key)] = str(value)

        display_name = metadata.get("display_name") or data.get("display_name")
        if display_name:
            metadata["display_name"] = str(display_name)

        for key, column in _METADATA_COLUMN_MAP.items():
            value = data.get(column)
            if value is None or value == "":
                continue
            metadata[key] = str(value)

        if "file_name" not in metadata:
            stored_path = data.get("path")
            if stored_path:
                metadata["file_name"] = Path(stored_path).name

        return metadata

    def _validate_pg_config(self) -> None:
        required = ("host", "port", "user", "database", "password")
        missing = [key for key in required if self.pg_config.get(key) in (None, "")]
        if missing:
            raise ValueError(f"Postgres config missing required fields: {', '.join(missing)}")


def _coerce_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_extra_text(payload: Dict[str, str]) -> str:
    parts: List[str] = []
    for key, value in payload.items():
        if value is None:
            continue
        value_str = str(value)
        parts.append(f"{key}:{value_str}")
        parts.append(value_str)
    return " ".join(parts)
