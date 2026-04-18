"""Executes SQL against Snowflake with safety checks.

Enforces:
- SELECT-only (no DDL/DML)
- Single statement per call
- Automatic LIMIT injection if missing
- Row count cap on returned results
- Timeout inherited from session (see SnowflakeClient)
"""
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from snowflake.connector.errors import ProgrammingError

from .snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)


class UnsafeQueryError(ValueError):
    """Raised when a query fails the safety checks."""


@dataclass
class QueryResult:
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int
    truncated: bool
    sql_executed: str

    def to_markdown(self, max_rows: int = 20) -> str:
        """Render the first max_rows as a markdown table."""
        if not self.rows:
            return "_No rows returned._"
        shown = self.rows[:max_rows]
        header = "| " + " | ".join(self.columns) + " |"
        sep = "| " + " | ".join("---" for _ in self.columns) + " |"
        body = "\n".join(
            "| " + " | ".join(str(r.get(c, "")) for c in self.columns) + " |"
            for r in shown
        )
        suffix = ""
        if self.truncated or len(self.rows) > max_rows:
            suffix = f"\n\n_Showing {len(shown)} of {self.row_count} rows._"
        return f"{header}\n{sep}\n{body}{suffix}"


# Forbidden keywords — matched as whole words (case-insensitive)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|"
    r"MERGE|COPY|CALL|EXECUTE|USE)\b",
    re.IGNORECASE,
)


class QueryExecutor:
    def __init__(self, client: SnowflakeClient):
        self._client = client
        self._max_rows = client.config.max_rows_returned

    def validate(self, sql: str) -> str:
        """Return normalized SQL or raise UnsafeQueryError."""
        if not sql or not sql.strip():
            raise UnsafeQueryError("Empty query.")

        # Strip trailing semicolons and comments, reject multi-statement
        cleaned = re.sub(r"--[^\n]*", "", sql)
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
        cleaned = cleaned.strip().rstrip(";").strip()

        if ";" in cleaned:
            raise UnsafeQueryError("Multiple statements are not allowed.")

        first_word = cleaned.split(None, 1)[0].upper() if cleaned else ""
        if first_word not in ("SELECT", "WITH"):
            raise UnsafeQueryError(
                f"Only SELECT/WITH queries are allowed (got '{first_word}')."
            )

        if _FORBIDDEN.search(cleaned):
            raise UnsafeQueryError("Query contains forbidden keywords.")

        return cleaned

    def _inject_limit(self, sql: str) -> str:
        """Add LIMIT if the outer query lacks one."""
        if re.search(r"\bLIMIT\s+\d+\s*$", sql, re.IGNORECASE):
            return sql
        return f"{sql}\nLIMIT {self._max_rows}"

    def execute(self, sql: str) -> QueryResult:
        cleaned = self.validate(sql)
        final_sql = self._inject_limit(cleaned)
        logger.info("Executing SQL: %s", final_sql)

        try:
            with self._client.cursor() as cur:
                cur.execute(final_sql)
                rows = cur.fetchall()
                columns = [d[0] for d in cur.description]
        except ProgrammingError as e:
            # Surface a clean error for the agent to relay to the user
            raise RuntimeError(f"SQL error: {e.msg}") from e

        truncated = len(rows) >= self._max_rows
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            sql_executed=final_sql,
        )
