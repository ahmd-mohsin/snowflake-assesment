"""Tests for the census-specific SQL semantic validator."""
import pytest

from module_2.sql_semantics import check_sql_semantics


class TestSumOfMedianDetection:
    def test_blocks_sum_of_median_income(self):
        sql = 'SELECT SUM("B19013e1") FROM "2020_CBG_B19"'
        result = check_sql_semantics(sql)
        assert not result.ok
        assert "B19013" in result.reason
        assert "weighted" in result.suggestion.lower()

    def test_blocks_sum_of_median_home_value(self):
        sql = 'SELECT SUM("B25077e1") FROM "2020_CBG_B25"'
        result = check_sql_semantics(sql)
        assert not result.ok

    def test_blocks_sum_of_median_age(self):
        sql = 'SELECT SUM("B01002e1") FROM "2020_CBG_B01"'
        result = check_sql_semantics(sql)
        assert not result.ok

    def test_blocks_sum_of_per_capita_income(self):
        sql = 'SELECT SUM("B19301e1") FROM "2020_CBG_B19"'
        result = check_sql_semantics(sql)
        assert not result.ok

    def test_case_insensitive(self):
        sql = 'select sum("b19013e1") from "2020_CBG_B19"'
        result = check_sql_semantics(sql)
        assert not result.ok


class TestWeightedAverageAllowed:
    def test_allows_weighted_average_of_medians(self):
        # The canonical fix: SUM(median * weights) / SUM(weights)
        sql = """
            SELECT SUM("B19013e1" * "B11001e1") / SUM("B11001e1") AS weighted
            FROM "2020_CBG_B19" JOIN "2020_CBG_B11" USING (CENSUS_BLOCK_GROUP)
        """
        result = check_sql_semantics(sql)
        assert result.ok, result.reason

    def test_allows_weighted_average_with_nullif(self):
        sql = """
            SELECT SUM("B25077e1" * "B25001e1") / NULLIF(SUM("B25001e1"), 0)
            FROM "2020_CBG_B25"
        """
        result = check_sql_semantics(sql)
        assert result.ok


class TestLegitimateSumsAllowed:
    def test_allows_sum_of_population_count(self):
        sql = 'SELECT SUM("B01001e1") FROM "2020_CBG_B01"'
        result = check_sql_semantics(sql)
        assert result.ok

    def test_allows_sum_of_household_count(self):
        sql = 'SELECT SUM("B11001e1") FROM "2020_CBG_B11"'
        result = check_sql_semantics(sql)
        assert result.ok

    def test_allows_sum_of_distribution_bucket(self):
        # B19001 is a household-income distribution — buckets are summable
        sql = 'SELECT SUM("B19001e11") FROM "2020_CBG_B19"'
        result = check_sql_semantics(sql)
        assert result.ok

    def test_allows_plain_select(self):
        sql = 'SELECT "B19013e1" FROM "2020_CBG_B19" LIMIT 5'
        result = check_sql_semantics(sql)
        assert result.ok

    def test_allows_count_aggregation(self):
        sql = 'SELECT COUNT(*) FROM "2020_CBG_B19" WHERE "B19013e1" IS NOT NULL'
        result = check_sql_semantics(sql)
        assert result.ok