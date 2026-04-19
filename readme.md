# Census Chat

A production-quality, chat-based agent that answers natural-language questions about US demographics, grounded in the Snowflake Marketplace **US Open Census Data: Neighborhood Insights** dataset.

Built as a 24-hour take-home for Snowflake's Applied AI team.

**Live demo:** _<https://snow-assesment.streamlit.app/>_
**Demo access:** no login required.

---

## What it does

Ask questions like:

> "What's the total population of California in 2020?"
> "How many uninsured people live in Texas?"
> "What's the median household income in the US?"
> "Compare renter-occupied housing in New York vs Florida."

The agent translates the question into Snowflake SQL, executes it against the census dataset, and returns a grounded natural-language answer. Results are rendered as interactive charts or scalar metric cards where possible, and the SQL that ran is always displayed underneath for transparency.

## Architecture

```
                ┌────────────────────────┐
  User ────────▶│  Module 3: Streamlit   │  Dark UI, auto-visualizations,
                │  (module_3/)           │  SQL inspector, session state
                └───────────┬────────────┘
                            │
                ┌───────────▼────────────┐
                │  Module 2: Agent       │  GPT-4o-mini + function calling
                │  (module_2/)           │  4 guardrail layers, retry loop
                └───────────┬────────────┘
                            │
             ┌──────────────┴──────────────┐
             │                             │
   ┌─────────▼─────────┐         ┌─────────▼──────────┐
   │ search_schema     │         │ execute_sql        │
   │ (FAISS over       │         │ (safety + semantic │
   │  16k fields)      │         │  validated)        │
   └─────────┬─────────┘         └─────────┬──────────┘
             │                             │
             └──────────────┬──────────────┘
                            │
                ┌───────────▼────────────┐
                │  Module 1: Data Layer  │  Connection pool, schema index
                │  (module_1/)           │  (OpenAI embeddings + FAISS)
                └───────────┬────────────┘
                            │
                ┌───────────▼────────────┐
                │  Snowflake Marketplace │  US_OPEN_CENSUS_DATA__
                │                        │  NEIGHBORHOOD_INSIGHTS__FREE_DATASET
                └────────────────────────┘
```

Each module has its own README with implementation detail:

- [`module_1/README.md`](module_1/README.md) — Snowflake connection, schema discovery, semantic index
- [`module_2/README.md`](module_2/README.md) — LLM agent, tools, guardrails, conversation state
- [`module_3/README.md`](module_3/README.md) — Streamlit UI, visualizations, deployment

See [`REFLECTION.md`](REFLECTION.md) for development process, architectural decisions, tradeoffs, and known edge cases.

## Key design decisions (short version)

1. **Semantic schema retrieval over prompt-stuffing.** The dataset has 16,000+ columns — too many for any context window. We pull all field descriptions from the `METADATA_CBG_FIELD_DESCRIPTIONS` tables, embed them with OpenAI's `text-embedding-3-small`, build a FAISS index, and cache it to disk. At query time, the LLM calls `search_schema(question)` to pull the top-K relevant fields into its prompt. Total embedding cost: ~$0.005 one-time.
2. **Function-calling agent, not one-shot text-to-SQL.** The LLM has two tools: `search_schema` and `execute_sql`. It typically runs 2–4 tool calls per question, which lets it recover from SQL errors and refine its schema search.
3. **Four layers of guardrails, each deterministic and testable.** See the "Guardrails" section below.
4. **Deadline-driven loop.** The agent tracks wall-clock and aborts with a graceful message at 50s (comfortable margin under the 60s SLA).
5. **GPT-4o-mini over self-hosted Qwen 3 8B.** I considered hosting Qwen on my RTX 5090 but chose an API for deployment reliability. Details in [`REFLECTION.md`](REFLECTION.md).
6. **Auto-visualization of tabular results.** Bar charts for breakdowns, scalar metric cards for single values, tables as fallback — decided structurally from the result shape, no extra LLM call.

## Guardrails — how the agent handles adversarial, ambiguous, or incomplete inputs

The "Production Quality" rubric explicitly asks: *how does the agent behave under ambiguous, incomplete, or adversarial inputs?* Every class of bad input maps to a specific defensive layer:

### Layer 1 — Input guardrail (`module_2/guardrails.py`)

**Catches:** off-topic requests, prompt injection, creative tasks, role-play, recipe requests.

- Reject empty inputs or inputs over 2000 characters.
- Pattern match against known adversarial shapes: *"ignore all previous instructions"*, *"pretend to be"*, *"write a poem"*, *"what is your system prompt"*, *"recipe / cook / bake"*.
- Require at least one demographic/geographic keyword OR a US place name to pass.
- Runs in ~1ms with zero API cost — the agent never sees these inputs.
- Lenient on short follow-ups (*"what about Texas?"*) when conversation history exists.

### Layer 2 — SQL safety (`module_1/query_executor.py`)

**Catches:** destructive SQL the LLM might generate, runaway queries.

- SELECT / WITH only. Blacklist of `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `MERGE`, `COPY`, `CALL`, `EXECUTE`, `USE`.
- Strip comments, reject multi-statement queries.
- Auto-inject `LIMIT 1000` if missing.
- Session-level `STATEMENT_TIMEOUT_IN_SECONDS = 45` so a runaway query dies on the Snowflake side.

### Layer 3 — SQL semantics (`module_2/sql_semantics.py`)

**Catches:** statistically meaningless aggregations that would otherwise execute and return a plausible-but-wrong number.

The canonical example: `SUM("B19013e1")` — valid SQL that sums 220,000 block-group median incomes and returns a ~$16 billion "median household income." We maintain an allowlist of 12 known median/mean/per-capita table prefixes (`B19013`, `B25077`, `B01002`, …) and reject any `SUM()` over them **unless** the pattern is a weighted average (`SUM(median * weights) / SUM(weights)`).

When the guard fires, the error message returned to the LLM includes a suggested fix, so the agent self-corrects on the next iteration.

### Layer 4 — Output grounding (`module_2/guardrails.py`)

**Catches:** LLM hallucinations — plausible numbers that didn't come from any SQL result.

- Extract every integer ≥ 1000 from the agent's answer.
- Verify each one is within 2% of some value seen in the conversation's SQL results (rounding), or matches a scaled representation (39M ≈ 39,512,223), or is a year (1900–2100).
- If any number fails this check: append a corrective instruction to the conversation and run the loop once more.
- If the retry still fails: **refuse** with a clear message rather than return a flagged answer.

### Ambiguity handling

- No year specified → default to 2020 and state the assumption in the answer.
- No location specified → default to national.
- Question truly unanswerable (2024 data, fictional location, below-block-group granularity) → the agent says so directly and briefly explains why.

## Hardening & testing

| What it protects against | How it's tested |
|---|---|
| Off-topic inputs, prompt injection | `module_2/tests/test_guardrails.py` (22 cases) |
| Destructive SQL generation | `module_1/tests/test_query_executor.py` (13 cases) |
| Sum-of-median class of bugs | `module_2/tests/test_sql_semantics.py` (12 cases) |
| LLM orchestration regressions | `module_2/tests/test_agent.py` (9 cases with fake LLM) |
| End-to-end data-layer behavior | `smoke_test.py` (hits real Snowflake) |
| End-to-end agent behavior | `smoke_test_module2.py`, `smoke_test_reasoning.py` |
| Adversarial / ambiguous / edge-case prompts | `test_adversarial.py` — **21 checks across 6 categories** |

The adversarial suite (`test_adversarial.py`) is the most interesting. It exercises:

| Category | # checks | Examples |
|---|---|---|
| **A. Adversarial** | 5 | Prompt injection, DAN jailbreak, creative tasks, SQL injection attempts, roleplay |
| **B. Ambiguous** | 3 | Unscoped "What is the population?", pure follow-up with no prior context |
| **C. Unanswerable** | 4 | Future years, predictions, fictional locations, sub-block-group addresses |
| **D. Incomplete** | 4 | Single-word prompts, typo-heavy queries, empty input, oversized input |
| **E. Partial match** | 2 | Real concepts the dataset can only approximate ("millionaires") |
| **F. Math trap** | 3 | Median income/home value — the sum-of-medians class |

Each check declares a list of predicates the response must satisfy. Failures print the exact predicate that broke, making debugging easy. See [`module_2/README.md`](module_2/README.md#testing) for more.

## Output presentation

Beyond the natural-language answer, the agent renders:

- **Scalar metric cards** for single-value results — e.g. "California population: 39.51M" displayed as a large, styled number.
- **Horizontal bar charts** (Plotly) when the SQL returns ≤30 rows with a label column and a numeric column — perfect for state comparisons or age-bracket distributions.
- **Formatted tables** (dark-themed, numeric columns comma-grouped) for all other results.
- **The SQL itself** with syntax highlighting — always shown so the user can verify the query.
- **Warning banners** when output guardrails flag an answer.

The visualization choice is made by `module_3/visualizations.py` based purely on the result shape, with no extra LLM call. See [`module_3/README.md`](module_3/README.md#auto-visualization) for the decision tree.

## Local setup

### Prerequisites

- Python 3.10 or 3.11 (avoid 3.14 — see `REFLECTION.md`)
- A Snowflake trial account with the **US Open Census Data: Neighborhood Insights** share mounted from the Marketplace
- An OpenAI API key with access to `gpt-4o-mini` and `text-embedding-3-small`

### Install

```bash
git clone https://github.com/<your-username>/snow-assesment.git
cd snow-assesment
pip install -r requirements.txt
```

### Configure

```bash
cp module_1/.env.example .env
```

Edit `.env`:

```
SNOWFLAKE_ACCOUNT=<account_identifier>        # e.g. xxc32630.us-east-1
SNOWFLAKE_USER=<your_user>
SNOWFLAKE_PASSWORD=<your_password>
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_ROLE=ACCOUNTADMIN
SNOWFLAKE_DATABASE=US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET
SNOWFLAKE_SCHEMA=PUBLIC
OPENAI_API_KEY=sk-...
```

### Run

```bash
streamlit run module_3/app.py
```

Opens at `http://localhost:8501`.

On the **very first run**, the app will build the schema index by embedding 16,284 census field descriptions via the OpenAI API (~20s, costs ~$0.005). Subsequent runs load the cached index in ~1 second.

## Testing

```bash
# Unit tests (72 total, run in ~25s)
python -m pytest module_1/tests/ module_2/tests/ module_3/tests/ -v

# End-to-end smoke tests (require live Snowflake + OpenAI)
python smoke_test.py              # Module 1 — data layer
python smoke_test_module2.py      # Module 2 — agent, multi-turn, guardrails
python smoke_test_reasoning.py    # Module 2 — aggregation-semantics regression

# Adversarial / ambiguous / edge-case suite (~3-5 min)
python test_adversarial.py
```

## Deployment (Streamlit Community Cloud)

1. Push this repo (can be private) to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) → sign in with GitHub → **Create app**.
3. Select the repo, branch `main`, main file `module_3/app.py`.
4. Click **Advanced settings → Secrets** and paste (TOML format):

   ```toml
   SNOWFLAKE_ACCOUNT = "xxc32630.us-east-1"
   SNOWFLAKE_USER = "muahmed"
   SNOWFLAKE_PASSWORD = "..."
   SNOWFLAKE_WAREHOUSE = "COMPUTE_WH"
   SNOWFLAKE_ROLE = "ACCOUNTADMIN"
   SNOWFLAKE_DATABASE = "US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET"
   SNOWFLAKE_SCHEMA = "PUBLIC"
   OPENAI_API_KEY = "sk-..."
   ```

5. Click **Deploy**.

First deploy takes ~3 min. First question after a cold deploy takes ~30-60s as the agent builds its schema index via the OpenAI embeddings API; subsequent questions complete in 5–15s.

## Project structure

```
snow-assesment/
├── README.md                   ← you are here
├── REFLECTION.md               ← required written reflection
├── requirements.txt            ← consolidated dependencies
├── .streamlit/
│   └── config.toml             ← dark-theme settings
├── module_1/                   ← data layer
│   ├── README.md
│   ├── config.py
│   ├── snowflake_client.py
│   ├── schema_explorer.py
│   ├── schema_index.py         ← OpenAI embeddings + FAISS
│   ├── query_executor.py
│   └── tests/
├── module_2/                   ← agent layer
│   ├── README.md
│   ├── agent.py
│   ├── prompts.py
│   ├── tools.py
│   ├── guardrails.py
│   ├── sql_semantics.py        ← blocks SUM-of-medians etc.
│   ├── conversation.py
│   ├── llm_client.py
│   └── tests/
├── module_3/                   ← UI layer
│   ├── README.md
│   ├── app.py
│   ├── styles.py
│   ├── components.py
│   ├── visualizations.py       ← auto-charts / scalar cards / tables
│   ├── session.py
│   └── tests/
├── smoke_test.py               ← module 1 smoke test
├── smoke_test_module2.py       ← module 2 smoke test
├── smoke_test_reasoning.py     ← semantic-guardrail regression test
└── test_adversarial.py         ← 21-check adversarial / ambiguous suite
```

## Known limitations

See [`REFLECTION.md`](REFLECTION.md) for the full list. The most important ones:

- **Weighted-average approximation of medians.** When asked for "median income," the agent computes a household-weighted average of block-group medians (labeled as an approximation). The true median cannot be computed from block-group data alone.
- **Cold start**: first question after a cold Streamlit Cloud container takes 30-60s while the schema index builds.
- **No token streaming** — progress is shown via status spinner instead.
- **Wrong-table risk**: for some questions the semantic index returns a more-specific-than-intended table (e.g. education-by-age when the user wanted simple age breakdown). The agent's answer is usually plausible but computed from the wrong universe.

## Credits

- Data: [SafeGraph US Open Census Data](https://www.safegraph.com/free-data/open-census-data) via Snowflake Marketplace
- LLM: OpenAI GPT-4o-mini
- Embeddings: OpenAI `text-embedding-3-small`
- Vector index: FAISS
- UI: Streamlit + Plotly