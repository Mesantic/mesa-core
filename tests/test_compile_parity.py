"""
test_compile_parity.py — SPEC_66 Slice 3b.

Prove the refit compiler is BEHAVIOR-PRESERVING: ``mesa_core.compiler`` produces
the SAME compiled SQL as the governance repo's ``compiler`` for the same input.

The governance repo's compiler imports ``api.*`` (sqlalchemy/pydantic), so it is
invoked in a SUBPROCESS — never imported into this test process. That keeps the
import-purity guarantee intact: the shipped mesa-core package and its own test
process never pull in the governance repo's web/DB/ORM stack.
"""

import json
import os
import subprocess
import sys

GOV_ROOT = "/Users/yennypassanante/Downloads/MESAProductDev/mesa-governance-api"

# The governance compiler imports api.* (sqlalchemy/pydantic). Those live in the
# governance repo's OWN venv, NOT in mesa-core's minimal venv (Python 3.14, only
# sqlglot/click/pyyaml/duckdb). Pin the parity subprocess to that venv's python
# so it can import the governance compiler regardless of which interpreter runs
# this test suite.
_GOV_VENV_PY = os.path.join(GOV_ROOT, ".venv", "bin", "python")
GOV_PYTHON = _GOV_VENV_PY if os.path.exists(_GOV_VENV_PY) else sys.executable


def _gov_compile_entity(entity_dict, metric_dicts, warehouse) -> dict:
    """Run the governance compiler in a subprocess, return its result dict."""
    payload = json.dumps({
        "entity": entity_dict,
        "metrics": metric_dicts,
        "warehouse": warehouse,
    })
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {GOV_ROOT!r})\n"
        "from compiler.query_compiler import compile_entity\n"
        "d = json.loads(sys.stdin.read())\n"
        "class E: pass\n"
        "e = E()\n"
        "for k, v in d['entity'].items(): setattr(e, k, v)\n"
        "ms = []\n"
        "for md in d['metrics']:\n"
        "    m = E();\n"
        "    for k, v in md.items(): setattr(m, k, v)\n"
        "    ms.append(m)\n"
        "r = compile_entity(e, ms, d['warehouse'])\n"
        "print(json.dumps({'metric_layer': r.compiled_metric_layer_sql,\n"
        "                  'widetable': r.compiled_widetable_sql,\n"
        "                  'metric_count': r.metric_count}))\n"
    )
    result = subprocess.run(
        [GOV_PYTHON, "-c", code],
        input=payload,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _gov_compile_from_expression(entity_dict, metric_name, expression) -> str:
    payload = json.dumps({
        "entity": entity_dict,
        "metric_name": metric_name,
        "expression": expression,
    })
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {GOV_ROOT!r})\n"
        "from compiler.query_compiler import compile_from_expression\n"
        "d = json.loads(sys.stdin.read())\n"
        "class E: pass\n"
        "e = E()\n"
        "for k, v in d['entity'].items(): setattr(e, k, v)\n"
        "print(compile_from_expression(e, d['metric_name'], d['expression']))\n"
    )
    result = subprocess.run(
        [GOV_PYTHON, "-c", code],
        input=payload,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.rstrip("\n")


def _make_fixture():
    """A small StakingEvents-style fixture (2 metrics, BigQuery)."""
    entity = {
        "entity_name": "StakingEvents",
        "base_table_name": "StakingEvents",
        "source_name": "anchorage_data_platform",
        "warehouse": "BigQuery",
        "identity_column": "ID",
    }
    metrics = [
        {
            "metric_name": "IsSettledStaking",
            "entity_name": "StakingEvents",
            "definition_sql": (
                "SELECT StakingEvents.ID\n"
                "     , UPPER(StakingEvents.RewardState) = 'SETTLED' AS IsSettledStaking\n"
                "FROM {{ source('anchorage_data_platform', 'StakingEvents') }} AS StakingEvents"
            ),
        },
        {
            "metric_name": "EarnPeriod",
            "entity_name": "StakingEvents",
            "definition_sql": (
                "SELECT StakingEvents.ID\n"
                "     , SUM(StakingEvents.EarnAmount) AS EarnPeriod\n"
                "FROM {{ source('anchorage_data_platform', 'StakingEvents') }} AS StakingEvents\n"
                "GROUP BY StakingEvents.ID"
            ),
        },
    ]
    return entity, metrics


def test_compile_entity_parity_bigquery():
    from mesa_core.model import Entity, Metric
    from mesa_core.compiler.query_compiler import compile_entity as mesa_compile

    entity_dict, metric_dicts = _make_fixture()

    entity_dc = Entity(**entity_dict)
    metrics_dc = [Metric(**m) for m in metric_dicts]
    mesa_result = mesa_compile(entity_dc, metrics_dc, warehouse="BigQuery")

    gov_result = _gov_compile_entity(entity_dict, metric_dicts, "BigQuery")

    assert mesa_result.compiled_metric_layer_sql == gov_result["metric_layer"]
    assert mesa_result.compiled_widetable_sql == gov_result["widetable"]
    assert mesa_result.metric_count == gov_result["metric_count"]


def test_compile_entity_parity_snowflake():
    from mesa_core.model import Entity, Metric
    from mesa_core.compiler.query_compiler import compile_entity as mesa_compile

    entity_dict, metric_dicts = _make_fixture()

    entity_dc = Entity(**entity_dict)
    metrics_dc = [Metric(**m) for m in metric_dicts]
    mesa_result = mesa_compile(entity_dc, metrics_dc, warehouse="Snowflake")

    gov_result = _gov_compile_entity(entity_dict, metric_dicts, "Snowflake")

    assert mesa_result.compiled_metric_layer_sql == gov_result["metric_layer"]
    assert mesa_result.compiled_widetable_sql == gov_result["widetable"]


def test_compile_from_expression_parity():
    from mesa_core.model import Entity
    from mesa_core.compiler.query_compiler import compile_from_expression as mesa_cfe

    entity_dict = {
        "entity_name": "StakingEvents",
        "base_table_name": "StakingEvents",
        "source_name": "anchorage_data_platform",
        "warehouse": "BigQuery",
        "identity_column": "ID",
    }
    entity_dc = Entity(**entity_dict)

    expr = "UPPER(StakingEvents.RewardState) = 'SETTLED'"
    mesa_out = mesa_cfe(entity_dc, "IsSettledStaking", expr).rstrip("\n")
    gov_out = _gov_compile_from_expression(entity_dict, "IsSettledStaking", expr)

    assert mesa_out == gov_out


def test_get_emitter_cube_and_dbt_no_code_connection():
    """MESA Core can construct the pure emitters without a CodeConnection."""
    from mesa_core.compiler.targets import get_emitter
    from mesa_core.compiler.targets.dbt import MesaDbtEmitter

    cube_emitter = get_emitter("cube")  # no code_connection -> fine in Core
    dbt_emitter = MesaDbtEmitter(dialect="snowflake")

    assert cube_emitter.target_name == "cube"
    assert dbt_emitter.target_name == "dbt"
    assert dbt_emitter._dialect == "snowflake"


def test_get_emitter_warehouse_rejected():
    """warehouse target is Mesantic-only — Core raises a clear error."""
    import pytest
    from mesa_core.compiler.targets import get_emitter

    with pytest.raises(ValueError) as exc:
        get_emitter("warehouse")
    assert "not available in MESA Core" in str(exc.value)


def test_lineage_name_identity_no_db_id():
    """lineage uses metric_name identity (no DB id/status on the dataclass)."""
    from mesa_core.model import Metric
    from mesa_core.compiler.lineage import find_dependents, parse_metric_dependencies

    base = Metric(
        metric_name="TenureDays",
        entity_name="Policy",
        definition_sql="SELECT Policy.ID AS ID, DATEDIFF('day', Policy.Policy:PolicyInceptionDate, CURRENT_DATE()) AS TenureDays FROM {{ ref('PolicyRaw') }} AS Policy",
    )
    derived = Metric(
        metric_name="RetentionRate",
        entity_name="Policy",
        definition_sql="SELECT TenureDays.ID AS ID, TenureDays.TenureDays / 30 AS RetentionRate FROM {{ ref('TenureDays') }} AS TenureDays",
    )
    all_metrics = [base, derived]

    deps = parse_metric_dependencies(derived, all_metrics)
    assert deps == ["TenureDays"]

    dependents = find_dependents(base, all_metrics)
    assert [d["metric_name"] for d in dependents] == ["RetentionRate"]
