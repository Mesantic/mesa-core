# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
wide_type.py — per-metric Snowflake wide-layer type inference.

SPEC_72 Slice 1. A faithful port of CAO's
``tools/generate_wide_layer.py`` type-inference (``resolve_wide_type``,
``TYPE_HEURISTICS``, ``WIDE_TYPE_ANNOTATION_RE``). This is the ONE piece of the
wide-layer assembly that serves every dialect — the inferred type feeds
Snowflake's ``::OBJECT(M TYPE)`` cast, Synapse's flat-column ``CAST``, and is
documentation-only on Redshift. Only the emission wrapper around the type
differs per warehouse.

HARD RULE: port verbatim — do not re-derive the heuristic table, the regex
priority order, or the single-line anchor guard.
"""

from __future__ import annotations

import re

# Anchored to end-of-line ([^\\n]+) rather than a whitespace-inclusive
# character class — the earlier version's char class included \\s, which let
# it match across blank lines into the next SQL block (WITH/SELECT/...) for
# any metric file whose CTE body starts on the next non-blank line. Always
# keep this anchored to a single line.
WIDE_TYPE_ANNOTATION_RE = re.compile(r"--\s*WIDE_TYPE\s*:\s*([^\n]+)", re.IGNORECASE)

# Heuristic type-inference regexes, checked in order against the metric's
# raw SQL text. First match wins. This is intentionally conservative —
# ambiguous cases fall through to the VARCHAR-with-warning default rather
# than guessing confidently wrong.
TYPE_HEURISTICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bTO_CHAR\s*\(", re.IGNORECASE), "VARCHAR"),
    (re.compile(r"\bAVG\s*\(", re.IGNORECASE), "FLOAT"),
    (re.compile(r"RETENTION\s*RATE|RATIO", re.IGNORECASE), "FLOAT"),
    (re.compile(r"\bCASE\b.*?\bTHEN\s+1\b.*?\bELSE\s+0\b", re.IGNORECASE | re.DOTALL), "NUMBER"),
    # Snowflake IFF(condition, 1, 0) — same 0/1 flag pattern as CASE/WHEN, just
    # the more compact Snowflake-native form (see InForce90DaysAfterChangeFlag.sql).
    (re.compile(r"\bIFF\s*\(.*?,\s*1\s*,\s*0\s*\)", re.IGNORECASE | re.DOTALL), "NUMBER"),
    (re.compile(r"\bSUM\s*\(", re.IGNORECASE), "NUMBER"),
    (re.compile(r"\bCOUNT\s*\(", re.IGNORECASE), "NUMBER"),
    (re.compile(r"\bDATEDIFF\s*\(", re.IGNORECASE), "NUMBER"),
]


def resolve_wide_type(metric_sql: str) -> tuple[str, bool]:
    """Returns (snowflake_type, was_inferred). was_inferred=True means
    no explicit WIDE_TYPE annotation was found and a heuristic (or the
    VARCHAR fallback) was used — caller should warn in that case."""
    m = WIDE_TYPE_ANNOTATION_RE.search(metric_sql)
    if m:
        return m.group(1).strip().upper(), False

    for pattern, sf_type in TYPE_HEURISTICS:
        if pattern.search(metric_sql):
            return sf_type, True

    return "VARCHAR", True
