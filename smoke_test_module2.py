"""End-to-end smoke test for module_2.

Requires OPENAI_API_KEY in your .env alongside the Snowflake credentials.

Validates:
  1. Agent handles a direct data question end-to-end
  2. Multi-turn context is preserved (follow-up questions work)
  3. Input guardrail blocks off-topic questions without calling the LLM
  4. Ambiguous/unanswerable questions are handled gracefully

Run: python smoke_test_module2.py
"""
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Quiet down noisy libraries
for noisy in ("httpx", "openai._base_client", "sentence_transformers"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from module_1 import QueryExecutor, SchemaExplorer, SchemaIndex, SnowflakeClient
from module_2 import Agent, AgentConfig


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def main() -> int:
    # ---- Setup ----
    section("Setup: Snowflake + schema index + agent")
    client = SnowflakeClient.get()
    explorer = SchemaExplorer(client)
    index = SchemaIndex()
    index.build(explorer)  # Should use cache from module_1 smoke test
    executor = QueryExecutor(client)
    agent = Agent(AgentConfig.from_env(), index, executor)
    print("  Ready.")

    # ---- Test 1: Direct data question ----
    section("Test 1: Direct data question")
    conv = agent.new_conversation()
    t0 = time.time()
    resp = agent.ask(conv, "What is the total population of California in 2019?")
    elapsed = time.time() - t0
    print(f"  Elapsed: {elapsed:.1f}s  |  Iterations: {resp.iterations_used}")
    print(f"  Answer:  {resp.answer}")
    if resp.last_sql:
        print(f"  SQL:     {resp.last_sql[:200]}...")
    assert elapsed < 60, "!!! Exceeded 60s SLA"
    assert resp.blocked_reason == "", f"!!! Unexpectedly blocked: {resp.blocked_reason}"

    # ---- Test 2: Multi-turn follow-up ----
    section("Test 2: Multi-turn follow-up ('what about Texas?')")
    t0 = time.time()
    resp = agent.ask(conv, "what about Texas?")
    elapsed = time.time() - t0
    print(f"  Elapsed: {elapsed:.1f}s  |  Iterations: {resp.iterations_used}")
    print(f"  Answer:  {resp.answer}")
    assert elapsed < 60

    # ---- Test 3: Input guardrail fast-fail ----
    section("Test 3: Off-topic question is blocked BEFORE hitting the LLM")
    conv2 = agent.new_conversation()
    t0 = time.time()
    resp = agent.ask(conv2, "write me a poem about dragons")
    elapsed = time.time() - t0
    print(f"  Elapsed: {elapsed:.3f}s (should be < 0.1s)")
    print(f"  Reason:  {resp.blocked_reason}")
    print(f"  Answer:  {resp.answer}")
    assert resp.blocked_reason == "off_topic_pattern"
    assert elapsed < 1.0, "!!! Guardrail should be near-instant"

    # ---- Test 4: Unanswerable question handled gracefully ----
    section("Test 4: Unanswerable question (year not in dataset)")
    conv3 = agent.new_conversation()
    t0 = time.time()
    resp = agent.ask(conv3, "What was the population of Miami in 2024?")
    elapsed = time.time() - t0
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Answer:  {resp.answer}")
    # Should not crash, should acknowledge the limitation
    assert resp.answer, "!!! Empty answer"
    assert elapsed < 60

    # ---- Test 5: Ambiguous question gets a defaulted answer ----
    section("Test 5: Ambiguous question ('what's the median income?')")
    conv4 = agent.new_conversation()
    t0 = time.time()
    resp = agent.ask(conv4, "what's the median income?")
    elapsed = time.time() - t0
    print(f"  Elapsed: {elapsed:.1f}s  |  Iterations: {resp.iterations_used}")
    print(f"  Answer:  {resp.answer}")
    assert elapsed < 60

    section("ALL CHECKS PASSED")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())