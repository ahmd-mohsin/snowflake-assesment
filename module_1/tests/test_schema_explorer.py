"""Tests for SchemaExplorer using a mocked Snowflake cursor."""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from module_1.schema_explorer import SchemaExplorer
from module_1.config import SnowflakeConfig


@contextmanager
def fake_cursor(rows):
    cur = MagicMock()
    cur.fetchall.return_value = rows
    yield cur


@pytest.fixture
def config():
    return SnowflakeConfig(account="x", user="x", password="x",
                           warehouse="x", role="x")


def test_list_tables_parses_rows(config):
    client = MagicMock()
    client.config = config
    client.cursor.return_value = fake_cursor([
        {"TABLE_NAME": "CBG_B01001", "ROW_COUNT": 220000, "COMMENT": "Sex by age"},
        {"TABLE_NAME": "CBG_B19013", "ROW_COUNT": 220000, "COMMENT": ""},
    ])

    explorer = SchemaExplorer(client)
    tables = explorer.list_tables()

    assert len(tables) == 2
    assert tables[0].name == "CBG_B01001"
    assert tables[0].description == "Sex by age"
    assert tables[1].description == ""


def test_list_columns_parses_rows(config):
    client = MagicMock()
    client.config = config
    client.cursor.return_value = fake_cursor([
        {"TABLE_NAME": "T1", "COLUMN_NAME": "GEOID",
         "DATA_TYPE": "VARCHAR", "COMMENT": "Census block group id"},
    ])

    explorer = SchemaExplorer(client)
    cols = explorer.list_columns()

    assert len(cols) == 1
    assert cols[0].column_name == "GEOID"
    assert "Census block group id" in cols[0].to_document()
