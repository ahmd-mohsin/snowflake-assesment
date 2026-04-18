"""Configuration loaded from environment variables."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    password: str
    warehouse: str
    role: str
    # Census dataset on the Snowflake Marketplace
    database: str = "US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET"
    schema: str = "CENSUS"
    query_timeout_seconds: int = 45  # leaves headroom below the 60s SLA
    max_rows_returned: int = 1000

    @classmethod
    def from_env(cls) -> "SnowflakeConfig":
        required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
                    "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_ROLE"]
        missing = [k for k in required if not os.getenv(k)]
        if missing:
            raise EnvironmentError(f"Missing required env vars: {missing}")

        return cls(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
            role=os.environ["SNOWFLAKE_ROLE"],
            database=os.getenv("SNOWFLAKE_DATABASE", cls.database),
            schema=os.getenv("SNOWFLAKE_SCHEMA", cls.schema),
        )


# Path where the schema index is cached to avoid re-embedding on every startup
SCHEMA_INDEX_PATH = os.getenv("SCHEMA_INDEX_PATH", "./.cache/schema_index")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
