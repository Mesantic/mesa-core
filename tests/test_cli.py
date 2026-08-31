"""
test_cli.py — SPEC_66 Slice 4a.

Exercises the ``mesa`` CLI (click CliRunner) and the mechanical scaffolder:
  - mesa init creates the four-tier dirs + mesa_project.yml
  - mesa validate on a fixture with a deliberate grain violation exits non-zero
    and names the violation
  - mesa build writes expected target files
  - mesa new entity stamps a stub with the doctrine header + hashed ID + a
    PascalCase alias per input column, and the metric folder is created empty
  - running validate on the freshly scaffolded (unfilled) stub surfaces the
    "fill in" findings rather than crashing
"""

import pytest
from click.testing import CliRunner

from mesa_core.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


# ── mesa init ────────────────────────────────────────────────────────────────

def test_init_creates_dirs_and_project_file(tmp_path, runner):
    result = runner.invoke(cli, ["init", str(tmp_path / "absproj"), "--warehouse", "BigQuery"])
    assert result.exit_code == 0, result.output

    root = tmp_path / "absproj"
    assert (root / "mesa_project.yml").exists()
    assert (root / "models" / "raw_layer").is_dir()
    assert (root / "models" / "metric_layer").is_dir()
    assert (root / "models" / "wide_layer").is_dir()
    assert (root / "models" / "view_layer").is_dir()
    assert (root / "models" / "sources").is_dir()
    assert (root / "target").is_dir()

    content = (root / "mesa_project.yml").read_text()
    assert "default_warehouse: BigQuery" in content


# ── mesa new entity (scaffold) ───────────────────────────────────────────────

def test_new_entity_from_columns(tmp_path, runner):
    cols = tmp_path / "cols.txt"
    cols.write_text("policy_id\npolicy_name\ninception_date\nzip_code\nstatus\n")

    models = tmp_path / "models"
    result = runner.invoke(cli, [
        "new", "entity", "Policy",
        "--from-columns", str(cols),
        "--models-dir", str(models),
    ])
    assert result.exit_code == 0, result.output

    raw_file = models / "raw_layer" / "Policy" / "PolicyRaw.sql"
    assert raw_file.exists()
    body = raw_file.read_text()
    assert "-- RAW ENTITY: Policy" in body
    assert "BASE64_ENCODE(SHA2(" in body  # hashed ID line
    assert "AS ID" in body
    for col in ("policy_id", "policy_name", "inception_date", "zip_code", "status"):
        assert col in body  # raw source column present
    # PascalCase alias per column
    assert "PolicyId" in body
    assert "PolicyName" in body
    assert "InceptionDate" in body
    assert "ZipCode" in body
    assert "Status" in body

    # Metric folder created empty (only the sidecar yml, no .sql).
    metric_dir = models / "metric_layer" / "Policy_Metrics"
    assert metric_dir.is_dir()
    assert list(metric_dir.glob("*.sql")) == []
    assert (metric_dir / "_policy_metrics.yml").exists()

    # Wide stub + sources stub.
    assert (models / "wide_layer" / "PolicyWide.sql").exists()
    assert (models / "sources" / "placeholder_source.yml").exists()


def test_new_entity_from_ddl(tmp_path, runner):
    ddl = tmp_path / "t.sql"
    ddl.write_text(
        "CREATE TABLE raw.customer (\n"
        "  customer_id INT,\n"
        "  name VARCHAR,\n"
        "  created_at TIMESTAMP\n"
        ");\n"
    )
    models = tmp_path / "models"
    result = runner.invoke(cli, [
        "new", "entity", "Customer",
        "--from-ddl", str(ddl),
        "--models-dir", str(models),
    ])
    assert result.exit_code == 0, result.output

    body = (models / "raw_layer" / "Customer" / "CustomerRaw.sql").read_text()
    assert "CustomerId" in body
    assert "Name" in body
    assert "CreatedAt" in body


def test_new_entity_requires_column_source(tmp_path, runner):
    models = tmp_path / "models"
    result = runner.invoke(cli, ["new", "entity", "Policy", "--models-dir", str(models)])
    assert result.exit_code != 0
    assert "from-columns" in result.output or "from-ddl" in result.output


def test_validate_scaffolded_stub_surfaces_fill_in(tmp_path, runner):
    """Running validate on an UNFILLED scaffold must surface fill-in findings,
    not crash."""
    cols = tmp_path / "cols.txt"
    cols.write_text("policy_id\npolicy_name\n")
    models = tmp_path / "models"
    runner.invoke(cli, ["new", "entity", "Policy", "--from-columns", str(cols), "--models-dir", str(models)])

    result = runner.invoke(cli, ["validate", "--models-dir", str(models)])
    assert result.exit_code != 0
    assert "MESA_RAW_UNFILLED" in result.output


# ── mesa build + validate on a real fixture ──────────────────────────────────

def _write_fixture_project(root):
    """A valid 1-entity project with a hashed-ID raw entity + 1 metric."""
    (root / "mesa_project.yml").write_text(
        "name: fixture\nversion: '1.0.0'\ndefault_warehouse: Snowflake\nmodel-paths: ['models']\n"
    )
    models = root / "models"
    (models / "raw_layer" / "Customer").mkdir(parents=True)
    (models / "raw_layer" / "Customer" / "CustomerRaw.sql").write_text(
        "-- RAW ENTITY: Customer\n"
        "-- Grain: one row per customer\n"
        "-- ID: hashed primary key — BASE64_ENCODE(SHA2(customer_id, 256))\n"
        "SELECT\n"
        "    TO_BASE64(SHA256(CAST(Customer.customer_id AS STRING))) AS ID\n"
        "    , Customer.name AS Name\n"
        "FROM {{ source('crm', 'customer') }} AS Customer\n"
    )
    (models / "metric_layer" / "Customer_Metrics").mkdir(parents=True)
    (models / "metric_layer" / "Customer_Metrics" / "NumberOfOrders.sql").write_text(
        "{{ config(tags=['metric_customer']) }}\n"
        "\n"
        "-- METRIC: NumberOfOrders\n"
        "-- Owner: Analytics\n"
        "-- Contract: 1 row per customer ID = 1:1\n"
        "\n"
        "SELECT\n"
        "    Customer.ID AS ID\n"
        "    , COUNT(Orders.order_id) AS NumberOfOrders\n"
        "FROM {{ ref('CustomerRaw') }} AS Customer\n"
        "JOIN {{ source('crm', 'orders') }} AS Orders ON Orders.customer_id = Customer.ID\n"
        "GROUP BY Customer.ID\n"
    )
    return models


def test_build_writes_target_files(tmp_path, runner):
    models = _write_fixture_project(tmp_path)
    result = runner.invoke(cli, ["build", "--models-dir", str(models)])
    assert result.exit_code == 0, result.output

    target = tmp_path / "target"
    assert (target / "raw_layer" / "CustomerRaw.sql").exists()
    assert (target / "metric_layer" / "CustomerMetric.sql").exists()
    assert (target / "wide_layer" / "CustomerWide.sql").exists()

    wide = (target / "wide_layer" / "CustomerWide.sql").read_text()
    assert "Customer" in wide


def test_validate_fixture_passes(tmp_path, runner):
    models = _write_fixture_project(tmp_path)
    result = runner.invoke(cli, ["validate", "--models-dir", str(models)])
    assert result.exit_code == 0, result.output


def test_validate_grain_violation_blocks(tmp_path, runner):
    """A metric with a cross-row aggregate in the raw layer, or a bare source-key
    passthrough ID, must block."""
    models = _write_fixture_project(tmp_path)
    # Rewrite the raw entity to use a bare passthrough ID (no hash) -> blocks.
    (models / "raw_layer" / "Customer" / "CustomerRaw.sql").write_text(
        "-- RAW ENTITY: Customer\n"
        "-- Grain: one row per customer\n"
        "SELECT\n"
        "    Customer.customer_id AS ID\n"
        "    , Customer.name AS Name\n"
        "FROM {{ source('crm', 'customer') }} AS Customer\n"
    )
    result = runner.invoke(cli, ["validate", "--models-dir", str(models)])
    assert result.exit_code != 0
    assert "MESA_RAW_ID_PASSTHROUGH" in result.output


def test_compile_single_entity(tmp_path, runner):
    models = _write_fixture_project(tmp_path)
    result = runner.invoke(cli, ["compile", "Customer", "--models-dir", str(models)])
    assert result.exit_code == 0, result.output
    assert "CustomerMetric" in result.output or "Customer.ID" in result.output
    assert "NumberOfOrders" in result.output


def test_learn_stub(tmp_path, runner):
    result = runner.invoke(cli, ["learn"])
    assert result.exit_code == 0
    assert "SPEC_67" in result.output
