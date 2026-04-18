"""Tests for SchemaExplorer and FieldDescription."""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from module_1.schema_explorer import SchemaExplorer, FieldDescription
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


class TestFieldDescription:
    def test_data_table_name_from_B_prefix(self):
        f = FieldDescription(
            column_name="B01001e10", table_number="B01001",
            table_title="Sex By Age", table_topics="Age and Sex",
            table_universe="Total population",
            field_levels=["Estimate", "SEX BY AGE", "Total population", "Total",
                          "Male", "22 to 24 years", "", "", "", ""],
            year=2019,
        )
        assert f.data_table_name == "2019_CBG_B01"

    def test_data_table_name_from_C_prefix(self):
        f = FieldDescription(
            column_name="C02003e1", table_number="C02003",
            table_title="t", table_topics="", table_universe="",
            field_levels=[""] * 10, year=2020,
        )
        assert f.data_table_name == "2020_CBG_C02"

    def test_human_label_skips_empty_levels(self):
        f = FieldDescription(
            column_name="x", table_number="B01001", table_title="",
            table_topics="", table_universe="",
            field_levels=["Estimate", "", "Total", "", "Male",
                          "22 to 24 years", "", "", "", ""],
            year=2019,
        )
        assert f.human_label == "Estimate > Total > Male > 22 to 24 years"

    def test_to_document_includes_meaning(self):
        f = FieldDescription(
            column_name="B01001e10", table_number="B01001",
            table_title="Sex By Age", table_topics="Age and Sex",
            table_universe="Total population",
            field_levels=["Estimate", "SEX BY AGE", "Total population", "Total",
                          "Male", "22 to 24 years", "", "", "", ""],
            year=2019,
        )
        doc = f.to_document()
        assert "2019" in doc
        assert "Sex By Age" in doc
        assert "Male" in doc
        assert "22 to 24 years" in doc
        assert "2019_CBG_B01" in doc


class TestLoadFieldDescriptions:
    def test_parses_metadata_row(self, config):
        client = MagicMock()
        client.config = config
        client.cursor.return_value = fake_cursor([{
            "TABLE_ID": "B01001e10",
            "TABLE_NUMBER": "B01001",
            "TABLE_TITLE": "Sex By Age",
            "TABLE_TOPICS": "Age and Sex",
            "TABLE_UNIVERSE": "Total population",
            "FIELD_LEVEL_1": "Estimate",
            "FIELD_LEVEL_2": "SEX BY AGE",
            "FIELD_LEVEL_3": "Total population",
            "FIELD_LEVEL_4": "Total",
            "FIELD_LEVEL_5": "Male",
            "FIELD_LEVEL_6": "22 to 24 years",
            "FIELD_LEVEL_7": None,
            "FIELD_LEVEL_8": None,
            "FIELD_LEVELl_9": None,   # typo preserved — matches source
            "FIELD_LEVEL_10": None,
        }])

        explorer = SchemaExplorer(client)
        fields = explorer.load_field_descriptions(2019)

        assert len(fields) == 1
        assert fields[0].column_name == "B01001e10"
        assert fields[0].data_table_name == "2019_CBG_B01"
        assert "Male" in fields[0].human_label

    def test_handles_missing_levels_gracefully(self, config):
        client = MagicMock()
        client.config = config
        client.cursor.return_value = fake_cursor([{
            "TABLE_ID": "B01001e1",
            "TABLE_NUMBER": "B01001",
            "TABLE_TITLE": "Sex By Age",
            "TABLE_TOPICS": "Age and Sex",
            "TABLE_UNIVERSE": "Total population",
            **{f"FIELD_LEVEL_{i}": None for i in [1, 2, 3, 4, 5, 6, 7, 8, 10]},
            "FIELD_LEVELl_9": None,
        }])

        explorer = SchemaExplorer(client)
        fields = explorer.load_field_descriptions(2019)

        assert len(fields) == 1
        assert fields[0].human_label == ""  # no levels populated, no crash
