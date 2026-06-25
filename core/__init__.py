"""Core package for Ai-Improve: the trainable model and internet access."""

from .model import TextClassifier, tokenize
from .web import fetch_url, search

__all__ = ["TextClassifier", "tokenize", "fetch_url", "search"]
