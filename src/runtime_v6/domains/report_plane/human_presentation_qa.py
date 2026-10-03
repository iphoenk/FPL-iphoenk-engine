from __future__ import annotations

"""Shared human-facing presentation leak gate for visible FPL report modes.

This validator is presentation-only. It never changes facts, models, decisions,
or report structure. It rejects internal identifiers and machine serialization
that should not appear in PRICE, DEADLINE, FINAL, or MATCH visible bodies.
"""

import re
from typing import Final

_LOCKED_MODES: Final[frozenset[str]] = frozenset({"PRICE", "DEADLINE", "FINAL", "MATCH"})

_FORBIDDEN_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    ("element_id", r"\belement_id\b"),
    ("entry_id", r"\bentry_id\b"),
    ("user_summary", r"\buser_summary\s*[:=]"),
    ("actual_paths", r"\bactual_paths\s*="),
    ("raw_run_or_workflow_id", r"\b(?:run_id|workflow_id)\b"),
    ("raw_sha_or_fingerprint", r"\b(?:sha256|fingerprint)\b"),
    ("generic_key_value", r"(?m)^[A-Za-z_][A-Za-z0-9_]{2,}\s*=\s*\S+"),
    ("raw_python_or_json_object", r"\{[^\n{}]{0,200}['\"][^\n{}]{0,200}\}"),
)

_FORBIDDEN_LITERALS: Final[tuple[str, ...]] = (
    "PERSONAL_AUTH_UNAVAILABLE",
    "CURRENT_VALID",
    "COVARIANCE_NOT_MODELLED_YET",
)

_UPPER_SNAKE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]{2,})+\b"
)


def validate_human_presentation_surface(
    body: str,
    *,
    report_mode: str,
) -> list[str]:
    """Return fail-closed visible-language violations for locked human modes."""
    mode = str(report_mode or "").strip().upper()
    if mode not in _LOCKED_MODES:
        return []

    text = str(body or "")
    failures: list[str] = []

    for label, pattern in _FORBIDDEN_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            failures.append(f"HUMAN_PRESENTATION_MACHINE_LANGUAGE_LEAK={label}")

    upper = text.upper()
    for literal in _FORBIDDEN_LITERALS:
        if literal in upper:
            failures.append(f"HUMAN_PRESENTATION_MACHINE_LANGUAGE_LEAK={literal}")

    for token in _UPPER_SNAKE_RE.findall(text):
        if token in _FORBIDDEN_LITERALS:
            continue
        failures.append(f"HUMAN_PRESENTATION_MACHINE_ENUM={token}")

    return list(dict.fromkeys(failures))
