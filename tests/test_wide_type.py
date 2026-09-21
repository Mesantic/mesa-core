"""
test_wide_type.py — SPEC_72 Slice 1.

Prove ``resolve_wide_type`` is a faithful port of CAO's
``generate_wide_layer.py`` type inference: annotation-wins-over-heuristic
priority, each heuristic mapping, the VARCHAR-with-warning fallback, and the
single-line anchor guard.
"""

from mesa_core.compiler.wide_type import resolve_wide_type


def test_annotation_wins_over_heuristic():
    # A body that would hit the SUM( heuristic, but has an explicit annotation.
    sql = (
        "-- WIDE_TYPE: FLOAT\n"
        "SELECT Policy.ID, SUM(Policy.Amount) AS TotalAmount\n"
        "FROM {{ ref('PolicyRaw') }} AS Policy\n"
    )
    sf_type, inferred = resolve_wide_type(sql)
    assert sf_type == "FLOAT"
    assert inferred is False


def test_annotation_is_case_insensitive_and_uppercased():
    sql = "-- wide_type: number\nSELECT 1 AS X\n"
    sf_type, inferred = resolve_wide_type(sql)
    assert sf_type == "NUMBER"
    assert inferred is False


def test_to_char_heuristic():
    sf_type, inferred = resolve_wide_type("SELECT TO_CHAR(d, 'YYYY-MM') AS M FROM t")
    assert sf_type == "VARCHAR"
    assert inferred is True


def test_avg_heuristic():
    sf_type, inferred = resolve_wide_type("SELECT AVG(x) AS M FROM t")
    assert sf_type == "FLOAT"
    assert inferred is True


def test_retention_rate_heuristic():
    sf_type, inferred = resolve_wide_type("SELECT x AS RetentionRate FROM t")
    assert sf_type == "FLOAT"
    assert inferred is True


def test_ratio_heuristic():
    sf_type, inferred = resolve_wide_type("SELECT a / b AS Ratio FROM t")
    assert sf_type == "FLOAT"
    assert inferred is True


def test_case_then_1_else_0_heuristic():
    sql = "SELECT CASE WHEN x > 1 THEN 1 ELSE 0 END AS Flag FROM t"
    sf_type, inferred = resolve_wide_type(sql)
    assert sf_type == "NUMBER"
    assert inferred is True


def test_iff_flag_heuristic():
    sql = "SELECT IFF(x > 1, 1, 0) AS Flag FROM t"
    sf_type, inferred = resolve_wide_type(sql)
    assert sf_type == "NUMBER"
    assert inferred is True


def test_sum_heuristic():
    sf_type, inferred = resolve_wide_type("SELECT SUM(amount) AS M FROM t")
    assert sf_type == "NUMBER"
    assert inferred is True


def test_count_heuristic():
    sf_type, inferred = resolve_wide_type("SELECT COUNT(*) AS M FROM t")
    assert sf_type == "NUMBER"
    assert inferred is True


def test_datediff_heuristic():
    sf_type, inferred = resolve_wide_type("SELECT DATEDIFF('day', a, b) AS M FROM t")
    assert sf_type == "NUMBER"
    assert inferred is True


def test_fallback_varchar_with_inferred():
    # A body matching none of the heuristics.
    sf_type, inferred = resolve_wide_type("SELECT Policy.Name AS Name FROM t")
    assert sf_type == "VARCHAR"
    assert inferred is True


def test_single_line_anchor_does_not_swallow_next_block():
    # A WIDE_TYPE comment followed by a blank line then a WITH/SELECT block
    # must NOT let the regex swallow the next non-blank line into the type.
    # The regex is anchored to [^\n]+, so only the text on the annotation's own
    # line is captured.
    sql = (
        "-- WIDE_TYPE: NUMBER\n"
        "\n"
        "WITH X AS (SELECT 1 AS n)\n"
        "SELECT n FROM X\n"
    )
    sf_type, inferred = resolve_wide_type(sql)
    assert sf_type == "NUMBER"
    assert inferred is False
