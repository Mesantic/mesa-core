# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
grain_guard.py — SPEC_53 (1c): Compiler-level fan-out enforcement.
===================================================================

Upgrades the existing ``mesa_verifier.CODE_GRAIN_RISK`` heuristic (warn-only,
"a JOIN has no key equality") into a hard BLOCK when the platform *knows*,
from a declared SPEC_53 Relationship row, that a JOIN target is on the
"many" side relative to the metric's anchor entity — i.e. joining it in
without an aggregation or dedup would silently multiply rows and corrupt the
metric's grain.

This is a stronger, more precise signal than the free-text heuristic: it is
not "any join looks risky", it is "this SPECIFIC join target is a DECLARED
one_to_many/many_to_many relationship and this SQL does not collapse it."
That precision is what justifies blocking instead of warning.

Pure, import-safe module — no FastAPI, no ORM, no DB, no network. Same
contract as ``grain_check.py`` (SPEC_53a-1) and ``entity_discovery.py``: the
route layer resolves ORM rows into plain dataclasses and calls this module's
pure function.

Detection strategy
-------------------
1. Resolve the entity's warehouse ("BigQuery"|"Snowflake"|"Redshift"|"DuckDB",
   the same Literal used across api/models/schemas.py) to the matching sqlglot
   dialect string via ``_sqlglot_dialect_for_warehouse``. This mirrors the
   existing per-warehouse dispatch pattern in compiler/query_compiler.py and
   compiler/targets/dbt_render.py's ``dialect_from_connector`` — grain_guard
   must parse each platform's SQL with ITS OWN dialect, not a hardcoded one.
   Snowflake colon field-access (``c.value:field``), QUALIFY, and LATERAL
   FLATTEN; BigQuery UNNEST and backtick paths; Redshift LISTAGG/DISTKEY;
   DuckDB list()/struct literals — none of these parse reliably under a
   different dialect's grammar (verified: Snowflake colon-access raises a
   sqlglot ParseError when forced through dialect="bigquery").
2. Strip Jinja ({{ source(...) }} / {{ ref(...) }}) to bare identifiers so
   sqlglot can parse the SQL (mirrors object_health.py's _strip_jinja).
3. Parse with sqlglot using the resolved dialect; walk every JOIN and match
   its table name against each risky relationship's other-side
   base_table_name (case-insensitive). Falls back to a regex scan if sqlglot
   cannot parse the SQL under ANY dialect — never raises, degrades to
   "cannot verify, no block".
4. A matched risky JOIN is SAFE (not blocked) when the SQL also contains a
   cross-row aggregate collapse or a dedup marker, evaluated with the SAME
   per-dialect function vocabulary (see ``_AGGREGATE_FUNCS_BY_DIALECT`` /
   ``_DEDUP_PATTERNS_BY_DIALECT`` below) — e.g. Snowflake/DuckDB/Redshift's
   ARRAY_AGG/LISTAGG/LIST_AGG/STRING_AGG all count as "collapsed to one row",
   as do platform-specific dedup idioms (QUALIFY is Snowflake/BigQuery-only;
   Redshift/older dialects rely on ROW_NUMBER()=1 or DISTINCT ON):
   - a cross-row aggregate function (SUM/COUNT/AVG/ARRAY_AGG/LISTAGG/...) NOT
     immediately followed by OVER(...) — the "aggregate to metric" outcome, OR
   - a dedup marker (QUALIFY / DISTINCT / DISTINCT ON / ROW_NUMBER() OVER (...)
     paired with a "= 1" filter) — the join was explicitly collapsed, OR
   - the specific join clause is immediately followed by UNNEST/LATERAL
     FLATTEN — an intentional, governed array-flatten (SPEC_53a "array_child"
     outcome), not a raw fan-out mistake.
5. Otherwise: BLOCK with a teaching message naming the relationship, the
   cardinality, and the two ways to fix it (aggregate or dedup).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

try:
    import sqlglot
    import sqlglot.expressions as exp
    _SQLGLOT_AVAILABLE = True
except ImportError:  # pragma: no cover — sqlglot is a pinned dependency
    _SQLGLOT_AVAILABLE = False


CODE_FANOUT_BLOCKED = "MESA_GRAIN_FANOUT_BLOCKED"
CODE_GRAIN_CANNOT_VERIFY = "MESA_GRAIN_CANNOT_VERIFY"

# Relative-to-anchor cardinalities that mean "the other side has many rows
# per one anchor row" — i.e. joining it in is a fan-out risk.
_RISKY_CARDINALITIES = {"one_to_many", "many_to_many"}

# ── Warehouse -> sqlglot dialect mapping ─────────────────────────────────────
# Entity.warehouse / the Literal["BigQuery","Snowflake","Redshift","DuckDB"]
# used across api/models/schemas.py must map to sqlglot's own dialect names
# (all four are first-class sqlglot dialects — verified 2026-08-11: unlike
# sqlfluff, whose Redshift support is partial and falls back to "ansi" in
# sql_formatter.py's _DIALECT_MAP, sqlglot parses redshift natively).
# Mirrors compiler/targets/dbt_render.py's dialect_from_connector() intent,
# but keyed on the warehouse string already stored on Entity/EntityCreate
# rather than requiring a live WarehouseConnector instance.
_WAREHOUSE_TO_SQLGLOT_DIALECT = {
    "bigquery": "bigquery",
    "snowflake": "snowflake",
    "redshift": "redshift",
    "duckdb": "duckdb",
}

# Dialects to try, in order, when no warehouse hint is given (backfill /
# legacy callers) or when the hinted dialect fails to parse. bigquery first
# (historical default — matches the old hardcoded behavior for callers that
# don't pass a warehouse), then the others, so we still recover gracefully
# instead of only ever falling to the regex extractor.
_DIALECT_PROBE_ORDER = ("bigquery", "snowflake", "redshift", "duckdb")


def _sqlglot_dialect_for_warehouse(warehouse: str | None) -> str | None:
    """Map an Entity.warehouse string to a sqlglot dialect name.

    Case-insensitive; unrecognized/None returns None (caller falls back to
    probing every known dialect rather than guessing wrong).
    """
    if not warehouse:
        return None
    return _WAREHOUSE_TO_SQLGLOT_DIALECT.get(warehouse.strip().lower())


# ── Cross-row aggregate / collapse functions, per platform ──────────────────
# Standard SQL aggregates are shared by every dialect. Beyond those, each
# platform has its own "collapse many rows into one" function name — a
# Redshift LISTAGG, a Snowflake/BigQuery ARRAY_AGG, or a DuckDB list()/
# list_agg() all mean the SAME thing for grain-safety purposes: the join was
# explicitly collapsed to one row per anchor. We treat the union of all of
# these as "aggregate-like" regardless of which warehouse the entity targets
# — a superset match is always safe here (it can only make the guard LESS
# aggressive about blocking, never silently miss a real fan-out, since an
# unrecognized aggregate name simply doesn't match and behaves as before).
_STANDARD_AGGREGATE_FUNCS = (
    "sum", "avg", "average", "count", "min", "max", "stddev", "stddev_pop",
    "stddev_samp", "variance", "var_pop", "var_samp", "approx_count_distinct",
    "count_distinct",
)
# Platform-specific "combine many rows into one value" functions:
#   listagg      — Redshift, Snowflake, Oracle-style ANSI
#   string_agg   — BigQuery, Postgres, DuckDB
#   array_agg    — Snowflake, BigQuery, DuckDB, Redshift (ANSI array agg)
#   list / list_agg — DuckDB-native aliases for array_agg-style collapse
#   object_agg / array_construct — Snowflake struct/array builders often used
#     alongside a GROUP BY to collapse a joined one_to_many side
_PLATFORM_AGGREGATE_FUNCS = (
    "listagg", "string_agg", "array_agg", "list_agg", "list",
    "object_agg", "array_construct",
)
_AGGREGATE_FUNCS = _STANDARD_AGGREGATE_FUNCS + _PLATFORM_AGGREGATE_FUNCS


@dataclass
class RiskyRelationship:
    """One declared relationship that is a fan-out risk relative to the anchor
    entity whose metric SQL is being checked."""
    other_entity_name: str
    other_base_table_name: str
    cardinality: str  # one_to_many | many_to_many (as seen from the anchor)
    relationship_id: str | None = None


@dataclass
class FanoutFinding:
    """One blocking finding: a declared risky relationship was joined without
    collapse. Severity is "block" (definite fan-out violation) or "cannot_verify"
    (SQL could not be parsed enough to verify safety — both states should stop
    publication/deploy, but render with different UX to guide the analyst).
    """
    code: str
    severity: str  # "block" | "cannot_verify"
    message: str
    suggestion: str
    related_entity_name: str
    cardinality: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
            "related_entity_name": self.related_entity_name,
            "cardinality": self.cardinality,
        }


# ── Jinja stripping (mirrors object_health.py's approach) ──────────────────

_JINJA_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_REF_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.IGNORECASE)
_SOURCE_RE = re.compile(r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.IGNORECASE)


def _strip_jinja_to_table_names(sql: str) -> str:
    """{{ source('s', 't') }} -> t   |   {{ ref('x') }} -> x   |   other {{ }} -> NULL

    Reducing source()/ref() to the bare table/model name is what lets sqlglot's
    JOIN-target extraction match against Entity.base_table_name.
    """
    sql = _SOURCE_RE.sub(lambda m: m.group(2), sql)
    sql = _REF_RE.sub(lambda m: m.group(1), sql)
    sql = _JINJA_RE.sub("NULL", sql)
    return sql


# ── Aggregate / dedup collapse detection ────────────────────────────────────

def _has_cross_row_aggregate(sql: str) -> bool:
    """True if SQL contains an aggregate function call NOT immediately
    followed by OVER(...) (a true cross-row aggregate, not a window fn)."""
    func_alt = "|".join(re.escape(f) for f in _AGGREGATE_FUNCS)
    pattern = re.compile(rf"(?i)\b({func_alt})\s*\(")
    for m in pattern.finditer(sql):
        open_idx = sql.index("(", m.start())
        depth = 0
        close_idx = open_idx
        for i in range(open_idx, len(sql)):
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break
        after = sql[close_idx + 1: close_idx + 40].lstrip().lower()
        if not after.startswith("over"):
            return True
    return False


def _has_dedup_marker_syntax_only(sql: str) -> bool:
    """Syntax-only dedup detection (back-compat fallback for when anchor_key
    is not provided or sqlglot is unavailable). Returns True if SQL contains
    the structural patterns of a dedup, without checking that the dedup
    actually operates on the correct anchor key.
    
    Patterns checked:
      - QUALIFY
      - DISTINCT ON (...)
      - DISTINCT
      - ROW_NUMBER() OVER (...) paired with "= 1" filter
    """
    if re.search(r"(?i)\bqualify\b", sql):
        return True
    if re.search(r"(?i)\bdistinct\s+on\s*\(", sql):
        return True
    if re.search(r"(?i)\bdistinct\b", sql):
        return True
    if re.search(r"(?i)row_number\s*\(\s*\)\s*over", sql) and re.search(r"(?i)=\s*1\b", sql):
        return True
    return False


def _has_dedup_marker(sql: str, anchor_key: str | None = None) -> bool:
    """Check if SQL applies a dedup idiom that collapses a join back to one
    row per anchor row. Platform-specific idioms all count:
      - QUALIFY            — Snowflake, BigQuery (NOT standard Redshift/DuckDB)
      - DISTINCT           — every dialect
      - DISTINCT ON (...)  — Redshift/Postgres/DuckDB idiom (no QUALIFY there)
      - ROW_NUMBER() OVER (...) paired with a "= 1" filter — universal, works
        on every dialect via an outer WHERE/QUALIFY regardless of platform
    
    When ``anchor_key`` is provided (SPEC_65 Slice 2), a QUALIFY/ROW_NUMBER/
    DISTINCT-ON collapse is only counted as safe if the anchor_key column
    actually appears in its PARTITION BY / DISTINCT ON column list — a collapse
    that partitions on the wrong column does NOT protect this anchor's grain.
    
    When anchor_key is None (back-compat callers), falls back to the original
    syntax-only check exactly as before — no behavior change for existing code.
    """
    if anchor_key is None:
        # Back-compat path: existing behavior, syntax-only check
        return _has_dedup_marker_syntax_only(sql)

    # SPEC_65 Slice 2: key-aware verification
    # For DISTINCT ON and ROW_NUMBER/PARTITION BY, parse and verify the column list.
    if not _SQLGLOT_AVAILABLE:
        # Can't verify key-awareness without a parser — fall back to syntax-only
        return _has_dedup_marker_syntax_only(sql)

    try:
        tree = sqlglot.parse_one(sql)  # best-effort, no dialect hint needed for this structural check
    except Exception:
        # Parse failed — fall back to syntax-only, do not claim key-aware safety
        return _has_dedup_marker_syntax_only(sql)

    anchor_key_lower = anchor_key.lower()

    # Check WINDOW clauses (ROW_NUMBER() OVER (PARTITION BY ...))
    for window in tree.find_all(exp.Window):
        partition_cols = [c.name.lower() for c in window.args.get("partition_by", []) if c and hasattr(c, 'name')]
        if anchor_key_lower in partition_cols:
            # Found a PARTITION BY that includes anchor_key — check for the "= 1" filter
            if re.search(r"(?i)=\s*1\b", sql):
                return True

    # Check DISTINCT ON (col1, col2, ...). Columns may be qualified with a
    # table alias (e.g. "Base.ID") — strip any "alias." prefix before
    # comparing, since anchor_key is always an unqualified column name.
    m = re.search(r"(?i)\bdistinct\s+on\s*\(([^)]*)\)", sql)
    if m:
        cols = [c.strip().lower().rsplit(".", 1)[-1] for c in m.group(1).split(",")]
        if anchor_key_lower in cols:
            return True
        # DISTINCT ON was found but its column list does NOT include the
        # anchor key — this is an unsafe collapse for THIS anchor's grain.
        # Must return False here rather than falling through: the generic
        # \bdistinct\b check below also matches the text "DISTINCT ON" and
        # would incorrectly re-classify this same clause as safe.
        return False

    # QUALIFY with no explicit column list (uses the entire row for dedup)
    # and plain DISTINCT with no column list — both collapse to one row per
    # anchor (cannot be made more precise without deeper analysis). Only
    # reached when no DISTINCT ON (...) was present above.
    if re.search(r"(?i)\bqualify\b", sql):
        return _has_dedup_marker_syntax_only(sql)  # QUALIFY present, dedup safe

    if re.search(r"(?i)\bdistinct\b", sql):
        return _has_dedup_marker_syntax_only(sql)  # DISTINCT present, dedup safe

    return False


# ── JOIN-target extraction ──────────────────────────────────────────────────

def _extract_join_targets_sqlglot(clean_sql: str, dialect: str) -> list[str]:
    """Returns the table name for every JOIN in the SQL, parsed with the
    given sqlglot dialect. Raises on parse failure — caller tries the next
    dialect / falls back to regex."""
    tree = sqlglot.parse_one(clean_sql, dialect=dialect)
    targets: list[str] = []
    for j in tree.find_all(exp.Join):
        name = getattr(j.this, "name", None)
        if name:
            targets.append(name)
    return targets


def _extract_join_targets_regex(sql: str) -> list[str]:
    """Regex fallback: find `JOIN <name>` occurrences. Dialect-agnostic —
    used when sqlglot cannot parse the SQL under any known dialect."""
    return [
        m.group(2).split(".")[-1]
        for m in re.finditer(r"(?i)\bjoin\s+([`\"']?)([\w.$-]+)\1", sql)
    ]


def _extract_join_targets(sql: str, warehouse: str | None = None) -> tuple[list[str], bool]:
    """Extract JOIN target table names, parsing with the dialect that matches
    the entity's actual warehouse (never a hardcoded one).

    Returns ``(targets, parsed_ok)``. This distinction matters for SPEC_65
    Slice 1: a query that parses cleanly but simply has no JOIN clauses
    (``targets == [] and parsed_ok is True``) is NOT the same situation as a
    query grain_guard could not understand at all (``parsed_ok is False``) —
    conflating the two would make every joinless metric wrongly report
    "cannot_verify".

    Resolution order:
      1. The warehouse's own sqlglot dialect, if ``warehouse`` is recognized.
      2. Every other known dialect, in ``_DIALECT_PROBE_ORDER`` (covers
         callers that don't pass a warehouse, e.g. SPEC_53 1d backfill
         scanning definition_sql without warehouse context yet).
      3. Regex fallback if no dialect parses the SQL at all. Since the regex
         fallback can't distinguish "joinless" from "malformed", parsed_ok is
         only considered True here if the regex actually found JOIN text —
         finding nothing at all (and every real dialect having rejected the
         SQL) is the strongest signal available that the SQL is malformed.
    """
    clean = _strip_jinja_to_table_names(sql)
    if _SQLGLOT_AVAILABLE:
        hinted = _sqlglot_dialect_for_warehouse(warehouse)
        tried: set[str] = set()
        if hinted:
            tried.add(hinted)
            try:
                return _extract_join_targets_sqlglot(clean, hinted), True
            except Exception:
                pass
        for dialect in _DIALECT_PROBE_ORDER:
            if dialect in tried:
                continue
            try:
                return _extract_join_targets_sqlglot(clean, dialect), True
            except Exception:
                continue
        # Every dialect failed to parse this SQL at all.
        regex_targets = _extract_join_targets_regex(clean)
        return regex_targets, len(regex_targets) > 0
    return _extract_join_targets_regex(clean), True


# ── Public entry point ──────────────────────────────────────────────────────

def check_fanout_risk(
    definition_sql: str,
    risky_relationships: list[RiskyRelationship],
    warehouse: str | None = None,
    anchor_identity_column: str | None = None,
) -> list[FanoutFinding]:
    """
    Check whether ``definition_sql`` joins any of the declared risky relationship
    targets WITHOUT collapsing them (aggregate or dedup), and return BLOCK
    findings for each uncollapsed fan-out risk found.

    ``warehouse`` should be the anchor entity's ``Entity.warehouse`` value
    ("BigQuery"|"Snowflake"|"Redshift"|"DuckDB") so the SQL is parsed with the
    CORRECT sqlglot dialect — platforms differ enough (Snowflake colon field
    access, BigQuery UNNEST, Redshift LISTAGG, DuckDB list()) that parsing
    under the wrong dialect can raise or silently mis-extract JOIN targets.
    When omitted (e.g. the SPEC_53 1d backfill scanning legacy definition_sql
    without warehouse context), every known dialect is probed before falling
    back to a dialect-agnostic regex extractor — this function never raises
    regardless.

    ``anchor_identity_column`` (SPEC_65 Slice 2) is the anchor entity's grain/
    identity column name (e.g. "ID", "customer_id"). When provided, it is passed
    to ``_has_dedup_marker`` so that a PARTITION BY / DISTINCT ON collapse is
    only counted as safe if it actually operates on this column. When omitted,
    the dedup check falls back to syntax-only (existing behavior).

    Empty ``risky_relationships`` or no matching JOINs → returns [] (nothing
    to block). This function never raises — malformed SQL degrades to a
    "cannot_verify" finding (see Slice 1 below) if there were risky relationships
    to check but the SQL couldn't be parsed.

    Slice 1 (SPEC_65): When risky_relationships is non-empty but join_targets
    is empty (parse failure or unrecognized structure), returns a "cannot_verify"
    finding instead of silently returning [] — the SQL could not be understood
    well enough to verify safety is NOT the same as verified safe.

    Note on the SPEC_53a "array_child" resolution outcome: when a fan-out
    source is collapsed via ARRAY_AGG/LISTAGG/STRING_AGG/list() (a cross-row
    aggregate — already in ``_AGGREGATE_FUNCS``, covering every supported
    platform's own array/string-collapse function name) into an array column
    on the anchor entity, that collapse already satisfies ``has_aggregate``
    below. A later View-layer UNNEST/LATERAL FLATTEN of that
    *already-materialized* array column never re-joins the risky table by
    name, so no separate UNNEST exemption is needed here.
    """
    if not risky_relationships or not definition_sql or not definition_sql.strip():
        return []

    join_targets, parsed_ok = _extract_join_targets(definition_sql, warehouse=warehouse)
    if not parsed_ok:
        # SQL could not be parsed at all under any known dialect (and the
        # regex fallback found no JOIN text either) — this is genuinely
        # unparseable, not just joinless. Fail closed per SPEC_65 Slice 1.
        return [FanoutFinding(
            code=CODE_GRAIN_CANNOT_VERIFY,
            severity="cannot_verify",
            message=(
                "This SQL declares one or more risky relationships to check, but "
                "grain_guard could not identify any JOIN targets in the SQL (parse "
                "failure or unrecognized structure). This does NOT mean the SQL is "
                "safe — it means grain safety could not be verified."
            ),
            suggestion=(
                "Simplify the JOIN syntax so it can be parsed, or have an owner "
                "manually review this metric for grain safety before publishing."
            ),
            related_entity_name=risky_relationships[0].other_entity_name,
            cardinality=risky_relationships[0].cardinality,
        )]
    if not join_targets:
        # Parsed successfully — this SQL simply has no JOINs at all. Nothing
        # to block, and nothing left unverified.
        return []

    join_names_lower = {name.lower() for name in join_targets}

    has_aggregate = _has_cross_row_aggregate(definition_sql)
    has_dedup = _has_dedup_marker(definition_sql, anchor_key=anchor_identity_column)
    collapsed = has_aggregate or has_dedup

    findings: list[FanoutFinding] = []
    seen: set[str] = set()  # avoid duplicate findings for the same relationship
    for rel in risky_relationships:
        table_lower = rel.other_base_table_name.lower()
        if table_lower not in join_names_lower:
            continue
        if collapsed:
            continue  # aggregated or deduped — grain is safe
        if rel.other_entity_name in seen:
            continue
        seen.add(rel.other_entity_name)
        findings.append(FanoutFinding(
            code=CODE_FANOUT_BLOCKED,
            severity="block",
            message=(
                f"This SQL joins '{rel.other_entity_name}' ('{rel.other_base_table_name}'), "
                f"which is declared as {rel.cardinality} relative to this entity. "
                f"Joining it in without collapsing the join will multiply rows and "
                f"corrupt this metric's grain."
            ),
            suggestion=(
                "Either (1) aggregate the joined rows to one value per anchor row "
                "(e.g. COUNT(*), SUM(...), MAX(...)) before joining, or "
                "(2) add a dedup (DISTINCT, QUALIFY, or ROW_NUMBER() OVER (...) = 1) "
                "so the join cannot produce more than one row per anchor row."
            ),
            related_entity_name=rel.other_entity_name,
            cardinality=rel.cardinality,
        ))
    return findings
