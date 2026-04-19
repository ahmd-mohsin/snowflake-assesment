# Reflection

*Required written reflection for the Snowflake Applied AI take-home.*

## Development process

I broke the 24 hours into three modules — data, agent, UI — and built them in order, treating each as a standalone piece with its own tests. This let me verify each layer in isolation before stacking the next, and kept the blast radius of any bug small.

Rough timeline:

| Hours | What I did |
|---|---|
| 0–1 | Read the spec twice. Wrote the three-module split. Checked in with my own judgment on the trickiest decisions — self-host vs API, prompt-stuffing vs retrieval, Streamlit vs Gradio — and decided to defend each explicitly. |
| 1–5 | Module 1: Snowflake connection, schema discovery, FAISS index, query executor. Hit dataset-specific quirks (digit-prefix tables, mixed-case columns, typo in `FIELD_LEVELl_9`) and worked around them. |
| 5–13 | Module 2: the agent. Function-calling loop, system prompt, input/output guardrails, conversation state, deadline mechanism. Tested manually with live Snowflake + OpenAI, caught the sum-of-medians bug, designed and added `sql_semantics.py` to block it deterministically. |
| 13–17 | Module 3: Streamlit UI with heavy custom CSS. Deployment to Streamlit Cloud — hit and fought several infra issues (see below). |
| 17–20 | Added auto-visualizations (charts, scalar metric cards) and the adversarial test suite (`test_adversarial.py`). |
| 20–23 | Regression tests, smoke tests, READMEs, this reflection. |
| 23–24 | Final manual QA, submission. |

I used AI coding tools (Claude) aggressively for boilerplate and scaffolding, and for pair-debugging when the LLM agent misbehaved. I tried to keep the judgment calls explicitly mine — when the assistant proposed something I disagreed with, I pushed back. Best example: the assistant initially wanted to put aggregation-safety logic in Module 1, and I moved it to Module 2 because the rules are agent-semantics concerns, not data-layer ones.

## Key architectural decisions

### 1. Semantic schema retrieval instead of prompt-stuffing

The dataset has 71 tables and 16,284 columns. No realistic prompt can contain all of it. My design pulls every field description from the `METADATA_CBG_FIELD_DESCRIPTIONS` tables, builds a FAISS index over embeddings, and exposes it to the LLM as a `search_schema` function. The LLM retrieves the top-K most relevant fields for the user's actual question at runtime.

Directly addresses the assignment's "Context Awareness" and "Comprehensive Mapping" tips. The alternative — hardcoding a subset of tables — would have limited the agent to a narrow slice and failed on nuanced questions.

### 2. OpenAI embeddings over sentence-transformers (pivoted mid-deployment)

I originally used `sentence-transformers/all-MiniLM-L6-v2` for local embeddings — the obvious choice for a cost-sensitive local build. During deployment to Streamlit Cloud, this decision collapsed: Streamlit Cloud's default Python 3.14 environment combined with the latest `transformers` library produced a cascade of failures (missing `torchvision`, `cannot schedule new futures after interpreter shutdown` from `transformers/core_model_loading.py`). Pinning Python 3.11 didn't work reliably. So I pivoted to the OpenAI embeddings API (`text-embedding-3-small`).

Tradeoff: $0.005 one-time cost per index build, and a recurring ~$0.000002 per question for query embedding. In exchange I removed torch, torchvision, transformers, and sentence-transformers entirely from `requirements.txt` — roughly 3GB of dependencies. The app deployed cleanly on the first attempt after the change. Embedding quality is actually slightly better than MiniLM-L6-v2.

**Lesson:** for cloud-deployed apps, prefer API-based dependencies where the marginal cost is negligible. The infra simplification is worth far more than the pennies saved.

### 3. Function-calling agent, not one-shot text-to-SQL

The LLM has two tools (`search_schema`, `execute_sql`) and runs 2–4 tool calls per question on average. I chose this over one-shot text-to-SQL because:
- The LLM can recover from SQL errors by retrying
- It can issue multiple schema searches to explore a topic before writing SQL
- Tool call logs are natural debugging artifacts

### 4. Four layers of guardrails, each deterministic

I mapped each class of failure to a specific defensive layer:

| Failure mode | Guardrail |
|---|---|
| User asks something off-topic | Input keyword/pattern filter (<1ms, no API cost) |
| LLM generates destructive SQL | SQL safety regex in `query_executor.py` |
| LLM generates syntactically valid but statistically meaningless SQL | SQL semantic check in `sql_semantics.py` |
| LLM hallucinates a number in its final answer | Output grounding check with retry-on-flag |

No single layer is reliable alone. The prompt's aggregation rules can be ignored, the semantic check only knows 12 median columns, the output check has tolerance windows. Stacking them gives real robustness.

### 5. GPT-4o-mini over self-hosted Qwen 3 8B

I own an RTX 5090 and could plausibly serve Qwen 3 8B via vLLM at 40–80 tokens/sec. I decided against it because "production quality" means not depending on my home machine staying on and my home internet being reachable. Cost difference is negligible (~$0.0001 per question with GPT-4o-mini); deployment reliability gain is substantial.

### 6. Deadline-driven loop with graceful degradation

The agent tracks wall-clock from the start of a turn. If it exceeds 50 seconds (tight margin under the 60s SLA), it aborts mid-loop and returns a helpful message. If a specific SQL query would hit the 45-second Snowflake session timeout, it fails server-side before we lose the whole turn.

### 7. Auto-visualization over LLM-generated charts

I considered having the LLM generate chart specifications (e.g. emit `VIZ: bar_chart(...)` tokens the UI could parse). I chose instead to decide visualization structurally based on SQL result shape: 1 row 1 col → scalar card, 2 cols with label + number → bar chart, otherwise → table.

Why: the LLM's natural-language answer is already a chart-in-prose. A second LLM-generated spec was redundant. A purely structural decision is deterministic, testable, and adds no latency.

## What I would improve with more time

### High-value, if I had another day

1. **LLM-as-judge eval harness** over a fixed ~50-question test set with expected answer ranges. Run nightly. The single most important test addition — unit tests cannot tell me whether a prompt tweak made answers worse on average.
2. **Auto-derive the median-column list.** `sql_semantics.py` currently hardcodes 12 known-median tables. A better implementation would query `METADATA_CBG_FIELD_DESCRIPTIONS` for any table title containing "Median," "Mean," "Per Capita," etc., and populate the allowlist automatically.
3. **Streaming token output** for the natural-language answer. Would reduce perceived latency significantly.
4. **Query result caching.** Deterministic hash of normalized SQL → cached Snowflake result.
5. **Pre-build and ship the FAISS index as a binary artifact** (via Git LFS) so the first-question latency on Streamlit Cloud drops from 30-60s to <5s.

### Medium-value

6. **Tighter `AppTest` coverage of the Streamlit UI.** Currently 3 unit tests; could meaningfully expand.
7. **Distribution-column handling.** For "distribution of income in California" the agent gives a point answer; it should return a histogram from the `B19001` bucket columns.
8. **Key-pair Snowflake authentication** in addition to password.
9. **US choropleth map** for state-level results.

### Nice-to-have

10. **Mobile layout polish** (the welcome-card stats row wraps awkwardly on narrow screens).
11. **Telemetry.** Log question, latency, iterations, cost to a database.
12. **Self-consistency for temporal questions** ("is California growing?"). Run twice, compare.

## Edge cases and failure modes I identified but did not fully address

### Weighted-average approximation of medians
When asked for "the median income," the agent computes a household-weighted average of block-group medians (with a clear disclaimer). This is principled but **systematically under- or over-estimates** depending on spatial income distribution. For California home values, the weighted average I get is ~$295k vs the true statewide median of ~$538k — largely because block-group medians are right-censored (Census top-codes high values).

**Why not fixed:** the true median requires underlying household records, which the ACS does not publish at block-group grain. Any computation from this dataset will be an approximation. Best I can do is label it honestly and point users to authoritative sources if precision matters.

### Wrong-table selection for distribution queries
Observed during testing: when the user asks "show me the age distribution in Massachusetts," the agent sometimes picks `B28005` (Age By Educational Attainment By Employment Status) instead of the simpler `B01001` (Sex By Age). The answer is plausible because the universe is similar, but computed from the wrong distribution. A fix would prefer simpler/shorter table titles when multiple candidates score close in the semantic index, or have the LLM verify `TABLE_TITLE` matches the question's granularity before querying.

### Partial-match concepts
"How many millionaires are in California?" — the dataset has household-income buckets but no "millionaire" flag per se. The agent correctly acknowledges this as an approximation, but the approximation quality depends heavily on how the LLM chooses to answer. More canonical examples in the prompt would help.

### Ambiguity of the word "state"
A user saying "state of housing" isn't asking about US states. My input guardrail's keyword list includes "state," so this passes, and the LLM handles it correctly in practice — but the guardrail is relying on the LLM to disambiguate rather than doing its own.

### Long conversations
Auto-trim after 12 user turns, keeping tool call/result pairs intact. Beyond that, distant context is lost. A real user asking 20+ follow-ups on the same topic would notice coherence decay.

### Cold start latency on Streamlit Cloud
First question after a cold container: 30-60 seconds. This is the single worst piece of UX. Pre-building the FAISS index into the repo as a binary artifact would fix it — noted for future work.

### Rate limiting / cost protection
No limits on how often a single user can ask questions. A malicious or accidental flood would burn OpenAI credits. Acceptable for a demo; not for real deployment.

## Testing approach

### Philosophy

I separated testing into three tiers by cost/speed:

**Tier 1 — Unit tests** (fast, deterministic, run on every commit).
Mock all external services. Test pure logic. Should run in <30 seconds total.

**Tier 2 — Smoke tests** (slow, requires live Snowflake + OpenAI, run manually).
End-to-end validation on a handful of canonical questions. Catches real integration issues.

**Tier 3 — Adversarial / edge-case suite** (slow, real services, predicate-based).
Exercises the agent against ambiguous, adversarial, and incomplete inputs to verify all four guardrail layers work together.

**Tier 4 — Manual UI QA**.
Click through the Streamlit UI, verify layout, chat flow, reset behavior, SQL display, chart rendering.

### Coverage

**72 unit tests** across all three modules:
- Module 1: 19 tests (SQL safety, schema parsing, column name mapping)
- Module 2: 49 tests (guardrails, conversation state, agent orchestration with fake LLM, SQL semantic validation, result-row plumbing)
- Module 3: 3 tests (`DisplayMessage` dataclass)

**3 smoke tests** at the repo root:
- `smoke_test.py` — Module 1 against real Snowflake
- `smoke_test_module2.py` — full agent on 5 representative questions
- `smoke_test_reasoning.py` — regression test for the sum-of-medians bug specifically

**Adversarial suite** (`test_adversarial.py`) — 21 checks across 6 categories:

| Category | # checks | Validates |
|---|---|---|
| Adversarial | 5 | Prompt injection, DAN jailbreak, creative tasks, SQL injection, roleplay |
| Ambiguous | 3 | Unscoped queries, pure follow-ups, vague metrics |
| Unanswerable | 4 | Future years, predictions, fictional locations, too-fine granularity |
| Incomplete | 4 | Single words, typos, empty input, oversized input |
| Partial match | 2 | Dataset-approximate concepts |
| Math trap | 3 | Sum-of-median class of errors |

Each check declares predicates the response must satisfy. Failures print the specific predicate that broke, making debugging easy.

### What I would add to the test suite

1. **LLM-as-judge eval** over a fixed ~50-question set with expected answer ranges. Run nightly.
2. **Regression tests for every historical failure mode.** The sum-of-medians bug is already covered (12 tests in `test_sql_semantics.py`); I'd add one for every future bug found.
3. **`AppTest` coverage of the Streamlit UI** — simulate user flows without a browser.
4. **Load testing** — how does the system behave with 10 concurrent users? Single Snowflake connection is a bottleneck.
5. **Expanded adversarial set** — currently 21 checks; easy to extend with more prompt-injection shapes, SQL-injection patterns, jailbreak attempts from public corpora.

### Tradeoffs I accepted

- **The LLM's behavior isn't unit-tested.** Everything around it is tested with a fake LLM. Verifying "does GPT-4o-mini pick the right columns for question X" is the job of smoke tests and the (future) eval harness.
- **UI coverage is minimal.** Streamlit UIs are hard to unit-test and I decided the time was better spent on guardrails and semantics. Real gap.
- **Coverage is uneven across modules.** Module 2 has the densest coverage because it has the most logic and highest failure surface. Module 1 is well-tested on parsing and safety. Module 3 is sparse. Appropriate prioritization for 24 hours, not a finished job.

## Two things I am genuinely proud of

### 1. The sum-of-medians fix

When I first ran the agent against "What's the median household income?", it confidently answered "$16.5 billion" — summing 220,000 block-group medians. That's exactly the kind of wrong-but-plausible answer that erodes user trust. It wasn't caught by my initial output guardrail because the number came from a real SQL result, just from a meaningless aggregation.

The fix was layered:
1. Rewrote the system prompt with explicit aggregation taxonomy and a worked example for median queries
2. Added `sql_semantics.py` — a deterministic, testable rule that blocks SUM of known median columns but allows weighted averages
3. Upgraded the output guardrail from "warn" to "retry once, then refuse"

Each layer alone would miss some cases. The combination means the agent now either gives a statistically honest weighted-average answer with a disclaimer, or it refuses. No more $16.5-billion answers.

### 2. Recovering from the Python 3.14 + transformers disaster

The deployment to Streamlit Cloud hit a wall: Python 3.14 environment + latest `transformers` library produced a cascade of failures that had nothing to do with my code. Missing `torchvision`, threadpool shutdown errors, dependency conflicts. Pinning Python 3.11 via `runtime.txt` didn't take. I could have burned hours fighting Streamlit Cloud's Python resolution.

Instead, I stepped back, recognized the whole `torch + transformers + sentence-transformers` dependency chain existed only to embed 16k short strings, and swapped to the OpenAI embeddings API. The deploy worked on the next attempt. Cost: half a cent. Benefit: no more deployment infra debugging.

The willingness to throw away a "free" local-compute solution in favor of a tiny-cost API solution — when the former was actively blocking progress — felt like the right call. It's the kind of pragmatic tradeoff I'd want to be making on a real team.