"""Streamlit session state helpers.

The Agent, SnowflakeClient, and SchemaIndex are expensive to build — we cache
them at module-level with @st.cache_resource so they survive across reruns and
are shared between users (safe because they are effectively read-only).

The Conversation object is per-user and lives in st.session_state.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

import streamlit as st

from module_1 import QueryExecutor, SchemaExplorer, SchemaIndex, SnowflakeClient
from module_2 import Agent, AgentConfig, Conversation


@dataclass
class DisplayMessage:
    """One message as shown in the UI (distinct from the LLM-format message)."""
    role: str                  # 'user' or 'assistant'
    content: str
    sql: str = ""
    warnings: List[str] = field(default_factory=list)
    elapsed: float = 0.0
    result_rows: List[dict] = field(default_factory=list)
    result_columns: List[str] = field(default_factory=list)


@st.cache_resource(show_spinner="Connecting to Snowflake and loading schema...")
def get_agent() -> Agent:
    """Build (or reuse) the Agent. Cached across reruns and sessions."""
    client = SnowflakeClient.get()
    explorer = SchemaExplorer(client)
    index = SchemaIndex()
    index.build(explorer)  # uses on-disk cache after first run
    executor = QueryExecutor(client)
    return Agent(AgentConfig.from_env(), index, executor)


def init_session_state() -> None:
    """Initialize per-user state on first run."""
    if "conversation" not in st.session_state:
        agent = get_agent()
        st.session_state.conversation = agent.new_conversation()
    if "display_messages" not in st.session_state:
        st.session_state.display_messages: List[DisplayMessage] = []
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt: str = ""


def add_display_message(msg: DisplayMessage) -> None:
    st.session_state.display_messages.append(msg)


def reset_conversation() -> None:
    """Start fresh without restarting the app."""
    agent = get_agent()
    st.session_state.conversation = agent.new_conversation()
    st.session_state.display_messages = []
    st.session_state.pending_prompt = ""


def has_messages() -> bool:
    return len(st.session_state.get("display_messages", [])) > 0