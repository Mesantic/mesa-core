"""
test_warehouses.py — SPEC_103 Slice 1: one warehouse identity.

The bug this locks down: an unrecognized warehouse name did not raise. It fell
through ``_build_widetable``'s final ``else`` branch and compiled as Redshift
``dbt_utils.star`` output. ``compile_entity(..., "AzureSynapse")``, ``"Postgres"``
and ``"TotallyUnknown"`` all returned plausible-looking Redshift SQL and nothing
said a word (measured 2026-10-18).

There were four lists that disagreed: mesa-core's compiler knew ``Synapse``,
governance's schemas knew four values, governance's connection schema knew three,
and ``migration_console.py`` knew six spelled ``AzureSynapse``. ``grain_guard``
knew only ``azuresqldb`` for the whole T-SQL family, so ``Synapse`` and
``AzureSQLDatabase`` both returned ``None`` and it silently fell back to probing
every dialect.

These tests pin the single source of truth and the loud failure.
"""

import pytest

from mesa_core.model import Entity, Metric
from mesa_core.warehouses import (
    AZURE_SQL_DATABASE,
    BIGQUERY,
    CANONICAL_WAREHOUSES,
    DUCKDB,
    REDSHIFT,
    SNOWFLAKE,
    SYNAPSE,
    TSQL_WAREHOUSES,
    UnknownWarehouseError,
    is_combiner_warehouse,
    is_known_warehouse,
    is_tsql,
    normalize_warehouse,
    sqlglot_dialect,
    try_normalize_warehouse,
    try_sqlglot_dialect,
)
from mesa_core.compiler.query_compiler import compile_entity
from mesa_core.validate.grain_guard import _sqlglot_dialect_for_warehouse


# ── The canonical list ───────────────────────────────────────────────────────

def test_exactly_six_canonical_warehouses():
    """SPEC_69 investigated Postgres, Databricks and SQL Server — not targets."""
    assert len(CANONICAL_WAREHOUSES) == 6
    assert set(CANONICAL_WAREHOUSES) == {
        SNOWFLAKE, BIGQUERY, REDSHIFT, SYNAPSE, AZURE_SQL_DATABASE, DUCKDB,
    }


def test_tsql_family_is_the_two_targets():
    assert set(TSQL_WAREHOUSES) == {SYNAPSE, AZURE_SQL_DATABASE}


# ── normalize_warehouse: canonical names and aliases ─────────────────────────

@pytest.mark.parametrize("name", CANONICAL_WAREHOUSES)
def test_canonical_names_normalize_to_themselves(name):
    assert normalize_warehouse(name) == name


@pytest.mark.parametrize("spelling", ["snowflake", "SNOWFLAKE", "SnowFlake", " sf "])
def test_snowflake_spellings(spelling):
    assert normalize_warehouse(spelling) == SNOWFLAKE


@pytest.mark.parametrize("spelling", ["bigquery", "BigQuery", "bq", "googlebigquery"])
def test_bigquery_spellings(spelling):
    assert normalize_warehouse(spelling) == BIGQUERY


@pytest.mark.parametrize("spelling", ["redshift", "Redshift", "rs"])
def test_redshift_spellings(spelling):
    assert normalize_warehouse(spelling) == REDSHIFT


@pytest.mark.parametrize(
    "spelling",
    ["Synapse", "synapse", "AzureSynapse", "azuresynapse", "SynapseDedicated",
     "SynapseDedicatedSQLPool", "azuresynapseanalytics"],
)
def test_synapse_spellings_all_resolve(spelling):
    """Governance and the migration console spell this ``AzureSynapse``;
    mesa-core historically spelled it ``Synapse``. Both must land on one name."""
    assert normalize_warehouse(spelling) == SYNAPSE


@pytest.mark.parametrize(
    "spelling",
    ["AzureSQLDatabase", "azuresqldatabase", "azuresqldb", "AzureSQL",
     "azure_sql_db", "azure_sql_database", "SQLDatabase"],
)
def test_azure_sql_spellings_all_resolve(spelling):
    assert normalize_warehouse(spelling) == AZURE_SQL_DATABASE


@pytest.mark.parametrize("spelling", ["duckdb", "DuckDB", "duck"])
def test_duckdb_spellings(spelling):
    assert normalize_warehouse(spelling) == DUCKDB


# ── The loud failure ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name", ["Postgres", "postgresql", "Databricks", "SQLServer", "TotallyUnknown", "", "   ", None]
)
def test_unknown_names_raise(name):
    """The old behavior was to fall through to Redshift output. That's the bug."""
    with pytest.raises(UnknownWarehouseError):
        normalize_warehouse(name)


def test_error_message_lists_the_valid_names():
    with pytest.raises(UnknownWarehouseError) as exc:
        normalize_warehouse("Postgres")
    message = str(exc.value)
    for name in CANONICAL_WAREHOUSES:
        assert name in message
    assert "Postgres" in message


def test_unknown_warehouse_error_is_a_value_error():
    """Existing ``except ValueError`` handlers keep working."""
    with pytest.raises(ValueError):
        normalize_warehouse("Postgres")


def test_try_normalize_returns_none_instead_of_raising():
    assert try_normalize_warehouse("Postgres") is None
    assert try_normalize_warehouse(None) is None
    assert try_normalize_warehouse("Synapse") == SYNAPSE


def test_is_known_warehouse():
    assert is_known_warehouse("AzureSynapse")
    assert not is_known_warehouse("Postgres")


# ── sqlglot dialect mapping ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "warehouse,expected",
    [
        (SNOWFLAKE, "snowflake"),
        (BIGQUERY, "bigquery"),
        (REDSHIFT, "redshift"),
        (DUCKDB, "duckdb"),
        (SYNAPSE, "tsql"),
        (AZURE_SQL_DATABASE, "tsql"),
    ],
)
def test_sqlglot_dialect(warehouse, expected):
    assert sqlglot_dialect(warehouse) == expected


def test_sqlglot_dialect_raises_for_unknown():
    with pytest.raises(UnknownWarehouseError):
        sqlglot_dialect("Postgres")


def test_try_sqlglot_dialect_returns_none_for_unknown():
    assert try_sqlglot_dialect("Postgres") is None


def test_is_tsql():
    assert is_tsql("Synapse")
    assert is_tsql("AzureSynapse")
    assert is_tsql("azuresqldb")
    assert not is_tsql("Snowflake")
    assert not is_tsql("Postgres")


def test_is_combiner_warehouse():
    """Snowflake + the two T-SQL targets emit a combiner; the other three don't."""
    assert is_combiner_warehouse("Snowflake")
    assert is_combiner_warehouse("Synapse")
    assert is_combiner_warehouse("AzureSQLDatabase")
    assert not is_combiner_warehouse("BigQuery")
    assert not is_combiner_warehouse("Redshift")
    assert not is_combiner_warehouse("DuckDB")


# ── grain_guard now resolves every T-SQL spelling ────────────────────────────

@pytest.mark.parametrize("spelling", ["Synapse", "AzureSynapse", "AzureSQLDatabase", "azuresqldb"])
def test_grain_guard_resolves_tsql_for_every_spelling(spelling):
    """Before this slice only ``azuresqldb`` mapped; the other three returned
    None and grain_guard silently probed every dialect instead of parsing T-SQL."""
    assert _sqlglot_dialect_for_warehouse(spelling) == "tsql"


def test_grain_guard_returns_none_for_unknown():
    assert _sqlglot_dialect_for_warehouse("Postgres") is None
    assert _sqlglot_dialect_for_warehouse(None) is None


# ── compile_entity: the three-way unknown-name probe ─────────────────────────

def _entity(warehouse: str) -> Entity:
    return Entity(
        entity_name="Policy",
        base_table_name="Policy",
        source_name="rten",
        warehouse=warehouse,
        identity_column="ID",
    )


def _metric() -> Metric:
    return Metric(
        metric_name="NumberOfPolicies",
        entity_name="Policy",
        definition_sql=(
            "SELECT Policy.ID, COUNT(Policy.ID) AS NumberOfPolicies\n"
            "FROM {{ ref('PolicyRaw') }} AS Policy\n"
            "GROUP BY Policy.ID\n"
        ),
    )


@pytest.mark.parametrize("name", ["Postgres", "TotallyUnknown", "Databricks"])
def test_unknown_warehouse_raises_instead_of_emitting_redshift_sql(name):
    """The acceptance criterion: the unknown-name probe from the SPEC_103 table
    raises instead of emitting Redshift SQL.

    Note ``AzureSynapse`` is deliberately NOT in this list. The spec's probe
    listed it as one of the three names that silently compiled as Redshift, but
    the correct fix for that one is to ACCEPT it — governance and the migration
    console both spell Synapse that way. It resolves to ``Synapse`` now (see
    ``test_synapse_spellings_all_resolve``); the genuinely unknown names raise.
    """
    with pytest.raises(UnknownWarehouseError):
        compile_entity(_entity(name), [_metric()], name)


def test_governance_synapse_spelling_compiles_as_synapse_not_redshift():
    """``AzureSynapse`` used to fall through to Redshift output. It must now
    compile as T-SQL."""
    result = compile_entity(_entity("AzureSynapse"), [_metric()], "AzureSynapse")
    assert result.warehouse == SYNAPSE
    assert "dbt_utils.star" not in result.compiled_widetable_sql
    assert result.compiled_combiner_sql  # T-SQL targets emit a combiner


@pytest.mark.parametrize("name", CANONICAL_WAREHOUSES)
def test_every_canonical_name_compiles(name):
    result = compile_entity(_entity(name), [_metric()], name)
    assert result.compiled_widetable_sql
    assert result.warehouse == name


def test_compile_entity_normalizes_the_stored_warehouse():
    """An entity stored with the governance spelling compiles as the canonical
    one, and the result reports the canonical name."""
    result = compile_entity(_entity("AzureSynapse"), [_metric()], "AzureSynapse")
    assert result.warehouse == SYNAPSE


def test_synapse_and_azure_sql_share_the_tsql_wide_shape():
    synapse = compile_entity(_entity("Synapse"), [_metric()], "Synapse")
    azure = compile_entity(_entity("AzureSQLDatabase"), [_metric()], "AzureSQLDatabase")
    assert synapse.compiled_widetable_sql == azure.compiled_widetable_sql
    assert synapse.compiled_combiner_sql == azure.compiled_combiner_sql


def test_redshift_and_duckdb_share_the_wildcard_shape():
    redshift = compile_entity(_entity("Redshift"), [_metric()], "Redshift")
    duckdb = compile_entity(_entity("DuckDB"), [_metric()], "DuckDB")
    assert redshift.compiled_widetable_sql == duckdb.compiled_widetable_sql
    assert "dbt_utils.star" in redshift.compiled_widetable_sql


def test_unknown_name_does_not_produce_redshift_sql():
    """The specific regression: a typo used to yield dbt_utils.star output."""
    with pytest.raises(UnknownWarehouseError):
        compile_entity(_entity("Postgres"), [_metric()], "Postgres")
