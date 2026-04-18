"""Tests for Conversation state management."""
from module_2.conversation import Conversation


def test_new_conversation_has_no_prior_turns():
    c = Conversation(system_prompt="sys")
    assert not c.has_prior_turns()


def test_user_message_alone_is_not_prior_turn():
    c = Conversation(system_prompt="sys")
    c.add_user("hi")
    assert not c.has_prior_turns()  # no assistant response yet


def test_assistant_message_marks_prior_turn():
    c = Conversation(system_prompt="sys")
    c.add_user("hi")
    c.add_assistant("hello")
    assert c.has_prior_turns()


def test_for_llm_prepends_system():
    c = Conversation(system_prompt="you are helpful")
    c.add_user("hi")
    msgs = c.for_llm()
    assert msgs[0] == {"role": "system", "content": "you are helpful"}
    assert msgs[1]["role"] == "user"


def test_trims_to_max_turns():
    c = Conversation(system_prompt="sys", max_turns=3)
    for i in range(10):
        c.add_user(f"q{i}")
        c.add_assistant(f"a{i}")
    # Should keep only the last 3 user turns + their responses
    user_msgs = [m for m in c.messages if m["role"] == "user"]
    assert len(user_msgs) == 3
    assert user_msgs[0]["content"] == "q7"
    assert user_msgs[-1]["content"] == "q9"


def test_tool_results_kept_paired_with_calls():
    c = Conversation(system_prompt="sys")
    c.add_user("q")
    c.add_assistant("", tool_calls=[{"id": "t1", "type": "function",
                                     "function": {"name": "f", "arguments": "{}"}}])
    c.add_tool_result("t1", '{"result": "ok"}')
    c.add_assistant("done")
    # No trimming since well under limit
    assert len(c.messages) == 4
    assert c.messages[1]["tool_calls"][0]["id"] == "t1"
    assert c.messages[2]["tool_call_id"] == "t1"
