"""Discover tables and fields in the Census dataset.

Strategy:
- INFORMATION_SCHEMA gives us the list of data tables (e.g. '2019_CBG_B01').
- The METADATA_CBG_FIELD_DESCRIPTIONS tables tell us what each opaque column
  (e.g. 'B01001e10') actually means in human-readable terms. That is what we
  embed for semantic search.
- Table names in this share start with digits (e.g. '2019_CBG_B01') so every
  identifier must be double-quoted when used in SQL.
"""
import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Optional

from .snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)


# Known vintages in this Marketplace share
SUPPORTED_YEARS = (2019, 2020)
METADATA_TABLE_TEMPLATE = "{year}_METADATA_CBG_FIELD_DESCRIPTIONS"
FIPS_TABLE_TEMPLATE = "{year}_METADATA_CBG_FIPS_CODES"
GEO_TABLE_TEMPLATE = "{year}_METADATA_CBG_GEOGRAPHIC_DATA"


@dataclass
class FieldDescription:
    """One column of a census data table, with its human-readable meaning."""
    column_name: str       # e.g. 'B01001e10'
    table_number: str      # e.g. 'B01001' — maps to data table '{year}_CBG_B01'
    table_title: str       # e.g. 'Sex By Age'
    table_topics: str      # e.g. 'Age and Sex'
    table_universe: str    # e.g. 'Total population'
    field_levels: List[str]
    year: int

    @property
    def data_table_name(self) -> str:
        """Map a field like 'B01001e10' -> data table '2019_CBG_B01'."""
        prefix = re.match(r"^([A-Z]\d{2})", self.table_number)
        if not prefix:
            return f"{self.year}_CBG_{self.table_number}"
        return f"{self.year}_CBG_{prefix.group(1)}"

    @property
    def human_label(self) -> str:
        """E.g. 'Male > 22 to 24 years' from the non-empty field levels."""
        return " > ".join(l for l in self.field_levels if l and l.strip())

    def to_document(self) -> str:
        """Searchable text for embedding."""
        return (
            f"Year: {self.year} | "
            f"Topic: {self.table_topics} | "
            f"Table: {self.table_title} | "
            f"Universe: {self.table_universe} | "
            f"Meaning: {self.human_label} | "
            f"Data table: {self.data_table_name} | "
            f"Column: {self.column_name}"
        )


@dataclass
class TableInfo:
    name: str
    row_count: Optional[int] = None
    kind: str = "TABLE"


class SchemaExplorer:
    def __init__(self, client: SnowflakeClient):
        self._client = client
        self._db = client.config.database
        self._schema = client.config.schema

    def list_tables(self) -> List[TableInfo]:
        query = f"""
            SELECT TABLE_NAME, ROW_COUNT, TABLE_TYPE
            FROM {self._db}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{self._schema}'
              AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
            ORDER BY TABLE_NAME
        """
        with self._client.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return [
            TableInfo(name=r["TABLE_NAME"], row_count=r.get("ROW_COUNT"),
                      kind=r.get("TABLE_TYPE", "TABLE"))
            for r in rows
        ]

    def load_field_descriptions(self, year: int) -> List[FieldDescription]:
        """Load all rows from the metadata field descriptions table for a given year."""
        table = METADATA_TABLE_TEMPLATE.format(year=year)
        # Note: table name requires double quotes (starts with digit).
        # FIELD_LEVELl_9 has a typo in the source data — we preserve it as-is.
        query = f'''
            SELECT
                TABLE_ID,
                TABLE_NUMBER,
                TABLE_TITLE,
                TABLE_TOPICS,
                TABLE_UNIVERSE,
                FIELD_LEVEL_1, FIELD_LEVEL_2, FIELD_LEVEL_3, FIELD_LEVEL_4,
                FIELD_LEVEL_5, FIELD_LEVEL_6, FIELD_LEVEL_7, FIELD_LEVEL_8,
                "FIELD_LEVELl_9", FIELD_LEVEL_10
            FROM {self._db}.{self._schema}."{table}"
        '''
        with self._client.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()

        descriptions: List[FieldDescription] = []
        for r in rows:
            levels = [
                r.get("FIELD_LEVEL_1") or "", r.get("FIELD_LEVEL_2") or "",
                r.get("FIELD_LEVEL_3") or "", r.get("FIELD_LEVEL_4") or "",
                r.get("FIELD_LEVEL_5") or "", r.get("FIELD_LEVEL_6") or "",
                r.get("FIELD_LEVEL_7") or "", r.get("FIELD_LEVEL_8") or "",
                r.get("FIELD_LEVELl_9") or "", r.get("FIELD_LEVEL_10") or "",
            ]
            descriptions.append(FieldDescription(
                column_name=r["TABLE_ID"],
                table_number=r.get("TABLE_NUMBER") or "",
                table_title=r.get("TABLE_TITLE") or "",
                table_topics=r.get("TABLE_TOPICS") or "",
                table_universe=r.get("TABLE_UNIVERSE") or "",
                field_levels=levels,
                year=year,
            ))
        logger.info("Loaded %d field descriptions for year %d", len(descriptions), year)
        return descriptions

    def load_all_field_descriptions(self) -> List[FieldDescription]:
        all_fields: List[FieldDescription] = []
        for year in SUPPORTED_YEARS:
            try:
                all_fields.extend(self.load_field_descriptions(year))
            except Exception as e:
                logger.warning("Could not load metadata for year %d: %s", year, e)
        return all_fields

    def get_fips_sample(self, year: int = 2019, limit: int = 5) -> List[Dict]:
        """Pull a few rows from the FIPS metadata so the agent sees the
        state/county/tract column names available for filtering."""
        table = FIPS_TABLE_TEMPLATE.format(year=year)
        query = f'SELECT * FROM {self._db}.{self._schema}."{table}" LIMIT {limit}'
        try:
            with self._client.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()
        except Exception as e:
            logger.warning("Could not load FIPS sample: %s", e)
            return []
