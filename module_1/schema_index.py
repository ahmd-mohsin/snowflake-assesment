"""Semantic search over census field descriptions.

Builds a FAISS index over human-readable field meanings (from metadata tables),
not raw column names. The index is cached to disk so subsequent app starts are
fast (~1s vs ~30s on first build).
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
from .schema_explorer import FieldDescription, SchemaExplorer

logger = logging.getLogger(__name__)


@dataclass
class SchemaMatch:
    field: FieldDescription
    score: float


class SchemaIndex:
    _INDEX_FILE = "faiss.index"
    _FIELDS_FILE = "fields.pkl"

    def __init__(self, cache_dir: str = SCHEMA_INDEX_PATH,
                 model_name: str = EMBEDDING_MODEL):
        self._cache_dir = cache_dir
        self._model_name = model_name
        self._model: SentenceTransformer | None = None
        self._index: faiss.Index | None = None
        self._fields: List[FieldDescription] = []

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def build(self, explorer: SchemaExplorer, force: bool = False) -> None:
        if not force and self._cache_exists():
            logger.info("Loading cached schema index from %s", self._cache_dir)
            self._load_cache()
            return

        logger.info("Building schema index from metadata tables")
        self._fields = explorer.load_all_field_descriptions()
        if not self._fields:
            raise RuntimeError(
                "No field descriptions loaded. Check Snowflake access and that "
                "METADATA_CBG_FIELD_DESCRIPTIONS tables are present."
            )

        docs = [f.to_document() for f in self._fields]
        model = self._load_model()
        embeddings = model.encode(docs, show_progress_bar=True,
                                  normalize_embeddings=True,
                                  batch_size=64)
        embeddings = np.asarray(embeddings, dtype="float32")

        self._index = faiss.IndexFlatIP(embeddings.shape[1])
        self._index.add(embeddings)
        self._save_cache()
        logger.info("Indexed %d fields", len(self._fields))

    def search(self, query: str, top_k: int = 15,
               year: int | None = None) -> List[SchemaMatch]:
        """Return top_k matching fields. If year is given, restrict to that vintage."""
        if self._index is None or not self._fields:
            raise RuntimeError("Index not built. Call build() first.")
        model = self._load_model()
        q_emb = model.encode([query], normalize_embeddings=True)
        q_emb = np.asarray(q_emb, dtype="float32")

        # Over-fetch when filtering by year so we still get top_k after filter
        fetch_k = top_k * 3 if year else top_k
        scores, idxs = self._index.search(q_emb, fetch_k)

        results: List[SchemaMatch] = []
        for s, i in zip(scores[0], idxs[0]):
            if i == -1:
                continue
            fld = self._fields[i]
            if year is not None and fld.year != year:
                continue
            results.append(SchemaMatch(field=fld, score=float(s)))
            if len(results) >= top_k:
                break
        return results

    def _cache_exists(self) -> bool:
        return (os.path.exists(os.path.join(self._cache_dir, self._INDEX_FILE))
                and os.path.exists(os.path.join(self._cache_dir, self._FIELDS_FILE)))

    def _save_cache(self) -> None:
        os.makedirs(self._cache_dir, exist_ok=True)
        faiss.write_index(self._index, os.path.join(self._cache_dir, self._INDEX_FILE))
        with open(os.path.join(self._cache_dir, self._FIELDS_FILE), "wb") as f:
            pickle.dump(self._fields, f)

    def _load_cache(self) -> None:
        self._index = faiss.read_index(os.path.join(self._cache_dir, self._INDEX_FILE))
        with open(os.path.join(self._cache_dir, self._FIELDS_FILE), "rb") as f:
            self._fields = pickle.load(f)
