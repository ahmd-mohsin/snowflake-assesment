"""Tool definitions exposed to the LLM, and implementations that call module_1.

Defines two tools:
  - search_schema: semantic search over census field descriptions
  - execute_sql: run a read-only SQL query

The JSON schemas here get passed to OpenAI as function definitions.
"""
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from module_1 import (
    QueryExecutor, QueryResult, SchemaIndex, SUPPORTED_YEARS, UnsafeQueryError,
)

logger = logging.getLogger(__name__)


# Tool schemas in OpenAI function-calling format
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_schema",
            "description": (
                "Search the census dataset's field descriptions using a natural "
                "language query. Returns the most relevant columns with their "
                "full meaning, table name, and column ID. Call this BEFORE "
                "writing SQL so you know what columns exist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look for, e.g. 'median household income' or 'women aged 65 or over'",
                    },
                    "year": {
                        "type": "integer",
                        "description": f"Optional: restrict to a year. Valid: {list(SUPPORTED_YEARS)}",
                        "enum": list(SUPPORTED_YEARS),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "How many results to return. Default 15, max 30.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": (
                "Run a read-only SQL query against the census Snowflake database. "
                "Use fully-qualified table names like "
                '`US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET.PUBLIC."2019_CBG_B01"`. '
                "Double-quote both table names (they start with digits) AND column "
                'names (they are mixed-case, e.g. "B01001e1"). Queries auto-timeout '
                "at 45 seconds. Only SELECT / WITH queries are allowed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The SQL query to run.",
                    },
                },
                "required": ["sql"],
            },
        },
    },
]


@dataclass
class ToolCallResult:
    """What we return to the LLM after a tool call."""
    content: str           # JSON-serialisable string for the 'tool' message
    numbers_seen: List[int]  # numbers extracted from results, for output guardrail


class ToolRunner:
    """Executes tool calls and formats results for the LLM."""

    def __init__(self, schema_index: SchemaIndex, query_executor: QueryExecutor,
                 max_rows_in_context: int = 30):
        self._index = schema_index
        self._executor = query_executor
        self._max_rows = max_rows_in_context

    def run(self, name: str, args_json: str) -> ToolCallResult:
        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError as e:
            return ToolCallResult(
                content=json.dumps({"error": f"Invalid JSON in tool arguments: {e}"}),
                numbers_seen=[],
            )

        if name == "search_schema":
            return self._run_search_schema(args)
        if name == "execute_sql":
            return self._run_execute_sql(args)
        return ToolCallResult(
            content=json.dumps({"error": f"Unknown tool: {name}"}),
            numbers_seen=[],
        )

    def _run_search_schema(self, args: Dict[str, Any]) -> ToolCallResult:
        query = args.get("query", "").strip()
        if not query:
            return ToolCallResult(
                content=json.dumps({"error": "query is required"}),
                numbers_seen=[],
            )
        year = args.get("year")
        top_k = min(args.get("top_k", 15), 30)

        try:
            matches = self._index.search(query, top_k=top_k, year=year)
        except Exception as e:
            logger.exception("schema search failed")
            return ToolCallResult(
                content=json.dumps({"error": f"Schema search failed: {e}"}),
                numbers_seen=[],
            )

        if not matches:
            return ToolCallResult(
                content=json.dumps({
                    "results": [],
                    "note": "No relevant fields found. Try a different query or drop the year filter.",
                }),
                numbers_seen=[],
            )

        results = [{
            "column": m.field.column_name,
            "table": m.field.data_table_name,
            "table_title": m.field.table_title,
            "topic": m.field.table_topics,
            "universe": m.field.table_universe,
            "meaning": m.field.human_label,
            "year": m.field.year,
            "score": round(m.score, 3),
        } for m in matches]

        return ToolCallResult(
            content=json.dumps({"results": results}, indent=None),
            numbers_seen=[],
        )

    def _run_execute_sql(self, args: Dict[str, Any]) -> ToolCallResult:
        sql = args.get("sql", "").strip()
        if not sql:
            return ToolCallResult(
                content=json.dumps({"error": "sql is required"}),
                numbers_seen=[],
            )

        # Semantic validation: block statistically meaningless aggregations
        # (e.g. SUM of median columns) before we spend a Snowflake query.
        from .sql_semantics import check_sql_semantics
        sem = check_sql_semantics(sql)
        if not sem.ok:
            logger.info("SQL rejected by semantic check: %s", sem.reason)
            return ToolCallResult(
                content=json.dumps({
                    "error": sem.reason,
                    "suggestion": sem.suggestion,
                }),
                numbers_seen=[],
            )

        try:
            result: QueryResult = self._executor.execute(sql)
        except UnsafeQueryError as e:
            return ToolCallResult(
                content=json.dumps({
                    "error": f"Query rejected by safety check: {e}. "
                             "Only SELECT/WITH queries are allowed.",
                }),
                numbers_seen=[],
            )
        except RuntimeError as e:
            # SQL compilation errors, runtime errors — bubble up the message
            # so the LLM can correct on next iteration
            return ToolCallResult(
                content=json.dumps({"error": str(e)}),
                numbers_seen=[],
            )
        except Exception as e:
            logger.exception("execute_sql crashed")
            return ToolCallResult(
                content=json.dumps({"error": f"Unexpected error: {e}"}),
                numbers_seen=[],
            )

        # Truncate rows we send back to the LLM — the UI will render the full
        # result separately
        rows_for_llm = result.rows[:self._max_rows]
        payload = {
            "columns": result.columns,
            "row_count": result.row_count,
            "rows": rows_for_llm,
        }
        if result.truncated:
            payload["note"] = (
                f"Result was truncated at {self._executor._max_rows} rows. "
                "Aggregate if you need totals."
            )
        elif result.row_count > self._max_rows:
            payload["note"] = (
                f"Showing first {self._max_rows} of {result.row_count} rows."
            )

        # Collect numeric values for the output guardrail
        numbers_seen = _collect_numbers(result)

        return ToolCallResult(
            content=json.dumps(payload, default=str),
            numbers_seen=numbers_seen,
        )


def _collect_numbers(result: QueryResult) -> List[int]:
    """Gather all integer-ish values from a QueryResult for grounding checks."""
    out: List[int] = []
    for row in result.rows:
        for v in row.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if v > 1000:  # small numbers are noise for this check
                    out.append(int(v))
    return out