"""Bounded Russian morphology shared by retrieval and evidence corroboration."""
from __future__ import annotations

from functools import lru_cache
import re
import threading

import snowballstemmer

_RUSSIAN_WORD = re.compile(r"[а-яё]{4,64}")
_THREAD = threading.local()


def russian_stem(word: str) -> str | None:
    """Return a lexical stem, never normalize paths or opaque identifiers."""
    if not _RUSSIAN_WORD.fullmatch(word.casefold()):
        return None
    return _stem_russian(word.casefold().replace("ё", "е"))


@lru_cache(maxsize=16384)
def _stem_russian(word: str) -> str | None:
    # Cache only validated short tokens. Snowball has mutable parsing state,
    # so concurrent callers share the bounded cache but not the stemmer.
    if getattr(_THREAD, "russian", None) is None:
        _THREAD.russian = snowballstemmer.stemmer("russian")
    stem = _THREAD.russian.stemWord(word)
    return stem if len(stem) >= 3 else None
