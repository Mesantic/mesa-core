# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
combiner.py — per-entity Snowflake metric-combiner default inference.

SPEC_72 (combiner architecture). A faithful port of CAO's
``tools/generate_metrics_combiner.py`` default-value inference
(``resolve_combiner_default``, ``DEFAULT_HEURISTICS``,
``COMBINER_DEFAULT_ANNOTATION_RE``).

The combiner collapses every metric file for an entity into ONE joined,
flat-columned model (``<entity_snake>_metrics``). That flat model is what lets
the Wide Layer use Snowflake's ``OBJECT_CONSTRUCT(alias.*)`` qualified-wildcard
pattern instead of one ``::OBJECT(...)`` cast per metric. This module resolves
only the *default value* each metric column should ``COALESCE`` to inside the
combiner — never a type (that's a different, narrower concern than
``wide_type.resolve_wide_type``, which this architecture no longer calls from
the Snowflake wide render, since the combiner form has no per-metric casts).

HARD RULE: port verbatim — do not re-derive the heuristic table, the regex
priority order, or the "NULL passes through, never zero-filled" default.
"""

from __future__ import annotations

import re

COMBINER_DEFAULT_ANNOTATION_RE = re.compile(r"--\s*COMBINER_DEFAULT\s*:\s*([^\n]+)", re.IGNORECASE)

# Heuristic default-value inference, checked in order against the metric's
# raw SQL text. First match wins. Conservative on purpose — an ambiguous
# metric falls through to "no COALESCE, pass NULL through" rather than
# guessing a default that could be silently wrong (e.g. defaulting an NPS
# score to 0 would look like a real, terrible score instead of "no data").
DEFAULT_HEURISTICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bCASE\b.*?\bTHEN\s+1\b.*?\bELSE\s+0\b", re.IGNORECASE | re.DOTALL), "0"),
    (re.compile(r"\bIFF\s*\(.*?,\s*1\s*,\s*0\s*\)", re.IGNORECASE | re.DOTALL), "0"),
    (re.compile(r"\bSUM\s*\(", re.IGNORECASE), "0"),
    (re.compile(r"\bCOUNT\s*\(", re.IGNORECASE), "0"),
]

# Metrics with survey/score-style averages (AVG(...) with no SUM/COUNT
# wrapper) are deliberately EXCLUDED from DEFAULT_HEURISTICS above — NULL
# ("no survey response") must stay NULL, never zero-filled, or a policy
# with no agent-change survey would look like it scored a 0 CSAT.


def resolve_combiner_default(metric_sql: str) -> str | None:
    """Returns the literal default expression to ``COALESCE`` with, or
    ``None`` if no default should be applied (metric passes through raw,
    NULL-preserving)."""
    m = COMBINER_DEFAULT_ANNOTATION_RE.search(metric_sql)
    if m:
        return m.group(1).strip()

    for pattern, default in DEFAULT_HEURISTICS:
        if pattern.search(metric_sql):
            return default

    return None


def to_snake_case(name: str) -> str:
    """PascalCase -> snake_case (e.g. "ChangeEvent" -> "change_event").

    Ported verbatim from ``generate_metrics_combiner.py`` / ``generate_wide_layer.py``'s
    ``_to_snake`` — used to name the combiner model (``<entity_snake>_metrics``).
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def combiner_model_name(entity_name: str) -> str:
    """The combiner model's ref-able name for an entity, e.g. "Policy" -> "policy_metrics"."""
    return f"{to_snake_case(entity_name)}_metrics"
