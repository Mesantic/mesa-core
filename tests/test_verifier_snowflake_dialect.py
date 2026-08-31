"""
test_verifier_snowflake_dialect.py — SPEC_66 addendum regression tests.

Pin the three verifier dialect fixes so correct Snowflake never regresses to a
false finding:

  Bug 1 — BASE64_ENCODE(SHA2(...)) (multi-line) is a hashed identity.
  Bug 2 — ARRAY_AGG ... WITHIN GROUP is array-nesting, not a cross-row metric;
          a watermark MAX(...) / campaign-grain COUNT(DISTINCT ...) at the raw
          layer is warn-not-block.
  Bug 3 — a CTE metric and a scalar-subquery metric count exactly ONE output
          column (not the CTE's inner columns, type casts, or subquery aliases).
"""

import re


# ── Bug 1: Snowflake hash idiom is recognized ────────────────────────────────

def test_snowflake_hash_single_line_is_hashed():
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    sql = (
        "SELECT\n"
        "  BASE64_ENCODE(SHA2(Policy.PLCY_CNTRCT_NUM, 256)) AS ID\n"
        "  , Policy.Name AS Name\n"
        "FROM {{ source('rten', 'rten_xcmpy_pif_tbl') }} AS Policy\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    codes = {f.code for f in result.findings}
    assert "MESA_RAW_ID_UNHASHED" not in codes
    assert "MESA_RAW_ID_PASSTHROUGH" not in codes


def test_snowflake_hash_multiline_is_hashed():
    """ChangeEventRaw's hash spans multiple lines — DOTALL must not break it."""
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    sql = (
        "SELECT\n"
        "    BASE64_ENCODE(SHA2(\n"
        "        AllEvents.PLCY_CNTRCT_NUM || '|' || AllEvents.EventType || '|' ||\n"
        "        CAST(AllEvents.EffectiveDate AS VARCHAR)\n"
        "        , 256\n"
        "    )) AS ID\n"
        "    , AllEvents.EventType AS EventType\n"
        "FROM AllEvents\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    codes = {f.code for f in result.findings}
    assert "MESA_RAW_ID_UNHASHED" not in codes


# ── Bug 2: array-nesting + watermark aggregates are not hard blocks ──────────

def test_array_agg_within_group_is_not_blocking():
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    sql = (
        "SELECT\n"
        "    BASE64_ENCODE(SHA2(Policy.PLCY_CNTRCT_NUM, 256)) AS ID\n"
        "    , ARRAY_AGG(\n"
        "        OBJECT_CONSTRUCT_KEEP_NULL('LoadYearMonthNum', Snapshot.SNAP_YR_MO_CD)\n"
        "    ) WITHIN GROUP (ORDER BY Snapshot.SNAP_YR_MO_CD) AS MonthlySnapshots\n"
        "FROM {{ source('rten', 'tfrdb_fws_pol_snap_mthly_rpt') }} AS Snapshot\n"
        "GROUP BY Policy.PLCY_CNTRCT_NUM\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    assert result.blocking_findings() == []


def test_watermark_max_is_warn_not_block():
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    sql = (
        "SELECT\n"
        "    BASE64_ENCODE(SHA2(Campaign.SurveyType || '|' || Campaign.InviteWave, 256)) AS ID\n"
        "    , Campaign.InvitesSent AS InvitesSent\n"
        "FROM Campaign\n"
        "WHERE Campaign.InviteWave >= (\n"
        "    SELECT COALESCE(MAX(SurveyRawPrev.Survey:InviteWave::DATE), CURRENT_DATE)\n"
        "    FROM {{ this }} AS SurveyRawPrev\n"
        ")\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    assert result.blocking_findings() == []
    # The MAX(...) may still surface as a WARN (MESA_RAW_HAS_AGGREGATE), never a block.
    for f in result.findings:
        assert f.severity != "block", f"expected no block finding, got {f.code}"


# ── Bug 3: CTE / scalar-subquery metrics count ONE output column ─────────────

def test_cte_metric_counts_one_output():
    from mesa_core.validate.core_rules import validate_metric_sql

    sql = (
        "WITH AgentChangeSurveys AS (\n"
        "    SELECT\n"
        "        SurveyResponse.value:SystemIds.PolicyNumber::VARCHAR AS PolicyNumber\n"
        "        , AVG(SurveyResponse.value:NpsScore::NUMBER) AS AvgNpsScore\n"
        "        , COUNT(*) AS SurveyResponseCount\n"
        "    FROM {{ ref('SurveyRaw') }} AS Survey\n"
        "    CROSS JOIN LATERAL FLATTEN(INPUT => Survey.Survey:Responses) AS SurveyResponse\n"
        "    GROUP BY SurveyResponse.value:SystemIds.PolicyNumber::VARCHAR\n"
        ")\n"
        "SELECT\n"
        "    Policy.ID AS ID\n"
        "    , AgentChangeSurveys.AvgNpsScore AS AgentChangeCsatScore\n"
        "FROM {{ ref('PolicyRaw') }} AS Policy\n"
    )
    violations = validate_metric_sql(sql, entity_name="Policy", identity_column="ID")
    codes = {v.rule_code for v in violations}
    assert "MESA-CORE-004" not in codes


def test_scalar_subquery_metric_counts_one_output():
    from mesa_core.validate.core_rules import validate_metric_sql

    sql = (
        "SELECT\n"
        "    Survey.ID AS ID\n"
        "    , (\n"
        "        SELECT AVG(TRY_CAST(Response.value:NpsScore AS NUMBER))\n"
        "        FROM TABLE(FLATTEN(INPUT => Survey.Survey:Responses)) AS Response\n"
        "        WHERE Response.value:NpsScore IS NOT NULL\n"
        "    ) AS RenewalAvgNps\n"
        "FROM {{ ref('SurveyRaw') }} AS Survey\n"
        "WHERE Survey.Survey:SurveyType = 'RENEWAL'\n"
    )
    violations = validate_metric_sql(sql, entity_name="Survey", identity_column="ID")
    codes = {v.rule_code for v in violations}
    assert "MESA-CORE-004" not in codes


def test_genuine_multi_output_still_blocks():
    """A real two-metric file still trips CORE-004 — the fix must not over-allow."""
    from mesa_core.validate.core_rules import validate_metric_sql

    sql = (
        "SELECT\n"
        "    Policy.ID AS ID\n"
        "    , COUNT(*) AS NumberOfOrders\n"
        "    , SUM(Orders.Amount) AS TotalAmount\n"
        "FROM {{ ref('PolicyRaw') }} AS Policy\n"
        "JOIN {{ ref('Orders') }} AS Orders ON Orders.PolicyID = Policy.ID\n"
        "GROUP BY Policy.ID\n"
    )
    violations = validate_metric_sql(sql, entity_name="Policy", identity_column="ID")
    codes = {v.rule_code for v in violations}
    assert "MESA-CORE-004" in codes
