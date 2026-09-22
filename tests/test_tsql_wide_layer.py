# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
test_tsql_wide_layer.py — SPEC_76 (T-SQL wide-layer render).

Prove the Synapse Dedicated + Azure SQL Database wide render emits the
flat-typed-CAST combiner form validated by SPEC_69a_BUILD / SPEC_69_BUILD_B:
a per-entity typed metric combiner (``CAST(COALESCE(...) AS <tsql_type>)`` per
metric) plus a plain flat wide join. Both targets have no native nested type,
so they share the SAME branch.
"""

from mesa_core.model import Entity, Metric
from mesa_core.compiler.query_compiler import compile_entity
from mesa_core.compiler.wide_type import resolve_tsql_type


def _customer_entity(warehouse: str) -> Entity:
    return Entity(
        entity_name="Customer",
        base_table_name="Customer",
        source_name="crm",
        warehouse=warehouse,
        identity_column="ID",
    )


def _customer_metrics() -> list[Metric]:
    return [
        Metric(
            metric_name="IsNewCustomer",
            entity_name="Customer",
            definition_sql=(
                "SELECT Customer.ID\n"
                "    , CASE WHEN Customer.CreatedAt >= DATEADD(day, -90, Dataset.MaxDate) THEN 1 ELSE 0 END AS IsNewCustomer\n"
                "FROM {{ ref('CustomerRaw') }} AS Customer\n"
            ),
        ),
        Metric(
            metric_name="TotalOrderCount",
            entity_name="Customer",
            definition_sql=(
                "SELECT Customer.ID, COUNT(DISTINCT Orders.ID) AS TotalOrderCount\n"
                "FROM {{ ref('CustomerRaw') }} AS Customer\n"
                "JOIN {{ source('crm', 'orders') }} AS Orders ON Orders.customer_id = Customer.ID\n"
                "GROUP BY Customer.ID\n"
            ),
        ),
        Metric(
            metric_name="TotalLifetimeValue",
            entity_name="Customer",
            definition_sql=(
                "SELECT Customer.ID, SUM(Orders.TotalPrice) AS TotalLifetimeValue\n"
                "FROM {{ ref('CustomerRaw') }} AS Customer\n"
                "JOIN {{ source('crm', 'orders') }} AS Orders ON Orders.customer_id = Customer.ID\n"
                "GROUP BY Customer.ID\n"
            ),
        ),
        Metric(
            metric_name="AvgSatisfactionScore",
            entity_name="Customer",
            definition_sql=(
                "SELECT Customer.ID, AVG(Survey.Score) AS AvgSatisfactionScore\n"
                "FROM {{ ref('CustomerRaw') }} AS Customer\n"
                "JOIN {{ source('crm', 'survey') }} AS Survey ON Survey.customer_id = Customer.ID\n"
                "GROUP BY Customer.ID\n"
            ),
        ),
    ]


def test_tsql_combiner_has_one_typed_cast_column_per_metric():
    for warehouse in ("Synapse", "AzureSQLDatabase"):
        entity = _customer_entity(warehouse)
        result = compile_entity(entity, _customer_metrics(), warehouse)

        combiner_sql = result.compiled_combiner_sql
        assert combiner_sql, f"combiner must be emitted for {warehouse}"

        # Header identifies the T-SQL combiner.
        assert "-- METRIC COMBINER: Customer Metrics (AUTO-GENERATED)" in combiner_sql

        # Flag → BIT; count → BIGINT; money SUM → DECIMAL(18,2); AVG (no
        # zero-fill default) → CAST through with FLOAT, NULL-preserving.
        assert "CAST(COALESCE(IsNewCustomer.IsNewCustomer, 0) AS BIT) AS IsNewCustomer" in combiner_sql
        assert "CAST(COALESCE(TotalOrderCount.TotalOrderCount, 0) AS BIGINT) AS TotalOrderCount" in combiner_sql
        assert "CAST(COALESCE(TotalLifetimeValue.TotalLifetimeValue, 0.0) AS DECIMAL(18,2)) AS TotalLifetimeValue" in combiner_sql

        # AVG metric has no safe zero-fill — NULL passes through (never a zero score).
        assert "CAST(AvgSatisfactionScore.AvgSatisfactionScore AS FLOAT) AS AvgSatisfactionScore" in combiner_sql
        assert "COALESCE(AvgSatisfactionScore" not in combiner_sql

        # One LEFT JOIN per metric, anchored on the raw model.
        assert "FROM {{ ref('CustomerRaw') }} AS Customer" in combiner_sql
        body = combiner_sql.split("SELECT\n", 1)[1]
        assert body.count("LEFT JOIN") == 4


def test_tsql_wide_is_flat_join_to_combiner():
    for warehouse in ("Synapse", "AzureSQLDatabase"):
        entity = _customer_entity(warehouse)
        result = compile_entity(entity, _customer_metrics(), warehouse)

        wide_sql = result.compiled_widetable_sql

        # Flat qualified-wildcard join — no nested type construction.
        assert "Customer.*" in wide_sql
        assert "CustomerMetrics.*" in wide_sql
        assert "OBJECT_CONSTRUCT" not in wide_sql
        assert "::OBJECT(" not in wide_sql
        assert "STRUCT" not in wide_sql

        # One join, to the combiner model.
        assert "LEFT JOIN {{ ref('customer_metrics') }} AS CustomerMetrics" in wide_sql
        assert "ON Customer.ID = CustomerMetrics.ID" in wide_sql
        body = wide_sql.split("SELECT\n", 1)[1]
        assert body.count("JOIN") == 1


def test_tsql_combiner_inner_join_for_inner_entity():
    entity = Entity(
        entity_name="Policy",
        base_table_name="Policy",
        source_name="rten",
        warehouse="Synapse",
        identity_column="ID",
        wide_join_type="INNER",
    )
    metrics = [
        Metric(
            metric_name="InForce90Flag",
            entity_name="Policy",
            definition_sql="SELECT Policy.ID, IFF(Policy.InForce, 1, 0) AS InForce90Flag FROM {{ ref('PolicyRaw') }} AS Policy",
        ),
    ]
    result = compile_entity(entity, metrics, "Synapse")
    assert "INNER JOIN {{ ref('policy_metrics') }} AS PolicyMetrics" in result.compiled_widetable_sql


def test_tsql_combiner_empty_entity_no_joins():
    entity = _customer_entity("Synapse")
    result = compile_entity(entity, [], "Synapse")
    assert "FROM {{ ref('CustomerRaw') }} AS Customer" in result.compiled_combiner_sql
    body = result.compiled_combiner_sql.split("FROM", 1)[1]
    assert "JOIN" not in body


def test_tsql_type_inference_warnings_present_for_unannotated():
    entity = _customer_entity("Synapse")
    result = compile_entity(entity, _customer_metrics(), "Synapse")
    # All four metrics lack a -- WIDE_TYPE_TSQL: annotation → all warned.
    assert len(result.type_inference_warnings) == 4
    assert any("IsNewCustomer" in w and "BIT" in w for w in result.type_inference_warnings)
    assert any("TotalLifetimeValue" in w and "DECIMAL(18,2)" in w for w in result.type_inference_warnings)


def test_tsql_no_type_warnings_when_annotated():
    entity = _customer_entity("Synapse")
    metrics = [
        Metric(
            metric_name="TotalOrderCount",
            entity_name="Customer",
            definition_sql=(
                "-- WIDE_TYPE_TSQL: BIGINT\n"
                "SELECT Customer.ID, COUNT(Orders.ID) AS TotalOrderCount\n"
                "FROM {{ ref('CustomerRaw') }} AS Customer\n"
                "JOIN {{ source('crm', 'orders') }} AS Orders ON Orders.customer_id = Customer.ID\n"
                "GROUP BY Customer.ID\n"
            ),
        ),
    ]
    result = compile_entity(entity, metrics, "Synapse")
    assert result.type_inference_warnings == []


def test_annotation_wins_over_heuristic_tsql():
    sql = (
        "-- WIDE_TYPE_TSQL: DECIMAL(10,3)\n"
        "SELECT Policy.ID, SUM(Policy.Amount) AS TotalAmount\n"
        "FROM {{ ref('PolicyRaw') }} AS Policy\n"
    )
    tsql_type, inferred = resolve_tsql_type(sql)
    assert tsql_type == "DECIMAL(10,3)"
    assert inferred is False


def test_tsql_flag_heuristic_precedes_count():
    # A flag CTE contains COUNT(...) inside its body but the terminal SELECT
    # is a 0/1 flag — flag-ness must win.
    sql = (
        "SELECT Policy.ID\n"
        "    , CASE WHEN COUNT(Claims.ID) > 0 THEN 1 ELSE 0 END AS HasClaims\n"
        "FROM {{ ref('PolicyRaw') }} AS Policy\n"
    )
    tsql_type, _ = resolve_tsql_type(sql)
    assert tsql_type == "BIT"


def test_tsql_ratio_rate_heuristic():
    tsql_type, inferred = resolve_tsql_type("SELECT a / b AS Ratio FROM t")
    assert tsql_type == "DECIMAL(8,2)"
    assert inferred is True


def test_tsql_standalone_rate_heuristic():
    tsql_type, _ = resolve_tsql_type("SELECT x * 100.0 / COUNT(y) AS Rate FROM t")
    assert tsql_type == "DECIMAL(8,2)"


def test_tsql_datediff_heuristic():
    tsql_type, _ = resolve_tsql_type("SELECT DATEDIFF(day, a, b) AS D FROM t")
    assert tsql_type == "INT"


def test_tsql_fallback_varchar():
    tsql_type, inferred = resolve_tsql_type("SELECT Customer.Name AS Name FROM t")
    assert tsql_type == "VARCHAR(MAX)"
    assert inferred is True