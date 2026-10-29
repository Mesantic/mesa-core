"""
test_conformance_duckdb.py — SPEC_103 Slice 8a.

The free, in-CI half of the conformance harness. What this suite is for:

  * It pins DuckDB's behavior for the claims the specs lean on. Only the
    IDENTITY_EXPR row executes compiler output (identity_expr against a SHA-256
    test vector); the rest are raw DuckDB SQL and say nothing about the compiler.
  * It pins the fixture's expected values so a "fix" that quietly changes what
    the fixture measures shows up as a test failure rather than a silently
    different report.

What it is NOT: proof of cloud behavior. DuckDB's ``concat`` ignores NULL and
``/`` returns a double, which is not what SQL Server does. Every DOCUMENTED row
about T-SQL, Redshift and BigQuery still waits for Slice 8b. The report says so
in its own closing section, and ``test_report_lists_the_warehouses_not_run``
pins that.
"""

import pytest

from mesa_core.conformance import (
    NASTY_CASES,
    Status,
    render_markdown,
    run_duckdb_conformance,
)
from mesa_core.conformance.fixture import FIXTURE_ROWS


@pytest.fixture(scope="module")
def report():
    return run_duckdb_conformance()


# ── The run itself ───────────────────────────────────────────────────────────

def test_duckdb_run_has_no_falsified_rows(report):
    """Every check must pass on DuckDB. A falsified row means either the fixture
    drifted or the compiler started assuming something DuckDB doesn't do."""
    assert report.falsified == [], [f"{r.case}: {r.actual}" for r in report.falsified]


def test_duckdb_run_covers_every_nasty_case(report):
    """No case may be silently dropped from the run."""
    covered = {r.case for r in report.results}
    expected = {c.key for c in NASTY_CASES}
    assert covered == expected


def test_report_records_the_warehouse_version(report):
    """A VERIFIED row is only reproducible if the version is recorded."""
    assert report.warehouse == "DuckDB"
    assert report.version  # e.g. "1.5.5"
    assert report.run_at  # e.g. "2026-10-28"


def test_summary_counts_add_up(report):
    total = len(report.verified) + len(report.falsified) + len(report.skipped)
    assert total == len(report.results)
    assert report.ok is True


# ── The individual behaviors, pinned ─────────────────────────────────────────

def _result(report, case: str):
    return next(r for r in report.results if r.case == case)


def test_null_key_concat_ignores_null_but_pipe_propagates(report):
    """DuckDB's measured behavior. This is the row that proves DuckDB is NOT a
    stand-in for SQL Server — the whole reason Slice 8b exists."""
    result = _result(report, "NULL_KEY")
    assert result.status is Status.VERIFIED
    assert "'ab'" in result.actual
    assert "None" in result.actual


def test_trailing_space_changes_the_hash(report):
    """'ABC ' and 'ABC' must not collide — a collision is a silent duplicate ID."""
    result = _result(report, "TRAILING_SPACE")
    assert result.status is Status.VERIFIED
    assert result.actual == "different"


def test_case_variant_changes_the_hash(report):
    result = _result(report, "CASE_VARIANT")
    assert result.status is Status.VERIFIED
    assert result.actual == "different"


def test_int_ratio_returns_a_double_on_duckdb(report):
    """DuckDB does NOT truncate int/int — it returns 3.5. Redshift and SQL Server
    are DOCUMENTED to truncate, which is why Slice 7's rule waits for 8b."""
    result = _result(report, "INT_RATIO")
    assert result.status is Status.VERIFIED
    assert "3.5" in result.actual
    assert "DOUBLE" in result.actual


def test_microsecond_precision_survives(report):
    result = _result(report, "MICROSECOND")
    assert result.status is Status.VERIFIED
    assert "123456" in result.actual


def test_struct_keys_are_case_preserved(report):
    """The OBJECT_CONSTRUCT uppercase-key bug: DuckDB preserves the literal key,
    Snowflake's wildcard form does not."""
    result = _result(report, "MIXED_CASE_KEYS")
    assert result.status is Status.VERIFIED
    assert "PascalKey=1" in result.actual
    assert "lowerkey=2" in result.actual


def test_min_max_works_on_boolean_in_duckdb(report):
    """DuckDB allows it. T-SQL BIT is DOCUMENTED not to — the macro still needs
    the count-only fallback."""
    result = _result(report, "BOOLEAN")
    assert result.status is Status.VERIFIED
    assert "MIN=False" in result.actual


def test_all_null_column_reports_zero_non_null(report):
    """The PolicyRaw bug: a dead column must be detectable."""
    result = _result(report, "ALL_NULL")
    assert result.status is Status.VERIFIED
    assert "non_null = 0" in result.actual


def test_constant_column_is_detected_as_constant(report):
    """lo = hi — the signal test must warn, not fail."""
    result = _result(report, "CONSTANT")
    assert result.status is Status.VERIFIED
    assert "lo='only'" in result.actual
    assert "hi='only'" in result.actual


# ── The fixture is hostile on purpose ────────────────────────────────────────

def test_fixture_has_a_null_natural_key():
    assert any(row[1] is None for row in FIXTURE_ROWS)


def test_fixture_has_a_trailing_space_and_a_case_variant():
    keys = [row[1] for row in FIXTURE_ROWS if row[1] is not None]
    assert "ABC " in keys
    assert "ABC" in keys
    assert "abc" in keys


def test_fixture_has_a_microsecond_timestamp():
    assert any(".123456" in str(row[4]) for row in FIXTURE_ROWS)


def test_fixture_has_an_all_null_column():
    assert all(row[6] is None for row in FIXTURE_ROWS)


def test_fixture_has_a_constant_column():
    values = {row[7] for row in FIXTURE_ROWS}
    assert len(values) == 1


def test_fixture_has_both_boolean_values():
    """A constant boolean would make the MIN/MAX check meaningless."""
    assert {row[5] for row in FIXTURE_ROWS} == {True, False}


# ── The report is honest about what it did NOT run ───────────────────────────

def test_report_lists_the_warehouses_not_run(report):
    """The closing section must name every warehouse the harness hasn't touched.
    Without this, an all-VERIFIED table reads as "every warehouse is fine"."""
    markdown = render_markdown([report])
    assert "Still DOCUMENTED, not VERIFIED" in markdown
    for name in ("Snowflake", "BigQuery", "Redshift", "Synapse", "AzureSQLDatabase"):
        assert name in markdown


def test_report_names_the_rows_that_wait_on_cloud_runs(report):
    markdown = render_markdown([report])
    assert "NULL in `CONCAT`" in markdown
    assert "Integer division" in markdown
    assert "`MIN`/`MAX` on `BIT`" in markdown


def test_report_renders_a_table_row_per_check(report):
    markdown = render_markdown([report])
    for result in report.results:
        assert f"`{result.case}`" in markdown
        assert result.status.value in markdown


def test_report_marks_duckdb_as_run(report):
    markdown = render_markdown([report])
    assert "## DuckDB" in markdown
    assert report.version in markdown
