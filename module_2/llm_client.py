"""Thin OpenAI wrapper with timeout and a single retry on transient errors."""
import logging
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI, APITimeoutError, APIConnectionError, RateLimitError

from .config import AgentConfig

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, config: AgentConfig):
        self._config = config
        self._client = OpenAI(
            api_key=config.openai_api_key,
            timeout=config.llm_timeout_seconds,
        )

    def chat(self, messages: List[Dict[str, Any]],
             tools: Optional[List[Dict[str, Any]]] = None,
             tool_choice: str = "auto") -> Any:
        """Send a chat completion. Retries once on transient network errors."""
        kwargs: Dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        last_err: Optional[Exception] = None
        for attempt in (1, 2):
            try:
                t0 = time.time()
                resp = self._client.chat.completions.create(**kwargs)
                logger.info("LLM call %d finished in %.2fs (tokens: in=%s out=%s)",
                            attempt,
                            time.time() - t0,
                            getattr(resp.usage, "prompt_tokens", "?"),
                            getattr(resp.usage, "completion_tokens", "?"))
                return resp
            except (APITimeoutError, APIConnectionError, RateLimitError) as e:
                logger.warning("LLM transient error on attempt %d: %s", attempt, e)
                last_err = e
                if attempt == 1:
                    time.sleep(1.0)
                    continue
                raise
        raise RuntimeError(f"LLM failed after retries: {last_err}")
