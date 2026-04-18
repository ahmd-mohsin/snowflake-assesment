"""Reusable UI components."""
import streamlit as st


# Carefully chosen examples that actually work well with the agent
EXAMPLE_QUESTIONS = [
    "What's the total population of California in 2020?",
    "How many people in Texas have no health insurance?",
    "Compare median household income in New York vs Florida",
    "What percentage of adults in Illinois have a bachelor's degree?",
    "How many renters are in Washington state?",
    "Show me the age distribution in Massachusetts",
]


def render_header():
    st.markdown(
        """
        <div class="app-header">
            <h1 class="app-title">Census Chat</h1>
            <span class="app-badge">GPT-4o-mini · Snowflake</span>
        </div>
        <p class="app-subtitle">
            Ask natural-language questions about US demographics. Grounded in the
            Snowflake Marketplace US Open Census dataset — 220,000+ block groups,
            16,000+ fields, 2019 & 2020 vintages.
        </p>
        """,
        unsafe_allow_html=True,
    )


def render_welcome_card(on_example_click):
    """The onboarding card. `on_example_click` is a callback taking the prompt."""
    st.markdown(
        """
        <div class="welcome-card">
            <h3>👋 Welcome to Census Chat</h3>
            <p>
                I can answer questions about US population, income, housing, education,
                race/ethnicity, health insurance, and more — at state, county, or census
                block group level.
            </p>
            <div class="dataset-stats">
                <div class="stat">
                    <span class="stat-value">220,333</span>
                    <span class="stat-label">Block Groups</span>
                </div>
                <div class="stat">
                    <span class="stat-value">16,284</span>
                    <span class="stat-label">Fields Indexed</span>
                </div>
                <div class="stat">
                    <span class="stat-value">71</span>
                    <span class="stat-label">Data Tables</span>
                </div>
                <div class="stat">
                    <span class="stat-value">2019, 2020</span>
                    <span class="stat-label">Vintages</span>
                </div>
            </div>
            <div class="examples-heading">Try one of these:</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Render example buttons in a 2-col grid
    cols = st.columns(2)
    for i, example in enumerate(EXAMPLE_QUESTIONS):
        with cols[i % 2]:
            # Unique key per example so Streamlit tracks click state correctly
            if st.button(example, key=f"example_{i}", use_container_width=True):
                on_example_click(example)


def render_sql_block(sql: str):
    """Render the SQL that was executed, styled as a code block with a label."""
    if not sql:
        return
    # Use markdown code fencing for syntax highlighting, with our custom label above
    st.markdown(
        '<div class="sql-label">SQL executed</div>',
        unsafe_allow_html=True,
    )
    st.code(sql.strip(), language="sql")


def render_warnings(warnings: list):
    for w in warnings:
        st.markdown(
            f'<div class="warning-banner">⚠️ {w}</div>',
            unsafe_allow_html=True,
        )


def render_footer():
    st.markdown(
        """
        <div class="app-footer">
            Built for Snowflake Applied AI · Data:
            <a href="https://app.snowflake.com/marketplace" target="_blank">US Open Census (SafeGraph)</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
