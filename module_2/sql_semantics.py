"""Semantic validation of SQL before execution.

This complements Module 1's safety validation (which blocks DDL/DML). Here we
block SQL that is *syntactically fine* but *statistically meaningless* given
census semantics.

The canonical case: `SUM(median_column)` — syntactically legal SQL that
produces a meaningless aggregate. We catch it here so the LLM gets a clear
error message back and can correct, rather than returning a bogus number that
the output guardrail might miss.
"""
import re
from dataclasses import dataclass
from typing import List


# Census columns that are medians, means, or other pre-aggregated statistics.
# Pattern: table prefix + 'e'/'m' + '1' (or sometimes the first few).
# We list table-prefix patterns so we don't have to enumerate all 16k columns.
#
# These tables publish a median/mean/per-capita statistic as their e1 column:
_MEDIAN_TABLES_E1 = {
    "B01002": "median age",
    "B19013": "median household income",
    "B19019": "median household income by size",
    "B19025": "aggregate household income (already a sum; don't re-sum)",
    "B19113": "median family income",
    "B19202": "median nonfamily income",
    "B19301": "per capita income",
    "B25031": "median gross rent by bedrooms",
    "B25058": "median contract rent",
    "B25064": "median gross rent",
    "B25077": "median value (owner-occupied)",
    "B25105": "median monthly housing costs",
    "C17002": "ratio of income to poverty",
}

# Regex: matches SUM("<table>e<digit>") or AVG/SUM of these columns.
# We match any variation of SUM / AVG / MIN / MAX (actually only SUM is wrong
# in most cases — a MIN/MAX of medians is less misleading but still weird).
_SUM_OF_MEDIAN = re.compile(
    r"\bSUM\s*\(\s*\"?(" + "|".join(_MEDIAN_TABLES_E1.keys()) + r")e\d+\"?\s*\)",
    re.IGNORECASE,
)

# Weighted-average pattern we want to ALLOW:
# SUM("B19013e1" * "B11001e1") / ... — this is legitimate. We detect it by
# requiring that a SUM of a median column is multiplied by something else.
_WEIGHTED_SUM = re.compile(
    r"\bSUM\s*\(\s*\"?(" + "|".join(_MEDIAN_TABLES_E1.keys()) + r")e\d+\"?\s*\*",
    re.IGNORECASE,
)


@dataclass
class SemanticValidation:
    ok: bool
    reason: str = ""
    suggestion: str = ""


def check_sql_semantics(sql: str) -> SemanticValidation:
    """Return ok=False if the SQL has a known bad aggregation pattern."""
    # Is there a SUM of a median column that is NOT part of a weighted average?
    weighted_spans = [m.span() for m in _WEIGHTED_SUM.finditer(sql)]

    for m in _SUM_OF_MEDIAN.finditer(sql):
        # If this SUM-of-median is actually the start of a weighted average
        # (SUM("B19013e1" * ...)), allow it.
        if any(ws <= m.start() < we for ws, we in weighted_spans):
            continue

        table_prefix = m.group(1).upper()
        col_description = _MEDIAN_TABLES_E1.get(table_prefix, "pre-aggregated")
        return SemanticValidation(
            ok=False,
            reason=(
                f"SUM of {table_prefix}e* is invalid — this column is a "
                f"{col_description} already summarized per block group. "
                f"Summing it produces a statistically meaningless value."
            ),
            suggestion=(
                "For a true national/state median, use a household-weighted "
                "average instead, e.g.:\n"
                '  SUM("B19013e1" * "B11001e1") / NULLIF(SUM("B11001e1"), 0)\n'
                "And label the result as an approximation of the median, "
                "since the true median cannot be exactly computed from "
                "block-group medians."
            ),
        )

    return SemanticValidation(ok=True)