"""
test_verifier_canonical_identity.py — SPEC_70 regression tests.

Pin the canonical SHA256 → base64 identity rule:

  1. MD5(...) as the raw-layer identity is REJECTED (MESA_RAW_ID_NON_CANONICAL).
  2. SHA1(...) is REJECTED for the same reason.
  3. The four canonical per-dialect idioms all VERIFY clean:
       BigQuery   TO_BASE64(SHA256(...))
       Snowflake  BASE64_ENCODE(SHA2_BINARY(TO_VARCHAR(...), 256))
       DuckDB     base64(from_hex(sha256(...)))
       Redshift   f_mesa_id(...)
"""


def test_md5_identity_is_non_canonical():
    from mesa_core.validate.mesa_verifier import (
        verify_raw_contract,
        CODE_ID_NON_CANONICAL,
    )

    sql = (
        "SELECT\n"
        "  MD5(CAST(Customer.c_custkey AS VARCHAR)) AS ID\n"
        "  , Customer.c_name AS CustomerName\n"
        "FROM {{ source('tpch', 'customer') }} AS Customer\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    codes = {f.code for f in result.findings}
    assert CODE_ID_NON_CANONICAL in codes
    assert result.status == "contradicted"


def test_sha1_identity_is_non_canonical():
    from mesa_core.validate.mesa_verifier import verify_raw_contract, CODE_ID_NON_CANONICAL

    sql = (
        "SELECT\n"
        "  SHA1(CAST(Customer.c_custkey AS VARCHAR)) AS ID\n"
        "  , Customer.c_name AS CustomerName\n"
        "FROM {{ source('tpch', 'customer') }} AS Customer\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    codes = {f.code for f in result.findings}
    assert CODE_ID_NON_CANONICAL in codes


def test_bigquery_identity_is_canonical():
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    sql = (
        "SELECT\n"
        "  TO_BASE64(SHA256(CAST(Customer.c_custkey AS STRING))) AS ID\n"
        "  , Customer.c_name AS CustomerName\n"
        "FROM {{ source('tpch', 'customer') }} AS Customer\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    assert result.blocking_findings() == []
    assert result.status == "verified"


def test_snowflake_identity_is_canonical():
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    sql = (
        "SELECT\n"
        "  BASE64_ENCODE(SHA2_BINARY(TO_VARCHAR(Customer.c_custkey), 256)) AS ID\n"
        "  , Customer.c_name AS CustomerName\n"
        "FROM {{ source('tpch', 'customer') }} AS Customer\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    assert result.blocking_findings() == []


def test_duckdb_identity_is_canonical():
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    sql = (
        "SELECT\n"
        "  base64(from_hex(sha256(CAST(Customer.c_custkey AS VARCHAR)))) AS ID\n"
        "  , Customer.c_name AS CustomerName\n"
        "FROM {{ source('tpch', 'customer') }} AS Customer\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    assert result.blocking_findings() == []


def test_redshift_native_sha2_identity_is_canonical():
    """Redshift's native SHA2(...) hex form is canonical — no UDF needed.
    (plpythonu was removed by AWS; verified live 2026-09-17 on both Serverless
    and provisioned — see /memories/repo/spec70_canonical_entity_id_sep2026.md.)"""
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    sql = (
        "SELECT\n"
        "  SHA2(CAST(Customer.c_custkey AS VARCHAR), 256) AS ID\n"
        "  , Customer.c_name AS CustomerName\n"
        "FROM {{ source('tpch', 'customer') }} AS Customer\n"
    )
    result = verify_raw_contract(sql, identity_column="ID")
    assert result.blocking_findings() == []


def test_identity_expr_per_dialect():
    from mesa_core.compiler.targets.dbt_render import identity_expr

    assert identity_expr("bigquery", "Customer.c_custkey") == (
        "TO_BASE64(SHA256(CAST(Customer.c_custkey AS STRING)))"
    )
    assert identity_expr("snowflake", "Customer.c_custkey") == (
        "BASE64_ENCODE(SHA2_BINARY(TO_VARCHAR(Customer.c_custkey), 256))"
    )
    assert identity_expr("duckdb", "Customer.c_custkey") == (
        "base64(from_hex(sha256(CAST(Customer.c_custkey AS VARCHAR))))"
    )
    # Redshift native form is HEX (no binary→base64, plpythonu removed).
    assert identity_expr("redshift", "Customer.c_custkey") == (
        "SHA2(CAST(Customer.c_custkey AS VARCHAR), 256)"
    )


def test_identity_hex_expr_per_dialect():
    """The 'hex only when needed' bridge: non-Redshift warehouses emit the hex
    form of SHA256 so a Redshift cross-warehouse join matches byte-for-byte."""
    from mesa_core.compiler.targets.dbt_render import identity_hex_expr

    assert identity_hex_expr("bigquery", "Customer.c_custkey") == (
        "TO_HEX(SHA256(CAST(Customer.c_custkey AS STRING)))"
    )
    assert identity_hex_expr("snowflake", "Customer.c_custkey") == (
        "SHA2(TO_VARCHAR(Customer.c_custkey), 256)"
    )
    assert identity_hex_expr("duckdb", "Customer.c_custkey") == (
        "sha256(CAST(Customer.c_custkey AS VARCHAR))"
    )
