# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
mesa_core — the free, MIT-licensed MESA semantic compiler.

This is the dbt-Core equivalent for MESA: it reads on-disk four-tier
definition files (raw / metric / wide / view) and compiles them into
correct, dialect-specific SQL, with MESA's opinionated validation refusing
bad definitions — all locally, with no account, no database, and no data
leaving the machine.

Hard rule (SPEC_66): this package must NEVER import fastapi, sqlalchemy,
aiosqlite, pydantic, or anything under ``api.*``. It is a pure, stateless,
one-shot compiler.
"""

__version__ = "0.1.0"
