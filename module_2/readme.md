# Module 2: Agent Layer

**Responsibility:** Turn a user question into a grounded, statistically correct natural-language answer. Owns the LLM, the tool definitions, the system prompt, guardrails at every boundary, and conversation state.

This module is the bulk of the engineering and the part most directly graded on "LLM / AI Engineering" and "Production Quality."

## File overview

| File | Responsibility |
|---|---|
| `agent.py` | The main loop: input-guardrail → tool-calling loop → output-guardrail → retry-on-ungrounded |
| `prompts.py` | The system prompt — encodes quoting rules, aggregation semantics, worked examples |
| `tools.py` | `search_schema` and `execute_sql` function definitions + handlers |
| `guardrails.py` | Input filter (keyword + pattern) and output grounding check |
| `sql_semantics.py` | Census-aware SQL validation (blocks `SUM(median_column)` etc.) |
| `conversation.py` | Message history + structured memory, auto-trims long conversations |
| `llm_client.py` | Thin OpenAI wrapper with timeout + one retry on transient errors |
| `config.py` | Model choice, deadlines, row limits |
| `tests/` | 49 unit tests covering guardrails, agent orchestration, semantic validation |

## The agent loop (at a glance)

```
┌──────────────────────────────────────────────────────────┐
│  1. Input guardrail                                      │
│     • empty / too long → reject                          │
│     • prompt-injection / off-topic patterns → reject     │
│     • keyword match OR US place name OR follow-up → pass │
└──────────────────┬───────────────────────────────────────┘
                   │ pass
                   ▼
┌──────────────────────────────────────────────────────────┐
│  2. Function-calling loop (max 5 iterations, 50s budget) │
│     LLM can call:                                        │
│       • search_schema(query, year?) — FAISS retrieval   │
│       • execute_sql(sql) — safety + semantic-checked    │
└──────────────────┬───────────────────────────────────────┘
                   │ LLM returns final text
                   ▼
┌──────────────────────────────────────────────────────────┐
│  3. Output guardrail                                     │
│     • Every numeric claim must trace to a SQL result     │
│     • If flagged: send corrective instruction, retry 1x  │
│     • If still flagged: refuse with explanation          │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
               Final answer
```

## LLM choice: GPT-4o-mini

Reasoning summarized:

| Option considered | Why rejected / chosen |
|---|---|
| **GPT-4o-mini (chosen)** | Fast (2–5s per turn), reliable function-calling, ~$0.0001 per question |
| Claude Haiku | Also viable; went with GPT-4o-mini for familiarity and lowest latency in testing |
| Qwen 3 8B on my RTX 5090 (self-hosted) | Technically works (~40–80 tok/s with vLLM) but deploying publicly means exposing my home machine via a tunnel. Too fragile for "production quality." |
| GPT-4 / Claude Opus | Overkill for this task; 10x the cost with marginal quality gain |

## System prompt strategy

See `prompts.py`. The prompt is organized into:

1. **Role + behavioral stance** — "rigorous data analyst who prioritizes correctness over speed"
2. **Tool reference** — terse descriptions of `search_schema` and `execute_sql`
3. **Critical dataset facts** — the quoting rules (must double-quote tables AND columns), the 2019/2020 vintage constraint, the `CENSUS_BLOCK_GROUP` structure
4. **Aggregation rules** — three categories of columns (summable counts, never-sum medians, summable distribution buckets) with explicit examples of each
5. **State FIPS code table** — saves a tool call when the user names a state
6. **Worked examples** — three canonical queries (population of a state, median household income, uninsured count) with full SQL shown
7. **Ambiguity handling** — defaults + state-the-assumption approach
8. **Output style** — readable numbers, honest labeling of approximations, refusal over wrong answer

The prompt is ~2500 tokens — noticeable but worthwhile. A shorter prompt led to more LLM errors (wrong columns, missing quotes, sum-of-medians).

## The three guardrail layers

This is worth emphasizing because it directly addresses the "operational guardrails" tip in the assignment and is the most interesting production-hardening work.

### Layer 1 — Input guardrail (`guardrails.py::check_input`)

**Purpose:** Fast-fail obvious off-topic or adversarial inputs before spending any LLM or Snowflake cost.

**How it works:**
1. **Length bounds** — reject empty or >2000 chars
2. **Pattern list** — reject prompt injection (`ignore previous instructions`), role-play (`pretend to be`), creative tasks (`write a poem`), system-prompt probes, recipes/cooking
3. **Keyword allowlist** — if the input contains ANY demographic/geographic/census term, pass
4. **Place names** — any US state name passes
5. **Follow-up leniency** — short messages (<120 chars) pass if there's conversation history, to allow "what about Ohio?"

**Cost:** ~1ms (pure Python regex + set lookups). Zero API cost.

**Known false-negative:** a sufficiently disguised injection that uses census vocabulary could slip through. The LLM's own system prompt provides a second line of defense.

**Known false-positive:** a legitimate question phrased entirely with proper-noun place names and no common keywords ("Orange County statistics") might be rejected. Follow-up leniency and the assistant's prompt-side refusal cover most of these.

### Layer 2 — SQL safety (`module_1/query_executor.py`)

Already covered in `module_1/README.md`. Ensures no DDL/DML, enforces `LIMIT`, applies server-side timeout.

### Layer 3 — SQL semantics (`sql_semantics.py`) — **the most interesting one**

**Purpose:** Catch statistically meaningless aggregations that are *syntactically* valid SQL.

**Motivating case:** During development the agent generated
```sql
SELECT SUM("B19013e1") FROM "2020_CBG_B19"
```
which *runs successfully* and returns a number in the ~$16 billion range, but that number is **meaningless** — it's a sum of 220,000 medians. The LLM confidently reported "$16.5 billion median household income" to the user.

**How the check works:** A small allowlist of known median/mean/per-capita table prefixes (`B19013`, `B25077`, `B01002`, etc.). Regex matches `SUM(<prefix>e<digits>)`. Weighted-average patterns (`SUM(col * weights) / SUM(weights)`) are explicitly allowed.

When triggered, the error message returned to the LLM includes a suggested fix (the weighted-average pattern), giving the LLM a clear signal to self-correct on the next iteration.

**Limitation:** The allowlist is hand-curated with 12 entries. A more complete implementation would auto-derive the list from field descriptions containing "Median," "Mean," "Per Capita," etc. Noted in `REFLECTION.md`.

### Layer 4 — Output grounding (`guardrails.py::check_output_grounded`)

**Purpose:** Catch the case where the LLM produces a plausible-sounding number that *didn't come from any SQL result it saw*. Classic hallucination.

**How it works:**
1. Extract every integer ≥1000 from the agent's answer (with comma grouping).
2. Compare against the union of numbers the agent saw in tool results across all iterations.
3. Allow: exact match, within 2% (rounding), million/thousand-scale representations (39M ≈ 39512223), year references (1900–2100), percentages (<1000).
4. Any remaining unexplained number → flag.

**What flagging does (this was upgraded during development):**
- **Old behavior:** append a warning banner to the answer. The user saw the warning but also saw the wrong number.
- **New behavior:** append a corrective instruction to the conversation (*"Your previous answer contained numeric figures that do not trace to any SQL result. Redo using only numbers from the tool results, or say so directly."*) and run one more loop iteration. If the retry is still flagged, the agent refuses with a clear explanation.

A flagged answer is worse than a refusal.

## Conversation state (`conversation.py`)

- OpenAI-format message history (`role`, `content`, `tool_calls`, `tool_call_id`)
- Prepends the system prompt when sending to the LLM
- Auto-trims to the last 12 user turns (keeps tool call/result pairs intact — we never cut in the middle of a tool sequence)
- Tracks `last_query` (the most recent user question + SQL) for UI display

**Why not semantic summarization of old turns?** On a 12-turn cap each conversation is well under the model's context window. Summarization would be a useful optimization for a truly long-running assistant but not worth the complexity here.

## Testing

```bash
python -m pytest module_2/tests/ -v
```

49 unit tests split across three files:

- **`test_guardrails.py`** (22 tests) — input filter edge cases, output grounding with various number formats, place-name matching, follow-up leniency.
- **`test_conversation.py`** (6 tests) — state initialization, trimming behavior, tool call/result pairing.
- **`test_agent.py`** (9 tests) — the orchestration loop with a fake LLM: single-turn, multi-turn, tool-loop, max-iteration fallback, deadline behavior, exception handling.
- **`test_sql_semantics.py`** (12 tests) — blocks `SUM` of each known median column; allows weighted averages; allows legitimate counts and distribution bucket sums.

**Testing philosophy:** Every test here either tests pure logic (guardrails, semantic check) or uses a fake LLM that returns canned responses. No network calls, no Snowflake, no OpenAI. This keeps CI fast and deterministic, and makes it easy to add regression tests for specific failure modes.

**What's NOT tested at the unit level:** the actual LLM's behavior — whether it chooses the right columns, formats numbers well, avoids sum-of-medians when prompted. These are behavioral properties that are hard to assert reliably in a unit test. Instead they're covered by `smoke_test_module2.py` and `smoke_test_reasoning.py`, which run the real agent against the real Snowflake + OpenAI and assert on properties like "answer contains a plausible number" and "answer does not contain 'billion' for a household median."

See `REFLECTION.md` for what I'd add: LLM-as-judge evals over a fixed question set, regression tests for each historical failure mode.

## What I'd do with more time

- **Streaming token output** to the UI. Currently the agent returns a complete response at the end; Streamlit shows a "thinking" spinner. For perceived latency improvement, stream tokens as they generate.
- **Auto-derive the median-column list** from metadata instead of hardcoding 12 entries.
- **Self-consistency for ambiguous questions.** For a question like "is California growing?" (which needs temporal comparison), run the agent twice and compare answers; surface disagreement to the user.
- **Query result caching.** Identical user questions within a short window should hit a cache rather than re-running Snowflake SQL. Would require a cache key on normalized SQL.
- **LLM-as-judge eval harness** over a fixed ~50-question test set with expected answer ranges.