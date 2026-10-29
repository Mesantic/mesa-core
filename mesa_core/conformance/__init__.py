# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
conformance — the warehouse behavior harness (SPEC_103 Slice 8).

Slice 8 exists because a lot of what the specs say about warehouse behavior is
DOCUMENTED, not VERIFIED. Nobody ran it. The harness turns those rows into
VERIFIED or FALSIFIED, one warehouse at a time.

Two halves, deliberately separated by cost:

  * **8a — DuckDB, free, runs in CI.** This is a regression suite for mesa-core's
    own compiler. It is NOT a stand-in for cloud behavior: DuckDB's ``concat``
    ignores NULL and ``/`` returns a double, which is not what SQL Server does.
    What it does prove is that the compiler's emitted SQL is stable and that the
    fixture's expected values don't drift between releases.
  * **8b — cloud, manual or nightly, ~$1/hr.** Needs Steve's OK per run. That's
    where the DOCUMENTED rows about T-SQL, Redshift and BigQuery actually get
    settled.

The fixture is one deliberately nasty table. Every row is a case that has bitten
a real build: a NULL natural key, a trailing space, case variants, an integer
ratio, a microsecond timestamp, mixed-case struct keys, a boolean column, and an
all-NULL column. Each check reports VERIFIED (with the warehouse version) or
FALSIFIED (with what actually happened) — never a silent pass.
"""

from mesa_core.conformance.fixture import (
    FIXTURE_DDL,
    FIXTURE_ROWS,
    NASTY_CASES,
    NastyCase,
)
from mesa_core.conformance.harness import (
    CheckResult,
    ConformanceReport,
    Status,
    run_duckdb_conformance,
)
from mesa_core.conformance.report import render_markdown

__all__ = [
    "FIXTURE_DDL",
    "FIXTURE_ROWS",
    "NASTY_CASES",
    "NastyCase",
    "CheckResult",
    "ConformanceReport",
    "Status",
    "run_duckdb_conformance",
    "render_markdown",
]
