# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
SQL Parser
===========
Parses SQL statements into a structured AST using sqlglot.
Used by both the REST query validation layer and the pgwire server.

sqlglot supports BigQuery, Snowflake, Redshift, and standard SQL dialects.
We parse to dialect-neutral AST first, then rewrite to the target dialect.
"""

from dataclasses import dataclass, field

try:
    import sqlglot
    import sqlglot.expressions as exp
    SQLGLOT_AVAILABLE = True
except ImportError:
    SQLGLOT_AVAILABLE = False


@dataclass
class ParsedQuery:
    """Structured representation of a parsed SQL query."""
    raw_sql: str
    query_type: str                         # SELECT | INSERT | UPDATE | DELETE | UNKNOWN
    entity_name: str | None = None          # Resolved entity name (from table alias / name)
    requested_metrics: list[str] = field(default_factory=list)  # column names from SELECT
    filters: list[dict] = field(default_factory=list)           # WHERE conditions
    limit: int | None = None
    order_by: list[str] = field(default_factory=list)
    is_star: bool = False                   # SELECT * — means "all metrics"
    raw_table_refs: list[str] = field(default_factory=list)     # all FROM/JOIN table names
    parse_error: str | None = None


def parse_sql(sql: str, dialect: str = "bigquery") -> ParsedQuery:
    """
    Parse a SQL string into a ParsedQuery.
    Returns a ParsedQuery with parse_error set if parsing fails.
    """
    if not SQLGLOT_AVAILABLE:
        return ParsedQuery(
            raw_sql=sql,
            query_type="UNKNOWN",
            parse_error="sqlglot is not installed. pip install sqlglot",
        )

    try:
        statements = sqlglot.parse(sql, dialect=dialect)
    except Exception as e:
        return ParsedQuery(raw_sql=sql, query_type="UNKNOWN", parse_error=str(e))

    if not statements:
        return ParsedQuery(raw_sql=sql, query_type="UNKNOWN", parse_error="Empty SQL")

    stmt = statements[0]

    # Only SELECT is supported for semantic queries
    if not isinstance(stmt, exp.Select):
        return ParsedQuery(
            raw_sql=sql,
            query_type=type(stmt).__name__.upper(),
            parse_error=f"Only SELECT statements are supported. Got: {type(stmt).__name__}",
        )

    result = ParsedQuery(raw_sql=sql, query_type="SELECT")

    # ── Extract table references ───────────────────────────────────────────
    for table in stmt.find_all(exp.Table):
        name = table.name
        if name:
            result.raw_table_refs.append(name)

    if result.raw_table_refs:
        # First table = entity name (MESA queries have one entity per query)
        result.entity_name = result.raw_table_refs[0]

    # ── Extract SELECT columns ────────────────────────────────────────────
    for sel in stmt.selects:
        if isinstance(sel, exp.Star):
            result.is_star = True
        elif isinstance(sel, exp.Column):
            result.requested_metrics.append(sel.name)
        elif isinstance(sel, exp.Alias):
            # Handle aliased expressions like COUNT(x) AS my_metric
            result.requested_metrics.append(sel.alias)
        else:
            # Complex expression — extract the top-level alias if present
            alias = sel.alias if hasattr(sel, "alias") else None
            if alias:
                result.requested_metrics.append(alias)

    # ── Extract LIMIT ─────────────────────────────────────────────────────
    limit_node = stmt.find(exp.Limit)
    if limit_node:
        try:
            result.limit = int(limit_node.expression.this)
        except Exception:
            pass

    # ── Extract ORDER BY ─────────────────────────────────────────────────
    for order in stmt.find_all(exp.Ordered):
        col = order.find(exp.Column)
        if col:
            result.order_by.append(col.name)

    # ── Extract WHERE filters ─────────────────────────────────────────────
    where = stmt.find(exp.Where)
    if where:
        result.filters = _extract_filters(where)

    return result


def _extract_filters(where_node) -> list[dict]:
    """Walk the WHERE clause and extract simple column = value conditions."""
    filters = []
    for pred in where_node.find_all(exp.EQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.NEQ):
        left = pred.left
        right = pred.right
        if isinstance(left, exp.Column):
            op_map = {
                exp.EQ: "=", exp.GT: ">", exp.GTE: ">=",
                exp.LT: "<", exp.LTE: "<=", exp.NEQ: "!=",
            }
            filters.append({
                "column": left.name,
                "operator": op_map.get(type(pred), "="),
                "value": right.this if right else None,
            })
    return filters


def transpile_to_dialect(sql: str, from_dialect: str, to_dialect: str) -> str:
    """
    Transpile SQL from one dialect to another.
    Useful when a BI tool sends BigQuery SQL but we're running on Snowflake.
    """
    if not SQLGLOT_AVAILABLE:
        return sql
    try:
        return sqlglot.transpile(sql, read=from_dialect, write=to_dialect, pretty=True)[0]
    except Exception:
        return sql  # Return original if transpilation fails
