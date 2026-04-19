# Module 1: Data Layer

**Responsibility:** Everything between the app and Snowflake. Connection management, schema discovery, semantic schema retrieval, safe SQL execution.

Module 2 (the agent) consumes this module's API and knows nothing about Snowflake connection details or FAISS indices.

## File overview

| File | Responsibility |
|---|---|
| `config.py` | Loads Snowflake credentials and index paths from env vars; fails loudly if anything's missing |
| `snowflake_client.py` | Singleton Snowflake connection with session-level timeout + auto-reconnect on stale connections |
| `schema_explorer.py` | Pulls tables from `INFORMATION_SCHEMA`, reads field descriptions from the dataset's `METADATA_CBG_FIELD_DESCRIPTIONS` tables |
| `schema_index.py` | Builds/loads a FAISS index over field-description embeddings for semantic retrieval |
| `query_executor.py` | Validates SQL safety, injects `LIMIT`, executes, formats results |
| `tests/` | Unit tests — 19 pure-logic tests that run without Snowflake |

## Why a separate data layer?

Keeping the Snowflake/FAISS details out of Module 2 means:
- **Module 2 is testable without a Snowflake trial account** — we mock the `SchemaIndex` and `QueryExecutor` in unit tests
- **Swapping the backend is tractable** — if someone wanted to port this to BigQuery or Postgres, only Module 1 changes
- **The safety rules are defined once** in `query_executor.py` rather than scattered across the LLM prompt

## Schema retrieval strategy

This is the most important design decision in Module 1, so it gets its own section.

**The problem:** The Marketplace share has 71 tables and 16,284 columns. The columns are opaque codes like `B01001e1`, `B19013m4`, etc. We cannot put the whole schema in an LLM prompt, and we cannot expect the LLM to guess which table has "median income for women over 65."

**The solution:** A two-step retrieval.

1. **On app startup (or first access):** Load *every* row from `2019_METADATA_CBG_FIELD_DESCRIPTIONS` and `2020_METADATA_CBG_FIELD_DESCRIPTIONS`. Each row becomes a `FieldDescription` with fields like:
   - `column_name` = `B01001e10`
   - `table_title` = "Sex By Age"
   - `table_topics` = "Age and Sex"
   - `field_levels` = ["Estimate", "SEX BY AGE", ..., "Male", "22 to 24 years"]

   Serialize each into a single document string, embed with `sentence-transformers/all-MiniLM-L6-v2`, build a FAISS `IndexFlatIP` (cosine similarity via normalized vectors), and persist both the index and the `FieldDescription` list to disk under `.cache/schema_index/`.

2. **At query time:** Module 2 calls `index.search("women over 65")` and gets the top-K matching fields, each with its `data_table_name`, `column_name`, and `human_label`. These are formatted as a compact JSON and returned to the LLM via the `search_schema` tool.

**Cache behavior:** First run takes ~30–60s (embedding 16k items on CPU). Every subsequent run loads from disk in ~1s. The cache is invalidated manually — if the dataset changes, delete `.cache/schema_index/` and rerun.

**Embedding model choice:** `all-MiniLM-L6-v2` is 22MB, CPU-friendly, and produces competent embeddings for this short-text retrieval task. For production I'd evaluate `bge-small-en-v1.5` or OpenAI `text-embedding-3-small`, but the marginal retrieval quality isn't worth the infra complexity for a 24-hour build.

## Dataset-specific quirks (important!)

These quirks caused real bugs during development and are worth internalizing before touching this module:

| Quirk | Fix |
|---|---|
| Table names start with digits (e.g. `2019_CBG_B01`) | Must double-quote in SQL: `"2019_CBG_B01"` |
| Column names are mixed-case (e.g. `B01001e1` — lowercase `e`) | Must double-quote: `"B01001e1"`. Without quotes, Snowflake auto-upper-cases to `B01001E1` and returns "invalid identifier". |
| Metadata table column `FIELD_LEVELl_9` has a typo (lowercase `l`) | Preserved in `schema_explorer.py` — must be quoted as `"FIELD_LEVELl_9"` |
| `INFORMATION_SCHEMA.COLUMNS.COMMENT` is blank for this share | We can't rely on column comments; all human-readable metadata must come from `METADATA_CBG_FIELD_DESCRIPTIONS` |
| Mounted schema is `PUBLIC`, not `CENSUS` | Default in `.env.example` reflects this |

## SQL safety

`query_executor.py` enforces four layers of defense before a query hits Snowflake:

1. **Structural validation:** Strip comments, reject multi-statement (semicolons in body), require `SELECT` or `WITH` as the first keyword.
2. **Keyword blacklist:** Reject any query containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `MERGE`, `COPY`, `CALL`, `EXECUTE`, `USE`.
3. **Row limit injection:** If the query lacks a `LIMIT`, we append `LIMIT 1000`. Stops an accidental full-table scan from blowing up Streamlit.
4. **Session timeout:** `ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 45` is set on every connection so a long-running query fails server-side before our 60s SLA.

**Tradeoff:** these are regex-based, not a real SQL parser. A skilled adversary could construct a query that passes the regex but does something unintended. For a demo where the Snowflake role is read-only anyway, this is acceptable. Production would use `sqlglot` or equivalent. See [`REFLECTION.md`](../REFLECTION.md).

## Connection management

`SnowflakeClient` is a process-wide singleton. On first access it opens one connection; subsequent access reuses it. A cheap `SELECT 1` probe runs before each cursor handout to detect stale connections (Snowflake connections can be terminated server-side after inactivity) and reconnect transparently.

**Why not a pool?** A single-connection reuse is sufficient for Streamlit's traffic profile (one user at a time through a Streamlit session). A real deployment with concurrent users would benefit from `snowflake-connector-python`'s built-in pooling.

## Testing

```bash
python -m pytest module_1/tests/ -v
```

19 unit tests covering:

- **`test_query_executor.py`** (13 tests) — every safety validation path: DDL rejection, multi-statement rejection, CTE acceptance, comment stripping that can't be used to hide DDL, quoted digit-prefix tables, LIMIT injection.
- **`test_schema_explorer.py`** (6 tests) — column code → table name mapping (the critical `B01001e10 → 2019_CBG_B01` logic), typo-preserving metadata column, graceful handling of null field levels.

The tests mock the Snowflake cursor directly — no network calls. This keeps them fast (~25s total including dependency loading) and deterministic.

End-to-end validation against a real Snowflake trial is done via `smoke_test.py` in the repo root.

## What I'd do with more time

- Auto-refresh the schema index when dataset version changes (currently manual).
- Replace the regex safety validator with `sqlglot` for a proper AST-based check.
- Support key-pair authentication in addition to password (required for many enterprise Snowflake setups).
- Parallelize the initial metadata load across years (currently sequential, ~2s total).