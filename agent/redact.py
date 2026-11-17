"""Mask secrets before anything leaves for the LLM, and trim long logs."""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"dapi[0-9a-f]{32}(-\d)?", re.I), "<DATABRICKS_TOKEN>"),
    (re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|sas)"
                r"(\s*[=:]\s*)(['\"]?)[^\s'\";,]+"), r"\1\2\3<REDACTED>"),
    (re.compile(r"(?i)AccountKey=[^;\s]+"), "AccountKey=<REDACTED>"),
    (re.compile(r"(?i)sig=[^&\s]+"), "sig=<REDACTED>"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "<JWT>"),
    (re.compile(r"(?i)(jdbc:[a-z]+://[^\s;]*;[^\s]*password=)[^;\s]+"), r"\1<REDACTED>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
]


def redact(text: str | None) -> str:
    if not text:
        return ""
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def head_tail(text: str, head: int, tail: int) -> str:
    """Keep the start (first exception / 'Caused by') and the end (final traceback)."""
    if len(text) <= head + tail:
        return text
    skipped = len(text) - head - tail
    return f"{text[:head]}\n\n... [{skipped} chars trimmed] ...\n\n{text[-tail:]}"
