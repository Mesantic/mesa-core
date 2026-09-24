# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
wide_columns.py — raw-entity column detection for the Snowflake wide render.

THE BUG THIS FILE FIXES (verified against real Farmers PolicyRaw, 2026-09-23)
-------------------------------------------------------------------------------
Snowflake's qualified-wildcard ``OBJECT_CONSTRUCT(alias.*)`` — the pattern
the Wide Layer has used for every entity since SPEC_72 — CANNOT auto-expand
a source column that is ITSELF already a typed ``OBJECT(...)`` or
``ARRAY(OBJECT(...))``. Snowflake raises:

    Function OBJECT_CONSTRUCT(*) does not support OBJECT(...) argument type

This is a genuine Snowflake platform limitation, not a MESA bug — the
wildcard-expansion form of OBJECT_CONSTRUCT has stricter type coercion than
the explicit key/value form. Any raw entity that follows MESA's own Raw
Layer doctrine (quarantine system IDs in a typed OBJECT, quarantine 1:many
detail in a typed ARRAY — see copilot-instructions.md §2) will eventually
hit this. ``CustomerAddressRaw`` hit it first and was hand-patched directly
in the committed wide file (a doctrine violation — Wide Layer files must
never be hand-edited); ``PolicyRaw`` hit it next when its ``SystemIds`` /
``MonthlySnapshots`` columns got exercised by a ``--full-refresh``.

THE FIX
-------
Detect, from the raw entity's OWN authored SQL, which top-level SELECT
columns are OBJECT/ARRAY-typed. If none are, keep emitting the safe
zero-maintenance wildcard (100% backward compatible — every entity that
worked before keeps working). If any are, emit the EXPLICIT key/value
``OBJECT_CONSTRUCT('Col', alias.Col, ...)`` form instead, casting only the
typed columns to ``::VARIANT`` (matching the ``CustomerAddressWide`` hand
patch that was already proven correct in production) — but doing it as a
mechanical, generated, always-in-sync render instead of a hand edit that
drifts from the generator.

CONSERVATIVE ON PURPOSE: if the raw SQL can't be confidently parsed (no
terminal SELECT/FROM found, or a column's alias can't be resolved), this
module returns ``None`` and the caller falls back to the wildcard form —
the previously-working default — rather than guessing wrong. This mirrors
the same discipline as ``wide_type.py``'s VARCHAR-with-warning fallback.

HARD RULE: this logic must be ported verbatim between mesa-core and CAO's
standalone ``tools/generate_wide_layer.py`` (which cannot import mesa-core —
no live warehouse connection, and Snowflake's server-side dbt runtime gets
an empty file-list graph). Do not let the two drift.
"""

from __future__ import annotations

import re

_OBJECT_ARRAY_CAST_RE = re.compile(r"::\s*(OBJECT|ARRAY)\s*\(", re.IGNORECASE)
_ALIAS_RE = re.compile(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _strip_line_comments(sql: str) -> str:
    """Strip ``-- ...`` line comments. Raw entity SQL in this project is
    doctrine-commented heavily (see copilot-instructions.md's doctrine-header
    convention) — a comment containing a comma (e.g. "-- 1:1 business
    attributes, no wrapping OBJECT.") would otherwise be mistaken for a
    column boundary by ``_split_top_level``. Line comments only (no ``/* */``
    block comments are used in this project's raw SQL)."""
    return _LINE_COMMENT_RE.sub("", sql)


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split ``text`` on ``sep`` only at paren-depth 0 — a top-level-comma
    splitter, so a column expression's own internal commas (inside a nested
    ``OBJECT_CONSTRUCT(...)`` or function call) are never mistaken for a
    column boundary."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _find_terminal_select_and_from(sql: str) -> tuple[int, int] | None:
    """Find the span of a raw entity's TERMINAL (paren-depth-0) column list —
    the text between the outermost ``SELECT`` and its matching top-level
    ``FROM``. Every CTE-internal ``SELECT``/``FROM`` lives inside balanced
    parens (``WITH x AS (SELECT ... FROM ...)``), so depth-0 tracking finds
    exactly the one that matters, regardless of how many CTEs precede it.

    Returns ``(start, end)`` character offsets, or ``None`` if no depth-0
    SELECT/FROM pair could be found — callers must treat ``None`` as "don't
    guess, fall back to the safe default."
    """
    depth = 0
    last_select_end: int | None = None
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0 and (ch.isalpha() or ch == "_"):
            m = _WORD_RE.match(sql, i)
            if m:
                if m.group(0).upper() == "SELECT":
                    last_select_end = m.end()
                i = m.end()
                continue
        i += 1

    if last_select_end is None:
        return None

    depth = 0
    i = last_select_end
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0 and (ch.isalpha() or ch == "_"):
            m = _WORD_RE.match(sql, i)
            if m:
                if m.group(0).upper() == "FROM":
                    return last_select_end, m.start()
                i = m.end()
                continue
        i += 1

    return None


def detect_wide_columns(raw_definition_sql: str) -> list[tuple[str, bool]] | None:
    """Parse a MESA raw-entity's authored SQL and return an ordered list of
    ``(ColumnAlias, is_object_or_array_typed)`` for every column in its
    terminal SELECT.

    Returns ``None`` if the SQL couldn't be confidently parsed — no terminal
    SELECT/FROM pair, or any column item whose alias couldn't be resolved —
    so the caller falls back to the pre-existing ``OBJECT_CONSTRUCT(alias.*)``
    wildcard form instead of risking a wrong/partial column list.
    """
    if not raw_definition_sql or not raw_definition_sql.strip():
        return None

    cleaned_sql = _strip_line_comments(raw_definition_sql)

    span = _find_terminal_select_and_from(cleaned_sql)
    if span is None:
        return None

    start, end = span
    items = _split_top_level(cleaned_sql[start:end], ",")

    columns: list[tuple[str, bool]] = []
    for raw_item in items:
        item = raw_item.strip()
        if not item:
            continue
        m = _ALIAS_RE.search(item)
        if not m:
            # Can't confidently resolve this item's alias — bail out
            # entirely rather than silently mislabeling/omitting a column.
            return None
        alias = m.group(1)
        is_typed = bool(_OBJECT_ARRAY_CAST_RE.search(item))
        columns.append((alias, is_typed))

    return columns or None


def has_typed_column(columns: list[tuple[str, bool]] | None) -> bool:
    """True if any detected column is OBJECT/ARRAY-typed — the signal that
    the safe wildcard form must be swapped for the explicit-column form."""
    return bool(columns) and any(is_typed for _, is_typed in columns)


def build_explicit_object_construct(
    alias_var: str,
    columns: list[tuple[str, bool]],
    indent: str = "",
    as_alias: str | None = None,
) -> str:
    """Render the explicit key/value ``OBJECT_CONSTRUCT(...)`` body for a raw
    entity that has one or more OBJECT/ARRAY-typed columns — the form
    ``OBJECT_CONSTRUCT(alias.*)`` cannot auto-expand those on Snowflake (see
    module docstring). Matches the ``CustomerAddressWide`` hand-patch shape
    exactly, but generated instead of hand-maintained.

    ``indent`` is prefixed onto every emitted line (including the opening
    and closing parens) so the caller can align the whole block under a
    ``SELECT`` without post-processing — every line, not just the first,
    needs the same left margin.

    ``as_alias``, if given, appends `` AS <as_alias>`` onto the closing-paren
    line (standard SQL style — the alias lands next to the ``)``, not on its
    own line).
    """
    lines = [f"{indent}OBJECT_CONSTRUCT("]
    for idx, (col, is_typed) in enumerate(columns):
        value_expr = f"{alias_var}.{col}::VARIANT" if is_typed else f"{alias_var}.{col}"
        prefix = f"{indent}    " if idx == 0 else f"{indent}    , "
        lines.append(f"{prefix}'{col}', {value_expr}")
    closing = f"{indent})"
    if as_alias:
        closing += f" AS {as_alias}"
    lines.append(closing)
    return "\n".join(lines)
