"""
test_annotations.py — SPEC_101 Slice 1.

The bug this locks down: ``project._load_metrics`` stored only
``_strip_config_and_header(sql)`` as ``Metric.definition_sql``, and every
annotation resolver ran its regex against THAT. The leading comment block — where
``-- COMBINER_DEFAULT:`` lives — was already gone, so an annotated metric and an
unannotated one were indistinguishable and the heuristic table always won.

The second bug, masked by the first: ``-- COMBINER_DEFAULT: NONE`` returned the
literal string ``'NONE'``, which the compiler would have emitted as
``COALESCE(col, NONE)`` — invalid SQL. Both fixes ship in one commit; these tests
prove each, plus that a project with no annotations compiles byte-identically to
before (aside from the new warnings).
"""

import shutil

import pytest
from click.testing import CliRunner

from mesa_core.annotations import parse_annotations
from mesa_core.model import Entity, Metric
from mesa_core.compiler.combiner import resolve_combiner_default
from mesa_core.compiler.query_compiler import compile_entity
from mesa_core.cli import cli
from mesa_core.project import load_project


# ── parse_annotations: the reader itself ─────────────────────────────────────

def test_parse_annotations_reads_leading_block():
    text = (
        "{{ config(materialized='table') }}\n"
        "-- METRIC: Number of agent change events\n"
        "-- Owner: Analytics\n"
        "-- COMBINER_DEFAULT: NONE\n"
        "SELECT 1\n"
    )
    ann = parse_annotations(text)
    assert ann == {"COMBINER_DEFAULT": "NONE"}


def test_parse_annotations_is_case_insensitive_on_key():
    text = "-- combiner_default: 0\nSELECT 1\n"
    assert parse_annotations(text) == {"COMBINER_DEFAULT": "0"}


def test_parse_annotations_first_occurrence_wins():
    text = "-- COMBINER_DEFAULT: 0\n-- COMBINER_DEFAULT: 1\nSELECT 1\n"
    assert parse_annotations(text) == {"COMBINER_DEFAULT": "0"}


def test_parse_annotations_ignores_body_comment():
    """An annotation-looking comment inside the SQL body is not an annotation."""
    text = (
        "-- Owner: Analytics\n"
        "SELECT\n"
        "    Policy.ID\n"
        "    -- COMBINER_DEFAULT: NONE\n"
        "    , SUM(Policy.Amount) AS TotalAmount\n"
        "FROM {{ ref('PolicyRaw') }} AS Policy\n"
    )
    assert parse_annotations(text) == {}


def test_parse_annotations_reads_all_three_keys():
    text = (
        "-- COMBINER_DEFAULT: 0\n"
        "-- WIDE_TYPE: NUMBER\n"
        "-- WIDE_TYPE_TSQL: BIGINT\n"
        "SELECT 1\n"
    )
    assert parse_annotations(text) == {
        "COMBINER_DEFAULT": "0",
        "WIDE_TYPE": "NUMBER",
        "WIDE_TYPE_TSQL": "BIGINT",
    }


# ── resolve_combiner_default: annotation argument ────────────────────────────

def test_annotation_none_returns_none_not_literal():
    """`NONE` means deliberate NULL — never the literal string 'NONE'."""
    assert resolve_combiner_default("SELECT SUM(x)", "NONE") is None
    assert resolve_combiner_default("SELECT SUM(x)", "none") is None
    assert resolve_combiner_default("SELECT SUM(x)", "NULL") is None


def test_annotation_zero_wins_over_sum_heuristic():
    assert resolve_combiner_default("SELECT SUM(x)", "0") == "0"


def test_annotation_arbitrary_value_passes_through():
    assert resolve_combiner_default("SELECT x", "CURRENT_DATE()") == "CURRENT_DATE()"


def test_no_annotation_falls_through_to_heuristic():
    assert resolve_combiner_default("SELECT SUM(x)", None) == "0"
    assert resolve_combiner_default("SELECT AVG(x)", None) is None


def test_raw_text_fallback_still_guards_none():
    """A caller handing over unstripped text must not get the literal 'NONE'."""
    assert resolve_combiner_default("-- COMBINER_DEFAULT: NONE\nSELECT SUM(x)") is None


# ── Compiler: the Farmers bug ────────────────────────────────────────────────

def _entity() -> Entity:
    return Entity(
        entity_name="ChangeEvent",
        base_table_name="ChangeEvent",
        source_name="rten",
        warehouse="Snowflake",
        identity_column="ID",
    )


def _sum_metric(annotation: str | None) -> Metric:
    anns = (("COMBINER_DEFAULT", annotation),) if annotation is not None else ()
    return Metric(
        metric_name="NumberOfAgentChangeEvents",
        entity_name="ChangeEvent",
        definition_sql=(
            "SELECT\n"
            "    ChangeEvent.ID\n"
            "    , SUM(ChangeEvent.Amount) AS NumberOfAgentChangeEvents\n"
            "FROM {{ ref('ChangeEventRaw') }} AS ChangeEvent\n"
            "GROUP BY ChangeEvent.ID\n"
        ),
        annotations=anns,
    )


def test_none_annotation_emits_no_coalesce():
    """The Farmers bug: `COMBINER_DEFAULT: NONE` over a SUM must NOT zero-fill."""
    result = compile_entity(_entity(), [_sum_metric("NONE")], "Snowflake")
    assert "COALESCE(NumberOfAgentChangeEvents.NumberOfAgentChangeEvents" not in result.compiled_combiner_sql
    assert ", NumberOfAgentChangeEvents.NumberOfAgentChangeEvents\n" in result.compiled_combiner_sql


def test_zero_annotation_over_sum_emits_coalesce_zero():
    result = compile_entity(_entity(), [_sum_metric("0")], "Snowflake")
    assert "COALESCE(NumberOfAgentChangeEvents.NumberOfAgentChangeEvents, 0) AS NumberOfAgentChangeEvents" in result.compiled_combiner_sql


def test_no_annotation_sum_zero_fills_and_warns():
    result = compile_entity(_entity(), [_sum_metric(None)], "Snowflake")
    assert "COALESCE(NumberOfAgentChangeEvents.NumberOfAgentChangeEvents, 0)" in result.compiled_combiner_sql
    assert len(result.annotation_warnings) == 1
    assert "COMBINER_DEFAULT inferred as 0" in result.annotation_warnings[0]


def test_annotation_produces_no_warning():
    result = compile_entity(_entity(), [_sum_metric("0")], "Snowflake")
    assert result.annotation_warnings == []


# ── Loader wiring: annotations reach the Metric ──────────────────────────────

POLICY_METRIC_TEMPLATE = (
    "{{{{ config(materialized='table') }}}}\n"
    "-- METRIC: {desc}\n"
    "-- Owner: Analytics\n"
    "-- COMBINER_DEFAULT: {default}\n"
    "SELECT\n"
    "    Policy.ID\n"
    "    , SUM(Policy.AmountRupees) AS {name}\n"
    "FROM {{{{ ref('PolicyRaw') }}}} AS Policy\n"
    "GROUP BY Policy.ID\n"
)


def _write_project(tmp_path, metrics: dict[str, str]):
    """Create a minimal valid Snowflake project. ``metrics`` maps metric-name ->
    COMBINER_DEFAULT annotation value ("" for none). Returns the models dir."""
    root = tmp_path / "proj"
    models = root / "models"
    for layer in ("raw_layer", "metric_layer", "wide_layer", "view_layer", "sources"):
        (models / layer).mkdir(parents=True, exist_ok=True)

    (root / "mesa_project.yml").write_text("name: proj\ndefault_warehouse: Snowflake\n")

    (models / "raw_layer" / "Policy").mkdir(parents=True, exist_ok=True)
    (models / "raw_layer" / "Policy" / "PolicyRaw.sql").write_text(
        "-- RAW ENTITY: Policy\n"
        "-- Grain: one row per policy\n"
        "SELECT\n"
        "    Policy.ID\n"
        "    , Policy.AmountRupees\n"
        "FROM {{ source('rten', 'Policy') }} AS Policy\n"
    )

    metric_dir = models / "metric_layer" / "Policy_Metrics"
    metric_dir.mkdir(parents=True, exist_ok=True)
    for name, default in metrics.items():
        body = POLICY_METRIC_TEMPLATE.format(
            desc=f"Description for {name}", default=default, name=name
        )
        if not default:
            body = body.replace("-- COMBINER_DEFAULT: \n", "")
        (metric_dir / f"{name}.sql").write_text(body)

    (models / "sources" / "sources.yml").write_text(
        "version: 2\nsources:\n  - name: rten\n    database: db\n    schema: sch\n"
        "    tables:\n      - name: Policy\n"
    )
    return models


def test_loader_populates_annotation_and_strips_it_from_description(tmp_path):
    models = _write_project(tmp_path, {"NumberOfPolicies": "NONE"})
    proj = load_project(models)
    metric = next(m for m in proj.metrics if m.metric_name == "NumberOfPolicies")

    assert metric.annotation("COMBINER_DEFAULT") == "NONE"
    # The annotation must NOT leak into the human description prose.
    assert metric.description is not None
    assert "COMBINER_DEFAULT" not in metric.description
    assert "description for numberofpolicies" in metric.description.lower()


def test_project_with_no_annotations_produces_no_annotation_warnings(tmp_path):
    models = _write_project(tmp_path, {"NumberOfPolicies": ""})
    proj = load_project(models)
    metric = next(m for m in proj.metrics if m.metric_name == "NumberOfPolicies")
    assert metric.annotation("COMBINER_DEFAULT") is None

    entity = proj.entities[0]
    result = compile_entity(entity, proj.metrics, "Snowflake")
    # Un-annotated SUM → heuristic 0 + exactly one warning.
    assert len(result.annotation_warnings) == 1


# ── Round trip: mesa build then mesa build --check ───────────────────────────

def test_build_then_check_is_clean(tmp_path, monkeypatch):
    """`mesa build` writes wide + combiner; a project that commits those files
    passes `mesa build --check`. Also proves NONE survives the load→compile path."""
    models = _write_project(tmp_path, {"NumberOfPolicies": "NONE"})
    proj = load_project(models)
    entity = proj.entities[0]

    # What `mesa build` would write into models/ (no generated banner).
    compiled = compile_entity(entity, proj.metrics, "Snowflake")
    (models / "wide_layer" / "PolicyWide.sql").write_text(compiled.compiled_widetable_sql + "\n")
    (models / "metric_layer" / "policy_metrics.sql").write_text(compiled.compiled_combiner_sql + "\n")

    # The NONE annotation survived and suppressed the COALESCE.
    assert "COALESCE(NumberOfPolicies.NumberOfPolicies" not in compiled.compiled_combiner_sql

    runner = CliRunner()
    monkeypatch.chdir(tmp_path / "proj")
    result = runner.invoke(cli, ["build", "--models-dir", str(models), "--check"])
    assert result.exit_code == 0, result.output
    assert "CHECK PASSED" in result.output


def test_build_prints_annotation_warning_to_stderr(tmp_path, monkeypatch):
    models = _write_project(tmp_path, {"NumberOfPolicies": ""})
    runner = CliRunner()
    monkeypatch.chdir(tmp_path / "proj")
    result = runner.invoke(cli, ["build", "--models-dir", str(models)])
    assert result.exit_code == 0, result.output
    # CliRunner merges stderr into output by default.
    assert "COMBINER_DEFAULT inferred as 0" in result.output


# ── Regression: no-annotation combiner output is unchanged ───────────────────

def test_combiner_form_unchanged_for_unannotated_metrics():
    """The heuristic path (ChangeEvent shape) still emits exactly what it did —
    pin the assertions the SPEC_72 test file relies on."""
    metrics = [
        Metric(
            metric_name="IsAgentChangeEvent",
            entity_name="ChangeEvent",
            definition_sql="SELECT ChangeEvent.ID, IFF(ChangeEvent.EventType = 'AGENT_CHANGE', 1, 0) AS IsAgentChangeEvent FROM {{ ref('ChangeEventRaw') }} AS ChangeEvent",
        ),
        Metric(
            metric_name="RetentionRate",
            entity_name="ChangeEvent",
            definition_sql="SELECT ChangeEvent.ID, AVG(ChangeEvent.Score) AS RetentionRate FROM {{ ref('ChangeEventRaw') }} AS ChangeEvent GROUP BY ChangeEvent.ID",
        ),
    ]
    result = compile_entity(_entity(), metrics, "Snowflake")
    assert "COALESCE(IsAgentChangeEvent.IsAgentChangeEvent, 0) AS IsAgentChangeEvent" in result.compiled_combiner_sql
    assert "COALESCE(RetentionRate.RetentionRate" not in result.compiled_combiner_sql
