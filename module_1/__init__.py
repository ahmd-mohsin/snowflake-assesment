"""Module 1: Data Layer — Snowflake connection, schema discovery, query execution."""
from .config import SnowflakeConfig
from .snowflake_client import SnowflakeClient
from .schema_explorer import SchemaExplorer, TableInfo, ColumnInfo
from .schema_index import SchemaIndex, SchemaMatch
from .query_executor import QueryExecutor, QueryResult, UnsafeQueryError

__all__ = [
    "SnowflakeConfig",
    "SnowflakeClient",
    "SchemaExplorer",
    "TableInfo",
    "ColumnInfo",
    "SchemaIndex",
    "SchemaMatch",
    "QueryExecutor",
    "QueryResult",
    "UnsafeQueryError",
]
