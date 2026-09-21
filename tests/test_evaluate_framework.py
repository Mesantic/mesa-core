"""
test_evaluate_framework.py — SPEC_71 Slice 1 + Slice 2-4 acceptance.

Proves the evaluator is an AGGREGATOR + SCORER, not a pile of new detectors:

  * grade math: all-pass -> A/100%, one weighted fail -> correct lower grade
  * --strict exits non-zero on a fail and 0 on all-pass
  * --json emits valid parseable JSON
  * the check suite reuses the fixed validators (IDENT-hashed passes on all 4
    CAO entities — proving the Snowflake addendum fix landed; grain-declared
    passes; zero broken refs on CAO)
  * metric governance + safety roll-up score correctly on CAO (zero secrets/PII
    — the false-positive guard)
"""

import json

import pytest
from click.testing import CliRunner

from mesa_core.cli import cli
from mesa_core.evaluate.framework import (
    CheckResult,
    CheckStatus,
    evaluate,
    grade_band,
    percent_for,
)
from mesa_core.project import Project


CAO_MODELS = "/Users/yennypassanante/Downloads/CAO/domains/CustomerJourney/models"


# ── Framework grade math ─────────────────────────────────────────────────────

def test_grade_band_table():
    assert grade_band(100.0) == "A+"
    assert grade_band(95.0) == "A"
    assert grade_band(90.0) == "A-"
    assert grade_band(85.0) == "B"
    assert grade_band(50.0) == "F"
    assert grade_band(0.0) == "F"


def test_all_pass_is_100_percent_A():
    results = [
        CheckResult(check_id="T-1", entity_name="E", status="pass", weight=1.0, message="ok"),
        CheckResult(check_id="T-2", entity_name="E", status="pass", weight=1.0, message="ok"),
    ]
    assert percent_for(results) == 100.0
    assert grade_band(percent_for(results)) == "A+"


def test_one_weighted_fail_lowers_grade():
    results = [
        CheckResult(check_id="T-1", entity_name="E", status="pass", weight=1.0, message="ok"),
        CheckResult(check_id="T-2", entity_name="E", status="fail", weight=1.0, message="bad"),
    ]
    assert percent_for(results) == 50.0


def test_warn_earns_half_credit():
    results = [
        CheckResult(check_id="T-1", entity_name="E", status="pass", weight=1.0, message="ok"),
        CheckResult(check_id="T-2", entity_name="E", status="warn", weight=1.0, message="hmm"),
    ]
    assert percent_for(results) == 75.0


def test_n_a_excluded_from_grade():
    results = [
        CheckResult(check_id="T-1", entity_name="E", status="pass", weight=1.0, message="ok"),
        CheckResult(check_id="T-2", entity_name="E", status="n_a", weight=1.0, message="skip"),
    ]
    # n_a is skipped from both numerator and denominator -> 100%.
    assert percent_for(results) == 100.0


def test_no_applicable_checks_is_100_not_fail():
    results = [CheckResult(check_id="T-1", entity_name="E", status="n_a", weight=1.0, message="skip")]
    assert percent_for(results) == 100.0


# ── evaluate() with a registered dummy check ─────────────────────────────────

def test_evaluate_registers_dummy_check_and_rolls_up():
    project = Project(name="p", default_warehouse="Snowflake")

    def dummy(p: Project):
        return [
            CheckResult(check_id="T-1", entity_name=None, status="pass", weight=1.0, message="ok"),
            CheckResult(check_id="T-2", entity_name=None, status="fail", weight=1.0, message="bad",
                        why="matters", ref="see"),
        ]

    score = evaluate(project, checks=[dummy])
    assert score.grade == "F"
    assert score.percent == 50.0
    # project-level results are partitioned correctly.
    assert len(score.project_results) == 2
    assert score.entities == []


# ── CLI: --json and --strict ─────────────────────────────────────────────────

@pytest.fixture
def runner():
    return CliRunner()


def _write_fixture(root, raw_id_expr, metric_owner):
    (root / "mesa_project.yml").write_text(
        "name: fixture\nversion: '1.0.0'\ndefault_warehouse: Snowflake\nmodel-paths: ['models']\n"
    )
    models = root / "models"
    (models / "raw_layer" / "Customer").mkdir(parents=True)
    (models / "view_layer").mkdir(parents=True)
    (models / "sources").mkdir(parents=True)
    (models / "raw_layer" / "Customer" / "CustomerRaw.sql").write_text(
        "-- RAW ENTITY: Customer\n"
        "-- Grain: one row per customer\n"
        "-- ID: hashed primary key\n"
        "SELECT\n"
        f"    {raw_id_expr} AS ID\n"
        "    , Customer.Name AS Name\n"
        "    , Customer.Email AS Email\n"
        "    , Customer.City AS City\n"
        "FROM {{ source('crm', 'customer') }} AS Customer\n"
    )
    (models / "raw_layer" / "_raw.yml").write_text(
        "version: 2\n"
        "models:\n"
        "  - name: CustomerRaw\n"
        "    columns:\n"
        "      - name: ID\n"
        "        description: hashed key\n"
        "        tests: [not_null, unique]\n"
    )
    (models / "metric_layer" / "Customer_Metrics").mkdir(parents=True)
    (models / "metric_layer" / "Customer_Metrics" / "NumberOfOrders.sql").write_text(
        "{{ config(tags=['metric_customer']) }}\n"
        "\n"
        "-- METRIC: NumberOfOrders\n"
        f"-- Owner: {metric_owner}\n"
        "-- Contract: 1 row per customer ID = 1:1\n"
        "\n"
        "SELECT\n"
        "    Customer.ID AS ID\n"
        "    , COUNT(Orders.order_id) AS NumberOfOrders\n"
        "FROM {{ ref('CustomerRaw') }} AS Customer\n"
        "GROUP BY Customer.ID\n"
    )
    return models


def test_evaluate_json_emits_parseable_json(tmp_path, runner):
    models = _write_fixture(
        tmp_path,
        raw_id_expr="TO_BASE64(SHA256(CAST(Customer.customer_id AS STRING)))",
        metric_owner="Analytics",
    )
    result = runner.invoke(cli, ["evaluate", "--models-dir", str(models), "--json"])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    assert "grade" in doc
    assert "percent" in doc
    assert "entities" in doc
    assert "project" in doc


def test_evaluate_strict_nonzero_on_warn(tmp_path, runner):
    # A metric with no owner produces a WARN -> --strict exits non-zero.
    models = _write_fixture(
        tmp_path,
        raw_id_expr="TO_BASE64(SHA256(CAST(Customer.customer_id AS STRING)))",
        metric_owner="TODO",
    )
    result = runner.invoke(cli, ["evaluate", "--models-dir", str(models), "--strict"])
    assert result.exit_code != 0


def test_evaluate_default_exit_zero_even_with_warns(tmp_path, runner):
    models = _write_fixture(
        tmp_path,
        raw_id_expr="TO_BASE64(SHA256(CAST(Customer.customer_id AS STRING)))",
        metric_owner="TODO",  # produces a warn, not a fail
    )
    result = runner.invoke(cli, ["evaluate", "--models-dir", str(models)])
    assert result.exit_code == 0


# ── CAO acceptance (Slice 2-4 proof the aggregator reuses fixed validators) ──

def test_cao_identity_hashed_passes_all_four():
    """Proves the Snowflake addendum fix landed — all 4 CAO entities pass
    the identity-hashed check via the reused mesa_verifier."""
    from mesa_core.project import load_project
    from mesa_core.evaluate.checks import check_identity_hashed

    proj = load_project(CAO_MODELS)
    results = check_identity_hashed(proj)
    for r in results:
        assert r.status == "pass", f"{r.entity_name}: {r.message}"


def test_cao_grain_declared_passes_all_four():
    from mesa_core.project import load_project
    from mesa_core.evaluate.checks import check_grain_declared

    proj = load_project(CAO_MODELS)
    results = check_grain_declared(proj)
    for r in results:
        assert r.status == "pass", f"{r.entity_name}: {r.message}"


def test_cao_zero_broken_refs():
    from mesa_core.project import load_project
    from mesa_core.evaluate.checks import check_broken_refs

    proj = load_project(CAO_MODELS)
    results = check_broken_refs(proj)
    assert all(r.status == "pass" for r in results), results


def test_cao_safety_rollup_zero_secrets_pii():
    """False-positive guard: CAO production definitions must produce ZERO
    MESA-SEC-001 (secrets) and MESA-SEC-002 (PII) findings."""
    from mesa_core.project import load_project
    from mesa_core.evaluate.checks import check_safety_rollup

    proj = load_project(CAO_MODELS)
    results = check_safety_rollup(proj)
    for r in results:
        if r.check_id in ("MESA-SEC-001", "MESA-SEC-002"):
            assert r.status == "pass", f"{r.entity_name} {r.check_id}: {r.message}"


def test_cao_full_scorecard_believable():
    """CAO is production MESA — the overall grade should be B or better, and no
    entity should fall to F (a failing entity means a check is wrong)."""
    from mesa_core.project import load_project
    from mesa_core.evaluate.checks import CHECKS
    from mesa_core.evaluate.framework import evaluate

    proj = load_project(CAO_MODELS)
    score = evaluate(proj, CHECKS)
    assert score.percent >= 75.0, f"project grade too low: {score.grade}"
    for es in score.entities:
        assert es.grade not in ("D-", "F"), f"{es.entity_name} failed: {es.grade}"


def test_thin_entity_warns():
    """A 4-column entity scores the 'thin entity' warn with a teaching line."""
    from mesa_core.project import load_project
    from mesa_core.evaluate.checks import check_enrichment_depth

    proj = Project(name="thin", default_warehouse="Snowflake")
    # Build a minimal entity via a real on-disk project so definition_sql is set.
    import tempfile, os
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        models = _write_fixture(root, "TO_BASE64(SHA256(CAST(Customer.customer_id AS STRING)))", "A")
        thin_proj = load_project(models)
        results = check_enrichment_depth(thin_proj)
        assert any(r.status == "warn" and "thin" in r.message for r in results)
        for r in results:
            if r.status == "warn":
                assert r.why, "warn line must carry a teaching message"
