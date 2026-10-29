"""
test_ratio_defaults.py — SPEC_101 Slice 1b: ratios stop zero-filling.

The defect: a rate with no rows is not 0, it's "no data". Zero-filling it is the
same class of bug as the 2026-10-07 "open windows shown as lost" defect — a rate
for a policy with no events rendered as 0% instead of blank.

The correction to the earlier plan matters and is pinned here: the defect is
DIVISION, not `SUM(`. A premium total with no rows genuinely is 0 the same way a
count is, so dropping bare `SUM(` would have broken every money metric to fix one
rate. These tests hold both halves of that line.

Measured on real CAO (40 metrics, 2026-10-18): 16 got a '0' default, 24 passed
NULL through, division appeared in 2. The terminal-projection rule flips exactly
ONE — AgentChangeResponseRate. The other division (IsLikelyMoveEvent) lives only
inside a CTE and its terminal SELECT is a 0/1 flag, so it keeps its '0'.
"""

import pytest

from mesa_core.model import Entity, Metric
from mesa_core.compiler.combiner import resolve_combiner_default
from mesa_core.compiler.query_compiler import compile_entity


# ── The rule itself ──────────────────────────────────────────────────────────

def test_plain_division_gets_no_default():
    """A terminal-projection division is a ratio — NULL means 'no data'."""
    sql = "SELECT t.ID, a.Total / b.Total AS Rate FROM t"
    assert resolve_combiner_default(sql, None) is None


def test_nullif_guarded_division_gets_no_default():
    """NULLIF guarding the denominator doesn't make it a count — still a ratio."""
    sql = "SELECT t.ID, a.Total / NULLIF(b.Total, 0) AS Rate FROM t"
    assert resolve_combiner_default(sql, None) is None


def test_div0_gets_no_default():
    """Snowflake's DIV0 is a division. sqlglot normalizes it to a Div node, so
    the rule catches it without a special case — this pins that behavior, because
    the real CAO AgentChangeResponseRate metric uses DIV0, not `/`."""
    sql = "SELECT t.ID, DIV0(a.Total, b.Total) AS Rate FROM t"
    assert resolve_combiner_default(sql, None) is None


def test_sum_over_division_still_gets_no_default():
    """`SUM(a) / SUM(b)` matches the SUM heuristic — the ratio rule must run
    FIRST or this would be zero-filled."""
    sql = "SELECT t.ID, SUM(a.Amount) / SUM(b.Amount) AS Rate FROM t"
    assert resolve_combiner_default(sql, None) is None


def test_plain_sum_still_zero_fills():
    """The correction: a premium total with no rows IS 0. Don't break money."""
    assert resolve_combiner_default("SELECT t.ID, SUM(t.Amount) AS Total FROM t", None) == "0"


def test_count_still_zero_fills():
    assert resolve_combiner_default("SELECT t.ID, COUNT(t.ID) AS N FROM t", None) == "0"


def test_zero_one_flag_still_zero_fills():
    sql = "SELECT t.ID, CASE WHEN t.Flag THEN 1 ELSE 0 END AS IsFlag FROM t"
    assert resolve_combiner_default(sql, None) == "0"


def test_division_only_inside_cte_with_flag_terminal_keeps_zero():
    """The IsLikelyMoveEvent shape: the division lives in a CTE, the terminal
    SELECT is a 0/1 flag. It's a flag, not a ratio — it keeps its '0'.

    A human confirmed 0 is the right default for it (a client×policy with no
    address change genuinely has zero likely-move events).
    """
    sql = (
        "WITH Scored AS (\n"
        "    SELECT t.ID, a.Distance / b.Length AS Score\n"
        "    FROM t\n"
        ")\n"
        "SELECT\n"
        "    Scored.ID\n"
        "    , CASE WHEN Scored.Score > 0.2 THEN 1 ELSE 0 END AS IsLikelyMoveEvent\n"
        "FROM Scored\n"
    )
    assert resolve_combiner_default(sql, None) == "0"


def test_annotation_always_wins_over_the_ratio_rule():
    """An author who says 0 is correct for a ratio gets 0."""
    sql = "SELECT t.ID, a.Total / b.Total AS Rate FROM t"
    assert resolve_combiner_default(sql, "0") == "0"


def test_annotation_none_wins_over_a_count():
    assert resolve_combiner_default("SELECT t.ID, COUNT(t.ID) AS N FROM t", "NONE") is None


# ── Warnings: never silent ───────────────────────────────────────────────────

def test_ratio_emits_a_warning():
    warnings: list[str] = []
    resolve_combiner_default(
        "SELECT t.ID, a.Total / b.Total AS Rate FROM t",
        None,
        warnings=warnings,
        metric_label="Policy.ResponseRate",
    )
    assert len(warnings) == 1
    assert "Policy.ResponseRate" in warnings[0]
    assert "ratio" in warnings[0]
    assert "NULL means 'no data'" in warnings[0]


def test_parse_failure_warns_and_keeps_heuristic_behavior():
    """A parse failure must not silently restore the zero-fill. It falls back to
    the heuristic table (today's behavior) AND says the parse failed."""
    warnings: list[str] = []
    # Unbalanced parens — sqlglot can't parse this.
    sql = "SELECT t.ID, SUM(t.Amount AS Total FROM t"
    result = resolve_combiner_default(
        sql, None, warnings=warnings, metric_label="Policy.Broken"
    )
    assert result == "0"  # heuristic still applied
    assert len(warnings) == 1
    assert "could not parse" in warnings[0]
    assert "Policy.Broken" in warnings[0]


def test_no_warning_for_a_plain_count():
    warnings: list[str] = []
    resolve_combiner_default(
        "SELECT t.ID, COUNT(t.ID) AS N FROM t", None, warnings=warnings
    )
    assert warnings == []


# ── Dialect neutrality (SPEC_103 Slice 3 extends this to all six) ────────────

@pytest.mark.parametrize("dialect", ["snowflake", "bigquery", "redshift", "duckdb", "tsql"])
def test_ratio_rule_is_dialect_neutral(dialect):
    """The resolver is the one SPEC_103 Slice 3 extends to every warehouse, so
    it has to work on every dialect's grammar."""
    sql = "SELECT t.ID, a.Total / b.Total AS Rate FROM t"
    assert resolve_combiner_default(sql, None, dialect=dialect) is None


@pytest.mark.parametrize("dialect", ["snowflake", "bigquery", "redshift", "duckdb", "tsql"])
def test_count_rule_is_dialect_neutral(dialect):
    sql = "SELECT t.ID, COUNT(t.ID) AS N FROM t"
    assert resolve_combiner_default(sql, None, dialect=dialect) == "0"


# ── Compiler: the emitted SQL ────────────────────────────────────────────────

def _entity(warehouse: str = "Snowflake") -> Entity:
    return Entity(
        entity_name="SurveyProgram",
        base_table_name="SurveyProgram",
        source_name="rten",
        warehouse=warehouse,
        identity_column="ID",
    )


def _rate_metric() -> Metric:
    return Metric(
        metric_name="AgentChangeResponseRate",
        entity_name="SurveyProgram",
        definition_sql=(
            "SELECT\n"
            "    SurveyProgram.ID\n"
            "    , DIV0(Responded.ResponseCount, Invited.InviteCount) AS AgentChangeResponseRate\n"
            "FROM {{ ref('SurveyProgramRaw') }} AS SurveyProgram\n"
        ),
    )


def _count_metric() -> Metric:
    return Metric(
        metric_name="NumberOfPolicies",
        entity_name="SurveyProgram",
        definition_sql=(
            "SELECT\n"
            "    SurveyProgram.ID\n"
            "    , COUNT(SurveyProgram.PolicyNumber) AS NumberOfPolicies\n"
            "FROM {{ ref('SurveyProgramRaw') }} AS SurveyProgram\n"
            "GROUP BY SurveyProgram.ID\n"
        ),
    )


def test_compiled_ratio_has_no_coalesce():
    """The acceptance criterion: AgentChangeResponseRate compiles with no COALESCE."""
    result = compile_entity(_entity(), [_rate_metric()], "Snowflake")
    assert "COALESCE(AgentChangeResponseRate" not in result.compiled_combiner_sql
    assert ", AgentChangeResponseRate.AgentChangeResponseRate\n" in result.compiled_combiner_sql


def test_compiled_ratio_emits_a_ratio_warning():
    result = compile_entity(_entity(), [_rate_metric()], "Snowflake")
    ratio_warnings = [w for w in result.annotation_warnings if "ratio" in w]
    assert len(ratio_warnings) == 1
    assert "AgentChangeResponseRate" in ratio_warnings[0]


def test_compiled_count_still_zero_fills_and_warns_as_inferred():
    """The other 15 zero-defaults are unchanged — still COALESCE 0, still warned
    as inferred (Slice 1 behavior, not a ratio warning)."""
    result = compile_entity(_entity(), [_count_metric()], "Snowflake")
    assert "COALESCE(NumberOfPolicies.NumberOfPolicies, 0)" in result.compiled_combiner_sql
    assert len(result.annotation_warnings) == 1
    assert "inferred as 0" in result.annotation_warnings[0]
    assert "ratio" not in result.annotation_warnings[0]


def test_ratio_and_count_together_only_the_ratio_moves():
    """The real CAO shape: one ratio and one count in the same entity."""
    result = compile_entity(_entity(), [_rate_metric(), _count_metric()], "Snowflake")
    sql = result.compiled_combiner_sql
    assert "COALESCE(AgentChangeResponseRate" not in sql
    assert "COALESCE(NumberOfPolicies.NumberOfPolicies, 0)" in sql


def test_tsql_combiner_also_skips_the_ratio_default():
    """The T-SQL combiner runs the same resolver, so a ratio passes NULL there
    too — no CAST(COALESCE(rate, 0.0))."""
    result = compile_entity(_entity("Synapse"), [_rate_metric()], "Synapse")
    assert "COALESCE(AgentChangeResponseRate.AgentChangeResponseRate" not in result.compiled_combiner_sql
    assert "CAST(AgentChangeResponseRate.AgentChangeResponseRate AS" in result.compiled_combiner_sql
