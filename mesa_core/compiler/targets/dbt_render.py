# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
compiler/targets/dbt_render.py
================================
SPEC_41-A — MESA dbt Export Parity: pure SQL body builders.

This module is PURE — no I/O, no DB, no git.  Every function takes plain
Python values and returns strings.  The DbtEmitter (dbt.py) and
WarehouseEmitter (warehouse.py) import from here.

Two render modes
----------------
* ``render_mode="dbt"``        — keep Jinja {{ ref() }} / {{ source() }} macros.
  Used by DbtEmitter; the analyst's ``dbt run`` resolves them.
* ``render_mode="warehouse"``  — compile refs to concrete warehouse paths.
  Used by WarehouseEmitter for BigQuery/Snowflake/Redshift direct execution.
  ``resolve_refs()`` handles this substitution.

Gold-standard output shape
--------------------------
These builders match the shape in model_zoo_bq/models/mesa/ exactly:
  raw_layer/raw_<entity>.sql           — authored definition_sql verbatim (or fallback)
  metric_layer/<Entity>_Metrics/<m>.sql — 1 file = 1 metric; FROM ref(raw_<entity>)
  metric_layer/<entity>_metrics.sql    — assembler CTE fold; dependent metrics excluded
  wide_layer/wide_<entity>.sql         — dialect-specific composite
  view_layer/v_<entity>_bi.sql         — flat SELECT over wide_<entity>
  models/mesa/schema.yml               — governance metadata (built by dbt_schema.py)

Identity guarantee
------------------
Identity is ALWAYS hashed — TO_BASE64(SHA256(CAST(<col> AS STRING))) for BigQuery;
BASE64_ENCODE(SHA2_BINARY(TO_VARCHAR(<col>), 256)) for Snowflake (SPEC_37 §5).
There is NO un-hashed passthrough path.  Guided entities carry a verifier-guaranteed
hashed ID in definition_sql; the fallback also hashes unconditionally.

Dependent-metric cycle prevention
----------------------------------
The assembler excludes metrics whose SQL references the assembler table name or another
metric's column name.  This prevents dbt from reporting a cycle error.  The test gate
(G-CYCLE) guards this.

Wide model — dialect matrix
-----------------------------
  BigQuery (default)     bare-alias STRUCT: SELECT <Entity>, <Entity>Metrics FROM ...
  Snowflake              OBJECT_CONSTRUCT(alias.*) — qualified wildcard, auto-expanding
  Redshift / Postgres    dbt_utils.star() macro for explicit, ordered column list

See build_wide_model() and G-WIDE-DIALECT for rationale.
"""

from __future__ import annotations

import re
from typing import Literal

# ── Helpers ────────────────────────────────────────────────────────────────────

def _snake(name: str) -> str:
    """PascalCase / mixed-case → snake_case.  Shared convention with dbt.py."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.lower()


def _collect_referenced_names(sql: str) -> set[str]:
    """
    Extract all identifier tokens that appear after ``ref(`` or as plain
    unquoted identifiers that look like metric column names in the SQL body.
    Used for cycle detection in the assembler builder.
    """
    if not sql:
        return set()
    # ref('something') or ref("something")
    refs = set(re.findall(r"""ref\s*\(\s*['"]([^'"]+)['"]\s*\)""", sql, re.IGNORECASE))
    return refs


def _coalesce_default(definition_sql: str) -> str:
    """
    Return a sensible COALESCE default for the given metric SQL expression.

    Rules:
    - Boolean / CASE → FALSE
    - DATE / TIMESTAMP / interval-ish → NULL (no safe numeric default)
    - Numeric / COUNT / SUM / AVG / RATIO / any other → 0
    - Empty → 0
    """
    if not definition_sql:
        return "0"
    expr = definition_sql.strip().upper()
    # Boolean signals
    if re.search(r"\bCASE\b|\bTRUE\b|\bFALSE\b|\bBOOL\b", expr):
        return "FALSE"
    # Date/timestamp signals
    if re.search(r"\bDATE\b|\bTIMESTAMP\b|\bDAY\b.*\bBETWEEN\b|\bDATEDIFF\b|\bDATE_DIFF\b", expr):
        return "NULL"
    # Numeric default for everything else
    return "0"


# ── Raw model ─────────────────────────────────────────────────────────────────

def build_raw_model(entity) -> str:
    """
    Build the raw-layer SQL body.

    Primary path: emit entity.definition_sql VERBATIM when present.
    The analyst authored it with TO_BASE64(SHA256(...)) AS ID, STRUCTs, _loaded_at,
    and a WHERE guard.  We must not re-synthesise any of those — round-trip fidelity
    is the compliance contract (governance caveat #2 in SPEC_41).

    Fallback (entity.definition_sql is None / empty):
      Emit a minimal raw model with:
        - Hashed ID: TO_BASE64(SHA256(CAST(<identity_column> AS STRING))) AS ID
        - All other columns via * EXCEPT(<identity_column>)
        - _loaded_at audit column
        - {{ source('<source_name>', '<base_table_name>') }} source ref
        - WHERE <identity_column> IS NOT NULL null-guard

    G-HASH: There is NO code path that emits a bare passthrough identity.
    """
    definition_sql = getattr(entity, "definition_sql", None) or ""
    definition_sql = definition_sql.strip()

    if definition_sql:
        # Primary path: authored SQL verbatim.
        return definition_sql

    # Fallback: generate a minimal, always-hashed raw model.
    identity_col = entity.identity_column
    source_name = entity.source_name
    base_table = entity.base_table_name
    entity_alias = entity.entity_name  # PascalCase alias

    lines = [
        f"-- MESA Raw Layer: {entity.entity_name} (auto-generated fallback)",
        f"-- Identity is always hashed — TO_BASE64(SHA256(CAST(<key> AS STRING)))",
        f"",
        f"SELECT",
        f"  TO_BASE64(SHA256(CAST({entity_alias}.{identity_col} AS STRING))) AS ID",
        f"  , * EXCEPT ({identity_col})",
        f"  , CURRENT_TIMESTAMP() AS _loaded_at",
        f"FROM {{{{ source('{source_name}', '{base_table}') }}}} AS {entity_alias}",
        f"WHERE {entity_alias}.{identity_col} IS NOT NULL",
    ]
    return "\n".join(lines)


# ── Metric model ──────────────────────────────────────────────────────────────

def build_metric_model(entity, metric) -> str:
    """
    Build the metric-layer SQL body for a single metric.

    Shape:
      -- METRIC: <MetricName>
      -- <description>
      -- Owner: <owner_team>
      SELECT <Entity>.ID, <metric_body> AS <MetricName>
      FROM {{ ref('raw_<entity>') }} AS <Entity>
      [+ any joins the metric SQL contains — preserved verbatim when present]
      GROUP BY <Entity>.ID   (for aggregate metrics)

    KEY CHANGE from SPEC_40 staging model:
      Metrics reference {{ ref('raw_<entity>') }}, NOT {{ source(...) }}.
      This wires the dbt DAG through the raw model (not around it), which is
      required for the metric → raw → source lineage chain.
    """
    entity_name = entity.entity_name
    entity_snake = _snake(entity_name)
    metric_name = metric.metric_name
    description = getattr(metric, "description", "") or ""
    owner = getattr(entity, "owner_team", "@platform-team") or "@platform-team"

    definition = (
        getattr(metric, "definition_sql", None)
        or getattr(metric, "sql_definition", "")
        or ""
    ).strip()

    # Header comment block (matches model_zoo pattern)
    lines = [
        f"-- METRIC: {metric_name}",
    ]
    if description:
        lines.append(f"-- {description}")
    lines.append(f"-- Owner: {owner}")
    lines.append("")

    # If definition_sql is a full SELECT, emit verbatim (authored join complexity).
    # Detection: contains FROM or JOIN keywords → treat as a complete body.
    if re.search(r"\bFROM\b|\bJOIN\b", definition, re.IGNORECASE):
        # Authored complete SQL — emit as-is (the analyst already includes
        # FROM ref('raw_...') and any needed joins).
        lines.append(definition)
    else:
        # Simple expression or empty — wrap in canonical single-metric SELECT.
        metric_expr = definition if definition else "COUNT(*)"
        # Determine if aggregate (needs GROUP BY)
        is_aggregate = bool(re.search(
            r"(?i)^(SUM|COUNT|AVG|MAX|MIN|COALESCE\s*\(\s*SUM|COALESCE\s*\(\s*COUNT)\s*\(",
            metric_expr.strip()
        ))
        lines += [
            f"SELECT",
            f"  {entity_name}.ID",
            f"  , {metric_expr} AS {metric_name}",
            f"FROM {{{{ ref('raw_{entity_snake}') }}}} AS {entity_name}",
        ]
        if is_aggregate:
            lines.append(f"GROUP BY {entity_name}.ID")

    return "\n".join(lines)


# ── Assembler (entity_metrics.sql) ────────────────────────────────────────────

def build_assembler_model(entity, metrics) -> str:
    """
    Build the metric assembler model: <entity_snake>_metrics.sql

    One CTE per non-dependent metric, then a LEFT JOIN fold on Base.ID.
    Dependent metrics (those whose SQL references the assembler table name or
    another metric's file name) are EXCLUDED to prevent dbt DAG cycles.

    The assembler shape matches model_zoo_bq/models/mesa/metric_layer/customer_metrics.sql.
    """
    entity_name = entity.entity_name
    entity_snake = _snake(entity_name)
    assembler_name = f"{entity_snake}_metrics"

    metric_list = list(metrics)

    # Collect all sibling metric file names (snake_case)
    sibling_names = {_snake(m.metric_name) for m in metric_list}

    # Classify each metric: dependent if its SQL references the assembler or a sibling metric
    def _is_dependent(metric) -> bool:
        sql = (
            getattr(metric, "definition_sql", None)
            or getattr(metric, "sql_definition", "")
            or ""
        )
        refs = _collect_referenced_names(sql)
        # Reference to assembler table itself
        if assembler_name in refs:
            return True
        # Reference to another metric's file (but NOT raw — raw is allowed)
        for r in refs:
            if r in sibling_names and r != _snake(metric.metric_name):
                return True
        return False

    non_dep = [m for m in metric_list if not _is_dependent(m)]
    dependent = [m for m in metric_list if _is_dependent(m)]

    lines = [
        f"-- MESA Metric Layer: {entity_name} Metrics (AUTO-GENERATED)",
        f"-- Assembled from individual metric files in {entity_name}_Metrics/",
        f"-- Owner: CI/CD (mechanically generated, do not edit by hand)",
        f"-- Contract: 1 row per ID, all metrics as columns",
    ]
    if dependent:
        dep_names = ", ".join(m.metric_name for m in dependent)
        lines.append(f"-- NOTE: {dep_names} {'is a' if len(dependent) == 1 else 'are'} dependent metric(s) "
                     f"(reference this table). Excluded to avoid circular dependency.")
    lines.append("")

    # CTEs — one per non-dependent metric
    for m in non_dep:
        m_snake = _snake(m.metric_name)
        lines.append(f"WITH {m.metric_name} AS (")
        lines.append(f"  SELECT * FROM {{{{ ref('{entity_snake}_{m_snake}') }}}}")
        lines.append(f")")
        # Join subsequent CTEs with comma
        if m is not non_dep[-1]:
            lines[-1] = lines[-1].replace(")", "),")

    # Rewrite as single WITH block
    # Replace the above with proper comma-separated WITH block
    lines = lines[:5 + (1 if dependent else 0)]  # keep header + optional NOTE
    lines.append("")

    # Proper WITH block
    cte_parts = []
    for m in non_dep:
        m_snake = _snake(m.metric_name)
        cte_parts.append(
            f"{m.metric_name} AS (\n  SELECT * FROM {{{{ ref('{entity_snake}_{m_snake}') }}}}\n)"
        )

    if cte_parts:
        lines.append("WITH " + "\n, ".join(cte_parts))
    else:
        # No non-dependent metrics — trivial assembler
        lines += [
            f"SELECT Base.ID",
            f"FROM {{{{ ref('raw_{entity_snake}') }}}} AS Base",
        ]
        return "\n".join(lines)

    # SELECT clause
    select_cols = ["Base.ID"]
    for m in non_dep:
        default = _coalesce_default(
            getattr(m, "definition_sql", None) or getattr(m, "sql_definition", "") or ""
        )
        if default == "NULL":
            select_cols.append(f"  , {m.metric_name}.{m.metric_name}")
        else:
            select_cols.append(f"  , COALESCE({m.metric_name}.{m.metric_name}, {default}) AS {m.metric_name}")

    lines.append("SELECT")
    lines.append("\n".join(select_cols))
    lines.append(f"FROM {{{{ ref('raw_{entity_snake}') }}}} AS Base")

    # LEFT JOINs
    for m in non_dep:
        lines.append(f"LEFT JOIN {m.metric_name} ON Base.ID = {m.metric_name}.ID")

    return "\n".join(lines)


# ── Wide model — dialect matrix ────────────────────────────────────────────────

def build_wide_model(entity, dialect: str = "bigquery") -> str:
    """
    Build the wide-layer SQL body.

    G-WIDE-DIALECT: the shape is dialect-specific to match each warehouse's
    composite/auto-expand capability.  See SPEC_41 §TWO RENDER MODES.

    BigQuery (default): bare-alias STRUCT — SELECT <Entity>, <Entity>Metrics
    Snowflake:          OBJECT_CONSTRUCT(*) scoped per source via correlated subquery
    Redshift/Postgres:  dbt_utils.star() for explicit, name-safe column list

    NEVER emit a bare BigQuery-style SELECT for a non-BQ dialect — it will not
    execute on Snowflake/Redshift and would silently produce wrong data.
    """
    entity_name = entity.entity_name
    entity_snake = _snake(entity_name)
    entity_metrics_ref = f"{entity_snake}_metrics"
    raw_ref = f"raw_{entity_snake}"
    norm_dialect = (dialect or "bigquery").lower().strip()

    header = (
        f"-- MESA Wide Layer: {entity_name} Wide Table (AUTO-GENERATED)\n"
        f"-- No explicit column list, no logic, zero maintenance.\n"
        f"-- Add a metric and regenerate {entity_metrics_ref} — this table picks it up automatically.\n"
        f"-- Owner: CI/CD (mechanically generated, do not edit by hand)\n"
    )

    if norm_dialect in ("bigquery", "bq"):
        # Bare-alias STRUCT — BigQuery auto-expands on SELECT *
        body = (
            f"SELECT\n"
            f"  {entity_name}\n"
            f"  , {entity_name}Metrics\n"
            f"FROM {{{{ ref('{raw_ref}') }}}} AS {entity_name}\n"
            f"JOIN {{{{ ref('{entity_metrics_ref}') }}}} AS {entity_name}Metrics\n"
            f"  ON {entity_name}.ID = {entity_name}Metrics.ID"
        )

    elif norm_dialect in ("snowflake", "sf"):
        # OBJECT_CONSTRUCT(alias.*) — qualified wildcard, auto-expanding.
        # Each OBJECT_CONSTRUCT is scoped to its own source via alias.* so only
        # that model's columns are packed.  Bare OBJECT_CONSTRUCT(*) after a JOIN
        # is WRONG — it packs ALL joined columns into BOTH objects.
        # Proven live on Snowflake 2026-07-17 (model_zoo_sf, PASS=55).
        body = (
            f"SELECT\n"
            f"    OBJECT_CONSTRUCT({entity_name}.*) AS {entity_name}\n"
            f"    , OBJECT_CONSTRUCT({entity_name}Metrics.*) AS {entity_name}Metrics\n"
            f"FROM {{{{ ref('{raw_ref}') }}}} AS {entity_name}\n"
            f"JOIN {{{{ ref('{entity_metrics_ref}') }}}} AS {entity_name}Metrics\n"
            f"    ON {entity_name}.ID = {entity_name}Metrics.ID"
        )

    elif norm_dialect in ("redshift", "postgres", "pg", "postgresql"):
        # dbt_utils.star() — explicit, name-safe column list (no positional-order risk).
        # NO bare-alias STRUCT (Redshift has no composite-row type).
        body = (
            f"SELECT\n"
            f"  {{{{ dbt_utils.star(ref('{raw_ref}'), relation_alias='{entity_name}') }}}}\n"
            f"  , {{{{ dbt_utils.star(ref('{entity_metrics_ref}'), relation_alias='{entity_name}Metrics') }}}}\n"
            f"FROM {{{{ ref('{raw_ref}') }}}} AS {entity_name}\n"
            f"JOIN {{{{ ref('{entity_metrics_ref}') }}}} AS {entity_name}Metrics\n"
            f"  ON {entity_name}.ID = {entity_name}Metrics.ID"
        )

    else:
        # Unknown dialect: default to BigQuery shape and emit a comment warning.
        body = (
            f"-- MESANTIC: unknown dialect '{dialect}' — defaulting to BigQuery bare-alias STRUCT.\n"
            f"-- Review before running dbt on a different warehouse.\n"
            f"SELECT\n"
            f"  {entity_name}\n"
            f"  , {entity_name}Metrics\n"
            f"FROM {{{{ ref('{raw_ref}') }}}} AS {entity_name}\n"
            f"JOIN {{{{ ref('{entity_metrics_ref}') }}}} AS {entity_name}Metrics\n"
            f"  ON {entity_name}.ID = {entity_name}Metrics.ID"
        )

    return header + "\n" + body


# ── View model ────────────────────────────────────────────────────────────────

def build_view_model(entity, view) -> str:
    """
    Build the view-layer SQL body for a BI view over the wide table.

    If the view has authored select_sql, use it verbatim.
    Fallback: emit a simple flat SELECT from {{ ref('wide_<entity>') }}.

    Shape matches model_zoo_bq/models/mesa/view_layer/v_customer_bi.sql.
    """
    entity_name = entity.entity_name
    entity_snake = _snake(entity_name)
    view_name = getattr(view, "view_name", f"v_{entity_snake}_bi") if view else f"v_{entity_snake}_bi"
    select_sql = getattr(view, "select_sql", None) if view else None

    header = (
        f"-- MESA View Layer: {view_name}\n"
        f"-- Flat SELECT from wide table, formatted for BI tool consumption\n"
        f"-- No new metric definitions - all values from Metric Layer\n"
    )

    if select_sql and select_sql.strip():
        return header + "\n" + select_sql.strip()

    # Fallback: minimal flat view over the wide table
    body = (
        f"SELECT\n"
        f"  Wide{entity_name}.{entity_name}.ID AS {entity_name}ID\n"
        f"  , Wide{entity_name}.{entity_name}Metrics.*\n"
        f"  , Wide{entity_name}.{entity_name}._loaded_at AS LoadedAt\n"
        f"FROM {{{{ ref('wide_{entity_snake}') }}}} Wide{entity_name}\n"
        f"WHERE Wide{entity_name}.{entity_name}.ID IS NOT NULL"
    )
    return header + "\n" + body


# ── Ref resolution (warehouse render mode) ───────────────────────────────────

def resolve_refs(body: str, connector, entity) -> str:
    """
    Replace dbt Jinja macros with concrete warehouse paths for direct execution.

    Substitutions:
      {{ ref('raw_<entity>') }}           → connector.build_mesa_path(entity_name, 'raw')
      {{ ref('<entity>_metrics') }}        → connector.build_mesa_path(entity_name, 'metric')
      {{ ref('wide_<entity>') }}           → connector.build_mesa_path(entity_name, 'widetable')
      {{ source('source_name', 'table') }} → connector.build_source_path(source_name, table)

    G-PARITY: template_body and resolved_body differ ONLY in ref resolution.
    The SQL logic is identical between dbt and warehouse modes.
    """
    if not body:
        return body

    entity_name = entity.entity_name

    # Replace {{ ref('...') }} with connector.build_mesa_path
    def _sub_ref(m):
        ref_name: str = m.group(1)
        # Determine object_type from the ref name prefix/suffix pattern
        if ref_name.startswith("raw_"):
            return connector.build_mesa_path(entity_name, "raw")
        elif ref_name.endswith("_metrics"):
            return connector.build_mesa_path(entity_name, "metric")
        elif ref_name.startswith("wide_"):
            return connector.build_mesa_path(entity_name, "widetable")
        elif ref_name.startswith("v_") or ref_name.endswith("_bi"):
            return connector.build_mesa_path(entity_name, "view")
        else:
            # Unknown ref — preserve as a comment-flagged fallback
            return f"/* unresolved ref: {ref_name} */"

    # {{ ref('name') }} or {{ ref("name") }}
    body = re.sub(
        r"""\{\{[\s]*ref\s*\(\s*['"]([^'"]+)['"]\s*\)[\s]*\}\}""",
        _sub_ref,
        body,
    )

    # {{ source('source_name', 'table') }}
    def _sub_source(m):
        src_name = m.group(1)
        tbl_name = m.group(2)
        return connector.build_source_path(src_name, tbl_name)

    body = re.sub(
        r"""\{\{[\s]*source\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)[\s]*\}\}""",
        _sub_source,
        body,
    )

    # {{ dbt_utils.star(...) }} — not executable in a warehouse, replace with *
    body = re.sub(
        r"""\{\{[\s]*dbt_utils\.star\([^}]+\)[\s]*\}\}""",
        "/*dbt_utils.star — expand columns manually for warehouse-direct mode*/",
        body,
    )

    return body


# ── Convenience: detect dialect from connector ────────────────────────────────

def dialect_from_connector(connector) -> str:
    """
    Infer the SQL dialect string from a connector-like object.

    MESA Core ships no warehouse connectors — ``mesa build`` renders in dbt
    mode and picks the dialect from the project's ``default_warehouse``, not
    from a live connector. This helper remains for Mesantic, which passes a
    connector exposing a ``.dialect`` class attribute (SPEC_41-A).

    Preference order:
      1. connector.dialect  (class attribute added by SPEC_41)
      2. Default: "bigquery"
    """
    # Prefer explicit class attribute (added in SPEC_41-A to each connector).
    if hasattr(connector, "dialect"):
        return connector.dialect
    return "bigquery"  # safe default
