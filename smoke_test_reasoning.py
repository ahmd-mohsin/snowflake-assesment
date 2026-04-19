"""Targeted smoke test for the reasoning/guardrail fix.

Specifically exercises the questions that previously failed:
  - "median household income" (was returning $16.5 billion)
  - "median home value" (same class of error)

Verifies the sql_semantics guard is firing and the agent recovers.
"""
import logging
import sys
import time

logging.basicConfig(level=logging.INFO)
for noisy in ("httpx", "openai._base_client", "sentence_transformers",
              "snowflake.connector"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from module_1 import QueryExecutor, SchemaExplorer, SchemaIndex, SnowflakeClient
from module_2 import Agent, AgentConfig


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def main() -> int:
    client = SnowflakeClient.get()
    explorer = SchemaExplorer(client)
    index = SchemaIndex()
    index.build(explorer)
    executor = QueryExecutor(client)
    agent = Agent(AgentConfig.from_env(), index, executor)

    # --- Test 1: the original failing case ---
    section("Test 1: 'What is the median household income in the US?'")
    conv = agent.new_conversation()
    t0 = time.time()
    resp = agent.ask(conv, "What is the median household income in the US for 2020?")
    elapsed = time.time() - t0
    print(f"  Elapsed: {elapsed:.1f}s  |  Iterations: {resp.iterations_used}")
    print(f"  Answer:  {resp.answer}")
    print(f"  SQL:     {resp.last_sql[:300]}")
    print(f"  Warnings: {resp.warnings}")

    # Sanity: answer should not contain "billion" for a household median
    assert "billion" not in resp.answer.lower(), \
        "!!! Answer still contains 'billion' — fix did not work"
    # Should either have a plausible $XX,XXX number OR be a refusal
    plausible = any(s in resp.answer.lower() for s in
                    ["$", "approximately", "weighted", "cannot", "approximat"])
    assert plausible, f"!!! Answer doesn't look right: {resp.answer}"

    # --- Test 2: median home value (same class of error) ---
    section("Test 2: 'What is the median home value in California?'")
    conv2 = agent.new_conversation()
    t0 = time.time()
    resp = agent.ask(conv2, "What is the median home value in California in 2020?")
    elapsed = time.time() - t0
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Answer:  {resp.answer}")
    print(f"  SQL:     {resp.last_sql[:300]}")
    assert "billion" not in resp.answer.lower()

    # --- Test 3: sanity — counts still work ---
    section("Test 3: 'Total population of California?' (sanity check)")
    conv3 = agent.new_conversation()
    t0 = time.time()
    resp = agent.ask(conv3, "What is the total population of California in 2020?")
    elapsed = time.time() - t0
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Answer:  {resp.answer}")
    # California pop should be ~39M
    assert "million" in resp.answer.lower() or "39" in resp.answer

    section("ALL CHECKS PASSED")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())