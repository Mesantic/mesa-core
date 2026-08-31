# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
scaffold.py — ``mesa new entity`` — mechanical four-tier stub generator.

SPEC_66 Slice 4b. The FREE gold-table onboarding path (dbt-codegen precedent).

HARD BOUNDARY (STOP RULE 7): this command reads a COLUMN LIST and nothing more.
It NEVER parses, interprets, classifies, or reasons about an existing gold
table's CTEs, joins, or metric logic. It maps column names to PascalCase alias
placeholders and stamps boilerplate — that is the entire job. Intelligent
decomposition is SPEC_63, lives in Mesantic, and is permanently out of scope.

``--from-ddl`` uses sqlglot ONLY to pull column NAMES out of a CREATE TABLE —
it never reads a SELECT/CTE body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScaffoldResult:
    entity_name: str
    files_created: list[str]


def _pascal_case(col_name: str) -> str:
    """snake_case / SCREAMING_SNAKE → PascalCase.

    Raw source columns are ALL_CAPS_WITH_UNDERSCORES (raw-layer doctrine); the
    enriched business attribute alias is PascalCase (no underscores).
    """
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", col_name) if p]
    if not parts:
        return col_name
    return "".join(p[:1].upper() + p[1:].lower() for p in parts)


def _extract_columns_from_ddl(ddl: str) -> list[str]:
    """Extract column NAMES from a CREATE TABLE DDL using sqlglot.

    Uses sqlglot ONLY for the column-name list — it never reads a SELECT/CTE
    body. If sqlglot is unavailable or fails, falls back to a regex on the
    parenthesised column list. Never raises.
    """
    try:
        import sqlglot
        statements = sqlglot.parse(ddl, dialect=None)
        if statements:
            stmt = statements[0]
            schema = getattr(stmt, "this", None)
            # sqlglot CREATE nodes expose a Schema with .expressions (columns).
            expressions = getattr(schema, "expressions", None)
            if expressions:
                cols = []
                for e in expressions:
                    name = getattr(e, "name", None) or getattr(e, "this", None)
                    if name is not None:
                        cols.append(str(name))
                if cols:
                    return cols
    except Exception:
        pass

    # Regex fallback: first parenthesised group after the table name.
    m = re.search(r"\(([^;]*)\)", ddl, re.DOTALL)
    if not m:
        return []
    cols = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        # "col_name TYPE ..." → leading identifier (possibly quoted/backticked).
        mm = re.match(r"[\"`']?([A-Za-z_][A-Za-z0-9_]*)[\"`']?", part)
        if mm:
            cols.append(mm.group(1))
    return cols


def _columns_from_duckdb(table_name: str, db_path: str | None = None) -> list[str]:
    """Read a column LIST from a local DuckDB table.

    DuckDB is imported lazily; if it is not installed, return [] and let the
    caller surface a clear message (rather than crash the CLI).
    """
    try:
        import duckdb
    except ImportError:
        raise RuntimeError(
            "duckdb is not installed. pip install duckdb to use --from-duckdb."
        )
    con = duckdb.connect(db_path) if db_path else duckdb.connect()
    try:
        rows = con.execute(f"DESCRIBE {table_name}").fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows]


def _raw_sql_stub(entity_name: str, columns: list[str]) -> str:
    alias_lines = "".join(
        f"        , Source.{col} AS {_pascal_case(col)}\n"
        for col in columns
    )
    return (
        f"-- RAW ENTITY: {entity_name}\n"
        f"-- Grain: one row per {entity_name.lower()} <-- FILL IN the exact grain>\n"
        f"-- ID: hashed primary key — BASE64_ENCODE(SHA2(<FILL IN natural key>, 256))\n"
        f"-- Doctrine: 1:1 enrichment at top level; 1:many detail as typed ARRAYs;\n"
        f"--           system IDs in typed system-specific OBJECTs, never bare.\n"
        f"--           THIS ENTITY IS THE CONTRACT.\n"
        f"\n"
        f"SELECT\n"
        f"    BASE64_ENCODE(SHA2(<FILL IN natural key>, 256)) AS ID\n"
        f"{alias_lines}"
        f"FROM {{{{ source('<source>', '<table>') }}}} AS Source\n"
    )


def _metric_yml_stub(entity_name: str) -> str:
    return (
        f"version: 2\n"
        f"\n"
        f"models:\n"
        f"  # Metric files for {entity_name} go in metric_layer/{entity_name}_Metrics/.\n"
        f"  # One file = one metric. Add column tests on ID: [not_null, unique].\n"
    )


def _source_yml_stub(entity_name: str) -> str:
    return (
        f"version: 2\n"
        f"\n"
        f"sources:\n"
        f"  - name: <source>\n"
        f"    database: <FILL IN>\n"
        f"    schema: <FILL IN>\n"
        f"    tables:\n"
        f"      - name: <table>\n"
        f"        description: Source table for the {entity_name} entity.\n"
    )


def _wide_yml_stub(entity_name: str) -> str:
    return (
        f"version: 2\n"
        f"\n"
        f"models:\n"
        f"  - name: {entity_name}Wide\n"
        f"    description: |\n"
        f"      WIDE LAYER: {entity_name} wide table — auto-assembled, do not hand-edit.\n"
    )


def scaffold_entity(
    entity_name: str,
    columns: list[str],
    *,
    models_dir: str | Path = "models",
) -> ScaffoldResult:
    """Stamp the four-tier stub for ONE entity from a column list.

    Matching CAO's verified layout:
      raw_layer/<Entity>/<Entity>Raw.sql
      raw_layer/_raw.yml (only if not already present — left alone otherwise)
      metric_layer/<Entity>_Metrics/ (empty) + _<entity>_metrics.yml sidecar
      wide_layer/<Entity>Wide.sql (auto-assembly stub) + _wide.yml
      sources/<source>.yml stub
    """
    if not entity_name:
        raise ValueError("entity name is required")
    if not columns:
        raise ValueError("no columns provided — pass a column list via --from-columns/--from-ddl/--from-duckdb")

    root = Path(models_dir)
    created: list[str] = []

    # 1. Raw layer
    raw_dir = root / "raw_layer" / entity_name
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / f"{entity_name}Raw.sql"
    raw_file.write_text(_raw_sql_stub(entity_name, columns))
    created.append(str(raw_file))

    # 2. Metric layer — empty folder + sidecar
    metric_dir = root / "metric_layer" / f"{entity_name}_Metrics"
    metric_dir.mkdir(parents=True, exist_ok=True)
    metric_yml = metric_dir / f"_{entity_name.lower()}_metrics.yml"
    metric_yml.write_text(_metric_yml_stub(entity_name))
    created.append(str(metric_yml))

    # 3. Wide layer — auto-assembly stub + sidecar
    wide_dir = root / "wide_layer"
    wide_dir.mkdir(parents=True, exist_ok=True)
    wide_file = wide_dir / f"{entity_name}Wide.sql"
    wide_file.write_text(
        f"-- WIDE LAYER: {entity_name} Wide Table\n"
        f"-- AUTO-GENERATED by mesa build — DO NOT EDIT BY HAND.\n"
        f"-- Consumer access: {entity_name}Wide.{entity_name}:<Field> / "
        f"{entity_name}Wide.<MetricName>:<MetricName> / ...\n"
        f"\n"
        f"SELECT\n"
        f"    {entity_name}.{entity_name} AS {entity_name}\n"
        f"FROM {{{{ ref('{entity_name}Raw') }}}} AS {entity_name}\n"
    )
    created.append(str(wide_file))
    wide_yml = wide_dir / "_wide.yml"
    if not wide_yml.exists():
        wide_yml.write_text(_wide_yml_stub(entity_name))
        created.append(str(wide_yml))

    # 4. Sources — stub
    src_dir = root / "sources"
    src_dir.mkdir(parents=True, exist_ok=True)
    source_file = src_dir / "placeholder_source.yml"
    if not source_file.exists():
        source_file.write_text(_source_yml_stub(entity_name))
        created.append(str(source_file))

    return ScaffoldResult(entity_name=entity_name, files_created=created)


# ── Project scaffold (``mesa init``) ─────────────────────────────────────────

def scaffold_project(name: str, *, root: str | Path, warehouse: str = "Snowflake") -> Path:
    """Scaffold an empty four-tier project + mesa_project.yml (``mesa init``)."""
    root = Path(root)
    (root / "models" / "raw_layer").mkdir(parents=True, exist_ok=True)
    (root / "models" / "metric_layer").mkdir(parents=True, exist_ok=True)
    (root / "models" / "wide_layer").mkdir(parents=True, exist_ok=True)
    (root / "models" / "view_layer").mkdir(parents=True, exist_ok=True)
    (root / "models" / "sources").mkdir(parents=True, exist_ok=True)
    (root / "target").mkdir(parents=True, exist_ok=True)

    proj_yml = root / "mesa_project.yml"
    proj_yml.write_text(
        f"name: {name}\n"
        f"version: '1.0.0'\n"
        f"default_warehouse: {warehouse}\n"
        f"model-paths: [\"models\"]\n"
        f"target-dir: target\n"
    )
    return proj_yml
