"""Tests for DisplayMessage and session helpers that don't need a running
Streamlit server.

Full UI-level testing would require AppTest (Streamlit's testing framework) or
Playwright — good candidates for a future test suite, noted in the reflection.
"""
from module_3.session import DisplayMessage


def test_display_message_defaults():
    msg = DisplayMessage(role="user", content="hi")
    assert msg.role == "user"
    assert msg.content == "hi"
    assert msg.sql == ""
    assert msg.warnings == []
    assert msg.elapsed == 0.0


def test_display_message_with_sql():
    msg = DisplayMessage(
        role="assistant",
        content="The population is 39M",
        sql='SELECT SUM("B01001e1") FROM "2019_CBG_B01"',
        warnings=[],
        elapsed=3.5,
    )
    assert "SUM" in msg.sql
    assert msg.elapsed == 3.5


def test_display_message_with_warning():
    msg = DisplayMessage(
        role="assistant",
        content="Answer",
        warnings=["Some numbers could not be verified"],
    )
    assert len(msg.warnings) == 1
