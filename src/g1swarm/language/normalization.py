"""Deterministic text normalization for the controlled Chinese grammar.

Normalization is deliberately small: it normalizes punctuation and whitespace,
but never changes numeric values, left/right words, or inserts missing
parameters. Any input that is not reducible by these rules is handled by the
grammar and fails closed.
"""

from __future__ import annotations

import re
import unicodedata

_PUNCTUATION_MAP = {
    "，": ",",
    "。": ",",
    "；": ",",
    ";": ",",
    "、": ",",
    "→": ",",
    "：": ",",
    ":": ",",
}


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(_PUNCTUATION_MAP.get(char, char) for char in normalized)
    normalized = re.sub(r"\s+", "", normalized)
    for connector in ("然后", "再", "接着", "之后", "最后"):
        normalized = normalized.replace(f",{connector}", connector)
        normalized = normalized.replace(f"{connector},", connector)
    if normalized.endswith(","):
        normalized = normalized[:-1]
    return normalized
