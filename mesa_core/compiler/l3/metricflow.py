# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
compiler/l3/metricflow.py
=========================
MetricFlow L3 adapter — emits native dbt Semantic Layer YAML.

Produces `semantic_models:` + `metrics:` YAML that is valid for
  dbt parse  (latest stable dbt-core + dbt-semantic-interfaces at build time).

# dbt version pin (SPEC_32-1b, 2026-07-09):
#   dbt-core          == 1.9.x  (latest stable as of build date)
#   dbt-semantic-interfaces == 0.7.x
#   MetricFlow        == 0.7.x  (bundled with dbt-semantic-interfaces)
# Record exact resolved versions in the commit message and in
# tests/test_l3_adapters.py (marked with # dbt-version-pin comments).

CRITICAL SPEC CONSTRAINTS (SPEC_32 §1.2):
  - NEVER strip {{ source() }} or {{ ref() }} — MetricFlow resolves natively.
  - model: ref('<base_table_name>') is the correct reference.
  - agg_time_dimension emitted as defaults.agg_time_dimension when Entity.time_column
    is set; omitted when None (non-time-series entities remain valid). SPEC_32 landed.
  - entity type: primary maps to entity.identity_column.
  - meta: block carries mesa_owner / mesa_steward / mesa_sensitivity — the
    governance enforcement MetricFlow itself lacks.
  - Uses pyyaml (already a project dep) with sort_keys=False for deterministic
    key order.

EXPRESSION → METRICFLOW MAPPING (from Opus STEP 1, /memories/repo/spec32_1b_...):
┌──────────────────┬─────────────────────────────────────────────────────────┬─────────────┐
│ Expression class │ semantic_model.measure                                  │ metric type │
├──────────────────┼─────────────────────────────────────────────────────────┼─────────────┤
│ BOOLEAN          │ agg:sum  expr:CASE WHEN <expr> THEN 1 ELSE 0 END        │ simple      │
│ COUNT/COUNT_DIST │ agg:count / agg:count_distinct  expr: inner col         │ simple      │
│ SUM              │ agg:sum  expr: inner col                                 │ simple      │
│ AVG              │ agg:average  expr: inner col    (MF uses "average")      │ simple      │
│ MIN / MAX        │ agg:min / agg:max  expr: inner col                      │ simple      │
│ RATIO            │ two measures (numerator / denominator)                  │ ratio       │
│ DERIVED          │ references existing metrics                             │ derived     │
│ SCALAR/DIM       │ NOT a measure → emitted as dimension on semantic_model  │ (no metric) │
└──────────────────┴─────────────────────────────────────────────────────────┴─────────────┘
"""

from __future__ import annotations

import re

import yaml

from mesa_core.model import Entity
from mesa_core.compiler.l3 import GovernanceContext, L3Adapter, L3Artifact
from mesa_core.compiler.query_compiler import compile_from_expression


# ---------------------------------------------------------------------------
# Expression classifier
# ---------------------------------------------------------------------------

# Patterns for aggregate functions at the top level of the expression.
_AGG_PATTERNS: list[tuple[str, str]] = [
    # count_distinct must be checked before count
    (r"^\s*COUNT\s*\(\s*DISTINCT\b", "count_distinct"),
    (r"^\s*COUNT\s*\(", "count"),
    (r"^\s*SUM\s*\(", "sum"),
    (r"^\s*AVG\s*\(", "avg"),
    (r"^\s*AVERAGE\s*\(", "avg"),
    (r"^\s*MIN\s*\(", "min"),
    (r"^\s*MAX\s*\(", "max"),
]

# Boolean indicators: comparison operators, IS NULL/NOT NULL, BETWEEN, LIKE, IN (...)
_BOOL_PATTERN = re.compile(
    r"[=<>!]+|"                        # comparison operators  =, <, >, !=, <=, >=
    r"\bIS\s+(NOT\s+)?NULL\b|"
    r"\bBETWEEN\b|"
    r"\bLIKE\b|"
    r"\bILIKE\b|"
    r"\bIN\s*\(",
    re.IGNORECASE,
)

# Ratio/division indicator — a division operator NOT inside a function call.
# Simple heuristic: if expression contains "/" but is not a pure aggregate.
_DIVISION_PATTERN = re.compile(r"(?<!['\"])/(?!['\"])")


def _classify_expression(expression: str) -> str:
    """Classify the expression into one of the adapter categories.

    Returns one of:
      'boolean', 'count_distinct', 'count', 'sum', 'avg', 'min', 'max',
      'ratio', 'scalar'
    """
    expr = expression.strip()

    # 1. Aggregate functions — match from the start of the expression.
    for pattern, kind in _AGG_PATTERNS:
        if re.match(pattern, expr, re.IGNORECASE):
            return kind

    # 2. Boolean — contains a comparison / IS NULL / BETWEEN / LIKE / IN.
    if _BOOL_PATTERN.search(expr):
        return "boolean"

    # 3. Ratio — division present (but no aggregate → ratio/derived arithmetic).
    if _DIVISION_PATTERN.search(expr):
        return "ratio"

    # 4. Default: treat as scalar dimension passthrough.
    return "scalar"


# ---------------------------------------------------------------------------
# Inner-column extraction helpers
# ---------------------------------------------------------------------------

def _extract_inner_col(expression: str, func: str) -> str:
    """Extract the column expression from a unary aggregate call.

    e.g. SUM(orders.amount) -> orders.amount
         COUNT(DISTINCT orders.id) -> orders.id
    Returns the original expression if extraction fails (safe fallback).
    """
    # Strip COUNT DISTINCT wrapper
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
    """PascalCase → snake_case.  Used for semantic model and measure names."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s).lower()


# ---------------------------------------------------------------------------
# MetricFlow adapter
# ---------------------------------------------------------------------------


class MetricFlowAdapter:
    """Emits native dbt Semantic Layer YAML (semantic_models: + metrics:)."""

    target: str = "metricflow"

    def emit(
        self,
        entity: Entity,
        metric_name: str,
        expression: str,
        governance: GovernanceContext,
    ) -> L3Artifact:
        """Build the MetricFlow artifact for this metric.

        The generated SQL (from compile_from_expression) is the single source
        of truth — this adapter reshapes it, never re-derives the SQL logic.
        """
        # Compile SQL first (keeps compile_from_expression as the SoT).
        # We don't embed the raw SQL in MetricFlow YAML — MetricFlow resolves
        # expressions natively via ref() — but we call it so the same
        # structural enforcement applies.
        compile_from_expression(entity, metric_name, expression)

        kind = _classify_expression(expression)
        semantic_model_name = _to_snake_case(entity.entity_name)
        measure_name = _to_snake_case(metric_name)

        # ── Build semantic_model ──────────────────────────────────────────
        semantic_model: dict = {
            "name": semantic_model_name,
            # MetricFlow uses ref() — NEVER strip it.
            "model": f"ref('{entity.base_table_name}')",
            "entities": [
                {
                    "name": semantic_model_name,
                    "type": "primary",
                    "expr": entity.identity_column,
                }
            ],
        }

        # ── Measures + metric type ────────────────────────────────────────
        measures: list[dict] = []
        metric_doc: dict = {}

        if kind == "boolean":
            # BOOLEAN → CASE WHEN ... THEN 1 ELSE 0 END, agg:sum, metric:simple
            case_expr = f"CASE WHEN {expression} THEN 1 ELSE 0 END"
            measures.append(
                {
                    "name": measure_name,
                    "agg": "sum",
                    "expr": case_expr,
                    "description": (
                        f"Count of rows where: {expression}"
                    ),
                }
            )
            metric_doc = {
                "name": metric_name,
                "type": "simple",
                "type_params": {"measure": measure_name},
                "meta": self._meta_block(governance),
            }

        elif kind in ("count", "count_distinct"):
            inner = _extract_inner_col(expression, kind)
            agg = "count_distinct" if kind == "count_distinct" else "count"
            measures.append(
                {
                    "name": measure_name,
                    "agg": agg,
                    "expr": inner,
                }
            )
            metric_doc = {
                "name": metric_name,
                "type": "simple",
                "type_params": {"measure": measure_name},
                "meta": self._meta_block(governance),
            }

        elif kind == "sum":
            inner = _extract_inner_col(expression, "sum")
            measures.append(
                {
                    "name": measure_name,
                    "agg": "sum",
                    "expr": inner,
                }
            )
            metric_doc = {
                "name": metric_name,
                "type": "simple",
                "type_params": {"measure": measure_name},
                "meta": self._meta_block(governance),
            }

        elif kind == "avg":
            inner = _extract_inner_col(expression, "avg")
            # MetricFlow spells the aggregation as "average" (not "avg").
            measures.append(
                {
                    "name": measure_name,
                    "agg": "average",
                    "expr": inner,
                }
            )
            metric_doc = {
                "name": metric_name,
                "type": "simple",
                "type_params": {"measure": measure_name},
                "meta": self._meta_block(governance),
            }

        elif kind in ("min", "max"):
            inner = _extract_inner_col(expression, kind)
            measures.append(
                {
                    "name": measure_name,
                    "agg": kind,
                    "expr": inner,
                }
            )
            metric_doc = {
                "name": metric_name,
                "type": "simple",
                "type_params": {"measure": measure_name},
                "meta": self._meta_block(governance),
            }

        elif kind == "ratio":
            # RATIO → derived metric referencing the full expression.
            # We emit a single 'sum' proxy measure for the numerator expression
            # and a 'derived' metric with the ratio sql.
            # Rationale: MetricFlow 'ratio' type requires two named measures;
            # a single arbitrary expression is better modelled as 'derived'.
            measures.append(
                {
                    "name": measure_name,
                    "agg": "sum",
                    "expr": expression,
                }
            )
            metric_doc = {
                "name": metric_name,
                "type": "derived",
                "type_params": {
                    "expr": measure_name,
                    "metrics": [{"name": metric_name}],
                },
                "meta": self._meta_block(governance),
            }

        else:
            # SCALAR / DIMENSION → emit as a dimension, no metric node.
            # MetricFlow cannot produce a metric from a bare scalar column.
            semantic_model["dimensions"] = [
                {
                    "name": measure_name,
                    "type": "categorical",
                    "expr": expression,
                    "description": (
                        f"Scalar dimension from expression: {expression}"
                    ),
                }
            ]
            # No metric node for scalar — return semantic model only.
            semantic_model["measures"] = []
            doc = {
                "semantic_models": [semantic_model],
                # scalar expressions produce NO metric entry
                "metrics": [],
            }
            content = self._render_yaml(doc)
            return L3Artifact(
                target=self.target,
                filename=f"{_to_snake_case(entity.entity_name)}.yml",
                content=content,
                language="yaml",
            )

        # Attach measures and assemble doc.
        semantic_model["measures"] = measures

        # agg_time_dimension — emit when Entity.time_column is set (SPEC_32 follow-up,
        # now landed). Omit when None so non-time-series entities stay valid.
        if getattr(entity, "time_column", None):
            semantic_model["defaults"] = {"agg_time_dimension": entity.time_column}

        doc = {
            "semantic_models": [semantic_model],
            "metrics": [metric_doc],
        }

        content = self._render_yaml(doc)

        return L3Artifact(
            target=self.target,
            filename=f"{semantic_model_name}.yml",
            content=content,
            language="yaml",
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _meta_block(self, governance: GovernanceContext) -> dict:
        """Governance meta: block — the enforcement MetricFlow itself lacks."""
        return {
            "mesa_owner": governance.get("owner", ""),
            "mesa_steward": governance.get("steward"),
            "mesa_sensitivity": governance.get("sensitivity", "standard"),
            "mesa_authoring_path": governance.get("authoring_path", "guided"),
        }

    def _render_yaml(self, doc: dict) -> str:
        """Emit YAML with deterministic key order (sort_keys=False, no floats)."""

        class MFDumper(yaml.SafeDumper):
            pass

        def _str_repr(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
            """Keep multi-line strings as block scalars."""
            if "\n" in data:
                return dumper.represent_scalar(
                    "tag:yaml.org,2002:str", data, style="|"
                )
            return dumper.represent_scalar("tag:yaml.org,2002:str", data)

        MFDumper.add_representer(str, _str_repr)

        return yaml.dump(
            doc,
            Dumper=MFDumper,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
