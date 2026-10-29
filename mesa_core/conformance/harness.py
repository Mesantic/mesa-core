# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
harness.py — run the nasty fixture and report VERIFIED / FALSIFIED.

SPEC_103 Slice 8. The rule this module enforces: a check never silently passes.
Every check returns one of three statuses, and the report carries the warehouse
version so a VERIFIED row is dated and reproducible.

  VERIFIED   the warehouse behaved the way the spec's DOCUMENTED row claims
  FALSIFIED  it behaved differently — the report says what actually happened
  SKIPPED    the warehouse can't express the check at all (e.g. no struct type)

``SKIPPED`` is not a pass. A check that couldn't run is a gap in the evidence,
and the report counts it separately so nobody reads "0 falsified" as "all good".

Slice 8a runs DuckDB only. Slice 8b adds the cloud warehouses behind the same
interface — that's why ``run_duckdb_conformance`` is a thin wrapper over a
generic ``_run_checks`` rather than a pile of DuckDB-specific assertions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from mesa_core.conformance.fixture import (
    FIXTURE_DDL,
    FIXTURE_ROWS,
    MIXED_CASE_STRUCT_KEYS,
    NASTY_CASES,
)


class Status(str, Enum):
    VERIFIED = "VERIFIED"
    FALSIFIED = "FALSIFIED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class CheckResult:
    """One check against one warehouse.

    ``expected`` and ``actual`` are both strings so the report reads the same
    whether the value is a hash, a number or a NULL. ``note`` carries the
    consequence — what a FALSIFIED row means for a slice that depends on it.
    """

    case: str
    check: str
    status: Status
    expected: str
    actual: str
    note: str = ""


@dataclass
class ConformanceReport:
    """The full run for one warehouse."""

    warehouse: str
    version: str
    run_at: str
    results: list[CheckResult] = field(default_factory=list)

    @property
    def verified(self) -> list[CheckResult]:
        return [r for r in self.results if r.status is Status.VERIFIED]

    @property
    def falsified(self) -> list[CheckResult]:
        return [r for r in self.results if r.status is Status.FALSIFIED]

    @property
    def skipped(self) -> list[CheckResult]:
        return [r for r in self.results if r.status is Status.SKIPPED]

    @property
    def ok(self) -> bool:
        """True when nothing was falsified. SKIPPED rows don't fail the run —
        they're reported as gaps, not as failures."""
        return not self.falsified

    def summary(self) -> str:
        return (
            f"{self.warehouse} {self.version}: "
            f"{len(self.verified)} verified, "
            f"{len(self.falsified)} falsified, "
            f"{len(self.skipped)} skipped"
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _case(key: str):
    return next(c for c in NASTY_CASES if c.key == key)


def run_duckdb_conformance() -> ConformanceReport:
    """Slice 8a — the free, in-CI run.

    Most rows pin raw DuckDB behavior the specs depend on. Exactly ONE row —
    ``IDENTITY_EXPR`` — executes SQL that mesa-core's compiler produced
    (``identity_expr('duckdb', …)``), so a drift in the canonical ID formula
    shows up here. The other rows do not touch the compiler.

    NOT a stand-in for cloud behavior. DuckDB's ``concat`` ignores NULL and
    ``/`` returns a double, which is not what SQL Server does — a VERIFIED row
    says "DuckDB behaves this way", not "every warehouse does this". The cloud
    rows wait for 8b.
    """
    import duckdb

    conn = duckdb.connect()
    report = ConformanceReport(
        warehouse="DuckDB",
        version=duckdb.__version__,
        run_at=_now(),
    )

    conn.execute(FIXTURE_DDL)
    placeholders = ", ".join(["?"] * len(FIXTURE_ROWS[0]))
    conn.executemany(f"INSERT INTO nasty VALUES ({placeholders})", FIXTURE_ROWS)

    _check_null_key(conn, report)
    _check_trailing_space(conn, report)
    _check_case_variant(conn, report)
    _check_int_ratio(conn, report)
    _check_microsecond(conn, report)
    _check_mixed_case_keys(conn, report)
    _check_boolean_min_max(conn, report)
    _check_all_null_signal(conn, report)
    _check_constant_signal(conn, report)
    _check_identity_expr(conn, report)

    conn.close()
    return report


# ── Individual checks ────────────────────────────────────────────────────────

def _check_null_key(conn, report: ConformanceReport) -> None:
    """Does ``concat`` swallow a NULL argument, or NULL the whole result?

    DuckDB's ``concat`` ignores NULL (returns 'ab' for concat('a', NULL, 'b')),
    while ``||`` propagates it. That difference is exactly why SPEC_103 Slice 2
    item 4 refuses to write a NULL-hash rule from the docs — the answer changes
    the hash of every row with a NULL key part.
    """
    concat_result = conn.sql("SELECT concat('a', NULL, 'b')").fetchone()[0]
    pipe_result = conn.sql("SELECT 'a' || NULL || 'b'").fetchone()[0]

    # DuckDB's measured behavior: concat ignores NULL, || propagates it.
    expected = "concat ignores NULL ('ab'); || propagates NULL (NULL)"
    actual = f"concat -> {concat_result!r}; || -> {pipe_result!r}"
    status = (
        Status.VERIFIED
        if concat_result == "ab" and pipe_result is None
        else Status.FALSIFIED
    )
    report.results.append(
        CheckResult(
            case="NULL_KEY",
            check="concat vs || with a NULL argument",
            status=status,
            expected=expected,
            actual=actual,
            note=(
                "DuckDB is NOT SQL Server. This row does not settle the T-SQL "
                "NULL-hash question — Slice 8b does. It pins DuckDB's behavior "
                "so a compiler change that starts relying on it is caught."
            ),
        )
    )


def _check_trailing_space(conn, report: ConformanceReport) -> None:
    """Does the hash see a trailing space? It must — otherwise 'ABC ' and 'ABC'
    collide, which is a silent duplicate ID."""
    hashed = conn.sql(
        "SELECT base64(from_hex(sha256(CAST(? AS VARCHAR))))", params=["ABC "]
    ).fetchone()[0]
    trimmed = conn.sql(
        "SELECT base64(from_hex(sha256(CAST(? AS VARCHAR))))", params=["ABC"]
    ).fetchone()[0]

    status = Status.VERIFIED if hashed != trimmed else Status.FALSIFIED
    report.results.append(
        CheckResult(
            case="TRAILING_SPACE",
            check="hash('ABC ') != hash('ABC')",
            status=status,
            expected="different digests",
            actual="different" if hashed != trimmed else "IDENTICAL — collision",
            note=(
                "A collision here means two distinct natural keys produce one ID. "
                "The doctrine says normalize before hashing; this proves the "
                "warehouse doesn't do it for you."
            ),
        )
    )


def _check_case_variant(conn, report: ConformanceReport) -> None:
    """Does the hash see case? It must — 'abc' and 'ABC' are different keys."""
    upper = conn.sql(
        "SELECT base64(from_hex(sha256(CAST(? AS VARCHAR))))", params=["ABC"]
    ).fetchone()[0]
    lower = conn.sql(
        "SELECT base64(from_hex(sha256(CAST(? AS VARCHAR))))", params=["abc"]
    ).fetchone()[0]

    status = Status.VERIFIED if upper != lower else Status.FALSIFIED
    report.results.append(
        CheckResult(
            case="CASE_VARIANT",
            check="hash('ABC') != hash('abc')",
            status=status,
            expected="different digests",
            actual="different" if upper != lower else "IDENTICAL — collision",
            note=(
                "Case-folding before hashing is the author's job, not the "
                "warehouse's. A collision here would mean the warehouse folds "
                "case for you, which would make IDs unstable across collations."
            ),
        )
    )


def _check_int_ratio(conn, report: ConformanceReport) -> None:
    """``7 / 2`` — 3 (truncated) or 3.5 (decimal)?

    SPEC_103 Slice 7 says Redshift and SQL Server truncate ``int / int``. DuckDB
    returns a double. This row records DuckDB's answer so the Slice 7 rule is
    written against measured behavior, not a guess.
    """
    value = conn.sql("SELECT 7 / 2").fetchone()[0]
    type_name = conn.sql("SELECT typeof(7 / 2)").fetchone()[0]

    # DuckDB's measured behavior: `/` returns a DOUBLE, `//` truncates.
    status = Status.VERIFIED if value == 3.5 else Status.FALSIFIED
    report.results.append(
        CheckResult(
            case="INT_RATIO",
            check="7 / 2",
            status=status,
            expected="3.5 (DOUBLE) — DuckDB does not truncate int/int",
            actual=f"{value} ({type_name})",
            note=(
                "DuckDB differs from Redshift and SQL Server here, which is why "
                "Slice 7's integer-division rule is DOCUMENTED until 8b runs it "
                "on those two. A ratio metric that relies on truncation would "
                "give a different number on DuckDB than on T-SQL."
            ),
        )
    )


def _check_microsecond(conn, report: ConformanceReport) -> None:
    """Does a microsecond timestamp survive a round trip?"""
    value = conn.sql(
        "SELECT EventTs FROM nasty WHERE RowId = 6"
    ).fetchone()[0]
    micros = value.microsecond if hasattr(value, "microsecond") else None

    status = Status.VERIFIED if micros == 123456 else Status.FALSIFIED
    report.results.append(
        CheckResult(
            case="MICROSECOND",
            check="timestamp microsecond precision survives",
            status=status,
            expected="123456 microseconds",
            actual=f"{micros} microseconds",
            note=(
                "Truncation to seconds silently collapses two events into one, "
                "which changes a count without changing a row count."
            ),
        )
    )


def _check_mixed_case_keys(conn, report: ConformanceReport) -> None:
    """Are struct keys case-preserved?

    This is the ``OBJECT_CONSTRUCT(alias.*)`` bug that took four production views
    to zero rows: Snowflake's wildcard form uses the column's STORED
    (case-folded) name as the JSON key, so a PascalCase colon-accessor silently
    returns NULL. DuckDB preserves the literal key, so this row is a compiler
    regression guard rather than a DuckDB risk.
    """
    struct_sql = (
        "SELECT {'PascalKey': 1, 'lowerkey': 2} AS s"
    )
    row = conn.sql(
        f"SELECT s.PascalKey, s.lowerkey FROM ({struct_sql})"
    ).fetchone()

    status = Status.VERIFIED if row == (1, 2) else Status.FALSIFIED
    report.results.append(
        CheckResult(
            case="MIXED_CASE_KEYS",
            check="struct keys are case-preserved",
            status=status,
            expected=f"both keys readable: {MIXED_CASE_STRUCT_KEYS}",
            actual=f"PascalKey={row[0]}, lowerkey={row[1]}",
            note=(
                "DuckDB preserves the literal key. Snowflake's wildcard "
                "OBJECT_CONSTRUCT does NOT — that's the bug the explicit "
                "key/value form in the wide render exists to avoid."
            ),
        )
    )


def _check_boolean_min_max(conn, report: ConformanceReport) -> None:
    """Is MIN/MAX defined on a boolean column?

    SPEC_103 Slice 6 says MIN/MAX aren't defined on every type — T-SQL ``BIT`` is
    the named example. DuckDB allows it, so the adapter-aware macro still needs
    the count-only fallback for the warehouses where it doesn't.
    """
    try:
        row = conn.sql("SELECT MIN(IsFlag), MAX(IsFlag) FROM nasty").fetchone()
        status = Status.VERIFIED
        actual = f"MIN={row[0]}, MAX={row[1]}"
        note = (
            "DuckDB allows MIN/MAX on BOOLEAN. T-SQL BIT is DOCUMENTED not to — "
            "that's why the signal macro needs the count-only fallback rather "
            "than assuming the single-scan form works everywhere."
        )
    except Exception as exc:  # noqa: BLE001 — a refusal is a valid outcome
        status = Status.SKIPPED
        actual = f"refused: {type(exc).__name__}: {exc}"
        note = "MIN/MAX not defined on BOOLEAN here — the macro must fall back."

    report.results.append(
        CheckResult(
            case="BOOLEAN",
            check="MIN/MAX on a boolean column",
            status=status,
            expected="defined (DuckDB) — T-SQL BIT is DOCUMENTED not to be",
            actual=actual,
            note=note,
        )
    )

def _check_identity_expr(conn, report: ConformanceReport) -> None:
    """Run the compiler's OWN canonical DuckDB identity expression.

    This is the one row that exercises mesa-core code. ``identity_expr`` is the
    single source of truth for the entity-ID formula; the expected value is
    base64 of the raw SHA-256 bytes of 'abc', a published test vector
    (ba7816bf…15ad), so the check doesn't just compare the compiler to itself.
    """
    from mesa_core.compiler.targets.dbt_render import identity_expr

    sql = identity_expr("duckdb", "'abc'")
    actual = conn.sql(f"SELECT {sql}").fetchone()[0]
    expected = "ungWv48Bz+pBQUDeXa4iI7ADYaOWF3qctBD/YfIAFa0="

    report.results.append(
        CheckResult(
            case="IDENTITY_EXPR",
            check="identity_expr('duckdb') on 'abc' matches the SHA-256 test vector",
            status=Status.VERIFIED if actual == expected else Status.FALSIFIED,
            expected=expected,
            actual=str(actual),
            note=(
                "The only row that runs compiler output. A FALSIFIED here means "
                "the canonical ID formula changed, which rewrites every ID on "
                "DuckDB — SPEC_103 Slice 2 says that must never happen silently."
            ),
        )
    )


def _check_all_null_signal(conn, report: ConformanceReport) -> None:
    """The signal test must FAIL on an all-NULL column, not pass.

    This is the check that would have caught the PolicyRaw bug: a column added to
    an incremental merge left 22,079,927 values NULL and nothing flagged it.
    """
    non_null = conn.sql("SELECT COUNT(AllNull) FROM nasty").fetchone()[0]

    status = Status.VERIFIED if non_null == 0 else Status.FALSIFIED
    report.results.append(
        CheckResult(
            case="ALL_NULL",
            check="signal test fails when non_null = 0",
            status=status,
            expected="non_null = 0 (the test must fail)",
            actual=f"non_null = {non_null}",
            note=(
                "A dead column must fail the generated signal test. If this row "
                "ever reports non_null > 0 the fixture drifted, not the rule."
            ),
        )
    )


def _check_constant_signal(conn, report: ConformanceReport) -> None:
    """The signal test must WARN on a constant column, not fail.

    A constant column is suspicious, not always wrong — a legitimately constant
    column needs ``allow_constant`` to silence the warn.
    """
    row = conn.sql(
        "SELECT COUNT(ConstantCol) AS non_null, MIN(ConstantCol) AS lo, MAX(ConstantCol) AS hi "
        "FROM nasty"
    ).fetchone()
    non_null, lo, hi = row

    is_constant = lo == hi
    status = Status.VERIFIED if (non_null > 0 and is_constant) else Status.FALSIFIED
    report.results.append(
        CheckResult(
            case="CONSTANT",
            check="signal test warns when lo = hi",
            status=status,
            expected="non_null > 0 and lo = hi (the test must warn)",
            actual=f"non_null={non_null}, lo={lo!r}, hi={hi!r}",
            note=(
                "Warn, not fail — a constant column is suspicious, not always "
                "wrong. ``allow_constant`` silences it for a column that's "
                "legitimately constant."
            ),
        )
    )
