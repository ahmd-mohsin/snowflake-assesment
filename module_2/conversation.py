"""Conversation state: OpenAI message history + a lightweight structured memory.

The message history is what we send to OpenAI on every turn. We cap it to
avoid runaway context growth on long conversations. The structured context
holds the last SQL we ran and its topic — useful for UI display and for
debugging, but the LLM primarily relies on the message history for continuity.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LastQueryInfo:
    """Lightweight record of the most recent successful query."""
    question: str
    sql: str
    row_count: int


@dataclass
class Conversation:
    """Holds OpenAI-format messages plus a bit of structured state."""
    system_prompt: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    last_query: Optional[LastQueryInfo] = None
    # Keep the last N user+assistant turn pairs; tool messages within them
    # stay attached
    max_turns: int = 12

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        self._trim()

    def add_assistant(self, text: str, tool_calls: Optional[List[Dict]] = None) -> None:
        msg: Dict[str, Any] = {"role": "assistant", "content": text}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    def for_llm(self) -> List[Dict[str, Any]]:
        """Return the full message list with system prompt prepended."""
        return [{"role": "system", "content": self.system_prompt}] + self.messages

    def has_prior_turns(self) -> bool:
        """True if the user has sent anything before this turn's new input."""
        return any(m["role"] == "assistant" for m in self.messages)

    def _trim(self) -> None:
        """Keep only the most recent max_turns user messages and everything after.

        This preserves the invariant that tool calls stay paired with their
        tool results (we never cut in the middle of a tool sequence).
        """
        user_indices = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if len(user_indices) <= self.max_turns:
            return
        cutoff = user_indices[-self.max_turns]
        self.messages = self.messages[cutoff:]
