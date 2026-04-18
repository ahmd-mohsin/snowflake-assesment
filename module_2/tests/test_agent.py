"""Tests for the Agent loop using a fake LLM and fake tools.

These cover the orchestration logic without hitting OpenAI or Snowflake.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from module_2.agent import Agent, DeadlineExceeded
from module_2.config import AgentConfig


def fake_llm_response(content: str = None, tool_calls: list = None):
    """Construct a response object shaped like OpenAI's SDK returns."""
    tc_list = None
    if tool_calls:
        tc_list = []
        for tc in tool_calls:
            tc_obj = SimpleNamespace(
                id=tc["id"],
                function=SimpleNamespace(
                    name=tc["name"],
                    arguments=json.dumps(tc.get("args", {})),
                ),
            )
            tc_obj.model_dump = lambda self=tc_obj: {
                "id": self.id, "type": "function",
                "function": {"name": self.function.name,
                             "arguments": self.function.arguments},
            }
            tc_list.append(tc_obj)

    msg = SimpleNamespace(content=content, tool_calls=tc_list)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


@pytest.fixture
def agent():
    config = AgentConfig(openai_api_key="fake")
    schema_index = MagicMock()
    executor = MagicMock()
    agent = Agent(config, schema_index, executor)
    return agent


class TestInputGuardrailIntegration:
    def test_blocks_off_topic_before_calling_llm(self, agent):
        agent._llm.chat = MagicMock(side_effect=AssertionError("LLM should not be called"))
        conv = agent.new_conversation()
        resp = agent.ask(conv, "write me a poem")
        assert resp.blocked_reason == "off_topic_pattern"
        assert "census" in resp.answer.lower() or "demographics" in resp.answer.lower()


class TestAgentLoop:
    def test_single_turn_with_no_tools(self, agent):
        agent._llm.chat = MagicMock(return_value=fake_llm_response(
            content="The population is based on census data.",
        ))
        conv = agent.new_conversation()
        resp = agent.ask(conv, "what is the population of california?")
        assert "population" in resp.answer.lower()
        assert resp.iterations_used == 1

    def test_tool_call_then_final_answer(self, agent):
        # First LLM turn: call execute_sql
        # Second LLM turn: produce final answer
        fake_sql_result = {
            "columns": ["TOTAL"], "row_count": 1,
            "rows": [{"TOTAL": 39512223}],
        }
        agent._tools.run = MagicMock(return_value=SimpleNamespace(
            content=json.dumps(fake_sql_result),
            numbers_seen=[39512223],
        ))
        agent._llm.chat = MagicMock(side_effect=[
            fake_llm_response(tool_calls=[{
                "id": "call_1", "name": "execute_sql",
                "args": {"sql": 'SELECT SUM("B01001e1") AS TOTAL FROM "2019_CBG_B01"'},
            }]),
            fake_llm_response(content="California has a population of 39,512,223."),
        ])

        conv = agent.new_conversation()
        resp = agent.ask(conv, "population of california")

        assert "39,512,223" in resp.answer
        assert resp.iterations_used == 2
        assert "SELECT" in resp.last_sql

    def test_max_iterations_fallback(self, agent):
        # LLM keeps requesting tools forever
        agent._tools.run = MagicMock(return_value=SimpleNamespace(
            content='{"error": "oops"}', numbers_seen=[],
        ))
        agent._llm.chat = MagicMock(return_value=fake_llm_response(
            tool_calls=[{"id": "c", "name": "execute_sql", "args": {"sql": "SELECT 1"}}],
        ))

        conv = agent.new_conversation()
        resp = agent.ask(conv, "what is the population")
        assert resp.iterations_used == agent._config.max_tool_iterations
        assert "rephrasing" in resp.answer.lower()

    def test_deadline_exceeded_returns_graceful_message(self, agent):
        agent._llm.chat = MagicMock(side_effect=lambda **kw: fake_llm_response(
            tool_calls=[{"id": "c", "name": "execute_sql", "args": {"sql": "X"}}],
        ))
        agent._tools.run = MagicMock(return_value=SimpleNamespace(
            content='{}', numbers_seen=[],
        ))
        # Patch time.time so we hit deadline immediately on iteration 2
        call_count = [0]

        def fake_time():
            call_count[0] += 1
            return 0 if call_count[0] < 3 else 10_000

        with patch("module_2.agent.time.time", fake_time):
            conv = agent.new_conversation()
            # Set very tight deadline
            agent._config = AgentConfig(openai_api_key="fake", total_deadline_seconds=1)
            resp = agent.ask(conv, "population of california")

        assert resp.blocked_reason == "deadline"

    def test_llm_crash_returns_graceful_message(self, agent):
        agent._llm.chat = MagicMock(side_effect=RuntimeError("boom"))
        conv = agent.new_conversation()
        resp = agent.ask(conv, "population of california")
        assert "unexpected error" in resp.answer.lower()
        assert resp.blocked_reason.startswith("exception")


class TestConversationState:
    def test_conversation_preserved_across_turns(self, agent):
        agent._llm.chat = MagicMock(return_value=fake_llm_response(
            content="Got it.",
        ))
        conv = agent.new_conversation()
        agent.ask(conv, "population of california")
        agent.ask(conv, "what about texas")

        user_msgs = [m for m in conv.messages if m["role"] == "user"]
        assert len(user_msgs) == 2
        assert "california" in user_msgs[0]["content"]
        assert "texas" in user_msgs[1]["content"]
