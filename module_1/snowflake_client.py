"""Thin wrapper around snowflake-connector-python with connection reuse."""
import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import snowflake.connector
from snowflake.connector import DictCursor
from snowflake.connector.errors import (
    DatabaseError,
    OperationalError,
    ProgrammingError,
)

from .config import SnowflakeConfig

logger = logging.getLogger(__name__)


class SnowflakeClient:
    """Singleton-ish client that lazily opens a connection and reuses it."""

    _instance: "SnowflakeClient | None" = None
    _lock = threading.Lock()

    def __init__(self, config: SnowflakeConfig):
        self._config = config
        self._conn: snowflake.connector.SnowflakeConnection | None = None
        self._conn_lock = threading.Lock()

    @classmethod
    def get(cls, config: SnowflakeConfig | None = None) -> "SnowflakeClient":
        with cls._lock:
            if cls._instance is None:
                if config is None:
                    config = SnowflakeConfig.from_env()
                cls._instance = cls(config)
            return cls._instance

    def _connect(self) -> snowflake.connector.SnowflakeConnection:
        """Open a new connection with session-level safety defaults."""
        logger.info("Opening Snowflake connection to %s", self._config.account)
        conn = snowflake.connector.connect(
            account=self._config.account,
            user=self._config.user,
            password=self._config.password,
            warehouse=self._config.warehouse,
            role=self._config.role,
            database=self._config.database,
            schema=self._config.schema,
            client_session_keep_alive=True,
        )
        # Enforce read-only behavior and query timeout at session level
        with conn.cursor() as cur:
            cur.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {self._config.query_timeout_seconds}")
            cur.execute("ALTER SESSION SET QUERY_TAG = 'census-chat-agent'")
        return conn

    def _get_conn(self) -> snowflake.connector.SnowflakeConnection:
        with self._conn_lock:
            if self._conn is None or self._conn.is_closed():
                self._conn = self._connect()
            return self._conn

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        """Yield a dict cursor. Reconnects once on transient failure."""
        conn = self._get_conn()
        try:
            cur = conn.cursor(DictCursor)
            try:
                yield cur
            finally:
                cur.close()
        except (OperationalError, DatabaseError) as e:
            logger.warning("Snowflake connection error, retrying once: %s", e)
            with self._conn_lock:
                self._conn = self._connect()
            cur = self._conn.cursor(DictCursor)
            try:
                yield cur
            finally:
                cur.close()

    def close(self) -> None:
        with self._conn_lock:
            if self._conn and not self._conn.is_closed():
                self._conn.close()
            self._conn = None

    @property
    def config(self) -> SnowflakeConfig:
        return self._config
