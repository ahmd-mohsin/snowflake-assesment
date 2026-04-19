"""The chat agent.

Owns the orchestration loop:
  1. Check input guardrail
  2. Call LLM with tools
  3. If LLM requests tools, run them and loop (up to max_iterations)
  4. When LLM returns a final text answer, check output guardrail
  5. Return the answer

Respects a wall-clock deadline so we never blow through the 60s SLA.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

from module_1 import QueryExecutor, SchemaIndex

from .config import AgentConfig
from .conversation import Conversation, LastQueryInfo
from .guardrails import check_input, check_output_grounded
from .llm_client import LLMClient
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_DEFINITIONS, ToolRunner

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """What the UI gets back."""
    answer: str
    iterations_used: int = 0
    elapsed_seconds: float = 0.0
    blocked_reason: str = ""    # set if guardrails blocked the turn
    last_sql: str = ""          # for display in the UI
    warnings: List[str] = field(default_factory=list)


class DeadlineExceeded(Exception):
    pass


class Agent:
    def __init__(self, config: AgentConfig, schema_index: SchemaIndex,
                 query_executor: QueryExecutor):
        self._config = config
        self._llm = LLMClient(config)
        self._tools = ToolRunner(
            schema_index, query_executor,
            max_rows_in_context=config.max_rows_in_llm_context,
        )

    def new_conversation(self) -> Conversation:
        return Conversation(system_prompt=SYSTEM_PROMPT)

    def ask(self, conversation: Conversation, question: str) -> AgentResponse:
        """Process one user turn. Mutates the conversation in-place."""
        start = time.time()

        # 1. Input guardrail
        gr = check_input(question, conversation_has_context=conversation.has_prior_turns())
        if not gr.allowed:
            logger.info("Input blocked: %s", gr.reason)
            conversation.add_user(question)
            conversation.add_assistant(gr.user_message)
            return AgentResponse(
                answer=gr.user_message,
                blocked_reason=gr.reason,
                elapsed_seconds=time.time() - start,
            )

        conversation.add_user(question)

        # 2-4. Tool loop
        try:
            answer, iterations, last_sql, numbers_seen = self._tool_loop(
                conversation, deadline=start + self._config.total_deadline_seconds,
            )
        except DeadlineExceeded:
            msg = (
                "I couldn't finish this question within the time limit. "
                "Try asking a narrower question (e.g. specify a state or year)."
            )
            conversation.add_assistant(msg)
            return AgentResponse(
                answer=msg,
                blocked_reason="deadline",
                elapsed_seconds=time.time() - start,
            )
        except Exception as e:
            logger.exception("Agent loop crashed")
            msg = (
                "I ran into an unexpected error trying to answer that. "
                "Please try rephrasing or ask a different question."
            )
            conversation.add_assistant(msg)
            return AgentResponse(
                answer=msg,
                blocked_reason=f"exception:{type(e).__name__}",
                elapsed_seconds=time.time() - start,
            )

        warnings: List[str] = []
        # 5. Output guardrail — if numbers don't trace to SQL results, retry once
        out_gr = check_output_grounded(answer, numbers_seen)
        if not out_gr.allowed:
            logger.warning("Output guardrail flagged answer: %s — retrying", out_gr.reason)
            # Give the LLM one chance to fix it with an explicit instruction
            conversation.messages.append({
                "role": "user",
                "content": (
                    "Your previous answer contained numeric figures that do not "
                    "trace to any SQL result in this conversation. Please redo "
                    "the answer using ONLY numbers that appear in the tool "
                    "results above, or if you cannot, say so directly and "
                    "explain what information is missing. Do not invent or "
                    "calculate new numbers."
                ),
            })
            try:
                retry_answer, retry_iters, retry_sql, retry_nums = self._tool_loop(
                    conversation,
                    deadline=start + self._config.total_deadline_seconds,
                )
                numbers_seen.extend(retry_nums)
                # Re-check the retry
                out_gr2 = check_output_grounded(retry_answer, numbers_seen)
                if out_gr2.allowed:
                    answer = retry_answer
                    iterations += retry_iters
                    if retry_sql:
                        last_sql = retry_sql
                else:
                    # Second attempt still flagged — return a refusal
                    answer = (
                        "I wasn't able to produce a statistically sound answer "
                        "for this question from the available data. The census "
                        "dataset provides block-group-level measurements; some "
                        "questions require underlying record-level data that is "
                        "not published here. Could you rephrase or ask something "
                        "more specific?"
                    )
                    warnings.append("Answer suppressed because numbers were not grounded.")
            except DeadlineExceeded:
                answer = (
                    "I needed more time to produce a verified answer than I had. "
                    "Try a narrower question."
                )
                warnings.append("Deadline reached during retry.")

        if last_sql:
            conversation.last_query = LastQueryInfo(
                question=question, sql=last_sql,
                row_count=0,
            )

        return AgentResponse(
            answer=answer,
            iterations_used=iterations,
            elapsed_seconds=time.time() - start,
            last_sql=last_sql,
            warnings=warnings,
        )

    def ask_streaming(self, conversation: Conversation,
                      question: str) -> Iterator[str]:
        """Progress-updates generator for the UI.

        Yields short status strings while the agent works, then finally yields
        a single string beginning with '__FINAL__:' containing the answer.
        This lets Streamlit show 'Thinking...' / 'Searching schema...' / etc.
        """
        start = time.time()
        gr = check_input(question, conversation_has_context=conversation.has_prior_turns())
        if not gr.allowed:
            conversation.add_user(question)
            conversation.add_assistant(gr.user_message)
            yield f"__FINAL__:{gr.user_message}"
            return

        conversation.add_user(question)
        yield "Thinking..."

        iterations = 0
        last_sql = ""
        numbers_seen: List[int] = []
        deadline = start + self._config.total_deadline_seconds

        try:
            while iterations < self._config.max_tool_iterations:
                if time.time() > deadline:
                    raise DeadlineExceeded()
                iterations += 1

                resp = self._llm.chat(
                    messages=conversation.for_llm(),
                    tools=TOOL_DEFINITIONS,
                )
                msg = resp.choices[0].message

                if msg.tool_calls:
                    conversation.add_assistant(
                        msg.content or "",
                        tool_calls=[tc.model_dump() for tc in msg.tool_calls],
                    )
                    for tc in msg.tool_calls:
                        fn = tc.function.name
                        yield f"Using tool: {fn}..."
                        result = self._tools.run(fn, tc.function.arguments)
                        numbers_seen.extend(result.numbers_seen)
                        if fn == "execute_sql":
                            try:
                                import json
                                args = json.loads(tc.function.arguments)
                                last_sql = args.get("sql", "")
                            except Exception:
                                pass
                        conversation.add_tool_result(tc.id, result.content)
                    continue

                # Final answer
                answer = msg.content or "(no answer)"
                conversation.add_assistant(answer)
                out_gr = check_output_grounded(answer, numbers_seen)
                if not out_gr.allowed:
                    answer += (
                        "\n\n⚠️ Note: some numbers above could not be verified "
                        "against the source data."
                    )
                if last_sql:
                    conversation.last_query = LastQueryInfo(
                        question=question, sql=last_sql, row_count=0,
                    )
                yield f"__FINAL__:{answer}"
                return

            # Hit max iterations without a final answer
            fallback = (
                "I wasn't able to get a clean answer after several attempts. "
                "Could you try rephrasing the question?"
            )
            conversation.add_assistant(fallback)
            yield f"__FINAL__:{fallback}"

        except DeadlineExceeded:
            msg = (
                "I couldn't finish this question within the time limit. "
                "Try asking a narrower question (e.g. specify a state or year)."
            )
            conversation.add_assistant(msg)
            yield f"__FINAL__:{msg}"
        except Exception as e:
            logger.exception("Agent streaming loop crashed")
            msg = "I ran into an unexpected error. Please try rephrasing."
            conversation.add_assistant(msg)
            yield f"__FINAL__:{msg}"

    # --- internals -------------------------------------------------------

    def _tool_loop(self, conversation: Conversation,
                   deadline: float) -> tuple[str, int, str, List[int]]:
        """Non-streaming loop. Returns (answer, iterations, last_sql, numbers)."""
        import json as _json

        iterations = 0
        last_sql = ""
        numbers_seen: List[int] = []

        while iterations < self._config.max_tool_iterations:
            if time.time() > deadline:
                raise DeadlineExceeded()
            iterations += 1

            resp = self._llm.chat(
                messages=conversation.for_llm(),
                tools=TOOL_DEFINITIONS,
            )
            msg = resp.choices[0].message

            if msg.tool_calls:
                conversation.add_assistant(
                    msg.content or "",
                    tool_calls=[tc.model_dump() for tc in msg.tool_calls],
                )
                for tc in msg.tool_calls:
                    result = self._tools.run(tc.function.name, tc.function.arguments)
                    numbers_seen.extend(result.numbers_seen)
                    if tc.function.name == "execute_sql":
                        try:
                            args = _json.loads(tc.function.arguments)
                            last_sql = args.get("sql", "")
                        except Exception:
                            pass
                    conversation.add_tool_result(tc.id, result.content)
                continue

            answer = msg.content or "(no answer)"
            conversation.add_assistant(answer)
            return answer, iterations, last_sql, numbers_seen

        fallback = (
            "I wasn't able to get a clean answer after several attempts. "
            "Could you try rephrasing the question?"
        )
        conversation.add_assistant(fallback)
        return fallback, iterations, last_sql, numbers_seen