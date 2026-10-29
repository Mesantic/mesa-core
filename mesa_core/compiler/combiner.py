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

try:
    import sqlglot
    from sqlglot import exp as _exp
    _SQLGLOT_AVAILABLE = True
except ImportError:  # pragma: no cover — sqlglot is a pinned dependency
    _SQLGLOT_AVAILABLE = False

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


# A deliberate NULL pass-through. `COMBINER_DEFAULT: NONE` (or NULL) means the
# metric is *annotated* to have no zero-fill — its NULL stays NULL. Before
# SPEC_101 Slice 1 the annotation branch returned the literal 'NONE', so the
# compiler emitted `COALESCE(col, NONE)` — invalid SQL. The only reason that
# never fired in production is the strip bug now fixed in the same slice.
_NULL_ANNOTATION_VALUES = frozenset({"NONE", "NULL"})

# ── SPEC_101 Slice 1b: ratios never zero-fill ────────────────────────────────
# A ratio with no rows is not 0 — it's "no data". Zero-filling it is the same
# class of bug as the 2026-10-07 "open windows shown as lost" defect: a rate for
# a policy with no events rendered as 0% instead of blank.
#
# The defect is DIVISION, not SUM. An earlier note blamed bare `SUM(` because it
# matched a ratio, but a premium total with no rows genuinely is 0 the same way a
# count is. Dropping `SUM(` would have broken every money metric to fix one rate.
#
# Measured on real CAO (40 metrics, 2026-10-18): 16 got a '0' default, 24 passed
# NULL through, division appeared in 2. A terminal-projection rule flips exactly
# ONE — AgentChangeResponseRate. The other division (IsLikelyMoveEvent) lives
# only inside a CTE and its terminal SELECT is a 0/1 flag, so it correctly keeps
# its '0'.
#
# Jinja is replaced with a placeholder identifier before parsing. The probe got
# zero parse failures across all 40 real metrics with this approach.
_JINJA_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_JINJA_PLACEHOLDER = "__mesa_jinja_ref__"

# Division-shaped function calls. sqlglot normalizes DIV0/SAFE_DIVIDE to a Div
# node on most dialects, but not all — check the name too so a dialect that
# keeps them as Anonymous still trips the rule.
_DIVISION_FUNCTIONS = frozenset({"DIV0", "SAFE_DIVIDE", "DIVIDE", "ZEROIFNULL_DIV"})


def _terminal_projection_has_division(metric_sql: str, dialect: str) -> tuple[bool, str | None]:
    """Does the metric's TERMINAL SELECT project a division?

    Returns ``(has_division, parse_error)``. ``parse_error`` is a short message
    when sqlglot couldn't parse the SQL at all — the caller warns rather than
    swallowing it, because a silent parse failure would quietly restore the
    zero-fill this rule exists to remove.

    Only the outermost SELECT is inspected. A division inside a CTE is a
    different thing: the CTE's result is consumed by the terminal projection,
    and if that projection is a 0/1 flag the metric is a flag, not a ratio.
    That's the IsLikelyMoveEvent shape, and it keeps its '0'.
    """
    if not _SQLGLOT_AVAILABLE:  # pragma: no cover — sqlglot is pinned
        return False, "sqlglot not installed"

    probe = _JINJA_RE.sub(_JINJA_PLACEHOLDER, metric_sql)
    try:
        tree = sqlglot.parse_one(probe, read=dialect)
    except Exception as exc:  # noqa: BLE001 — any parse failure is the same signal
        return False, f"{type(exc).__name__}: {exc}"

    if tree is None:
        return False, "empty parse result"

    select = tree if isinstance(tree, _exp.Select) else tree.find(_exp.Select)
    if select is None:
        return False, "no SELECT found"

    for projection in select.expressions:
        for node in projection.walk():
            is_division = isinstance(node, _exp.Div) or (
                isinstance(node, _exp.Anonymous)
                and str(node.this).upper() in _DIVISION_FUNCTIONS
            )
            # A division INSIDE an aggregate is a row-level expression, not a
            # ratio: SUM(AmountCents / 100) is a money total with a unit
            # conversion and a genuine 0 when empty. Only a division applied
            # to the aggregated results — SUM(a) / SUM(b) — is a ratio.
            if is_division and not _inside_aggregate(node, projection):
                return True, None
    return False, None


def _inside_aggregate(node, boundary) -> bool:
    """True when ``node`` sits under an aggregate function, walking up no
    further than ``boundary`` (the projection that contains it)."""
    parent = node.parent
    while parent is not None:
        if isinstance(parent, _exp.AggFunc):
            return True
        if parent is boundary:
            return False
        parent = parent.parent
    return False


def resolve_combiner_default(
    metric_sql: str,
    annotation: str | None = None,
    *,
    dialect: str = "snowflake",
    warnings: list[str] | None = None,
    metric_label: str | None = None,
) -> str | None:
    """Returns the literal default expression to ``COALESCE`` with, or
    ``None`` if no default should be applied (metric passes through raw,
    NULL-preserving).

    SPEC_101 Slice 1 — the annotation is an explicit argument, read from the
    metric file's leading header by ``annotations.parse_annotations``. It has to
    come from the file text, not from ``metric_sql``: the loader strips the
    header before the compiler ever sees the SQL, so a regex over the body can
    never match a real annotation.

    Resolution order (SPEC_103 Slice 3 extends this same chain to every
    warehouse, so keep it dialect-neutral):
      1. annotation, when present
      2. the ratio rule (SPEC_101 Slice 1b) — a terminal-projection division
         gets no default, because NULL means "no data"
      3. the heuristic table

    Annotation semantics:
      ``NONE`` / ``NULL`` (case-insensitive) -> ``None`` (deliberate NULL signal)
      anything else                         -> that literal, stripped
      no annotation                         -> ratio rule, then heuristic table

    ``dialect`` is the sqlglot dialect to parse with. ``warnings``, when given,
    collects a message for a ratio (so the author knows why no default was
    applied) and for a parse failure (so it's never silent). ``metric_label``
    prefixes those messages, e.g. ``"Policy.NumberOfPolicies"``.
    """
    if annotation is not None:
        value = annotation.strip()
        if value.upper() in _NULL_ANNOTATION_VALUES:
            return None
        return value

    m = COMBINER_DEFAULT_ANNOTATION_RE.search(metric_sql)
    if m:
        # Raw-text fallback for any caller still handing over an unstripped file.
        # Same NONE guard: never emit the literal 'NONE' into COALESCE.
        value = m.group(1).strip()
        if value.upper() in _NULL_ANNOTATION_VALUES:
            return None
        return value

    # SPEC_101 Slice 1b — a ratio gets no default. Checked BEFORE the heuristic
    # table, because `SUM(a) / SUM(b)` matches the SUM heuristic and would
    # otherwise be zero-filled.
    has_division, parse_error = _terminal_projection_has_division(metric_sql, dialect)
    if parse_error is not None:
        # Keep today's behavior (fall through to the heuristics) but say so.
        if warnings is not None:
            label = f"{metric_label}: " if metric_label else ""
            warnings.append(
                f"{label}could not parse metric SQL to check for a ratio "
                f"({parse_error}) — the default came from the heuristic table. "
                f"Add '-- COMBINER_DEFAULT: <value>' to pin it."
            )
    elif has_division:
        if warnings is not None:
            label = f"{metric_label}: " if metric_label else ""
            warnings.append(
                f"{label}ratio — no default applied (NULL means 'no data'). "
                f"Add '-- COMBINER_DEFAULT: 0' if a zero is correct."
            )
        return None

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
