# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
warehouses.py — the ONE warehouse identity for mesa-core.

SPEC_103 Slice 1. Before this module there were four lists that disagreed:

  * ``query_compiler`` knew ``Synapse`` and ``AzureSQLDatabase`` (``_TSQL_WAREHOUSES``)
  * ``grain_guard`` knew ``azuresqldb`` -> ``tsql`` and nothing else T-SQL
  * ``cli.py compile`` had its own if/elif ladder, and passed anything it didn't
    recognize straight through "as-is"
  * governance spelled Synapse ``AzureSynapse`` while mesa-core spelled it ``Synapse``

The failure mode that mattered: an unrecognized warehouse name did not raise. It
fell through ``_build_widetable``'s final ``else`` branch and compiled as Redshift
``dbt_utils.star`` output. A typo produced plausible-looking SQL for the wrong
warehouse, and nothing said a word. ``compile_entity(..., "AzureSynapse")``,
``"Postgres"`` and ``"TotallyUnknown"`` all returned Redshift SQL (measured
2026-10-18).

This module is the single source of truth. Every consumer normalizes through
``normalize_warehouse`` and asks ``sqlglot_dialect`` / ``is_tsql`` rather than
keeping a private copy of the list. An unknown name raises
``UnknownWarehouseError`` — loudly, at the boundary, before any SQL is emitted.

HARD RULE: this module imports nothing from mesa_core. It is the bottom of the
dependency graph so every other module can import it without a cycle.
"""

from __future__ import annotations

# The six warehouses MESA supports. SPEC_69 investigated Postgres, Databricks
# and SQL Server and they are NOT targets — don't add them here.
SNOWFLAKE = "Snowflake"
BIGQUERY = "BigQuery"
REDSHIFT = "Redshift"
SYNAPSE = "Synapse"
AZURE_SQL_DATABASE = "AzureSQLDatabase"
DUCKDB = "DuckDB"

# Canonical order. This is the order the CLI help text, the error message and
# the portability report all list them in, so a user sees one consistent list.
CANONICAL_WAREHOUSES: tuple[str, ...] = (
    SNOWFLAKE,
    BIGQUERY,
    REDSHIFT,
    SYNAPSE,
    AZURE_SQL_DATABASE,
    DUCKDB,
)

# The two T-SQL targets. Both share the flat-typed-CAST wide shape (SPEC_76)
# because neither has a native nested type.
TSQL_WAREHOUSES: tuple[str, ...] = (SYNAPSE, AZURE_SQL_DATABASE)

# Aliases accepted at the boundary, keyed by the lowercased spelling a caller
# might hand us. Governance stores ``AzureSynapse``; the migration console
# spells it that way too; a user typing ``--warehouse azure_sql`` should work.
# Every alias maps to a canonical name — the database keeps whatever it has,
# the normalizer translates at the edge.
_ALIASES: dict[str, str] = {
    # Snowflake
    "snowflake": SNOWFLAKE,
    "sf": SNOWFLAKE,
    # BigQuery
    "bigquery": BIGQUERY,
    "bq": BIGQUERY,
    "googlebigquery": BIGQUERY,
    # Redshift
    "redshift": REDSHIFT,
    "rs": REDSHIFT,
    # Synapse Dedicated SQL Pool — governance and the migration console both
    # spell this "AzureSynapse"; mesa-core historically spelled it "Synapse".
    "synapse": SYNAPSE,
    "azuresynapse": SYNAPSE,
    "azuresynapseanalytics": SYNAPSE,
    "synapsededicated": SYNAPSE,
    "synapsededicatedsqlpool": SYNAPSE,
    # Azure SQL Database
    "azuresqldatabase": AZURE_SQL_DATABASE,
    "azuresqldb": AZURE_SQL_DATABASE,
    "azuresql": AZURE_SQL_DATABASE,
    "azure_sql_db": AZURE_SQL_DATABASE,
    "azure_sql_database": AZURE_SQL_DATABASE,
    "sqldatabase": AZURE_SQL_DATABASE,
    # DuckDB
    "duckdb": DUCKDB,
    "duck": DUCKDB,
}

# Warehouse -> sqlglot dialect name. sqlglot calls the T-SQL family "tsql";
# both Synapse and Azure SQL Database parse with it.
_SQLGLOT_DIALECTS: dict[str, str] = {
    SNOWFLAKE: "snowflake",
    BIGQUERY: "bigquery",
    REDSHIFT: "redshift",
    SYNAPSE: "tsql",
    AZURE_SQL_DATABASE: "tsql",
    DUCKDB: "duckdb",
}


class UnknownWarehouseError(ValueError):
    """Raised when a warehouse name isn't one of the six MESA supports.

    A ``ValueError`` subclass so existing ``except ValueError`` handlers keep
    working, but distinct enough that a caller can catch it specifically and
    turn it into a 422 at an API boundary.
    """

    def __init__(self, name: object) -> None:
        self.name = name
        valid = ", ".join(CANONICAL_WAREHOUSES)
        super().__init__(
            f"Unknown warehouse {name!r}. MESA supports: {valid}. "
            f"Accepted aliases include AzureSynapse (-> Synapse) and "
            f"azuresqldb (-> AzureSQLDatabase)."
        )


def normalize_warehouse(name: str | None) -> str:
    """Return the canonical warehouse name for ``name``.

    Case-insensitive, alias-aware. Raises ``UnknownWarehouseError`` for anything
    unrecognized — including ``None`` and the empty string. That's deliberate:
    a missing warehouse is a bug at the call site, not a request to guess. The
    old behavior (fall through to Redshift) is exactly what this module exists
    to stop.
    """
    if not isinstance(name, str) or not name.strip():
        raise UnknownWarehouseError(name)

    key = name.strip().lower().replace("-", "").replace(" ", "")
    canonical = _ALIASES.get(key)
    if canonical is None:
        raise UnknownWarehouseError(name)
    return canonical


def try_normalize_warehouse(name: str | None) -> str | None:
    """``normalize_warehouse`` that returns ``None`` instead of raising.

    For callers that legitimately have no warehouse yet (a backfill scanning
    ``definition_sql`` with no entity context) and want to fall back to probing
    every dialect rather than fail.
    """
    try:
        return normalize_warehouse(name)
    except UnknownWarehouseError:
        return None


def is_known_warehouse(name: str | None) -> bool:
    """True when ``name`` normalizes to one of the six canonical warehouses."""
    return try_normalize_warehouse(name) is not None


def sqlglot_dialect(name: str | None) -> str:
    """Return the sqlglot dialect name for a warehouse.

    Raises ``UnknownWarehouseError`` for an unrecognized name — a parser handed
    the wrong dialect produces confidently wrong results, so guessing is worse
    than failing.
    """
    return _SQLGLOT_DIALECTS[normalize_warehouse(name)]


def try_sqlglot_dialect(name: str | None) -> str | None:
    """``sqlglot_dialect`` that returns ``None`` for an unknown warehouse."""
    canonical = try_normalize_warehouse(name)
    return _SQLGLOT_DIALECTS[canonical] if canonical else None


def is_tsql(name: str | None) -> bool:
    """True for the two T-SQL targets (Synapse Dedicated, Azure SQL Database)."""
    canonical = try_normalize_warehouse(name)
    return canonical in TSQL_WAREHOUSES


def is_combiner_warehouse(name: str | None) -> bool:
    """True for the warehouses that emit a separate metric-combiner model.

    Snowflake and the two T-SQL targets build a per-entity combiner model that
    the wide layer joins to once. BigQuery, Redshift and DuckDB render the wide
    layer directly against the metric model, so they have no combiner and no
    ``COMBINER_DEFAULT`` to apply (SPEC_103 Slice 3 changes that — until then
    this predicate is the honest description of the code).
    """
    canonical = try_normalize_warehouse(name)
    return canonical == SNOWFLAKE or canonical in TSQL_WAREHOUSES
