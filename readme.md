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

The agent translates the question into Snowflake SQL, executes it against the census dataset, and returns a grounded natural-language answer. The SQL that ran is always displayed under the answer for transparency.

## Architecture

```
                ┌────────────────────────┐
  User ────────▶│  Module 3: Streamlit   │  Dark-themed chat UI, SQL inspector,
                │  (module_3/)           │  @st.cache_resource agent, sidebar
                └───────────┬────────────┘
                            │
                ┌───────────▼────────────┐
                │  Module 2: Agent       │  GPT-4o-mini + function calling loop
                │  (module_2/)           │  Guardrails: input / SQL / output
                └───────────┬────────────┘
                            │
             ┌──────────────┴──────────────┐
             │                             │
   ┌─────────▼─────────┐         ┌─────────▼──────────┐
   │ search_schema     │         │ execute_sql        │
   │ (FAISS over       │         │ (safety-validated  │
   │  16k fields)      │         │  Snowflake query)  │
   └─────────┬─────────┘         └─────────┬──────────┘
             │                             │
             └──────────────┬──────────────┘
                            │
                ┌───────────▼────────────┐
                │  Module 1: Data Layer  │  Connection pool, schema index
                │  (module_1/)           │  semantic retrieval, SQL executor
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
- [`module_3/README.md`](module_3/README.md) — Streamlit UI + deployment

See [`REFLECTION.md`](REFLECTION.md) for development process, architectural decisions, tradeoffs, and known edge cases.

## Key design decisions (short version)

1. **Semantic schema retrieval over prompt-stuffing.** The dataset has 16,000+ columns — too many for any context window. On first run we pull all field descriptions from the `METADATA_CBG_FIELD_DESCRIPTIONS` tables, build a FAISS index with sentence-transformer embeddings, and cache it to disk. At query time, the LLM calls `search_schema(question)` to pull the top-K relevant fields into the prompt.
2. **Function-calling agent, not one-shot text-to-SQL.** The LLM has two tools: `search_schema` and `execute_sql`. It typically runs 2–4 tool calls per question. This lets it recover from SQL errors and schema misses.
3. **Three-layer guardrails, each deterministic and testable.**
   - **Input** (keyword + pattern match) — rejects off-topic / prompt-injection before any LLM or Snowflake cost is incurred. Runs in <1ms.
   - **SQL safety** (regex) — SELECT/WITH only, no DDL/DML, forced row limit, per-session timeout.
   - **SQL semantics** (census-aware) — blocks statistically meaningless aggregations like `SUM(median_column)`.
   - **Output grounding** — ensures numeric claims trace to SQL results; retries with a corrective instruction if not.
4. **Deadline-driven loop.** The agent tracks wall-clock and aborts with a friendly message at 50s (comfortable margin under the 60s SLA).
5. **GPT-4o-mini over self-hosted Qwen 3 8B.** I considered hosting Qwen on my RTX 5090 but chose an API for deployment reliability. Details in [`REFLECTION.md`](REFLECTION.md).

## Local setup

### Prerequisites

- Python 3.10+
- A Snowflake trial account with the **US Open Census Data: Neighborhood Insights** share mounted from the Marketplace
- An OpenAI API key

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

Edit `.env` and fill in:

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

On the **very first run**, the app will build the schema index (~30–60 seconds). Subsequent runs use the cached index (~1 second).

## Testing

```bash
python -m pytest module_1/tests/ module_2/tests/ module_3/tests/ -v
```

All 71 unit tests pass. End-to-end smoke tests:

```bash
python smoke_test.py              # Module 1 — Snowflake + schema index + query exec
python smoke_test_module2.py      # Module 2 — agent, multi-turn, guardrails
python smoke_test_reasoning.py    # Module 2 — aggregation semantics fix
```

See [`module_2/README.md`](module_2/README.md) for testing strategy and coverage philosophy.

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

First deploy takes ~5 min (installs `faiss-cpu`, `sentence-transformers`, etc.). First question after a cold deploy takes ~60–90s as the schema index rebuilds; subsequent questions complete in 5–15s.

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
│   ├── schema_index.py
│   ├── query_executor.py
│   └── tests/
├── module_2/                   ← agent layer
│   ├── README.md
│   ├── agent.py
│   ├── prompts.py
│   ├── tools.py
│   ├── guardrails.py
│   ├── sql_semantics.py
│   ├── conversation.py
│   ├── llm_client.py
│   └── tests/
├── module_3/                   ← UI layer
│   ├── README.md
│   ├── app.py
│   ├── styles.py
│   ├── components.py
│   ├── session.py
│   └── tests/
├── smoke_test.py               ← module 1 smoke test
├── smoke_test_module2.py       ← module 2 smoke test
└── smoke_test_reasoning.py     ← semantic-guardrail regression test
```

## Known limitations

See [`REFLECTION.md`](REFLECTION.md) for the full list. The most important ones:

- **Weighted-average approximation of medians** — when the user asks for "the median income," the agent computes a household-weighted average of block-group medians, which skews somewhat from the true median. The agent labels this clearly in its answer.
- **Schema index is warmed on first deploy**, so the first question after a cold Streamlit container takes ~60–90s. Subsequent questions are fast.
- **No actual streaming** — I yield status updates ("Searching schema…", "Running SQL…") rather than streaming token-by-token. Would have added streaming with more time.

## Credits

- Data: [SafeGraph US Open Census Data](https://www.safegraph.com/free-data/open-census-data) via Snowflake Marketplace
- LLM: OpenAI GPT-4o-mini
- Embeddings: `sentence-transformers/all-MiniLM-L6-v2`
- Vector index: FAISS
- UI: Streamlit
