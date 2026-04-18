"""Census Chat — Streamlit app.

Run locally:
    streamlit run module_3/app.py

Deployment: Streamlit Community Cloud. See README for setup.
"""
import logging
import sys
import time
from pathlib import Path

# Make sibling modules (module_1, module_2, module_3) importable regardless of
# how Streamlit invokes this file. Streamlit Cloud runs from the repo root but
# does not automatically add it to sys.path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

# Set page config BEFORE anything else imports streamlit widgets
st.set_page_config(
    page_title="Census Chat",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed",
)

from module_3.components import (
    render_header,
    render_welcome_card,
    render_sql_block,
    render_warnings,
    render_footer,
)
from module_3.session import (
    DisplayMessage,
    add_display_message,
    get_agent,
    has_messages,
    init_session_state,
    reset_conversation,
)
from module_3.styles import CUSTOM_CSS

logging.basicConfig(level=logging.INFO)
# Quiet noisy libraries so Streamlit's log stream is readable
for noisy in ("httpx", "openai._base_client", "sentence_transformers",
              "snowflake.connector"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def run_turn(prompt: str):
    """Process a new user turn end-to-end and append results to the display log."""
    agent = get_agent()
    conversation = st.session_state.conversation

    # Record user message immediately so it appears while we're thinking
    add_display_message(DisplayMessage(role="user", content=prompt))

    # Render the user message NOW so the UI updates before we kick off the LLM
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    # Assistant response with a status spinner for progress transparency
    with st.chat_message("assistant", avatar="🤖"):
        status = st.status("Thinking...", expanded=False)
        t0 = time.time()
        try:
            resp = agent.ask(conversation, prompt)
            status.update(label=f"Done in {resp.elapsed_seconds:.1f}s",
                          state="complete", expanded=False)
        except Exception as e:
            status.update(label=f"Error: {e}", state="error")
            msg = (
                "I ran into an unexpected error. Please try rephrasing your "
                "question or refresh the page."
            )
            st.markdown(msg)
            add_display_message(DisplayMessage(role="assistant", content=msg))
            return

        # Render the answer, any warnings, and the SQL that ran
        st.markdown(resp.answer)
        if resp.warnings:
            render_warnings(resp.warnings)
        if resp.last_sql:
            render_sql_block(resp.last_sql)

    add_display_message(DisplayMessage(
        role="assistant",
        content=resp.answer,
        sql=resp.last_sql,
        warnings=resp.warnings,
        elapsed=resp.elapsed_seconds,
    ))


def render_history():
    """Re-render previous messages after a rerun."""
    for msg in st.session_state.display_messages:
        avatar = "👤" if msg.role == "user" else "🤖"
        with st.chat_message(msg.role, avatar=avatar):
            st.markdown(msg.content)
            if msg.warnings:
                render_warnings(msg.warnings)
            if msg.sql:
                render_sql_block(msg.sql)


def main():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    render_header()

    # Sidebar: reset button + about
    with st.sidebar:
        st.markdown("### Session")
        if st.button("🔄 New Conversation", use_container_width=True):
            reset_conversation()
            st.rerun()

        st.markdown("---")
        st.markdown("### About")
        st.markdown(
            "This chatbot answers questions about US demographics using the "
            "**US Open Census** dataset from the Snowflake Marketplace.\n\n"
            "Data spans ~220,000 census block groups across the US for 2019 "
            "and 2020. Answers are grounded in real SQL queries — you can "
            "see the exact query behind every response."
        )
        st.markdown("---")
        st.markdown(
            "<p style='font-size:0.75rem;color:#64748b;'>"
            "Model: GPT-4o-mini · Data: Snowflake · "
            "Agent: function-calling loop with input & output guardrails"
            "</p>",
            unsafe_allow_html=True,
        )

    # Initialize state (cached agent loads here on first run)
    try:
        init_session_state()
    except Exception as e:
        st.error(
            f"**Couldn't start the agent.** Please check that all environment "
            f"variables are set.\n\n`{e}`"
        )
        st.stop()

    # Welcome card appears only on a fresh conversation
    def set_prompt(p: str):
        st.session_state.pending_prompt = p

    if not has_messages():
        render_welcome_card(on_example_click=set_prompt)
    else:
        render_history()

    # Chat input — a fresh input on every rerun
    user_input = st.chat_input("Ask about US demographics...")

    # An example button click stashes its prompt; pick it up on the next rerun
    prompt = user_input or st.session_state.pending_prompt
    st.session_state.pending_prompt = ""

    if prompt:
        # If this is the first message, clear the welcome card by rerunning after
        # processing (history renderer takes over)
        run_turn(prompt)
        st.rerun()

    render_footer()


if __name__ == "__main__":
    main()
