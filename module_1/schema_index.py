"""Semantic search over schema using sentence-transformers + FAISS.

The census dataset has too many columns to fit in an LLM prompt. On first run
we embed every column's (table + name + description) and cache the index to
disk. At query time we retrieve the top-K most relevant columns for the user's
natural language question and inject only those into the prompt.
"""
import logging
import os
import pickle
from dataclasses import dataclass
from typing import List

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from .config import EMBEDDING_MODEL, SCHEMA_INDEX_PATH
from .schema_explorer import ColumnInfo, SchemaExplorer

logger = logging.getLogger(__name__)


@dataclass
class SchemaMatch:
    column: ColumnInfo
    score: float


class SchemaIndex:
    """Builds and queries a FAISS index over column metadata."""

    _INDEX_FILE = "faiss.index"
    _DOCS_FILE = "docs.pkl"

    def __init__(self, cache_dir: str = SCHEMA_INDEX_PATH,
                 model_name: str = EMBEDDING_MODEL):
        self._cache_dir = cache_dir
        self._model_name = model_name
        self._model: SentenceTransformer | None = None
        self._index: faiss.Index | None = None
        self._columns: List[ColumnInfo] = []

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def build(self, explorer: SchemaExplorer, force: bool = False) -> None:
        """Build the index from Snowflake. Skips work if cache exists."""
        if not force and self._cache_exists():
            logger.info("Loading cached schema index from %s", self._cache_dir)
            self._load_cache()
            return

        logger.info("Building schema index from Snowflake")
        tables = explorer.build_full_schema()
        self._columns = [c for t in tables for c in t.columns]
        if not self._columns:
            raise RuntimeError("No columns found — check Snowflake access and dataset.")

        docs = [c.to_document() for c in self._columns]
        model = self._load_model()
        embeddings = model.encode(docs, show_progress_bar=True,
                                  normalize_embeddings=True)
        embeddings = np.asarray(embeddings, dtype="float32")

        # Inner product on normalized vectors == cosine similarity
        self._index = faiss.IndexFlatIP(embeddings.shape[1])
        self._index.add(embeddings)
        self._save_cache()

    def search(self, query: str, top_k: int = 15) -> List[SchemaMatch]:
        if self._index is None or not self._columns:
            raise RuntimeError("Index not built. Call build() first.")
        model = self._load_model()
        q_emb = model.encode([query], normalize_embeddings=True)
        q_emb = np.asarray(q_emb, dtype="float32")
        scores, idxs = self._index.search(q_emb, top_k)
        return [
            SchemaMatch(column=self._columns[i], score=float(s))
            for s, i in zip(scores[0], idxs[0]) if i != -1
        ]

    def _cache_exists(self) -> bool:
        return (os.path.exists(os.path.join(self._cache_dir, self._INDEX_FILE))
                and os.path.exists(os.path.join(self._cache_dir, self._DOCS_FILE)))

    def _save_cache(self) -> None:
        os.makedirs(self._cache_dir, exist_ok=True)
        faiss.write_index(self._index, os.path.join(self._cache_dir, self._INDEX_FILE))
        with open(os.path.join(self._cache_dir, self._DOCS_FILE), "wb") as f:
            pickle.dump(self._columns, f)

    def _load_cache(self) -> None:
        self._index = faiss.read_index(os.path.join(self._cache_dir, self._INDEX_FILE))
        with open(os.path.join(self._cache_dir, self._DOCS_FILE), "rb") as f:
            self._columns = pickle.load(f)
