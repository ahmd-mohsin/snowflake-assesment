"""Configuration for the agent layer."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AgentConfig:
    openai_api_key: str
    model: str = "gpt-4o-mini"
    # Tight budgets so we stay well under the 60s SLA even with retries
    llm_timeout_seconds: int = 20
    total_deadline_seconds: int = 50
    max_tool_iterations: int = 5
    # Temperature 0 for reproducibility on data questions
    temperature: float = 0.0
    # Max rows to show the LLM inline (we pass a sample, full result goes to UI)
    max_rows_in_llm_context: int = 30

    @classmethod
    def from_env(cls) -> "AgentConfig":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise EnvironmentError("OPENAI_API_KEY is required")
        return cls(
            openai_api_key=key,
            model=os.getenv("OPENAI_MODEL", cls.model),
        )
