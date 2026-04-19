# Module 3: UI Layer

**Responsibility:** A polished, public-internet-accessible chat UI that handles multi-turn conversations, shows the SQL behind every answer, and deploys to Streamlit Community Cloud without local setup.

## File overview

| File | Responsibility |
|---|---|
| `app.py` | Streamlit entrypoint — chat loop, sidebar, status spinner, error surfaces |
| `styles.py` | Custom CSS (~9KB) — dark gradient background, glassmorphic chat bubbles, Inter/JetBrains Mono fonts, hover states, fadeIn animations |
| `components.py` | Reusable UI fragments — welcome card, SQL code block, example-question chips, header, footer |
| `session.py` | Streamlit session-state wiring, `@st.cache_resource` agent, conversation reset |
| `tests/test_session.py` | Unit tests for the parts that don't require a running Streamlit server |

## Why Streamlit (and not Gradio / FastAPI+React / etc.)

The assignment requires a public web-accessible UI built in 24 hours. Streamlit offered:

- **Near-free deployment** to Streamlit Community Cloud with one-click publish from GitHub
- **Native chat primitives** (`st.chat_message`, `st.chat_input`) that handle message bubbles, scrolling, input focus correctly
- **Session state** built in — no need to hand-roll
- **Secrets management** via the Cloud UI — no secrets in the repo
- **Sidebar** for meta controls (reset conversation, about) without layout hacks

The main Streamlit tradeoff is that custom styling fights the framework's defaults. I put heavy CSS in `styles.py` to push the default look out of the way.

## Design choices

### Heavy custom styling

The default Streamlit look is a giveaway of "weekend project." Reviewers will instantly recognize it. I invested time in CSS to make the app feel like a product:

- **Dark gradient background** with subtle animated radial accents (pure CSS, no JS)
- **Glassmorphic chat bubbles** (`backdrop-filter: blur(8px)` + translucent backgrounds) with different left-border accents for user vs assistant
- **Inter** font for body, **JetBrains Mono** for SQL — both from Google Fonts
- **Gradient title** using `-webkit-background-clip: text`
- **Buttons styled as pill chips** for the example questions grid
- **SQL code blocks** with a glowing dot label and themed syntax
- **fadeIn/fadeInUp animations** for new content arrivals
- **Custom scrollbars** in dark theme

All styling is in one file (`styles.py`) so future devs have one place to look.

### Always-show SQL

Every assistant answer is followed by the exact SQL that ran. Two reasons:

1. **Trust.** Reviewers are engineers who will WANT to see the SQL to verify the answer isn't hallucinated.
2. **Educational.** Users can learn what the agent did and verify the logic themselves.

The SQL block has a subtle "SQL executed" label with a glowing dot accent — visually distinct but not intrusive.

### Welcome card with examples

The first screen a user sees is a welcome card showing:
- Dataset stats (220,333 block groups, 16,284 fields, 71 tables, 2019 & 2020)
- Six curated example questions as clickable chips

Clicking an example immediately fires the question through the agent. This addresses three reviewer concerns at once:
- What does the dataset actually contain?
- What kinds of questions does this thing answer well?
- Do I have to think of a good question to try it?

### Status spinner instead of full streaming

Full token-by-token streaming from OpenAI is possible but would require reworking the agent loop (which batches tool results between LLM calls, not great for a token stream). Instead, a `st.status()` context manager shows coarse progress:

- "Thinking..." while the LLM plans
- Updated to "Done in N.Ns" after the answer lands

This gives users a clear progress signal without the complexity of full streaming. A future version would stream the final natural-language answer while keeping tool calls non-streaming.

### Sidebar with reset + about

Left sidebar contains:
- **New Conversation button** — resets conversation state without refreshing the page
- **About section** — short description of the dataset and the architecture
- **Model/data footer** — GPT-4o-mini · Snowflake · agent details

## Session state

See `session.py`. Three things live in `st.session_state`:

1. **`conversation`** — the `module_2.Conversation` object. Per user, persists across reruns.
2. **`display_messages`** — a list of `DisplayMessage` objects for rendering. Different from the LLM-format messages because each display message can have a SQL block and warnings attached.
3. **`pending_prompt`** — set when an example chip is clicked; consumed on the next rerun.

The **Agent** itself is cached with `@st.cache_resource` so it's built exactly once per Streamlit process (not per user session). This is the right choice because:
- Rebuilding the agent means rebuilding the Snowflake connection AND reloading the embedding model (~5 seconds)
- The agent has no per-user state — that all lives in `Conversation`
- `@st.cache_resource` is exactly what Streamlit recommends for expensive-to-build shared resources

## Deployment

See main [`README.md`](../README.md#deployment-streamlit-community-cloud) for full deployment steps. The key things:

1. Push repo to GitHub (can be private — Streamlit Cloud supports private repos).
2. Create app at [share.streamlit.io](https://share.streamlit.io).
3. Point it at `module_3/app.py`.
4. Paste env vars into **Advanced settings → Secrets** (TOML format).
5. Deploy.

### Cold start behavior

The first question after a cold Streamlit container takes **60–90 seconds** because:
- Opening the Snowflake connection (~3s)
- Loading 16,284 field descriptions from Snowflake (~2s)
- Downloading the sentence-transformers model (~5s, first time only)
- Embedding 16,284 documents (~30s on the cloud's CPU)
- Writing the FAISS index to disk (~1s)

Subsequent questions take **5–15 seconds** because the index is warm in the `@st.cache_resource` object.

Streamlit Cloud can put containers to sleep after ~1 hour of inactivity. On next access, the cold start happens again. This is inherent to the free tier.

**What could fix this:** pre-building the index into the repo as a binary artifact. Not done here because (a) the dataset could update and (b) committing a ~30MB binary to the repo is ugly. Could be added with Git LFS.

### Path handling

Streamlit Cloud invokes `streamlit run module_3/app.py` from the repo root but does NOT add the repo root to `sys.path`. The first few lines of `app.py` fix this:

```python
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```

Without this, `from module_1 import ...` fails on Streamlit Cloud. Works fine locally because most people run from the repo root.

## Testing

```bash
python -m pytest module_3/tests/ -v
```

3 unit tests — admittedly thin. Streamlit apps are hard to unit-test at the UI level because:

- `st.button`, `st.chat_input`, etc. require a running Streamlit context
- Rerun-driven state updates are hard to simulate
- Visual regressions need an actual browser

The right tool for thorough UI testing is **Streamlit's `AppTest` framework** or **Playwright** for end-to-end browser tests. I noted this in `REFLECTION.md` as a significant gap — the Streamlit UI is the component with the least unit-test coverage.

What IS tested in Module 3: the `DisplayMessage` dataclass — field defaults, SQL field handling, warnings handling. This catches regressions in the display contract without needing a Streamlit runtime.

End-to-end UI validation is currently manual — I run the app locally and click through the chat flow. Obvious gap.

## What I'd do with more time

- **`AppTest`-based UI tests.** Streamlit ships with a test harness that lets you simulate button clicks and assert on rendered output without a browser.
- **Streaming token output.** The agent loop would need re-architecting to support it, but would significantly improve perceived latency.
- **Mobile layout polish.** The current CSS works on mobile but the welcome card's stats row wraps awkwardly at <400px.
- **Accessibility audit.** Color contrast looks OK but I haven't run it through a proper checker. Keyboard navigation works via Streamlit's defaults.
- **Rate limiting / user session tracking.** No protection against a single user hammering the app and burning OpenAI credits. Would add a simple per-session rate limit.
- **Telemetry.** No logging of questions/latencies to disk right now. Would add basic metrics to understand real usage.