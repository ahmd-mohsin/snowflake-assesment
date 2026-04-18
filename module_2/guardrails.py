"""Guardrails around the agent.

Input guardrail: keyword-based topic filter. Fast (microseconds), zero cost.
Brittle by design — a quick reject catches obvious off-topic asks before we
spend tokens. Everything else falls through to the LLM, which itself is
prompted to refuse non-census questions.

Output guardrail: best-effort check that numeric claims in the answer actually
appear in the SQL results the agent saw. Not bulletproof (LLM might reformat
numbers) but catches blatant hallucinations.
"""
import re
from dataclasses import dataclass
from typing import List, Set


# Terms that suggest the question is on-topic (census/demographics/geography)
_ON_TOPIC_TERMS: Set[str] = {
    # demographics
    "population", "people", "resident", "residents", "citizen", "citizens",
    "demographic", "demographics", "census", "household", "households",
    "family", "families", "men", "women", "male", "female", "children",
    "child", "kids", "adult", "adults", "senior", "seniors", "elderly",
    "age", "aged", "old", "young", "youth",
    # race/ethnicity
    "race", "racial", "ethnic", "ethnicity", "hispanic", "latino", "latina",
    "white", "black", "asian", "native", "pacific", "islander",
    # income / economics
    "income", "poverty", "poor", "wealth", "rich", "wealthy", "salary",
    "wage", "wages", "earning", "earnings", "employed", "unemployed",
    "employment", "unemployment", "job", "jobs", "worker", "workers",
    "labor", "workforce",
    # housing
    "housing", "house", "houses", "home", "homes", "rent", "rental",
    "renter", "renters", "owner", "owners", "mortgage", "occupied",
    "vacant",
    # education
    "education", "educational", "school", "schools", "degree", "degrees",
    "college", "bachelor", "master", "graduate", "diploma", "literacy",
    # health
    "insurance", "insured", "uninsured", "health", "healthcare", "medicare",
    "medicaid", "disability", "disabled",
    # geography — generic
    "state", "states", "county", "counties", "city", "cities", "town",
    "towns", "zip", "zipcode", "neighborhood", "district",
    "region", "tract", "block", "fips",
    # ACS structural
    "acs", "bureau", "statistics", "dataset",
    # aggregation verbs that are strong data-question signals
    "compare", "comparison", "percentage", "percent",
    "rate", "median", "distribution", "breakdown",
}

# All US states + DC — any of these is a strong on-topic signal
_US_PLACES: Set[str] = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
    "dc", "d.c.", "washington dc", "united states", "usa", "us", "u.s.",
}

# Obvious off-topic categories — cheap way to fast-fail.
# Patterns use `.{0,30}` for short filler words between key terms.
_OFF_TOPIC_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(write|compose|generate|create)\b.{0,20}\b(poem|song|story|essay|joke|haiku|novel|script)\b", re.IGNORECASE),
    re.compile(r"\b(ignore|disregard|forget|override)\b.{0,30}\b(instruction|instructions|prompt|system|rule|rules|context)\b", re.IGNORECASE),
    re.compile(r"\b(what|reveal|show|print)\b.{0,20}\b(system\s+prompt|your\s+prompt|your\s+instructions)\b", re.IGNORECASE),
    re.compile(r"\bpretend\s+(to\s+be|you're|you\s+are)\b", re.IGNORECASE),
    re.compile(r"\b(roleplay|role\s*play)\b", re.IGNORECASE),
    re.compile(r"\b(recipe|cook|cooking|bake|baking)\b", re.IGNORECASE),  # pizza recipe etc.
]


@dataclass
class GuardrailResult:
    allowed: bool
    reason: str = ""
    user_message: str = ""  # what to show the user if blocked


def check_input(question: str, conversation_has_context: bool = False) -> GuardrailResult:
    """Decide whether the question is on-topic enough to pass to the agent.

    If there's already conversation context (the user said "show me Texas
    population" before and now says "what about Ohio?"), we're more lenient —
    short follow-ups often wouldn't pass the keyword check in isolation.
    """
    if not question or not question.strip():
        return GuardrailResult(
            allowed=False,
            reason="empty",
            user_message="Please enter a question.",
        )

    if len(question) > 2000:
        return GuardrailResult(
            allowed=False,
            reason="too_long",
            user_message="That question is too long. Please shorten it to under 2000 characters.",
        )

    q_lower = question.lower()

    # Fast-fail obvious off-topic / prompt injection attempts
    for pat in _OFF_TOPIC_PATTERNS:
        if pat.search(question):
            return GuardrailResult(
                allowed=False,
                reason="off_topic_pattern",
                user_message=(
                    "I can only answer questions about the US Census dataset "
                    "(population, demographics, income, housing, education, etc.). "
                    "Could you ask something about US demographics?"
                ),
            )

    # Follow-ups in an ongoing conversation get the benefit of the doubt
    if conversation_has_context and len(question) < 120:
        return GuardrailResult(allowed=True)

    # Check for on-topic keywords or US place names
    tokens = set(re.findall(r"\b[a-z]+\b", q_lower))
    if tokens & _ON_TOPIC_TERMS:
        return GuardrailResult(allowed=True)

    for place in _US_PLACES:
        if place in q_lower:
            return GuardrailResult(allowed=True)

    return GuardrailResult(
        allowed=False,
        reason="no_on_topic_terms",
        user_message=(
            "I'm not sure how to answer that from the US Census dataset. "
            "Try asking about population, income, housing, education, race, "
            "or demographics in a US state, county, or city."
        ),
    )


# --- Output guardrail ------------------------------------------------------

_NUMBER_IN_TEXT = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{4,})(?:\.\d+)?\b")


def extract_numbers(text: str) -> List[int]:
    """Pull integers out of a text blob (comma-formatted or 4+ digit)."""
    raw = _NUMBER_IN_TEXT.findall(text)
    out: List[int] = []
    for r in raw:
        try:
            out.append(int(r.replace(",", "")))
        except ValueError:
            continue
    return out


def check_output_grounded(answer: str, sql_result_numbers: List[int],
                          tolerance: float = 0.02) -> GuardrailResult:
    """Check that large numbers in the answer match numbers seen in SQL results.

    Best-effort only — this catches blatant hallucinations like the LLM making
    up a population figure when the SQL returned nothing. It allows:
      - Numbers within `tolerance` of a seen number (rounding: 1,247,821 -> 1.25M)
      - Percentages and small numbers (<1000) — often derived math
      - Year numbers (1900-2100) — context, not data claims
    """
    answer_nums = extract_numbers(answer)
    if not answer_nums:
        return GuardrailResult(allowed=True)

    seen = set(sql_result_numbers)
    suspicious: List[int] = []

    for n in answer_nums:
        if n < 1000:
            continue  # small numbers are often derived (percentages, counts)
        if 1900 <= n <= 2100:
            continue  # year reference
        if n in seen:
            continue
        # Allow nearby rounded numbers
        if any(abs(n - s) <= max(1, int(s * tolerance)) for s in seen):
            continue
        # Also allow order-of-magnitude matches (e.g. answer says "39 million"
        # and SQL returned 39512223 — different representations)
        if any(abs(n - s / 1_000_000) < 1 for s in seen):
            continue
        if any(abs(n - s / 1000) < 1 for s in seen):
            continue
        suspicious.append(n)

    if suspicious:
        return GuardrailResult(
            allowed=False,
            reason=f"ungrounded_numbers: {suspicious[:3]}",
            user_message="",  # the caller decides how to handle
        )
    return GuardrailResult(allowed=True)
