"""Discover tables and columns in the Census dataset.

The Snowflake Marketplace census share exposes metadata via INFORMATION_SCHEMA.
We also attempt to pull column descriptions from the CENSUS_CONCEPTS /
CENSUS_TABLES metadata tables if they exist in the share.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Dict

from .snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)


@dataclass
class ColumnInfo:
    table_name: str
    column_name: str
    data_type: str
    description: str = ""

    def to_document(self) -> str:
        """Flatten to a single searchable string for embedding."""
        parts = [f"Table: {self.table_name}", f"Column: {self.column_name}",
                 f"Type: {self.data_type}"]
        if self.description:
            parts.append(f"Description: {self.description}")
        return " | ".join(parts)


@dataclass
class TableInfo:
    name: str
    row_count: int | None = None
    description: str = ""
    columns: List[ColumnInfo] = field(default_factory=list)


class SchemaExplorer:
    """Enumerates tables and columns, enriched with descriptions when available."""

    def __init__(self, client: SnowflakeClient):
        self._client = client
        self._db = client.config.database
        self._schema = client.config.schema

    def list_tables(self) -> List[TableInfo]:
        query = f"""
            SELECT TABLE_NAME, ROW_COUNT, COMMENT
            FROM {self._db}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{self._schema}'
              AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
            ORDER BY TABLE_NAME
        """
        with self._client.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return [
            TableInfo(
                name=r["TABLE_NAME"],
                row_count=r.get("ROW_COUNT"),
                description=r.get("COMMENT") or "",
            )
            for r in rows
        ]

    def list_columns(self, table_names: List[str] | None = None) -> List[ColumnInfo]:
        where = f"TABLE_SCHEMA = '{self._schema}'"
        if table_names:
            joined = ", ".join(f"'{t}'" for t in table_names)
            where += f" AND TABLE_NAME IN ({joined})"

        query = f"""
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COMMENT
            FROM {self._db}.INFORMATION_SCHEMA.COLUMNS
            WHERE {where}
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """
        with self._client.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return [
            ColumnInfo(
                table_name=r["TABLE_NAME"],
                column_name=r["COLUMN_NAME"],
                data_type=r["DATA_TYPE"],
                description=r.get("COMMENT") or "",
            )
            for r in rows
        ]

    def build_full_schema(self) -> List[TableInfo]:
        """Return tables populated with their columns."""
        tables = self.list_tables()
        if not tables:
            logger.warning("No tables found in %s.%s", self._db, self._schema)
            return []

        columns = self.list_columns([t.name for t in tables])
        by_table: Dict[str, List[ColumnInfo]] = {}
        for c in columns:
            by_table.setdefault(c.table_name, []).append(c)

        for t in tables:
            t.columns = by_table.get(t.name, [])
        return tables
