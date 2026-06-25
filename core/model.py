"""Incremental text classifier for Ai-Improve.

A from-scratch multinomial Naive Bayes model that learns *online*: every
example is folded into the running counts immediately, so the AI keeps
improving as you teach it instead of needing a full retrain. State is
persisted to disk so learning accumulates across restarts.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from datetime import datetime, timezone

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "is", "are", "was", "were",
    "be", "to", "of", "in", "on", "at", "for", "with", "as", "by", "it",
    "this", "that", "these", "those", "i", "you", "he", "she", "we", "they",
}


def tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, drop stopwords -> list of tokens."""
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS]


class TextClassifier:
    """Online multinomial Naive Bayes with Laplace smoothing."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        # label -> number of documents seen
        self.doc_counts: dict[str, int] = {}
        # label -> {token: count}
        self.word_counts: dict[str, dict[str, int]] = {}
        # label -> total tokens seen (cached for speed)
        self.label_totals: dict[str, int] = {}
        self.vocab: set[str] = set()
        self.total_docs = 0
        self.history: list[dict] = []  # recent training events (capped)
        self._load()

    # ---- training -------------------------------------------------------
    def train(self, text: str, label: str, *, source: str = "manual") -> dict:
        """Fold a single (text, label) example into the model immediately."""
        label = (label or "").strip()
        tokens = tokenize(text)
        if not label:
            raise ValueError("label is required")
        if not tokens:
            raise ValueError("text contained no usable words")

        with self._lock:
            self.doc_counts[label] = self.doc_counts.get(label, 0) + 1
            self.total_docs += 1
            bucket = self.word_counts.setdefault(label, {})
            for tok in tokens:
                bucket[tok] = bucket.get(tok, 0) + 1
                self.vocab.add(tok)
            self.label_totals[label] = self.label_totals.get(label, 0) + len(tokens)
            self.history.append({
                "text": text[:200],
                "label": label,
                "source": source,
                "tokens": len(tokens),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            self.history = self.history[-100:]
            self._save()

        return {"label": label, "tokens": len(tokens), "total_docs": self.total_docs}

    def train_batch(self, examples: list[dict]) -> dict:
        """Train on many examples at once. Each item: {text, label}."""
        trained, skipped = 0, 0
        for ex in examples:
            try:
                self.train(ex.get("text", ""), ex.get("label", ""),
                           source=ex.get("source", "batch"))
                trained += 1
            except ValueError:
                skipped += 1
        return {"trained": trained, "skipped": skipped, "total_docs": self.total_docs}

    # ---- inference ------------------------------------------------------
    def predict(self, text: str, top_k: int = 3) -> dict:
        tokens = tokenize(text)
        with self._lock:
            if not self.doc_counts:
                return {"label": None, "confidence": 0.0, "scores": [],
                        "message": "Model is untrained. Teach it some examples first."}
            vocab_size = max(len(self.vocab), 1)
            log_scores: dict[str, float] = {}
            for label, doc_count in self.doc_counts.items():
                # log prior
                score = math.log(doc_count / self.total_docs)
                total = self.label_totals.get(label, 0)
                bucket = self.word_counts.get(label, {})
                denom = total + vocab_size  # Laplace smoothing denominator
                for tok in tokens:
                    count = bucket.get(tok, 0)
                    score += math.log((count + 1) / denom)
                log_scores[label] = score

            # softmax over log scores for human-readable confidence
            mx = max(log_scores.values())
            exps = {lbl: math.exp(s - mx) for lbl, s in log_scores.items()}
            denom = sum(exps.values()) or 1.0
            probs = sorted(
                ({"label": lbl, "confidence": round(v / denom, 4)}
                 for lbl, v in exps.items()),
                key=lambda d: d["confidence"], reverse=True,
            )

        best = probs[0]
        return {
            "label": best["label"],
            "confidence": best["confidence"],
            "scores": probs[:top_k],
            "matched_tokens": [t for t in tokens if t in self.vocab],
        }

    # ---- introspection / admin -----------------------------------------
    def stats(self) -> dict:
        with self._lock:
            return {
                "total_docs": self.total_docs,
                "labels": {l: self.doc_counts[l] for l in sorted(self.doc_counts)},
                "vocab_size": len(self.vocab),
                "recent": list(reversed(self.history[-10:])),
            }

    def reset(self) -> dict:
        with self._lock:
            self.doc_counts.clear()
            self.word_counts.clear()
            self.label_totals.clear()
            self.vocab.clear()
            self.total_docs = 0
            self.history.clear()
            self._save()
        return {"ok": True, "total_docs": 0}

    # ---- persistence ----------------------------------------------------
    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({
                "doc_counts": self.doc_counts,
                "word_counts": self.word_counts,
                "label_totals": self.label_totals,
                "vocab": sorted(self.vocab),
                "total_docs": self.total_docs,
                "history": self.history,
            }, fh)
        os.replace(tmp, self.path)

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.doc_counts = data.get("doc_counts", {})
            self.word_counts = data.get("word_counts", {})
            self.label_totals = data.get("label_totals", {})
            self.vocab = set(data.get("vocab", []))
            self.total_docs = data.get("total_docs", 0)
            self.history = data.get("history", [])
        except (json.JSONDecodeError, OSError):
            pass  # start fresh if the store is corrupt
