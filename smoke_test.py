"""End-to-end smoke test for module_1.

Validates:
  1. Snowflake credentials work and we can query INFORMATION_SCHEMA
  2. Metadata tables are readable
  3. Schema index builds and caches to disk
  4. Semantic search returns sensible matches
  5. SQL executor runs a real query against a census data table

Run: python smoke_test.py
"""
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("smoke")

from module_1 import (
    SnowflakeClient, SchemaExplorer, SchemaIndex, QueryExecutor,
)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def main() -> int:
    # 1. Connection
    section("1. Snowflake connection")
    t0 = time.time()
    client = SnowflakeClient.get()
    with client.cursor() as cur:
        cur.execute("SELECT CURRENT_ACCOUNT(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
        row = cur.fetchone()
        print(f"  Connected in {time.time()-t0:.1f}s")
        print(f"  Account:   {row['CURRENT_ACCOUNT()']}")
        print(f"  Role:      {row['CURRENT_ROLE()']}")
        print(f"  Warehouse: {row['CURRENT_WAREHOUSE()']}")

    # 2. Table listing
    section("2. Listing tables in the census schema")
    explorer = SchemaExplorer(client)
    tables = explorer.list_tables()
    print(f"  Found {len(tables)} tables/views")
    if len(tables) == 0:
        print("  !!! No tables found — check SNOWFLAKE_DATABASE and SNOWFLAKE_SCHEMA in .env")
        return 1
    for t in tables[:5]:
        print(f"    - {t.name}  (rows={t.row_count})")
    print(f"    ... and {max(0, len(tables) - 5)} more")

    # 3. Build / load schema index
    section("3. Building schema index (first run ~30-60s, cached after)")
    t0 = time.time()
    index = SchemaIndex()
    index.build(explorer)
    print(f"  Index ready in {time.time()-t0:.1f}s")
    print(f"  Indexed {len(index._fields)} fields across all years")

    # 4. Semantic search
    section("4. Semantic search — does it return sensible matches?")
    test_queries = [
        "median household income",
        "women over 65",
        "hispanic or latino population",
        "people with no health insurance",
    ]
    for q in test_queries:
        print(f"\n  Query: '{q}'")
        matches = index.search(q, top_k=3)
        for m in matches:
            print(f"    [{m.score:.3f}] {m.field.data_table_name}.{m.field.column_name}  "
                  f"— {m.field.table_title}: {m.field.human_label[:80]}")

    # 5. Execute a real query
    section("5. Running a real SQL query on the census data")
    executor = QueryExecutor(client)

    # Query total population for 5 random block groups in 2019
    # Column names are case-sensitive in this share (lowercase 'e'/'m'),
    # so they must be double-quoted or Snowflake auto-upper-cases them.
    sql = '''
        SELECT CENSUS_BLOCK_GROUP, "B01001e1" AS total_population
        FROM US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET.PUBLIC."2019_CBG_B01"
        WHERE "B01001e1" IS NOT NULL
        LIMIT 5
    '''
    try:
        result = executor.execute(sql)
        print(f"  Returned {result.row_count} rows in columns: {result.columns}")
        print("\n" + result.to_markdown())
    except Exception as e:
        print(f"  !!! Query failed: {e}")
        return 1

    # 6. Safety check — make sure bad queries are blocked
    section("6. Guardrail check — unsafe queries must be rejected")
    from module_1 import UnsafeQueryError
    bad = [
        "DROP TABLE \"2019_CBG_B01\"",
        "SELECT 1; DROP TABLE x",
        "INSERT INTO x VALUES (1)",
    ]
    for q in bad:
        try:
            executor.validate(q)
            print(f"  !!! FAILED to block: {q}")
            return 1
        except UnsafeQueryError as e:
            print(f"  OK - blocked: {q[:40]}...  ({e})")

    section("ALL CHECKS PASSED")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())