# Module 3: UI Layer

**Responsibility:** A polished, public-internet-accessible chat UI that handles multi-turn conversations, auto-visualizes SQL results as charts/tables/metric cards, always shows the SQL, and deploys to Streamlit Community Cloud without local setup.

## File overview

| File | Responsibility |
|---|---|
| `app.py` | Streamlit entrypoint — chat loop, sidebar, status spinner, error surfaces |
| `styles.py` | Custom CSS (~10KB) — dark gradient background, glassmorphic chat bubbles, Inter/JetBrains Mono fonts, animations, scalar-metric cards, Plotly container styling |
| `components.py` | Reusable UI fragments — welcome card, SQL code block, example-question chips, header, footer |
| `visualizations.py` | Auto-renders SQL results as Plotly bar charts, scalar metric cards, or formatted tables based on result shape |
| `session.py` | Streamlit session-state wiring, `@st.cache_resource` agent, conversation reset |
| `tests/test_session.py` | Unit tests for `DisplayMessage` and session helpers |

## Why Streamlit (and not Gradio / FastAPI+React)

The assignment requires a public web-accessible UI built in 24 hours. Streamlit offered:

- **Near-free deployment** to Streamlit Community Cloud with one-click publish from GitHub
- **Native chat primitives** (`st.chat_message`, `st.chat_input`) that handle message bubbles, scrolling, input focus correctly
- **Session state** built in — no need to hand-roll
- **Secrets management** via the Cloud UI — no secrets in the repo
- **Sidebar** for meta controls (reset conversation, about) without layout hacks

Main tradeoff: custom styling fights the framework's defaults. Heavy CSS in `styles.py` pushes the default look out of the way.

## Auto-visualization

Tabular answers become interactive, not walls of prose. The agent returns raw SQL rows alongside the natural-language answer, and `visualizations.py` picks a rendering based purely on result shape — no extra LLM call.

### Decision tree

```
SQL result shape                     →  Visualization
─────────────────────────────────────────────────────────────
1 row, 1 column                      →  Large scalar metric card
2 columns (label + number), 2-30 rows →  Horizontal bar chart + table
1 column, many rows                  →  Formatted table only
Everything else                      →  Formatted table only
No result                            →  Nothing rendered
```

### Examples from the deployed app

| User question | SQL result | Rendered as |
|---|---|---|
| "What's the population of California?" | `(39,512,223)` | **39.51M** scalar card |
| "Show me the age distribution in Massachusetts" | 10 rows of `(bracket, count)` | Bar chart + table |
| "Compare California vs Texas population" | `[(CA, 39M), (TX, 29M)]` | 2-bar chart + table |
| "What's the median income in Chicago?" | `(~$67,000)` | **$67.00K** scalar card |

### Implementation notes

- **Plotly over Altair/matplotlib** — Plotly handles interactivity (hover, zoom, pan) out of the box and integrates cleanly with Streamlit's dark theme via `plot_bgcolor: rgba(0,0,0,0)`.
- **Horizontal bars over vertical** for breakdowns — labels are typically longer than numbers, so horizontal orientation avoids crowded x-axis labels.
- **Numbers formatted at render time** — the raw SQL returns `39512223`; the scalar card shows `39.51M`. Prevents "unreadable wall of digits" while keeping the full precision in the table below.
- **No map visualizations** — considered a US choropleth for state-by-state results, but it adds a geopandas / state-boundary-data dependency that wasn't worth the 24h cost. Noted for future work.

## Design choices

### Heavy custom styling

The default Streamlit look is a giveaway of "weekend project." Reviewers will instantly recognize it. I invested time in CSS to make the app feel like a product:

- **Dark gradient background** with subtle animated radial accents (pure CSS, no JS)
- **Glassmorphic chat bubbles** (`backdrop-filter: blur(8px)` + translucent backgrounds) with different left-border accents for user vs assistant
- **Gradient title text** using `-webkit-background-clip: text`
- **Buttons styled as pill chips** for the example questions grid
- **SQL code blocks** with a glowing dot label and themed syntax
- **Scalar metric cards** with gradient accent backgrounds for single-value answers
- **Plotly charts** wrapped in styled containers matching the chat bubbles
- **fadeIn / fadeInUp animations** for new content arrivals
- **Custom scrollbars** in dark theme

All styling is in one file (`styles.py`) so future devs have one place to look.

### Always-show SQL

Every assistant answer is followed by the exact SQL that ran, with syntax highlighting. Two reasons:

1. **Trust.** Reviewers are engineers who will WANT to see the SQL to verify the answer isn't hallucinated.
2. **Educational.** Users can learn what the agent did.

### Welcome card with examples

First-time visitors see:
- Dataset stats (220,333 block groups, 16,284 fields, 71 tables, 2019 & 2020)
- Six curated example questions as clickable chips

Clicking an example fires the question through the agent. Addresses three reviewer concerns at once: what does the dataset contain, what kinds of questions work, do I have to think of a good test query.

### Status spinner instead of full streaming

Full token-by-token streaming would require reworking the agent loop. Instead, `st.status()` shows coarse progress ("Thinking...", "Done in N.Ns"). Clear progress signal without the complexity of streaming. Noted in reflection as a "with more time" item.

### Sidebar with reset + about

- **New Conversation button** — resets conversation state without refreshing the page
- **About section** — dataset description, architecture summary
- **Model/data footer** — GPT-4o-mini · Snowflake · guardrail details

## Session state

See `session.py`. Three things live in `st.session_state`:

1. **`conversation`** — the `module_2.Conversation` object. Per user, persists across reruns.
2. **`display_messages`** — a list of `DisplayMessage` objects for rendering, each carrying the answer text, SQL, warnings, elapsed time, and raw result rows/columns.
3. **`pending_prompt`** — set when an example chip is clicked; consumed on the next rerun.

The **Agent** itself is cached with `@st.cache_resource` so it's built exactly once per Streamlit process. Rebuilding the agent means rebuilding the Snowflake connection and reloading the schema index (~30s), and the agent has no per-user state — that all lives in `Conversation`.

## Deployment

See main [`README.md`](../README.md#deployment-streamlit-community-cloud) for full deployment steps. Key points:

1. Push repo to GitHub (can be private).
2. Create app at [share.streamlit.io](https://share.streamlit.io).
3. Point it at `module_3/app.py`.
4. Paste env vars into **Advanced settings → Secrets** (TOML format).
5. Deploy.

### Cold start behavior

First question after a cold Streamlit container: **30-60 seconds**, because:
- Opening the Snowflake connection (~3s)
- Loading 16,284 field descriptions from Snowflake (~2s)
- Embedding all fields via OpenAI API in 64 batches (~15-20s total)
- Writing the FAISS index to disk (~1s)

Subsequent questions take **5–15 seconds** because the index is warm in the `@st.cache_resource` object.

Streamlit Cloud can put containers to sleep after ~1 hour of inactivity. On next access, the cold start happens again. This is inherent to the free tier.

### Path handling

Streamlit Cloud invokes `streamlit run module_3/app.py` from the repo root but does NOT add the repo root to `sys.path`. The first few lines of `app.py` fix this:

```python
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```

Without this, `from module_1 import ...` fails on Streamlit Cloud (works locally because most people run from repo root).

## Testing

```bash
python -m pytest module_3/tests/ -v
```

3 unit tests — admittedly thin. Streamlit apps are hard to unit-test at the UI level because `st.button`, `st.chat_input`, etc. require a running Streamlit context, rerun-driven state updates are hard to simulate, and visual regressions need a browser.

What IS tested: the `DisplayMessage` dataclass — field defaults, SQL handling, warnings, result rows plumbing. Catches regressions in the display contract without needing Streamlit runtime.

**UI QA is currently manual** — run the app locally and click through chat flow. Noted in `REFLECTION.md` as a significant gap.

## What I'd do with more time

- **`AppTest`-based UI tests.** Streamlit ships a test harness that simulates button clicks and asserts on rendered output without a browser.
- **Streaming token output.** Would significantly improve perceived latency.
- **US choropleth map** for state-level results.
- **Mobile layout polish.** Welcome card stats row wraps awkwardly at <400px.
- **Accessibility audit.** Color contrast looks OK but not formally checked.
- **Rate limiting / telemetry.** No protection against a user hammering the app and burning OpenAI credits; no logging of real usage patterns.