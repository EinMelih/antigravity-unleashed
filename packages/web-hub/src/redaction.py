"""Shared, dependency-free redaction for public diagnostics and previews."""

from __future__ import annotations

import re
from typing import Any


_SENSITIVE_SUBSTITUTIONS = (
    (
        re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/])[^;\r\n\"']+"),
        "[PATH REDACTED]",
    ),
    (
        re.compile(r"(?<![\\\w])\\\\[^\\\s]+\\[^;\r\n\"']+"),
        "[PATH REDACTED]",
    ),
    (
        re.compile(r"(?<!\w)/(?:home|Users|private|tmp|var/folders)/[^;\r\n\"']+"),
        "[PATH REDACTED]",
    ),
    (
        re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"']+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+\-/]+=*"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(?:github_pat_|gh[pousr]_|sk-|AIza)"
            r"[A-Za-z0-9_.-]{8,}"
        ),
        "[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(token|api[_-]?key|secret|password|passwd)"
            r"(\s*(?:=|:)\s*|\s+)[^\s\"';&|]+"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"(https?://[^:/\s]+:)[^@\s]+@"),
        r"\1[REDACTED]@",
    ),
)


def redact_sensitive_text(value: Any, *, maximum: int = 500) -> str:
    """Redact common secrets and private paths from one bounded string."""
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0:
        raise ValueError("maximum must be a non-negative integer.")
    text = str(value or "").strip()
    for pattern, replacement in _SENSITIVE_SUBSTITUTIONS:
        text = pattern.sub(replacement, text)
    return text[:maximum]


__all__ = ["redact_sensitive_text"]
