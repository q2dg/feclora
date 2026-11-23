"""Conservative classification of explicit imaging-process read failures."""

from __future__ import annotations

import re

_READ_FAILURE_PATTERNS = (
    re.compile(r"\berror reading\b", re.IGNORECASE),
    re.compile(r"\bread error\b", re.IGNORECASE),
    re.compile(r"\bfailed to read\b", re.IGNORECASE),
    re.compile(r"\bunable to read\b", re.IGNORECASE),
    re.compile(r"\bcannot read\b", re.IGNORECASE),
)


def process_diagnostic_category(detail: str) -> str | None:
    """Return read_error only for explicit read-failure wording in tool stderr."""
    if not isinstance(detail, str):
        return None
    if any(pattern.search(detail) for pattern in _READ_FAILURE_PATTERNS):
        return "read_error"
    return None
