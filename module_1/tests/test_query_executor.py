"""Tests for QueryExecutor.validate — pure logic, no Snowflake needed."""
import pytest
from unittest.mock import MagicMock

from module_1.query_executor import QueryExecutor, UnsafeQueryError
from module_1.config import SnowflakeConfig


@pytest.fixture
def executor():
    mock_client = MagicMock()
    mock_client.config = SnowflakeConfig(
        account="x", user="x", password="x",
        warehouse="x", role="x",
    )
    return QueryExecutor(mock_client)


class TestValidate:
    def test_rejects_empty(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.validate("")

    def test_rejects_insert(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.validate("INSERT INTO t VALUES (1)")

    def test_rejects_drop(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.validate("DROP TABLE t")

    def test_rejects_multi_statement(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.validate("SELECT 1; SELECT 2")

    def test_rejects_ddl_even_after_select(self, executor):
        with pytest.raises(UnsafeQueryError):
            executor.validate("SELECT 1 UNION CREATE TABLE t (x INT)")

    def test_allows_simple_select(self, executor):
        result = executor.validate("SELECT * FROM t")
        assert result == "SELECT * FROM t"

    def test_allows_cte(self, executor):
        sql = "WITH x AS (SELECT 1) SELECT * FROM x"
        assert executor.validate(sql) == sql

    def test_allows_quoted_digit_prefix_tables(self, executor):
        # Census tables start with digits and must be double-quoted
        sql = 'SELECT B01001e1 FROM "2019_CBG_B01" LIMIT 10'
        assert executor.validate(sql) == sql

    def test_strips_trailing_semicolon(self, executor):
        assert executor.validate("SELECT 1;") == "SELECT 1"

    def test_strips_comments(self, executor):
        # comments stripped; inline comments shouldn't bypass validation
        sql = "SELECT 1 -- this is fine"
        assert "SELECT 1" in executor.validate(sql)

    def test_comment_cannot_hide_ddl(self, executor):
        # A clever user might try: SELECT 1 /* */ ; DROP TABLE t
        # After comment stripping, the semicolon should still trigger multi-stmt
        with pytest.raises(UnsafeQueryError):
            executor.validate("SELECT 1 /* comment */; DROP TABLE t")


class TestLimitInjection:
    def test_adds_limit_when_missing(self, executor):
        result = executor._inject_limit("SELECT * FROM t")
        assert "LIMIT" in result

    def test_respects_existing_limit(self, executor):
        result = executor._inject_limit("SELECT * FROM t LIMIT 5")
        assert result.count("LIMIT") == 1
