"""
test_wide_layer_assembly.py — SPEC_72 (combiner architecture).

Prove the Snowflake wide-layer rewrite produces CAO's decided two-OBJECT
combiner form (raw side: qualified-wildcard ``OBJECT_CONSTRUCT(alias.*)``
unless a typed column forces the explicit form; metrics side: ALWAYS
explicit key/value ``OBJECT_CONSTRUCT('MetricName', alias.MetricName, ...)``
— never the wildcard, per the 2026-09-28 key-casing fix), ONE join to a
per-entity combiner model, that the combiner model itself is emitted with
the correct COALESCE-defaulted columns, and that ``mesa build --check``
detects drift in either file.

KEY-CASING FIX (2026-09-28): Snowflake's ``OBJECT_CONSTRUCT(alias.*)``
stores each key using the column's case-folded (uppercase) name, not its
authored PascalCase name. Every consumer view accesses metrics with a
PascalCase colon-accessor — the wildcard silently NULLs every accessor with
no error. Confirmed in a real deployment where multiple consumer views
returned zero rows / "No data" despite the query succeeding. The metrics
side must always use explicit keys so the stored key text matches the
metric's authored name exactly.
"""

import pytest
from click.testing import CliRunner

from mesa_core.model import Entity, Metric
from mesa_core.compiler.query_compiler import compile_entity
from mesa_core.cli import cli


def _change_event_entity() -> Entity:
    return Entity(
        entity_name="ChangeEvent",
        base_table_name="ChangeEvent",
        source_name="rten",
        warehouse="Snowflake",
        identity_column="ID",
        wide_join_type="LEFT",
    )


def _change_event_metrics() -> list[Metric]:
    return [
        Metric(
            metric_name="IsAgentChangeEvent",
            entity_name="ChangeEvent",
            definition_sql=(
                "SELECT\n"
                "    ChangeEvent.ID\n"
                "    , IFF(ChangeEvent.EventType = 'AGENT_CHANGE', 1, 0) AS IsAgentChangeEvent\n"
                "FROM {{ ref('ChangeEventRaw') }} AS ChangeEvent\n"
            ),
        ),
        Metric(
            metric_name="IsZipChangeEvent",
            entity_name="ChangeEvent",
            definition_sql=(
                "SELECT\n"
                "    ChangeEvent.ID\n"
                "    , IFF(ChangeEvent.EventType = 'ZIP_CHANGE', 1, 0) AS IsZipChangeEvent\n"
                "FROM {{ ref('ChangeEventRaw') }} AS ChangeEvent\n"
            ),
        ),
        Metric(
            metric_name="RetentionRate",
            entity_name="ChangeEvent",
            definition_sql=(
                "SELECT\n"
                "    ChangeEvent.ID\n"
                "    , AVG(ChangeEvent.Score) AS RetentionRate\n"
                "FROM {{ ref('ChangeEventRaw') }} AS ChangeEvent\n"
                "GROUP BY ChangeEvent.ID\n"
            ),
        ),
    ]


def test_snowflake_wide_is_two_object_combiner_form():
    entity = _change_event_entity()
    metrics = _change_event_metrics()
    result = compile_entity(entity, metrics, "Snowflake")

    sql = result.compiled_widetable_sql

    # Header matches CAO's decided combiner form.
    assert "-- WIDE LAYER: ChangeEvent Wide Table (AUTO-GENERATED)" in sql

    # Raw side stays the qualified wildcard (no typed columns on this entity).
    assert "OBJECT_CONSTRUCT(ChangeEvent.*) AS ChangeEvent" in sql

    # Metrics side: explicit PascalCase key/value pairs, NOT the qualified
    # wildcard (2026-09-28 key-casing fix — see _build_widetable_snowflake
    # docstring). The wildcard silently breaks every PascalCase colon-
    # accessor because Snowflake stores the wildcard-expanded key in its
    # case-folded (uppercase) form.
    assert "OBJECT_CONSTRUCT(ChangeEventMetrics.*) AS ChangeEventMetrics" not in sql
    assert "'ID', ChangeEventMetrics.ID" in sql
    assert "'IsAgentChangeEvent', ChangeEventMetrics.IsAgentChangeEvent" in sql
    assert "'IsZipChangeEvent', ChangeEventMetrics.IsZipChangeEvent" in sql
    assert "'RetentionRate', ChangeEventMetrics.RetentionRate" in sql
    assert ") AS ChangeEventMetrics" in sql

    # ONE join, to the combiner model — not one join per metric.
    assert "LEFT JOIN {{ ref('change_event_metrics') }} AS ChangeEventMetrics" in sql
    assert "ON ChangeEvent.ID = ChangeEventMetrics.ID" in sql
    body = sql.split("SELECT\n", 1)[1]  # ignore header-comment prose mentioning "JOIN"
    assert body.count("JOIN") == 1

    # No per-metric typed casts or per-metric joins leaked into the wide file.
    assert "OBJECT_CONSTRUCT_KEEP_NULL" not in sql
    assert "as_struct" not in sql
    assert "{{ source(" not in sql


def test_snowflake_metrics_side_never_uses_wildcard_and_keys_match_metric_case():
    """Regression test for the 2026-09-28 key-casing bug: Snowflake's
    qualified-wildcard OBJECT_CONSTRUCT(alias.*) stores each key using the
    column's case-folded (uppercase) name, not its authored PascalCase name.
    Every consumer view accesses metrics with a PascalCase colon-accessor
    (e.g. PolicyMetrics:NumberOfAgentChangeEvents) — the wildcard form
    silently NULLs every one of those accessors with no error thrown.
    Confirmed in production: ChangedProducer and 3 onboarding views all
    returned zero rows / "No data" while the underlying query succeeded.
    The metrics side must ALWAYS use explicit key/value pairs so the stored
    key text matches the metric's authored PascalCase name exactly."""
    entity = _change_event_entity()
    metrics = _change_event_metrics()
    result = compile_entity(entity, metrics, "Snowflake")
    sql = result.compiled_widetable_sql

    # No CODE line emits the wildcard on the metrics side (explanatory
    # header comments are allowed to mention the pattern by name).
    code_lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    code_only = "\n".join(code_lines)
    assert "OBJECT_CONSTRUCT(ChangeEventMetrics.*)" not in code_only

    for metric in metrics:
        assert f"'{metric.metric_name}', ChangeEventMetrics.{metric.metric_name}" in sql


def test_snowflake_inner_join_for_inner_entity():
    entity = Entity(
        entity_name="Policy",
        base_table_name="Policy",
        source_name="rten",
        warehouse="Snowflake",
        identity_column="ID",
        wide_join_type="INNER",
    )
    metrics = [
        Metric(
            metric_name="InForce90Flag",
            entity_name="Policy",
            definition_sql="SELECT Policy.ID, IFF(x, 1, 0) AS InForce90Flag FROM {{ ref('PolicyRaw') }} AS Policy",
        ),
    ]
    result = compile_entity(entity, metrics, "Snowflake")
    sql = result.compiled_widetable_sql
    assert "INNER JOIN {{ ref('policy_metrics') }} AS PolicyMetrics" in sql
    body = sql.split("SELECT\n", 1)[1]  # ignore header-comment prose mentioning "JOIN"
    assert body.count("JOIN") == 1


def test_no_type_inference_warnings_for_combiner_form():
    """The combiner form has no per-metric ``::OBJECT(TYPE)`` cast — there is
    nothing to infer a type for, so no warnings should ever be produced."""
    entity = _change_event_entity()
    metrics = _change_event_metrics()
    result = compile_entity(entity, metrics, "Snowflake")
    assert result.type_inference_warnings == []


# ── Combiner model itself ───────────────────────────────────────────────────

def test_combiner_sql_has_one_left_join_per_metric_and_coalesce_defaults():
    entity = _change_event_entity()
    metrics = _change_event_metrics()
    result = compile_entity(entity, metrics, "Snowflake")

    combiner_sql = result.compiled_combiner_sql
    assert combiner_sql  # non-empty for Snowflake

    assert "-- METRIC COMBINER: ChangeEvent Metrics (AUTO-GENERATED)" in combiner_sql
    assert "FROM {{ ref('ChangeEventRaw') }} AS ChangeEvent" in combiner_sql

    # One LEFT JOIN per metric file inside the combiner.
    assert "LEFT JOIN IsAgentChangeEvent" in combiner_sql
    assert "LEFT JOIN IsZipChangeEvent" in combiner_sql
    assert "LEFT JOIN RetentionRate" in combiner_sql

    # IFF(cond, 1, 0)-shaped metrics get a COALESCE(..., 0) default.
    assert "COALESCE(IsAgentChangeEvent.IsAgentChangeEvent, 0) AS IsAgentChangeEvent" in combiner_sql
    assert "COALESCE(IsZipChangeEvent.IsZipChangeEvent, 0) AS IsZipChangeEvent" in combiner_sql

    # AVG(...)-shaped metrics (survey/score style) pass through with NO
    # COALESCE — NULL must never be zero-filled for a score.
    assert "COALESCE(RetentionRate.RetentionRate" not in combiner_sql
    assert ", RetentionRate.RetentionRate\n" in combiner_sql


def test_combiner_sql_empty_entity_has_no_joins():
    entity = Entity(
        entity_name="Contact",
        base_table_name="Contact",
        source_name="rten",
        warehouse="Snowflake",
        identity_column="ID",
    )
    result = compile_entity(entity, [], "Snowflake")
    assert "FROM {{ ref('ContactRaw') }} AS Contact" in result.compiled_combiner_sql
    body = result.compiled_combiner_sql.split("FROM", 1)[1]  # ignore header-comment prose mentioning "JOIN"
    assert "JOIN" not in body


def test_typed_object_raw_column_uses_explicit_object_construct():
    """Verified 2026-09-23 against real Farmers PolicyRaw: Snowflake's
    OBJECT_CONSTRUCT(alias.*) wildcard cannot expand a raw column that is
    itself a typed OBJECT(...)/ARRAY(OBJECT(...)) — raises "Function
    OBJECT_CONSTRUCT(*) does not support OBJECT(...) argument type". When the
    raw entity's own definition_sql has such a column, the wide render must
    switch the RAW side to the explicit key/value form with ::VARIANT casts
    on the typed columns — the combiner side is unaffected."""
    entity = Entity(
        entity_name="Policy",
        base_table_name="Policy",
        source_name="rten",
        warehouse="Snowflake",
        identity_column="ID",
        wide_join_type="INNER",
        definition_sql=(
            "SELECT\n"
            "    BASE64_ENCODE(SHA2(Policy.PLCY_CNTRCT_NUM, 256)) AS ID\n"
            "    , Policy.BUS_ENTITY AS BusinessEntity\n"
            "    , OBJECT_CONSTRUCT_KEEP_NULL(\n"
            "        'RtenPlcyCntrctNum', CAST(Policy.PLCY_CNTRCT_NUM AS VARCHAR)\n"
            "    )::OBJECT(\n"
            "        RtenPlcyCntrctNum VARCHAR\n"
            "    ) AS SystemIds\n"
            "    , COALESCE(\n"
            "        PolicyMonthlyHistory.MonthlySnapshots::ARRAY (OBJECT(\n"
            "            LoadYearMonthNum NUMBER\n"
            "        ))\n"
            "        , ARRAY_CONSTRUCT()::ARRAY (OBJECT(\n"
            "            LoadYearMonthNum NUMBER\n"
            "        ))\n"
            "    ) AS MonthlySnapshots\n"
            "FROM {{ source('rten', 'rten_xcmpy_pif_tbl') }} AS Policy\n"
            "LEFT JOIN PolicyMonthlyHistory\n"
            "    ON Policy.PLCY_CNTRCT_NUM = PolicyMonthlyHistory.PLCY_CNTRCT_NUM\n"
        ),
    )
    metrics = [
        Metric(
            metric_name="InForce90Flag",
            entity_name="Policy",
            definition_sql="SELECT Policy.ID, IFF(x, 1, 0) AS InForce90Flag FROM {{ ref('PolicyRaw') }} AS Policy",
        ),
    ]
    result = compile_entity(entity, metrics, "Snowflake")
    sql = result.compiled_widetable_sql

    # RAW side: explicit key/value form, typed columns cast to ::VARIANT.
    assert "OBJECT_CONSTRUCT(Policy.*) AS Policy" not in sql
    assert "'ID', Policy.ID" in sql
    assert "'BusinessEntity', Policy.BusinessEntity" in sql
    assert "'SystemIds', Policy.SystemIds::VARIANT" in sql
    assert "'MonthlySnapshots', Policy.MonthlySnapshots::VARIANT" in sql

    # COMBINER side: also explicit key/value form (2026-09-28 key-casing
    # fix) — never the qualified wildcard, regardless of whether the raw
    # side needed the typed-column workaround.
    assert "OBJECT_CONSTRUCT(PolicyMetrics.*) AS PolicyMetrics" not in sql
    assert "'ID', PolicyMetrics.ID" in sql
    assert "'InForce90Flag', PolicyMetrics.InForce90Flag" in sql
    assert "INNER JOIN {{ ref('policy_metrics') }} AS PolicyMetrics" in sql


def test_untyped_raw_columns_keep_wildcard_form():
    """A raw entity with only flat/scalar columns must keep emitting the
    zero-maintenance wildcard — this is the 100%-backward-compatible path
    every existing entity (ChangeEvent, Contact, ...) relies on."""
    entity = Entity(
        entity_name="Contact",
        base_table_name="Contact",
        source_name="rten",
        warehouse="Snowflake",
        identity_column="ID",
        definition_sql=(
            "SELECT\n"
            "    Contact.ID AS ID\n"
            "    , Contact.Name AS Name\n"
            "FROM {{ source('rten', 'contact') }} AS Contact\n"
        ),
    )
    result = compile_entity(entity, [], "Snowflake")
    sql = result.compiled_widetable_sql
    assert "OBJECT_CONSTRUCT(Contact.*) AS Contact" in sql


def test_unparseable_raw_sql_falls_back_to_wildcard():
    """If the raw entity's definition_sql can't be confidently parsed (e.g.
    empty, or no depth-0 SELECT/FROM pair), never guess — fall back to the
    previously-working wildcard form."""
    entity = Entity(
        entity_name="Contact",
        base_table_name="Contact",
        source_name="rten",
        warehouse="Snowflake",
        identity_column="ID",
        definition_sql="",
    )
    result = compile_entity(entity, [], "Snowflake")
    sql = result.compiled_widetable_sql
    assert "OBJECT_CONSTRUCT(Contact.*) AS Contact" in sql


def test_bigquery_and_redshift_have_no_combiner():
    """The combiner model is Snowflake-only — every other dialect's wide
    render works directly against the entity's existing combined metric
    model, so ``compiled_combiner_sql`` must stay empty."""
    entity = _change_event_entity()
    metrics = _change_event_metrics()

    for warehouse in ("BigQuery", "Redshift", "DuckDB"):
        entity_for_wh = Entity(
            entity_name=entity.entity_name,
            base_table_name=entity.base_table_name,
            source_name=entity.source_name,
            warehouse=warehouse,
            identity_column="ID",
        )
        result = compile_entity(entity_for_wh, metrics, warehouse)
        assert result.compiled_combiner_sql == ""


# ── Slice 5: mesa build --check drift mode (now covers the combiner too) ───

def _write_check_fixture(root):
    (root / "mesa_project.yml").write_text(
        "name: fixture\nversion: '1.0.0'\ndefault_warehouse: Snowflake\nmodel-paths: ['models']\n"
    )
    models = root / "models"
    (models / "raw_layer" / "Customer").mkdir(parents=True)
    (models / "raw_layer" / "Customer" / "CustomerRaw.sql").write_text(
        "-- RAW ENTITY: Customer\n"
        "-- Grain: one row per customer\n"
        "SELECT\n"
        "    TO_BASE64(SHA256(CAST(Customer.customer_id AS STRING))) AS ID\n"
        "    , Customer.name AS Name\n"
        "FROM {{ source('crm', 'customer') }} AS Customer\n"
    )
    (models / "metric_layer" / "Customer_Metrics").mkdir(parents=True)
    (models / "metric_layer" / "Customer_Metrics" / "NumberOfOrders.sql").write_text(
        "SELECT Customer.ID, COUNT(Orders.order_id) AS NumberOfOrders\n"
        "FROM {{ ref('CustomerRaw') }} AS Customer\n"
        "JOIN {{ source('crm', 'orders') }} AS Orders ON Orders.customer_id = Customer.ID\n"
        "GROUP BY Customer.ID\n"
    )
    (models / "wide_layer").mkdir(parents=True)
    return models


def _commit_generated_wide_and_combiner(tmp_path, models):
    """Run build(), then copy the generated wide + combiner SQL into
    models/ so they're "committed" (mirrors what a real repo would have)."""
    from mesa_core.project import load_project
    from mesa_core import build as _build
    from mesa_core.build import _GENERATED_BANNER

    proj = load_project(models)
    _build.build(proj, target_dir=tmp_path / "target")

    wide_sql = (tmp_path / "target" / "wide_layer" / "CustomerWide.sql").read_text()
    committed_wide = wide_sql[len(_GENERATED_BANNER):].strip() + "\n"
    (models / "wide_layer" / "CustomerWide.sql").write_text(committed_wide)

    combiner_sql = (tmp_path / "target" / "metric_layer" / "customer_metrics.sql").read_text()
    committed_combiner = combiner_sql[len(_GENERATED_BANNER):].strip() + "\n"
    (models / "metric_layer" / "customer_metrics.sql").write_text(committed_combiner)

    return proj


def test_check_passes_when_up_to_date(tmp_path):
    from mesa_core import build as _build

    models = _write_check_fixture(tmp_path)
    proj = _commit_generated_wide_and_combiner(tmp_path, models)

    drifted = _build.check_wide_layer(proj, models)
    assert drifted == []


def test_check_detects_stale_wide(tmp_path):
    from mesa_core.project import load_project
    from mesa_core import build as _build

    models = _write_check_fixture(tmp_path)
    # Committed wide file is deliberately stale (old per-metric form).
    (models / "wide_layer" / "CustomerWide.sql").write_text(
        "-- WIDE LAYER: Customer Wide Table\n"
        "-- STALE — missing the combiner join\n"
        "SELECT\n"
        "    Customer.Customer AS Customer\n"
        "FROM {{ ref('CustomerRaw') }} AS Customer\n"
    )

    proj = load_project(models)
    drifted = _build.check_wide_layer(proj, models)
    assert drifted == ["Customer"]


def test_check_detects_stale_combiner_even_if_wide_matches(tmp_path):
    """Drift can hide in the combiner model even when the wide file itself
    is byte-correct — the check must inspect both, not just the wide file."""
    from mesa_core import build as _build

    models = _write_check_fixture(tmp_path)
    proj = _commit_generated_wide_and_combiner(tmp_path, models)

    # Now make the committed combiner stale (as if a metric was added/removed
    # without regenerating).
    (models / "metric_layer" / "customer_metrics.sql").write_text(
        "-- STALE combiner — missing NumberOfOrders\n"
        "SELECT\n"
        "    Customer.ID\n"
        "FROM {{ ref('CustomerRaw') }} AS Customer\n"
    )

    drifted = _build.check_wide_layer(proj, models)
    assert drifted == ["Customer"]


def test_check_cli_exits_nonzero_on_drift(tmp_path):
    models = _write_check_fixture(tmp_path)
    (models / "wide_layer" / "CustomerWide.sql").write_text("-- stale\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["build", "--check", "--models-dir", str(models)])
    assert result.exit_code != 0
    assert "CustomerWide.sql" in result.output


def test_check_cli_passes_when_clean(tmp_path):
    models = _write_check_fixture(tmp_path)
    _commit_generated_wide_and_combiner(tmp_path, models)

    runner = CliRunner()
    res = runner.invoke(cli, ["build", "--check", "--models-dir", str(models)])
    assert res.exit_code == 0, res.output
    assert "PASSED" in res.output
