# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
wide_type.py — per-metric wide-layer type inference.

Two inference engines live here:

1. ``resolve_wide_type`` (SPEC_72 Slice 1) — Snowflake. A faithful port of
   CAO's ``tools/generate_wide_layer.py`` type-inference. The inferred type
   feeds Snowflake's ``::OBJECT(M TYPE)`` cast and is documentation-only on
   Redshift. Retired from the Snowflake *combiner* wide render (which has no
   per-metric cast) but kept as a pure function.

2. ``resolve_tsql_type`` (SPEC_76) — Synapse Dedicated SQL Pool + Azure SQL
   Database. T-SQL-native inference for the flat-column ``CAST``. Snowflake's
   ``NUMBER``/``FLOAT``/``VARCHAR`` buckets do NOT translate 1:1 to T-SQL
   (which distinguishes ``BIT`` vs ``BIGINT`` vs ``INT`` vs ``DECIMAL``), so
   this is a SEPARATE table, not a translation of the Snowflake one. It
   mirrors the same discipline: annotation wins, heuristic table, VARCHAR
   fallback, ``was_inferred`` flag.

HARD RULE: port verbatim — do not re-derive the heuristic tables, the regex
priority order, or the single-line anchor guards.
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


# ── T-SQL (Synapse Dedicated + Azure SQL Database) type inference ───────────

# T-SQL annotation: ``-- WIDE_TYPE_TSQL: <type>``. A distinct annotation so a
# metric can carry BOTH a Snowflake WIDE_TYPE and a T-SQL type without the two
# colliding (the T-SQL cast vocabulary is different from Snowflake's).
WIDE_TYPE_TSQL_ANNOTATION_RE = re.compile(r"--\s*WIDE_TYPE_TSQL\s*:\s*([^\n]+)", re.IGNORECASE)

# Heuristic T-SQL type inference, checked in order. First match wins.
# Conservative on purpose — ambiguous cases fall through to VARCHAR(MAX) with a
# warning rather than guessing a numeric type that could truncate or fail a
# cast at deploy time.
#
# Ground-truth vocabulary (SPEC_69a_BUILD / SPEC_69_BUILD_B, the live Azure
# SQL DB + Synapse four-tier builds):
#   boolean flag          → BIT
#   count / distinct cnt  → BIGINT
#   date parts / deltas   → INT
#   money / count-quantity→ DECIMAL(18,2)
#   rate / percent        → DECIMAL(8,2)
#   float-like avg        → FLOAT
#   text                  → VARCHAR(MAX)
#
# The 0/1 CASE/IFF flag pattern deliberately precedes COUNT/SUM — a flag CTE
# can contain a COUNT(...) inside its body, but the terminal SELECT is a 0/1
# flag, and flag-ness is the tighter, more correct signal.
TSQL_TYPE_HEURISTICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bCASE\b.*?\bTHEN\s+1\b.*?\bELSE\s+0\b", re.IGNORECASE | re.DOTALL), "BIT"),
    (re.compile(r"\bIFF\s*\(.*?,\s*1\s*,\s*0\s*\)", re.IGNORECASE | re.DOTALL), "BIT"),
    (re.compile(r"\bAVG\s*\(", re.IGNORECASE), "FLOAT"),
    (re.compile(r"RETENTION\s*RATE|RATIO|\bRATE\b", re.IGNORECASE), "DECIMAL(8,2)"),
    (re.compile(r"\bCOUNT\s*\(", re.IGNORECASE), "BIGINT"),
    (re.compile(r"\bDATEDIFF\s*\(", re.IGNORECASE), "INT"),
    (re.compile(r"\bDATEADD\s*\(", re.IGNORECASE), "DATE"),
    (re.compile(r"\bSUM\s*\(", re.IGNORECASE), "DECIMAL(18,2)"),
    (re.compile(r"\bTO_CHAR\s*\(|\bCONVERT\s*\(\s*VARCHAR", re.IGNORECASE), "VARCHAR(MAX)"),
]


def resolve_tsql_type(metric_sql: str) -> tuple[str, bool]:
    """Returns (tsql_type, was_inferred) for the flat-column ``CAST``.

    Annotation (``-- WIDE_TYPE_TSQL:``) wins; otherwise the T-SQL heuristic
    table; otherwise VARCHAR(MAX) with ``was_inferred=True`` so the caller can
    surface the same fallback warning Snowflake does.
    """
    m = WIDE_TYPE_TSQL_ANNOTATION_RE.search(metric_sql)
    if m:
        return m.group(1).strip().upper(), False

    for pattern, tsql_type in TSQL_TYPE_HEURISTICS:
        if pattern.search(metric_sql):
            return tsql_type, True

    return "VARCHAR(MAX)", True
