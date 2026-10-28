"""Which headlines might bear on which promise?

Two interchangeable matchers:
  * EmbeddingMatcher - bge-m3 via Ollama (best, needs a GPU/CPU box with Ollama)
  * KeywordMatcher   - tf-idf over crude word stems, pure Python (works anywhere, e.g. a cloud agent)
Both only *propose* candidates; whoever judges (local model, API model, or an agent) makes the call.
"""
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

from common import CACHE, backend, embed, ensure_ollama, item_text, log


def _stems(text: str) -> set[str]:
    """Crude stemmer: first five letters of every word of 4+ letters (good enough for Bulgarian inflection)."""
    return {w[:5] for w in re.findall(r"\w{4,}", text.casefold())}


class KeywordMatcher:
    kind = "keywords"
    min_key, dup_key = "keyword_cosine_min", "duplicate_keyword_cosine"

    def __init__(self, promises: list[dict], items: list[dict]):
        docs = [_stems(p["text"] + " " + p["match_text"]) for p in promises] + [_stems(item_text(i)) for i in items]
        df = Counter(s for d in docs for s in d)
        self.n = len(docs)
        self.idf = {s: math.log((self.n + 1) / (c + 0.5)) for s, c in df.items()}

    def _vec(self, text: str) -> dict[str, float]:
        return {s: self.idf.get(s, math.log(self.n + 1)) for s in _stems(text)}

    @staticmethod
    def _cos(a: dict, b: dict) -> float:
        dot = sum(a[s] * b[s] for s in a.keys() & b.keys())
        na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    def scores(self, promises: list[dict], items: list[dict]) -> np.ndarray:
        pv = [self._vec(p["text"] + " " + p["match_text"]) for p in promises]
        return np.array([[self._cos(self._vec(item_text(i)), v) for v in pv] for i in items], dtype=np.float32)

    def max_similarity(self, text: str, others: list[str]) -> float:
        v = self._vec(text)
        return max((self._cos(v, self._vec(o)) for o in others), default=0.0)


class EmbeddingMatcher:
    kind = "embeddings"
    min_key, dup_key = "embed_cosine_min", "duplicate_promise_cosine"

    def __init__(self, model: str):
        self.model = model

    def _item_vectors(self, items: list[dict]) -> np.ndarray:
        path = CACHE / "news_emb.npz"
        ids, vecs = [], np.zeros((0, 1024), dtype=np.float32)  # bge-m3 is 1024-d
        if path.exists():
            z = np.load(path, allow_pickle=False)
            ids, vecs = list(z["ids"]), z["vecs"]
        have = set(ids)
        todo = [i for i in items if i["id"] not in have]
        if todo:
            log(f"match: embedding {len(todo)} new headlines")
            new = embed(self.model, [item_text(i) for i in todo])
            ids += [i["id"] for i in todo]
            vecs = np.vstack([vecs, new]) if len(vecs) else new
            CACHE.mkdir(parents=True, exist_ok=True)
            np.savez(path, ids=np.array(ids), vecs=vecs)
        index = {iid: n for n, iid in enumerate(ids)}
        return vecs[[index[i["id"]] for i in items]] if items else vecs[:0]

    def scores(self, promises: list[dict], items: list[dict]) -> np.ndarray:
        pv = embed(self.model, [p["match_text"] for p in promises])
        return self._item_vectors(items) @ pv.T

    def max_similarity(self, text: str, others: list[str]) -> float:
        if not others:
            return 0.0
        return float((embed(self.model, others) @ embed(self.model, [text])[0]).max())


def make(models: dict, promises: list[dict], items: list[dict]):
    kind = backend()["matcher"]
    if kind in ("embeddings", "auto"):
        try:
            if ensure_ollama():
                embed(models["embed"], ["test"])
                return EmbeddingMatcher(models["embed"])
        except Exception as e:  # noqa: BLE001
            if kind == "embeddings":
                raise
            log(f"match: embeddings unavailable ({type(e).__name__}); using keyword matcher")
    return KeywordMatcher(promises, items)
