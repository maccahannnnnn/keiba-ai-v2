"""Course name aliases for KeibaAI internal normalization.

The formal internal name for Chukyo is ``chuukyou``.  Legacy ``chukyo`` inputs
remain readable and are normalized at load time.  Knowledge modules may still
use historical module names, so ``knowledge_course_key`` maps the formal name
back to the existing module key where needed.
"""

from __future__ import annotations


FORMAL_COURSE_NAMES = {
    "tokyo",
    "nakayama",
    "chuukyou",
    "kyoto",
    "hanshin",
    "niigata",
    "fukushima",
    "hakodate",
    "sapporo",
    "kokura",
}

COURSE_ALIASES = {
    "tokyo": "tokyo",
    "nakayama": "nakayama",
    "chukyo": "chuukyou",
    "chuukyou": "chuukyou",
    "kyoto": "kyoto",
    "hanshin": "hanshin",
    "niigata": "niigata",
    "fukushima": "fukushima",
    "hakodate": "hakodate",
    "sapporo": "sapporo",
    "kokura": "kokura",
}

KNOWLEDGE_COURSE_KEYS = {
    "chuukyou": "chukyo",
}


def normalize_course_name(value):
    """Return the formal internal course name, or the lower-cased input."""

    text = str(value or "").strip()
    if not text:
        return None
    lower = text.lower()
    return COURSE_ALIASES.get(lower, lower)


def is_known_course(value) -> bool:
    """Return True when a course value is known after alias normalization."""

    normalized = normalize_course_name(value)
    return normalized in FORMAL_COURSE_NAMES


def knowledge_course_key(value):
    """Return the course key used by existing knowledge modules."""

    normalized = normalize_course_name(value)
    return KNOWLEDGE_COURSE_KEYS.get(normalized, normalized)
