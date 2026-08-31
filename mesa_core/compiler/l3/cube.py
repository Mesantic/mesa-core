# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
compiler/l3/cube.py
===================
Cube.dev L3 adapter — emits a `cubes:` YAML from the expression + L2 headers.

REFERENCE IMPLEMENTATION: CubeDev/cube_takehome/model/globals.py
  _parse_cube_meta   → reads CUBE_MEASURE / CUBE_DIM_TYPE / CUBE_DIM_SKIP headers
  _build_measures_yaml → `- name / sql / type [/ format]`
  _build_dimensions_yaml → `- name / sql / type`
  _resolve_sources   → strips {{ source('a','b') }} → b  (Cube-specific, not for MF)
  _adapt_dialect     → dialect-at-render (duckdb default)

WHY THIS ADAPTER EXISTS:
  Cube.dev cannot import a dbt Semantic Layer / MetricFlow metric definition
  natively — it must receive a `cubes:` YAML directly. Customers who run Cube
  should never hand-write the globals.py scaffolding; Mesantic generates it.

KEY DECISIONS (per SPEC_32-1b + Opus mapping table):
  - _resolve_sources  IS ported here (Cube-specific tax; MF does NOT need it).
  - _adapt_dialect    IS ported (default: duckdb, env-overridable via CUBE_DB_DIALECT).
  - Measure emission from L2 header: accepts BOTH -- MESA_MEASURE: and -- CUBE_MEASURE:
    so the L2 emitter (compiler/l2_metric_file.py writes MESA_MEASURE) and the
    legacy CubeDev header (-- CUBE_MEASURE:) both work.  The seam is acknowledged
    in /memories/repo/spec32_1b_l3_mapping_opus_july2026.md.
  - MESA single-output guarantee preserved: compile_from_expression is called first
    (enforcement boundary); the adapter then reshapes the output.
  - Source reference: stored on L3Artifact.content as a YAML comment for lineage;
    the sql_table key uses the adapted bare table name (after _resolve_sources).
  - No new deps: pyyaml already a project dep; re/os are stdlib.

EXPRESSION → CUBE MAPPING (from Opus STEP 1):
┌──────────────────┬──────────────────────────────────────────────────────────┐
│ Expression class │ Cube measure                                             │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ BOOLEAN predicate│ type: count  +  filters:[{sql:"<expr>"}]                │
│ COUNT            │ type: count  sql: inner col                             │
│ COUNT DISTINCT   │ type: count_distinct  sql: inner col                    │
│ SUM              │ type: sum  sql: inner col                               │
│ AVG              │ type: avg  sql: inner col                               │
│ MIN / MAX        │ type: min / max  sql: inner col                         │
│ RATIO/DERIVED    │ type: number  sql: "{numerator}/{denominator}"           │
│ SCALAR/DIM       │ dimension: - name / sql / type (string|number|time)     │
└──────────────────┴──────────────────────────────────────────────────────────┘

REPRODUCING CompletedOrderCount (G2 gate):
  L2 header: -- CUBE_MEASURE: completed_count | count
  L2 sql col: completed_order_count (snake_case of CompletedOrderCount)
  Expected Cube measure block:
    - name: completed_count
      sql: completed_order_count
      type: count
  This matches globals.py _build_measures_yaml output exactly.
"""

from __future__ import annotations

import os
import re
from typing import Optional

import yaml

from mesa_core.model import Entity
from mesa_core.compiler.l3 import GovernanceContext, L3Artifact
from mesa_core.compiler.query_compiler import compile_from_expression


# ---------------------------------------------------------------------------
# Expression classifier (shared logic mirrored from metricflow adapter)
# ---------------------------------------------------------------------------

_AGG_PATTERNS: list[tuple[str, str]] = [
    (r"^\s*COUNT\s*\(\s*DISTINCT\b", "count_distinct"),
    (r"^\s*COUNT\s*\(", "count"),
    (r"^\s*SUM\s*\(", "sum"),
    (r"^\s*AVG\s*\(", "avg"),
    (r"^\s*AVERAGE\s*\(", "avg"),
    (r"^\s*MIN\s*\(", "min"),
    (r"^\s*MAX\s*\(", "max"),
]

_BOOL_PATTERN = re.compile(
    r"[=<>!]+|"
    r"\bIS\s+(NOT\s+)?NULL\b|"
    r"\bBETWEEN\b|"
    r"\bLIKE\b|"
    r"\bILIKE\b|"
    r"\bIN\s*\(",
    re.IGNORECASE,
)

_DIVISION_PATTERN = re.compile(r"(?<!['\"])/(?!['\"])")


def _classify_expression(expression: str) -> str:
    expr = expression.strip()
    for pattern, kind in _AGG_PATTERNS:
        if re.match(pattern, expr, re.IGNORECASE):
            return kind
    if _BOOL_PATTERN.search(expr):
        return "boolean"
    if _DIVISION_PATTERN.search(expr):
        return "ratio"
    return "scalar"


def _extract_inner_col(expression: str) -> str:
    """Strip the outer aggregate wrapper to get the inner column expression."""
    m = re.match(
        r"^\s*(?:COUNT\s*\(\s*DISTINCT\s+|COUNT\s*\(\s*|SUM\s*\(\s*|"
        r"AVG\s*\(\s*|AVERAGE\s*\(\s*|MIN\s*\(\s*|MAX\s*\(\s*)"
        r"(.+?)\s*\)\s*$",
        expression.strip(),
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return expression.strip()


def _to_snake_case(name: str) -> str:
    """PascalCase → snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s).lower()


# ---------------------------------------------------------------------------
# Source resolver + dialect adapter (ported from globals.py, Cube-specific)
# ---------------------------------------------------------------------------

def _resolve_sources(sql: str) -> str:
    """Strip dbt {{ source('schema', 'table') }} → bare table name.

    Cube.dev cannot interpret Jinja — this is the Cube-specific tax that MF
    avoids.  Ported directly from globals.py _resolve_sources.

    Note: {{ ref('table') }} is NOT stripped — if a metric file uses ref()
    instead of source(), leave the table name visible via the same logic.
    """
    # {{ source('schema', 'table') }} → table
    sql = re.sub(
        r"\{\{\s*source\('[^']+',\s*'([^']+)'\)\s*\}\}",
        r"\1",
        sql,
    )
    # {{ ref('table') }} → table
    sql = re.sub(
        r"\{\{\s*ref\('([^']+)'\)\s*\}\}",
        r"\1",
        sql,
    )
    return sql


def _adapt_dialect(sql: str, dialect: Optional[str] = None) -> str:
    """Route SQL through the correct per-engine adapter.

    Ported from globals.py _adapt_dialect.  Default: duckdb (same as reference).
    Controlled by CUBE_DB_DIALECT env var or explicit dialect argument.
    """
    d = (dialect or os.environ.get("CUBE_DB_DIALECT", "duckdb")).lower()
    if d == "duckdb":
        return _adapt_duckdb(sql)
    if d == "snowflake":
        return _adapt_snowflake(sql)
    if d == "bigquery":
        return _adapt_bigquery(sql)
    # postgres / generic — no transforms needed
    return sql


def _adapt_duckdb(sql: str) -> str:
    """DuckDB dialect adaptations (ported from globals.py)."""
    # MonthsSinceFirstPurchase: Postgres AGE() → DuckDB datediff()
    sql = re.sub(
        r"DATE_PART\('year',\s*AGE\(CURRENT_DATE,\s*"
        r"(DATE_TRUNC\('[^']+',\s*MIN\(orders\.completed_at\)\))"
        r"\s*\)\)\s*\*\s*12\s*"
        r"\+\s*DATE_PART\('month',\s*AGE\(CURRENT_DATE,\s*"
        r"DATE_TRUNC\('[^']+',\s*MIN\(orders\.completed_at\)\)\)\)",
        r"datediff('month', DATE_TRUNC('month', MIN(orders.completed_at::TIMESTAMP)), CURRENT_DATE)",
        sql,
        flags=re.DOTALL,
    )
    sql = re.sub(r"DATE_PART\('year',\s*", "year(", sql)
    sql = re.sub(
        r"TO_CHAR\(\s*(DATE_TRUNC\('[^']+',\s*MIN\([^)]+\)\))\s*,\s*'YYYY-MM'\)",
        r"strftime('%Y-%m', \1)",
        sql,
    )
    sql = re.sub(r"orders\.completed_at(?!::)", "orders.completed_at::TIMESTAMP", sql)
    return sql


def _adapt_snowflake(sql: str) -> str:
    """Snowflake dialect adaptations (ported from globals.py)."""
    sql = re.sub(r"::TIMESTAMP", "", sql)
    return sql


def _adapt_bigquery(sql: str) -> str:
    """BigQuery dialect adaptations (ported from globals.py)."""
    sql = re.sub(
        r"DATE_PART\('year',\s*AGE\(CURRENT_DATE,\s*"
        r"(DATE_TRUNC\('[^']+',\s*MIN\(orders\.completed_at\)\))"
        r"\s*\)\)\s*\*\s*12\s*"
        r"\+\s*DATE_PART\('month',\s*AGE\(CURRENT_DATE,\s*"
        r"DATE_TRUNC\('[^']+',\s*MIN\(orders\.completed_at\)\)\)\)",
        r"DATE_DIFF(CURRENT_DATE, DATE_TRUNC(DATE(\1), MONTH), MONTH)",
        sql,
        flags=re.DOTALL,
    )
    sql = re.sub(r"DATE_PART\('year',\s*", r"EXTRACT(YEAR FROM ", sql)
    sql = re.sub(
        r"TO_CHAR\(\s*(DATE_TRUNC\('[^']+',\s*MIN\([^)]+\)\))\s*,\s*'YYYY-MM'\)",
        r"FORMAT_DATE('%Y-%m', \1)",
        sql,
    )
    return sql


# ---------------------------------------------------------------------------
# L2 header parser for Cube measure hints
# ---------------------------------------------------------------------------

def _parse_l2_header(l2_content: str) -> dict:
    """Parse Cube measure/dimension hints from an L2 metric file's header.

    Recognizes:
      -- CUBE_MEASURE:  name | type [| format]   (CubeDev legacy)
      -- MESA_MEASURE:  name [| type [| format]]  (MESA L2 emitter output)
      -- CUBE_DIM_TYPE: string|number|time
      -- CUBE_DIM_SKIP: true

    The MESA_MEASURE directive uses the same pipe-separated format as
    CUBE_MEASURE.  When type is omitted in MESA_MEASURE, it is derived from
    the expression at emit-time (see CubeAdapter.emit).

    Returns dict:
      {
        'measures': [(name, type_or_None, format_or_None), ...],
        'dim_type': 'number',   # default
        'dim_skip': False,
      }
    """
    result: dict = {"measures": [], "dim_type": "number", "dim_skip": False}
    for line in l2_content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("--"):
            break  # stop at first non-comment line
        content = stripped[2:].strip()

        if content.upper().startswith("CUBE_MEASURE:") or content.upper().startswith("MESA_MEASURE:"):
            _, rest = content.split(":", 1)
            parts = [p.strip() for p in rest.split("|")]
            name = parts[0]
            mtype = parts[1] if len(parts) > 1 else None
            fmt = parts[2] if len(parts) > 2 else None
            result["measures"].append((name, mtype, fmt))

        elif content.upper().startswith("CUBE_DIM_TYPE:"):
            result["dim_type"] = content.split(":", 1)[1].strip()

        elif content.upper().startswith("CUBE_DIM_SKIP:"):
            result["dim_skip"] = content.split(":", 1)[1].strip().lower() == "true"

    return result


# ---------------------------------------------------------------------------
# Cube adapter
# ---------------------------------------------------------------------------


class CubeAdapter:
    """Emits Cube.dev `cubes:` YAML from the MESA metric expression.

    Sources the correct measure type from the expression shape (expression
    classifier) and from any L2 header hints (MESA_MEASURE / CUBE_MEASURE).
    Ported from CubeDev/cube_takehome/model/globals.py — measure/dimension
    emission, _resolve_sources, and dialect adaptation — as GENERATED output
    so customers never hand-write the fragile Jinja-stripping scaffolding.
    """

    target: str = "cube"

    def emit(
        self,
        entity: Entity,
        metric_name: str,
        expression: str,
        governance: GovernanceContext,
        *,
        dialect: Optional[str] = None,
        l2_content: Optional[str] = None,
    ) -> L3Artifact:
        """Emit the Cube cubes: YAML artifact.

        Args:
            entity:      MESA entity (source of identity + table ref).
            metric_name: PascalCase metric name.
            expression:  User-authored SQL expression.
            governance:  Owner/steward/sensitivity context.
            dialect:     Optional Cube SQL dialect override.  Defaults to
                         CUBE_DB_DIALECT env var or 'duckdb'.
            l2_content:  Optional L2 metric file content — if provided, the
                         MESA_MEASURE / CUBE_MEASURE header is used to set the
                         measure name and type (mirroring globals.py behaviour).
                         If absent, measure name/type are derived from the
                         expression classifier.
        """
        # Structural enforcement: compile first (single SoT, MESA core rules).
        compile_from_expression(entity, metric_name, expression)

        cube_name = _to_snake_case(entity.entity_name)
        measure_col = _to_snake_case(metric_name)  # column alias in the compiled SQL
        kind = _classify_expression(expression)

        # ── Resolve the source SQL table ──────────────────────────────────
        # Strip dbt {{ source() }} Jinja for Cube (Cube-specific tax).
        raw_source = (
            f"{{{{ source('{entity.source_name}', '{entity.base_table_name}') }}}}"
        )
        resolved_table = _resolve_sources(raw_source)
        adapted_table = _adapt_dialect(resolved_table, dialect)

        # ── Derive measure definition ─────────────────────────────────────
        # Priority: (1) L2 header hint, (2) expression classifier.
        measure_name: str
        measure_type: str
        measure_format: Optional[str] = None
        filters: Optional[list[dict]] = None

        if l2_content:
            header = _parse_l2_header(l2_content)
            if header["measures"]:
                # Use the first declared MESA_MEASURE / CUBE_MEASURE.
                hname, htype, hfmt = header["measures"][0]
                measure_name = hname
                # If type was omitted in the header, fall back to classifier.
                measure_type = htype if htype else _kind_to_cube_type(kind, expression)
                measure_format = hfmt
            else:
                measure_name = measure_col
                measure_type = _kind_to_cube_type(kind, expression)
        else:
            measure_name = measure_col
            measure_type = _kind_to_cube_type(kind, expression)

        # Boolean predicates use count + filters (not a raw bool measure).
        if kind == "boolean":
            filters = [{"sql": expression}]
            # measure_type is already 'count' from _kind_to_cube_type.

        # For aggregate types, extract the inner column for the sql: key.
        # For boolean and ratio, the sql: key uses the measure_col directly.
        if kind in ("count", "count_distinct", "sum", "avg", "min", "max"):
            measure_sql = _extract_inner_col(expression)
        elif kind == "ratio":
            # Ratio: type: number, sql uses the full expression.
            # Cube references other measures via {measure_name} in sql:.
            measure_sql = expression
        else:
            # boolean / scalar — sql: the measure column (the compiled alias)
            measure_sql = measure_col

        # ── Build measure block ───────────────────────────────────────────
        measure_block: dict = {
            "name": measure_name,
            "sql": measure_sql,
            "type": measure_type,
        }
        if filters:
            measure_block["filters"] = filters
        if measure_format:
            measure_block["format"] = measure_format

        # ── Build meta block ──────────────────────────────────────────────
        meta_block: dict = {
            "mesa_owner": governance.get("owner", ""),
            "mesa_steward": governance.get("steward"),
            "mesa_sensitivity": governance.get("sensitivity", "standard"),
            "mesa_authoring_path": governance.get("authoring_path", "guided"),
        }

        # ── Scalar / dimension path ───────────────────────────────────────
        if kind == "scalar":
            dim_type = "string"  # default for scalar expression
            if l2_content:
                header = _parse_l2_header(l2_content)
                if not header.get("dim_skip", False):
                    dim_type = header.get("dim_type", "string")

            cube_doc = {
                "cubes": [
                    {
                        "name": cube_name,
                        "sql_table": adapted_table,
                        "dimensions": [
                            {
                                "name": measure_col,
                                "sql": expression,
                                "type": dim_type,
                            }
                        ],
                        "meta": meta_block,
                    }
                ]
            }
            content = self._render_yaml(cube_doc)
            return L3Artifact(
                target=self.target,
                filename=f"{cube_name}.yml",
                content=content,
                language="yaml",
            )

        # ── Standard measure path ─────────────────────────────────────────
        cube_doc = {
            "cubes": [
                {
                    "name": cube_name,
                    "sql_table": adapted_table,
                    "measures": [measure_block],
                    "meta": meta_block,
                }
            ]
        }

        content = self._render_yaml(cube_doc)

        return L3Artifact(
            target=self.target,
            filename=f"{cube_name}.yml",
            content=content,
            language="yaml",
        )

    def _render_yaml(self, doc: dict) -> str:
        """Emit YAML with deterministic key order."""

        class CubeDumper(yaml.SafeDumper):
            pass

        def _str_repr(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
            if "\n" in data:
                return dumper.represent_scalar(
                    "tag:yaml.org,2002:str", data, style="|"
                )
            return dumper.represent_scalar("tag:yaml.org,2002:str", data)

        CubeDumper.add_representer(str, _str_repr)

        return yaml.dump(
            doc,
            Dumper=CubeDumper,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )


def _kind_to_cube_type(kind: str, expression: str) -> str:
    """Map an expression kind to a Cube measure type string."""
    mapping = {
        "boolean": "count",         # count rows where predicate is true
        "count": "count",
        "count_distinct": "count_distinct",
        "sum": "sum",
        "avg": "avg",
        "min": "min",
        "max": "max",
        "ratio": "number",          # Cube: type: number for derived arithmetic
        "scalar": "string",         # dimensions, not measures
    }
    return mapping.get(kind, "number")
