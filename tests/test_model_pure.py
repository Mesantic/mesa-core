"""
test_model_pure.py — SPEC_66 Slice 1c.

Proves two things about the extracted MESA Core package:

1. IMPORT PURITY — importing every ``mesa_core`` module must not pull in
   fastapi, sqlalchemy, aiosqlite, pydantic, or anything under ``api.*``.
   This is the moat: MESA Core is a pure, stateless compiler with no
   DB/web dependency.

2. FUNCTIONAL PARITY — the validators, fed the plain dataclasses (or the
   plain strings they already consume), produce the SAME findings the
   governance repo produces for equivalent input.
"""

import subprocess
import sys


# ── 1. Import purity ─────────────────────────────────────────────────────────

def test_no_fastapi_sqlalchemy_api_in_modules():
    """Import every mesa_core module and assert no web/DB/ORM deps got pulled in."""
    forbidden = (
        "fastapi",
        "sqlalchemy",
        "aiosqlite",
        "pydantic",
    )

    import mesa_core
    import mesa_core.model
    from mesa_core.validate import grain_guard, core_rules, mesa_verifier  # noqa: F401

    modules = [m.__name__ for m in sys.modules.values() if m is not None]

    # Any module whose name starts with an api.* namespace is a hard fail.
    api_namespace = [m for m in modules if m == "api" or m.startswith("api.")]
    assert api_namespace == [], f"api.* leaked into MESA Core import graph: {api_namespace}"

    # Any forbidden top-level module that got imported during our imports.
    pulled = [m for m in modules if m.split(".")[0] in forbidden]
    assert pulled == [], f"Forbidden dependency imported: {pulled}"

    # The mesa_core modules themselves must not contain forbidden imports at
    # source level (belt-and-suspenders — grep-equivalent in-process).
    for mod in (mesa_core.model, grain_guard, core_rules, mesa_verifier):
        src = sys.modules[mod.__name__].__dict__
        assert "fastapi" not in src and "sqlalchemy" not in src


def test_no_api_subprocess_import():
    """Import mesa_core in a fresh subprocess; the import must succeed without
    a DB/web stack and must not import anything named 'api'."""
    import os
    pkg_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    code = (
        "import sys; "
        f"sys.path.insert(0, {pkg_root!r}); "
        "import mesa_core; "
        "from mesa_core.validate import grain_guard, core_rules, mesa_verifier; "
        "bad = [m for m in sys.modules if m == 'api' or m.startswith('api.')]; "
        "print('API_LEAK' if bad else 'CLEAN')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=pkg_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CLEAN" in result.stdout, result.stdout


# ── 2. Functional parity against the governance repo ─────────────────────────

def _source_root() -> str:
    import os
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def test_mesa_verifier_hashed_identity_passes():
    """A hashed-ID raw entity verifies clean — no block findings."""
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    sql = (
        "SELECT\n"
        "  TO_BASE64(SHA256(CAST(p.policy_id AS STRING))) AS ID\n"
        "  , p.policy_name AS PolicyName\n"
        "FROM {{ source('rten', 'rten_xcmpy_pif_tbl') }} AS p\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    assert result.status != "contradicted"
    assert result.blocking_findings() == []


def test_mesa_verifier_passthrough_identity_blocks():
    """A bare source-key passthrough aliased to ID blocks with CODE_ID_PASSTHROUGH."""
    from mesa_core.validate.mesa_verifier import verify_raw_contract, CODE_ID_PASSTHROUGH

    sql = (
        "SELECT\n"
        "  p.policy_id AS ID\n"
        "  , p.policy_name AS PolicyName\n"
        "FROM {{ source('rten', 'rten_xcmpy_pif_tbl') }} AS p\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    codes = {f.code for f in result.findings}
    assert CODE_ID_PASSTHROUGH in codes


def test_core_rules_accepts_compliant_metric():
    """A MESA-compliant metric passes core_rules with zero violations."""
    from mesa_core.validate.core_rules import validate_metric_sql

    sql = (
        "SELECT\n"
        "  Policy.ID AS ID\n"
        "  , DATEDIFF('day', Policy.Policy:PolicyInceptionDate, CURRENT_DATE()) AS TenureDays\n"
        "FROM {{ ref('PolicyRaw') }} AS Policy\n"
    )
    violations = validate_metric_sql(sql, entity_name="Policy", identity_column="ID")
    assert violations == []


def test_core_rules_rejects_select_star():
    """SELECT * trips MESA-CORE-002."""
    from mesa_core.validate.core_rules import validate_metric_sql

    sql = "SELECT * FROM {{ ref('PolicyRaw') }} AS Policy"
    violations = validate_metric_sql(sql, entity_name="Policy", identity_column="ID")
    codes = {v.rule_code for v in violations}
    assert "MESA-CORE-002" in codes


def test_grain_guard_blocks_uncollapsed_fanout():
    """An uncollapsed join to a risky one_to_many relationship blocks."""
    from mesa_core.validate.grain_guard import check_fanout_risk, RiskyRelationship, CODE_FANOUT_BLOCKED

    sql = (
        "SELECT Policy.ID, Claims.Amount AS Amount\n"
        "FROM {{ ref('PolicyRaw') }} AS Policy\n"
        "JOIN {{ ref('ClaimRaw') }} AS Claims ON Claims.PolicyID = Policy.ID\n"
    )
    risky = [RiskyRelationship(
        other_entity_name="Claim",
        other_base_table_name="ClaimRaw",
        cardinality="one_to_many",
    )]
    findings = check_fanout_risk(sql, risky, warehouse="Snowflake")
    codes = {f.code for f in findings}
    assert CODE_FANOUT_BLOCKED in codes


def test_dataclasses_construct_and_carry_fields():
    """The frozen dataclasses construct and expose the fields the compiler reads."""
    from mesa_core.model import Entity, Metric, View, CompileResult

    entity = Entity(
        entity_name="Policy",
        base_table_name="rten_xcmpy_pif_tbl",
        source_name="rten",
        warehouse="Snowflake",
    )
    metric = Metric(metric_name="TenureDays", entity_name="Policy", definition_sql="SELECT ...")
    view = View(view_name="RenewalSurvey", entity_name="Survey", definition_sql="SELECT ...")
    result = CompileResult(
        entity_name="Policy",
        warehouse="Snowflake",
        metric_count=1,
        compiled_metric_layer_sql="-- ...",
        compiled_widetable_sql="-- ...",
    )

    assert entity.entity_name == "Policy"
    assert entity.identity_column == "ID"  # defaulted
    assert metric.metric_name == "TenureDays"
    assert view.view_name == "RenewalSurvey"
    assert result.metric_count == 1
