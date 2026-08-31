# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
lineage.py
==========
Parses metric SQL to produce an upstream/downstream lineage graph.

Upstream  — what does this metric depend on?
  • source refs:   {{ source('schema', 'table') }} extractions
  • column refs:   Entity.ColumnName patterns (heuristic, best-effort)
  • metric deps:   other metric names referenced in this metric's SQL (derived metrics)

Downstream — what would break if this metric changed?
  • wide_table:           always {EntityName}Metric (the compiled Wide Layer)
  • dependent_metrics:    other metrics in the same entity whose SQL references this metric's name
"""

import re
from mesa_core.model import Metric, Entity

# {{ source('schema_name', 'table_name') }}
_SOURCE_RE = re.compile(r"\{\{\s*source\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)\s*\}\}")

# Entity.ColumnName — both sides start with uppercase letter
_COL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\.([A-Z][A-Za-z0-9_]+)\b")

# SQL keywords to skip when they appear as the "table" side of a dot-reference
_SQL_KEYWORDS = {
    "AS", "ON", "AND", "OR", "NOT", "IN", "IS", "NULL", "FROM", "WHERE",
    "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "CROSS", "WITH",
    "SELECT", "STRUCT", "TRUE", "FALSE", "CASE", "WHEN", "THEN", "ELSE", "END",
    "BY", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET",
}


def parse_upstream(metric: Metric, entity: Entity) -> dict:
    """
    Extract source refs and column references from metric SQL.

    Returns:
        {
            "source_refs":  [{"source_name": str, "table_name": str}, ...],
            "column_refs":  [{"table": str, "column": str}, ...],
        }
    """
    sql = metric.definition_sql or ""

    # Source references: {{ source('schema', 'table') }}
    source_refs = [
        {"source_name": m.group(1), "table_name": m.group(2)}
        for m in _SOURCE_RE.finditer(sql)
    ]

    # Column references: TableName.ColumnName
    seen: set[str] = set()
    col_refs = []
    for m in _COL_RE.finditer(sql):
        table, col = m.group(1), m.group(2)
        if table.upper() in _SQL_KEYWORDS:
            continue
        key = f"{table}.{col}"
        if key not in seen:
            seen.add(key)
            col_refs.append({"table": table, "column": col})

    return {"source_refs": source_refs, "column_refs": col_refs}


def parse_metric_dependencies(metric: Metric, all_metrics: list[Metric]) -> list[str]:
    """
    Find other metrics whose CTE names appear as identifiers in this metric's SQL.
    These are "derived metrics" — this metric's output builds on another metric.

    Example: if EarnQuarter's SQL references the EarnPeriod CTE, EarnPeriod is listed here.
    """
    sql = metric.definition_sql or ""
    return [
        m.metric_name
        for m in all_metrics
        if m.metric_name != metric.metric_name
        and re.search(rf"\b{re.escape(m.metric_name)}\b", sql)
    ]


def find_dependents(metric: Metric, all_metrics: list[Metric]) -> list[dict]:
    """
    Find other metrics in the same entity whose SQL references this metric's name.
    These metrics would be broken if this metric were renamed or removed.

    Returns list of {"metric_name": str} — the plain dataclass has no DB id or
    status, so identity is the metric_name (the file name), which is the MESA
    one-file-one-metric contract's own natural key.
    """
    return [
        {"metric_name": m.metric_name}
        for m in all_metrics
        if m.metric_name != metric.metric_name
        and re.search(rf"\b{re.escape(metric.metric_name)}\b", m.definition_sql or "")
    ]
