"""Semantic search over census field descriptions.

Builds a FAISS index over human-readable field meanings (from metadata tables).
Uses OpenAI's text-embedding-3-small to avoid the heavy torch+transformers
dependency chain. The index is cached to disk so subsequent app starts load
instantly.

Why OpenAI over sentence-transformers?
  - No torch / torchvision / transformers install (3GB+ saved)
  - No Python 3.14 incompatibilities
  - Quality is slightly better for short-text retrieval
  - Cost is negligible: 16k fields ≈ $0.005 one-time to index
  - Requires OPENAI_API_KEY which the agent needs anyway
"""
import logging
import os
import pickle
import time
from dataclasses import dataclass
from typing import List

import faiss
import numpy as np
from openai import OpenAI

from .config import SCHEMA_INDEX_PATH
from .schema_explorer import FieldDescription, SchemaExplorer

logger = logging.getLogger(__name__)


EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = 1536  # text-embedding-3-small dimension
_BATCH_SIZE = 256     # OpenAI embeddings API batch limit is 2048; 256 is safe


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
        self._client: OpenAI | None = None
        self._index: faiss.Index | None = None
        self._fields: List[FieldDescription] = []

    def _get_client(self) -> OpenAI:
        if self._client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is required for embeddings")
            self._client = OpenAI(api_key=api_key)
        return self._client

    def _embed_batch(self, texts: List[str]) -> np.ndarray:
        """Embed a list of texts via OpenAI's batch API."""
        client = self._get_client()
        resp = client.embeddings.create(
            model=self._model_name,
            input=texts,
        )
        vectors = np.asarray([d.embedding for d in resp.data], dtype="float32")
        # Normalize for cosine similarity via inner product
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        return vectors / norms

    def _embed_many(self, texts: List[str]) -> np.ndarray:
        """Embed all texts in batches, concatenating results."""
        out: List[np.ndarray] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            chunk = texts[i:i + _BATCH_SIZE]
            t0 = time.time()
            out.append(self._embed_batch(chunk))
            logger.info("Embedded batch %d/%d (%d texts) in %.1fs",
                        i // _BATCH_SIZE + 1,
                        (len(texts) + _BATCH_SIZE - 1) // _BATCH_SIZE,
                        len(chunk), time.time() - t0)
        return np.vstack(out)

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
        logger.info("Embedding %d field documents via %s", len(docs), self._model_name)
        embeddings = self._embed_many(docs)

        # Inner product on normalized vectors == cosine similarity
        self._index = faiss.IndexFlatIP(embeddings.shape[1])
        self._index.add(embeddings)
        self._save_cache()
        logger.info("Indexed %d fields", len(self._fields))

    def search(self, query: str, top_k: int = 15,
               year: int | None = None) -> List[SchemaMatch]:
        if self._index is None or not self._fields:
            raise RuntimeError("Index not built. Call build() first.")

        q_emb = self._embed_batch([query])
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