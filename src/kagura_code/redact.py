"""Credential redaction for log output. Conservative patterns."""
from __future__ import annotations

import re

# Patterns redacted in log output. Conservative on purpose.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{6,}"),
]


def redact_secrets(text: str) -> str:
    """Replace credential-looking substrings with ***REDACTED***."""
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("***REDACTED***", out)
    return out
