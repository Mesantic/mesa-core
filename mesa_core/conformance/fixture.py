# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
fixture.py — the one deliberately nasty table (SPEC_103 Slice 8).

Every row here is a case that has bitten a real build, or that a DOCUMENTED row
in SPEC_103 depends on. The point is not to be realistic — it's to be hostile in
the specific ways warehouses disagree.

The cases, and why each one is here:

  NULL_KEY        A NULL natural key. SPEC_103 Slice 2 item 4 says ``CONCAT``
                  treats NULL differently on SQL Server than on Snowflake. This
                  row is what settles it.
  TRAILING_SPACE  ``'ABC '`` vs ``'ABC'``. A hash over the raw string differs; a
                  hash over a trimmed string doesn't. Which one a warehouse does
                  is the question.
  CASE_VARIANT    ``'abc'`` vs ``'ABC'``. Same shape of question as the trailing
                  space, and the answer is usually "differs" — which is why the
                  doctrine says normalize before hashing.
  INT_RATIO       ``7 / 2``. SPEC_103 Slice 7 says Redshift and SQL Server
                  truncate ``int / int`` to 3. DuckDB returns 3.5. This row is
                  the integer-division check.
  MICROSECOND     A timestamp with microseconds. Truncation to seconds silently
                  collapses two events into one.
  MIXED_CASE_KEYS A struct/object with ``PascalKey`` and ``lowerkey``. This is
                  the ``OBJECT_CONSTRUCT(alias.*)`` uppercase-key bug that took
                  four production views to zero rows.
  BOOLEAN         A ``BIT``/boolean column. SPEC_103 Slice 6 says ``MIN``/``MAX``
                  aren't defined on every type — T-SQL ``BIT`` is the example.
  ALL_NULL        A column that is NULL in every row. The signal test must fail
                  on this (``non_null = 0``), not pass.
  CONSTANT        A column with one distinct value. The signal test must WARN
                  (``lo = hi``), not fail — a constant column is suspicious, not
                  always wrong.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NastyCase:
    """One hostile case in the fixture, with what it's probing for."""

    key: str
    description: str
    # The SPEC_103 row this case settles, or None when it's a compiler regression
    # guard rather than a DOCUMENTED warehouse claim.
    spec_row: str | None = None


NASTY_CASES: tuple[NastyCase, ...] = (
    NastyCase(
        key="NULL_KEY",
        description="A NULL natural key — does CONCAT/|| swallow it or NULL the whole hash?",
        spec_row="Slice 2 item 4 (NULL in CONCAT)",
    ),
    NastyCase(
        key="TRAILING_SPACE",
        description="'ABC ' vs 'ABC' — does the hash see the trailing space?",
        spec_row="Slice 2 item 5 (input bytes)",
    ),
    NastyCase(
        key="CASE_VARIANT",
        description="'abc' vs 'ABC' — does the hash see case?",
        spec_row="Slice 2 item 5 (input bytes)",
    ),
    NastyCase(
        key="INT_RATIO",
        description="7 / 2 — integer division truncates or returns a decimal?",
        spec_row="Slice 7 item 1 (integer division)",
    ),
    NastyCase(
        key="MICROSECOND",
        description="A microsecond timestamp — does it survive, or truncate to seconds?",
        spec_row=None,
    ),
    NastyCase(
        key="MIXED_CASE_KEYS",
        description="A struct with PascalKey + lowerkey — are keys case-preserved?",
        spec_row="Slice 6 (OBJECT_CONSTRUCT uppercase keys)",
    ),
    NastyCase(
        key="BOOLEAN",
        description="A boolean/BIT column — is MIN/MAX defined on it?",
        spec_row="Slice 6 item 1 (MIN/MAX on BIT)",
    ),
    NastyCase(
        key="ALL_NULL",
        description="A column NULL in every row — the signal test must FAIL, not pass.",
        spec_row="Slice 6 (signal test)",
    ),
    NastyCase(
        key="CONSTANT",
        description="A column with one distinct value — the signal test must WARN.",
        spec_row="Slice 6 (signal test)",
    ),
)

# The fixture table. Deliberately plain ANSI so every warehouse can create it;
# the interesting parts are the VALUES, not the DDL.
FIXTURE_DDL = """
CREATE TABLE nasty (
    RowId        INTEGER      NOT NULL,
    NaturalKey   VARCHAR,
    RatioNum     INTEGER      NOT NULL,
    RatioDen     INTEGER      NOT NULL,
    EventTs      TIMESTAMP,
    IsFlag       BOOLEAN,
    AllNull      VARCHAR,
    ConstantCol  VARCHAR
)
"""

# (RowId, NaturalKey, RatioNum, RatioDen, EventTs, IsFlag, AllNull, ConstantCol)
#
# Row 1  — the baseline: a clean key.
# Row 2  — NULL natural key (NULL_KEY).
# Row 3  — trailing space (TRAILING_SPACE).
# Row 4  — case variant of row 1's key (CASE_VARIANT).
# Row 5  — the integer ratio 7/2 (INT_RATIO).
# Row 6  — a microsecond timestamp (MICROSECOND).
# Row 7  — a boolean false, so the column isn't constant (BOOLEAN).
FIXTURE_ROWS: tuple[tuple, ...] = (
    (1, "ABC", 7, 2, "2026-01-01 00:00:00.000000", True, None, "only"),
    (2, None, 7, 2, "2026-01-01 00:00:00.000000", True, None, "only"),
    (3, "ABC ", 7, 2, "2026-01-01 00:00:00.000000", True, None, "only"),
    (4, "abc", 7, 2, "2026-01-01 00:00:00.000000", True, None, "only"),
    (5, "DEF", 7, 2, "2026-01-01 00:00:00.000000", True, None, "only"),
    (6, "GHI", 7, 2, "2026-01-01 00:00:00.123456", True, None, "only"),
    (7, "JKL", 7, 2, "2026-01-01 00:00:00.000000", False, None, "only"),
)

# The mixed-case struct, kept separate because not every warehouse can put a
# struct in a table column. Each harness builds it inline in its own dialect.
MIXED_CASE_STRUCT_KEYS: tuple[str, ...] = ("PascalKey", "lowerkey")
