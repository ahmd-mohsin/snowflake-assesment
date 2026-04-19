# Reflection

*Required written reflection for the Snowflake Applied AI take-home.*

## Development process

I broke the 24 hours into three modules — data, agent, UI — and built them in order, treating each as a standalone piece with its own tests. This let me verify each layer in isolation before stacking the next, and kept the blast radius of any bug small.

Rough timeline:

| Hours | What I did |
|---|---|
| 0–1 | Read the spec twice. Wrote the three-module split. Checked in with my own judgment on the trickiest decisions — self-host vs API, prompt-stuffing vs retrieval, Streamlit vs Gradio — and decided to defend each explicitly. |
| 1–5 | Module 1: Snowflake connection, schema discovery, FAISS index, query executor. Hit the dataset-specific quirks (digit-prefix tables, mixed-case columns, typo in `FIELD_LEVELl_9`) and worked around them. Wrote unit tests as I went. |
| 5–13 | Module 2: the agent. Function-calling loop, system prompt, input/output guardrails, conversation state, the deadline mechanism. Tested manually with live Snowflake + OpenAI, caught the sum-of-medians bug, designed and added `sql_semantics.py` to block it deterministically. |
| 13–17 | Module 3: Streamlit UI with heavy custom CSS. Deployment to Streamlit Cloud — hit the `sys.path` issue, fixed it, verified end-to-end. |
| 17–22 | Regression tests, smoke tests, READMEs, this reflection. |
| 22–24 | Buffer for deployment issues, final manual QA, submission. |

I used AI coding tools (mostly Claude) aggressively for boilerplate and scaffolding, and for pair-debugging when the LLM agent misbehaved. I tried to keep the judgment calls explicitly mine — when the assistant proposed something I disagreed with, I pushed back in writing and we resolved it. Best example: the assistant initially wanted to put aggregation-safety logic in Module 1, and I moved it to Module 2 because the rules are agent-semantics, not data-layer concerns.

## Key architectural decisions

### 1. Semantic schema retrieval instead of prompt-stuffing

The dataset has 71 tables and 16,284 columns. No realistic prompt can contain all of it. My design pulls every field description from the `METADATA_CBG_FIELD_DESCRIPTIONS` tables, builds a FAISS index with sentence-transformer embeddings, and expose it to the LLM as a `search_schema` function. The LLM retrieves the top-K most relevant fields for the user's actual question at runtime.

This directly addresses the assignment's tip about "Context Awareness" and "Comprehensive Mapping." The alternative — hardcoding a subset of tables — would have limited the agent to a narrow slice of the dataset and failed on any nuanced question.

### 2. Function-calling agent, not one-shot text-to-SQL

The LLM has two tools (`search_schema`, `execute_sql`) and runs 2–4 tool calls per question on average. I chose this over one-shot text-to-SQL because:
- The LLM can recover from SQL errors by retrying
- The LLM can issue multiple schema searches to explore a topic before writing SQL
- Tool call logs are natural debugging artifacts

### 3. Three layers of guardrails, each deterministic

I mapped each class of failure to a specific guardrail:

| Failure mode | Guardrail |
|---|---|
| User asks something off-topic | Input keyword/pattern filter (<1ms, no API cost) |
| LLM generates destructive SQL | SQL safety regex in `query_executor.py` |
| LLM generates syntactically valid but statistically meaningless SQL | SQL semantic check in `sql_semantics.py` |
| LLM hallucinates a number in its final answer | Output grounding check with retry-on-flag |

No single layer is reliable alone. The prompt's aggregation rules can be ignored, the semantic check only knows 12 median columns, the output check has tolerance windows. Stacking them gives real robustness.

### 4. GPT-4o-mini over self-hosted Qwen 3 8B

I own an RTX 5090 and could plausibly serve Qwen 3 8B via vLLM at 40–80 tokens/sec — fast enough to hit the 60s SLA. I decided against it because "production quality" means not depending on my home machine staying on and my home internet being reachable. A public demo tunneled through ngrok would be fragile.

The cost difference is negligible (~$0.0001 per question with GPT-4o-mini). The deployment reliability gain is substantial.

### 5. Deadline-driven loop with graceful degradation

The agent tracks wall-clock from the start of a turn. If it exceeds 50 seconds (tight margin under the 60s SLA), it aborts mid-loop and returns a helpful message. If a specific SQL query would hit the 45-second Snowflake session timeout, it fails server-side before we lose the whole turn.

This matches the assignment's "fast-fail" guidance — the agent quickly identifies and rejects unanswerable questions rather than making the user wait.

## What I would improve with more time

### High-value, if I had another day

1. **Auto-derive the median-column list.** `sql_semantics.py` currently hardcodes 12 known-median tables. A more complete implementation would query `METADATA_CBG_FIELD_DESCRIPTIONS` for any table title containing "Median," "Mean," "Per Capita," etc., and populate the allowlist automatically. This would generalize beyond what I happened to think of.
2. **LLM-as-judge eval harness.** I would write ~50 question/expected-answer pairs (population queries, income queries, edge cases, adversarial inputs) and run a nightly eval that uses a stronger LLM to grade responses. This is the only way to catch subtle regressions — unit tests can't tell you that a prompt tweak made answers worse on average.
3. **Streaming token output** for the natural-language answer portion. Would reduce perceived latency significantly without changing the architecture.
4. **Query result caching.** Deterministic hash of normalized SQL → cached Snowflake result. Would speed up repeat questions dramatically and cut Snowflake usage.

### Medium-value

5. **Tighter `AppTest` coverage of the Streamlit UI.** Currently the UI has 3 unit tests. Using Streamlit's test harness I could simulate button clicks and message exchanges to catch UI regressions.
6. **Distribution-column handling.** For questions like "what's the distribution of household income in California?" the agent currently gives a point answer. It should return a histogram from the `B19001` bucket columns.
7. **Key-pair Snowflake authentication** in addition to password. Required in many enterprise setups.
8. **Proactive schema-cache invalidation.** Currently manual — delete `.cache/schema_index/` to rebuild.

### Nice-to-have

9. **Mobile layout polish** (the stats row in the welcome card wraps awkwardly on narrow screens).
10. **Telemetry.** Log question, latency, iterations, cost to a database so I can understand real usage patterns.
11. **Self-consistency for temporal questions** ("is California growing?"). Run twice, compare.

## Edge cases and failure modes I identified but did not fully address

### Weighted-average approximation of medians
When the user asks for "the median income," the agent now computes a household-weighted average of block-group medians (with a clear disclaimer). This is a principled approximation but **systematically underestimates or overestimates** depending on the spatial distribution of the underlying data. For California home values, for example, the weighted average comes in around $295k, while the true statewide median is closer to $538k — the gap is largely because block-group medians are right-censored by the Census Bureau at their top-code.

**Why I didn't fix it:** The *true* median requires underlying household records, which the ACS does not publish at block-group grain. Any attempt to compute it from this dataset will be an approximation. The best I can do is label it honestly — which I do — and point the user at more authoritative sources if precision matters.

### Partial matches and composed questions
"How many Hispanic women over 65 in California?" would require combining sex/age (B01001), Hispanic origin (B03003), and geography. The agent can technically do this via multiple queries, but the intersection math isn't exact because the ACS publishes each breakdown separately — there's no "Hispanic women over 65" column. The agent would either (a) use a rough proportion assumption or (b) say it can't compute an exact answer. I tested this briefly and the agent handles it OK but I didn't exhaustively validate.

### Ambiguity of the word "state"
A user saying "state of housing" isn't asking about US states. My input guardrail's keyword list happens to include "state" so this gets let through, and the LLM handles it correctly, but the guardrail is relying on the LLM to disambiguate rather than doing its own.

### Long conversations
The conversation auto-trims after 12 user turns, keeping tool call/result pairs intact. Beyond that, distant context is lost. In practice reviewers will never hit this, but a user who asked 20 follow-ups on the same topic would notice coherence decay.

### Cold start latency
First question after a cold Streamlit Cloud container: 60–90 seconds. This is the single worst piece of UX in the app. It would take a separate ~2-hour push to pre-build and ship the index as a binary artifact (probably via Git LFS) to fix properly.

### Rate limiting / cost protection
No limits on how often a single user can ask questions. A malicious or accidental flood would burn OpenAI credits. For a demo this is acceptable; for real deployment I'd add per-IP rate limits.

## Testing approach

### Philosophy

I separated testing into three tiers by cost/speed:

**Tier 1 — Unit tests** (fast, deterministic, run on every commit).
Mock all external services. Test pure logic: guardrail rules, SQL validation, schema parsing, conversation state. Should run in <30 seconds total.

**Tier 2 — Smoke tests** (slow, requires live Snowflake + OpenAI, run manually before deploy).
End-to-end validation on a handful of canonical questions. Catches real integration issues and is the only way to verify the LLM's actual behavior on representative inputs.

**Tier 3 — Manual UI QA**.
Click through the Streamlit UI, verify layout, chat flow, reset behavior, SQL display.

### Coverage

**71 unit tests pass across all three modules:**
- Module 1: 19 tests (SQL safety, schema parsing, column name mapping)
- Module 2: 49 tests (guardrails, conversation state, agent orchestration with fake LLM, SQL semantic validation)
- Module 3: 3 tests (`DisplayMessage` dataclass)

**3 smoke tests** exist at the repo root:
- `smoke_test.py` — Module 1 against real Snowflake
- `smoke_test_module2.py` — full agent on representative questions
- `smoke_test_reasoning.py` — regression test for the sum-of-medians bug

### What I would add to the test suite

1. **LLM-as-judge eval** over a fixed ~50-question set with expected answer ranges. Run nightly. This is the single most important test addition — unit tests cannot tell me whether a prompt edit degraded answer quality on average, and smoke tests only cover 5 questions.
2. **Regression tests for every historical failure mode.** The sum-of-medians bug is covered by `test_sql_semantics.py` (12 tests) — I'd add one for every future bug I find.
3. **`AppTest` coverage of the Streamlit UI** — simulate user flows without a browser.
4. **Load testing** — how does the system behave with 10 concurrent users? Single Snowflake connection is a bottleneck that would need addressing.
5. **Adversarial prompt set** — a curated list of prompt-injection attempts to verify the input guardrail catches them.

### Tradeoffs I accepted

- **The LLM's behavior isn't unit-tested.** I test everything around it with a fake LLM. Testing "does GPT-4o-mini pick the right columns for question X" is the job of smoke tests and the (future) eval harness.
- **UI coverage is minimal.** Streamlit UIs are genuinely hard to unit-test and I decided the time was better spent on guardrails and semantics. This is a real gap.
- **Coverage is uneven across modules.** Module 2 has the densest coverage because it has the most logic and the highest failure surface. Module 1 is well-tested on parsing and safety. Module 3 is sparse. I'd call this appropriate prioritization for 24 hours, not a finished job.

## One thing I am genuinely proud of

When I first ran the agent against "What's the median household income?", it confidently answered "$16.5 billion" — summing 220,000 block-group medians. That's exactly the kind of wrong-but-plausible answer that erodes user trust. It wasn't caught by my initial output guardrail because the number came from a real SQL result, just from a meaningless aggregation.

The fix was layered:
1. Rewrote the system prompt with explicit aggregation taxonomy and a worked example for median queries
2. Added `sql_semantics.py` — a deterministic, testable rule that blocks SUM of known median columns but allows weighted averages
3. Upgraded the output guardrail from "warn" to "retry once, then refuse" so a flagged answer never reaches the user

Each layer on its own would miss some cases. The combination means the agent now either gives a statistically honest weighted-average answer with a disclaimer, or it refuses. No more $16.5-billion answers.

This is the kind of bug I wouldn't have caught without running the full system against real data — which is why smoke tests matter — and it's the kind of fix that's only robust when you treat guardrails as a defense-in-depth system rather than a single checkpoint.