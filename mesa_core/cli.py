# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
cli.py — the ``mesa`` command-line interface (file-based, NO server).

SPEC_66 Slice 4. This CLI compiles locally from files on disk — it is the
dbt-Core-equivalent front door. It does NOT call a running server (that was the
old httpx client in the governance repo). No httpx, no fastapi, no DB.

Commands:
  mesa init <name>              scaffold a new four-tier project
  mesa new entity <name>        mechanical four-tier stub from a column list
  mesa build                    compile all layers -> target/
  mesa compile <entity>         compile one entity's metric+wide layers
  mesa validate                 run the validation brain; non-zero on violation
  mesa fmt                      run the formatter, rewrite authored files
  mesa lint                     formatter check-mode; non-zero on violation
  mesa learn                    the guided ~20-minute tutorial (SPEC_67)
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mesa_core import __version__


def _load(models_dir: str):
    from mesa_core.project import load_project

    proj = load_project(models_dir)
    if proj.load_errors:
        click.echo(click.style("Warnings loading project:", fg="yellow"), err=True)
        for err in proj.load_errors:
            click.echo(f"  - {err}", err=True)
    return proj


@click.group()
@click.version_option(__version__, "-V", "--version", prog_name="mesa",
                      message="%(prog)s %(version)s")
def cli() -> None:
    """MESA Core — compile + validate on-disk four-tier definitions locally.

    MESA enforces a strict four-tier architecture. Data flows one direction,
    and each tier has exactly one job:

    \b
      1. Raw Layer     business entities with hashed IDs (identity, no logic)
      2. Metric Layer  one file = one metric = one owner (all the logic)
      3. Wide Layer    pure assembly, no logic (auto-generated)
      4. View Layer    consumer-facing, BI-ready output

    \b
    Quick start:
      mesa init myproject                              # scaffold a project
      cd myproject
      mesa new entity Customer --from-columns cols.txt # stub an entity
      mesa validate                                    # check for violations
      mesa build                                       # compile to target/

    \b
    New to MESA? Learn the vocabulary hands-on in ~20 minutes:
      mesa learn

    Run 'mesa COMMAND --help' for detailed help and examples on any command.
    """


@cli.command()
@click.argument("name")
@click.option("--warehouse", default="Snowflake",
              help="Default warehouse dialect (Snowflake|BigQuery|Redshift|DuckDB).")
def init(name: str, warehouse: str) -> None:
    """Scaffold a new four-tier project in ./<name>.

    Creates a complete MESA project structure so you can start authoring
    entities right away.

    \b
    What gets created:
      - models/ directory (raw, metric, wide, view layers)
      - mesa_project.yml (project metadata)
      - sources.yml (source system registry)
      - .gitignore, README

    After running this, cd into the project directory and create your
    first entity with 'mesa new entity'.

    \b
    Examples:
      mesa init myproject
      mesa init analytics --warehouse BigQuery
      mesa init warehouse --warehouse Snowflake
    """
    from mesa_core.scaffold import scaffold_project

    root = Path(name)
    proj_yml = scaffold_project(name, root=root, warehouse=warehouse)
    click.echo(f"Created project '{name}' at {root}/ (project file: {proj_yml.name}).")
    click.echo(f"Next: cd {name} && mesa new entity <EntityName> --from-columns cols.txt")


@cli.group()
def new() -> None:
    """Scaffold new objects into an existing project.

    Run this from inside a project created by 'mesa init'. Today the only
    object type is 'entity' — it stamps all four tiers for one business
    concept from a column list.

    \b
    Examples:
      mesa new entity Customer --from-columns cols.txt
      mesa new entity Order --from-ddl order_schema.sql

    See 'mesa new entity --help' for the full column-source options.
    """


@new.command("entity")
@click.argument("entity")
@click.option("--from-columns", type=click.Path(exists=True, dir_okay=False),
              help="File with one column name per line.")
@click.option("--from-ddl", type=click.Path(exists=True, dir_okay=False),
              help="CREATE TABLE DDL file (column names extracted via sqlglot).")
@click.option("--from-duckdb", metavar="TABLE",
              help="Read column list from a local DuckDB table.")
@click.option("--duckdb-path", default=None, metavar="PATH",
              help="Path to the DuckDB database file (for --from-duckdb).")
@click.option("--models-dir", default="models", metavar="DIR",
              help="Models directory to scaffold into (default: models).")
def new_entity(entity: str, from_columns, from_ddl, from_duckdb, duckdb_path, models_dir) -> None:
    """Stamp a mechanical four-tier stub for ONE entity from a column list.

    You provide the column list, MESA generates the structure. After
    scaffolding, fill in the grain, natural key logic, and mark which
    columns are enrichment vs system-STRUCT vs link-carrier.

    \b
    Creates all four layers for a new entity:
      - models/raw_layer/<Entity>Raw.sql       (with hashed ID)
      - models/metric_layer/<Entity>/          (empty, ready for metrics)
      - models/wide_layer/<Entity>Wide.sql     (assembly template)
      - models/view_layer/<Entity>View.sql     (consumer template)

    \b
    Three ways to provide columns:
      --from-columns   plain text file, one column per line
      --from-ddl       CREATE TABLE statement (parsed via sqlglot)
      --from-duckdb    pull schema from a local DuckDB table

    \b
    Examples:
      mesa new entity Customer --from-columns customer_cols.txt
      mesa new entity Order --from-ddl order_schema.sql
      mesa new entity Policy --from-duckdb my_policies --duckdb-path data.db

    \b
    Next steps after scaffolding:
      1. Edit <Entity>Raw.sql — fix the grain and hashed ID logic
      2. Run 'mesa validate' to catch violations
      3. Add metrics in models/metric_layer/<Entity>/
      4. Run 'mesa build' to compile
    """
    from mesa_core.scaffold import (
        scaffold_entity,
        _extract_columns_from_ddl,
        _columns_from_duckdb,
    )

    if from_columns:
        columns = [ln.strip() for ln in Path(from_columns).read_text().splitlines() if ln.strip()]
    elif from_ddl:
        columns = _extract_columns_from_ddl(Path(from_ddl).read_text())
    elif from_duckdb:
        columns = _columns_from_duckdb(from_duckdb, duckdb_path)
    else:
        raise click.UsageError(
            "provide one of --from-columns, --from-ddl, or --from-duckdb"
        )

    if not columns:
        raise click.UsageError("no columns extracted — check your input")

    result = scaffold_entity(entity, columns, models_dir=models_dir)
    click.echo(f"Scaffolded entity '{result.entity_name}' ({len(columns)} columns):")
    for f in result.files_created:
        click.echo(f"  {f}")
    click.echo(click.style(
        "Fill in the grain, natural key, and which columns are enrichment vs "
        "system-STRUCT vs link-carrier, then `mesa validate`.", fg="yellow"))


@cli.command()
@click.option("--models-dir", default="models", metavar="DIR", help="Models directory.")
def build(models_dir: str) -> None:
    """Compile all four tiers into target/.

    Compiles every entity's metrics and wide tables, writing dialect-specific
    SQL to the target/ directory. This is the "dbt compile" equivalent — it
    validates that your models/ directory is internally consistent and
    produces warehouse-ready SQL.

    \b
    What gets compiled:
      - Metric Layer: one CTE per metric file, wrapped in a single SELECT
      - Wide Layer:   joins Raw + Metric STRUCTs for each entity
      - View Layer:   copied as-is (authored views are already final SQL)

    The target/ directory structure mirrors models/ but contains only
    compiled SQL ready for deployment (via dbt, Snowsight, or CI/CD).

    \b
    Examples:
      mesa build
      mesa build --models-dir custom_models/

    Use 'mesa compile <Entity>' to compile just one entity and see the SQL.
    """
    from mesa_core import build as _build

    proj = _load(models_dir)
    target_dir = Path(models_dir).resolve().parent / "target"
    written = _build.build(proj, target_dir=target_dir)
    click.echo(f"Compiled {proj.name} ({len(proj.entities)} entities) -> {len(written)} files in {target_dir}/.")


@cli.command()
@click.argument("entity")
@click.option("--models-dir", default="models", metavar="DIR", help="Models directory.")
@click.option("--warehouse", default=None, metavar="WAREHOUSE", help="Override target warehouse (Snowflake, BigQuery, Redshift, DuckDB).")
@click.option("--out", default=None, metavar="PATH", help="Write output to a file instead of stdout.")
def compile(entity: str, models_dir: str, warehouse: str, out) -> None:
    """Compile one entity's metric + wide layers.

    Compiles a single entity and prints the resulting SQL to stdout (or a
    file with --out). Use this to inspect what SQL MESA generates from your
    metric files, or to see how semantic compilation produces different SQL
    for different warehouses.

    Unlike 'mesa build', this doesn't write to target/ — it's a dry-run for
    one entity, useful for debugging or learning how the compiler works.

    The --warehouse flag demonstrates MESA's "compile once, ship everywhere"
    capability: the same metric definitions produce BigQuery-flavored SQL,
    Snowflake-flavored SQL, etc.

    \b
    Examples:
      mesa compile Customer
      mesa compile Order --warehouse BigQuery
      mesa compile Policy --warehouse Snowflake --out policy_wide.sql
      mesa compile Customer --out - | less

    \b
    What you see:
      - Metric Layer SQL (all metrics as one CTE-wrapped SELECT)
      - Wide Layer SQL  (Raw + Metric assembly with STRUCTs)
    """
    from mesa_core import build as _build

    proj = _load(models_dir)
    target = next((e for e in proj.entities if e.entity_name == entity), None)
    if target is None:
        click.echo(f"Entity '{entity}' not found.", err=True)
        sys.exit(1)

    # Override warehouse if specified, normalize to expected casing
    if warehouse:
        # Normalize warehouse names to match compiler expectations
        wh_lower = warehouse.lower()
        if wh_lower == "bigquery":
            target_warehouse = "BigQuery"
        elif wh_lower == "snowflake":
            target_warehouse = "Snowflake"
        elif wh_lower == "redshift":
            target_warehouse = "Redshift"
        elif wh_lower == "duckdb":
            target_warehouse = "DuckDB"
        else:
            target_warehouse = warehouse  # pass through as-is
    else:
        target_warehouse = target.warehouse

    metrics = _build.metrics_for_entity(proj, target)
    result = _build.compile_entity(target, metrics, target_warehouse)

    metric_sql = result.compiled_metric_layer_sql.rstrip() + "\n"
    wide_sql = result.compiled_widetable_sql.rstrip() + "\n"

    if out:
        from mesa_core.build import _GENERATED_BANNER

        Path(out).write_text(_GENERATED_BANNER + metric_sql + "\n" + wide_sql)
        click.echo(f"Wrote {out}")
    else:
        click.echo(f"-- {entity}Metric (Metric Layer)")
        click.echo(metric_sql)
        click.echo(f"-- {entity}Wide (Wide Layer)")
        click.echo(wide_sql)


@cli.command()
@click.option("--models-dir", default="models", metavar="DIR", help="Models directory.")
def validate(models_dir: str) -> None:
    """Run the validation brain over all definitions (refuse bad code).

    MESA's validation engine checks for architectural violations that would
    break the four-tier contract. This is the gatekeeper — code that passes
    validation is guaranteed to be semantically sound and audit-ready.

    \b
    What gets checked:
      - Hashed IDs: every Raw Layer entity must have a hashed primary key
        with source_system prefix (prevents fat-finger join collisions)
      - No SELECT *: explicit column lists required everywhere
      - Metric shape: exactly 2 columns (ID + metric value)
      - Wide Layer purity: no CASE, no WHERE, only STRUCT assembly
      - Cross-entity joins: only via declared link STRUCTs
      - Metric naming conventions: IsActive, NumberOfOrders, etc.

    \b
    Exit codes:
      0  validation passed, no findings
      1  blocking violations found (CI should fail)

    Use this in CI as a quality gate before deploying. If validation fails,
    the findings tell you exactly what to fix and why it matters.

    \b
    Examples:
      mesa validate
      mesa validate --models-dir custom_models/

    Run this after every edit, before committing. Think of it as "pytest for
    your data architecture."
    """
    from mesa_core import build as _build

    proj = _load(models_dir)
    result = _build.validate(proj)

    for f in result.findings:
        color = "red" if f.severity == "block" else "yellow"
        click.echo(click.style(f"[{f.severity.upper()}] {f.code}", fg=color, bold=True))
        click.echo(f"  {f.message}")
        if f.location:
            click.echo(f"  (in {f.location})")

    if result.blocking:
        click.echo(click.style(
            f"VALIDATION FAILED: {len(result.blocking)} blocking finding(s).",
            fg="red", bold=True))
        sys.exit(1)
    if result.findings:
        click.echo(click.style(f"{len(result.findings)} warning(s), no blockers.", fg="yellow"))
    else:
        click.echo(click.style("VALIDATION PASSED — no findings.", fg="green"))


@cli.command()
@click.option("--models-dir", default="models", metavar="DIR", help="Models directory.")
def fmt(models_dir: str) -> None:
    """Run the MESA formatter over authored SQL files, rewriting in place.

    \b
    Rewrites SQL files to match MESA's strict formatting rules:
      - PascalCase for all aliases
      - Leading commas (comma BEFORE each field)
      - Explicit table prefixes on every column
      - Consistent indentation and alignment

    This ensures diffs are minimal and code reviews focus on logic, not
    style. Safe to run repeatedly — formatting is idempotent.

    Only touches authored files in models/. Generated files in target/ are
    not formatted (they're compiler output).

    \b
    Examples:
      mesa fmt
      mesa fmt --models-dir custom_models/

    Use 'mesa lint' in CI to verify files are formatted without modifying them.
    """
    from mesa_core import build as _build

    proj = _load(models_dir)
    rewritten = _build.format_project(proj, models_dir)
    if rewritten:
        click.echo(f"Formatted {len(rewritten)} file(s):")
        for f in rewritten:
            click.echo(f"  {f}")
    else:
        click.echo("No files needed reformatting.")


@cli.command()
@click.option("--models-dir", default="models", metavar="DIR", help="Models directory.")
def lint(models_dir: str) -> None:
    """Formatter check-mode — non-zero exit on any violation (CI gate).

    Checks if all SQL files match MESA formatting rules without modifying
    them. Exits 1 if any file needs reformatting, 0 if everything is clean.

    \b
    Use this in CI/CD pipelines as a pre-merge gate:
      - Prevents unformatted code from landing in main
      - Forces contributors to run 'mesa fmt' before pushing
      - Keeps diffs minimal and code reviews focused on logic

    If lint fails, run 'mesa fmt' locally, commit the changes, and push again.

    \b
    Examples:
      mesa lint
      mesa lint --models-dir custom_models/

    \b
    Typical CI workflow:
      mesa lint        # fail if unformatted
      mesa validate    # fail if architecture violations
      mesa build       # fail if compilation errors
    """
    from mesa_core import build as _build

    proj = _load(models_dir)
    findings = _build.lint_project(proj, models_dir)
    if findings:
        for f in findings:
            click.echo(click.style(
                f"[LINT] {f.get('rule', '')} {f.get('message', '')}",
                fg="red"))
        click.echo(click.style(f"LINT FAILED: {len(findings)} finding(s).", fg="red", bold=True))
        sys.exit(1)
    click.echo(click.style("LINT PASSED.", fg="green"))


@cli.command()
@click.option("--reset", is_flag=True, help="Reset progress and start from Lesson 1.")
@click.option("--jump", metavar="N", type=int, help="Jump to lesson N (1-5).")
def learn(reset: bool, jump: int) -> None:
    """The guided tutorial — learn MESA in ~20 minutes.

    Interactive hands-on lessons that teach MESA's four-tier architecture
    through break-first pedagogy — you'll see the mess naive code creates,
    then learn how MESA prevents it.

    \b
    Five lessons:
      1. Fat-finger join collision  → hashed IDs with source_system prefix
      2. Silent schema change       → explicit column contracts
      3. Buried metric in gold SQL  → one-file-one-metric-one-owner
      4. Semantic compilation       → compile once, ship everywhere
      5. Entity isolation           → Reference Carrier for cross-entity links

    The tutorial runs entirely locally using DuckDB — no warehouse, no
    network, no setup. Progress is saved automatically — quit anytime and
    resume where you left off.

    \b
    Examples:
      mesa learn               # start (or resume) the tutorial
      mesa learn --reset       # start over from lesson 1
      mesa learn --jump 4      # skip to the semantic compilation lesson

    After completing the tutorial, you'll understand MESA vocabulary and be
    ready to scaffold your first project with 'mesa init'.
    """
    from pathlib import Path
    from mesa_core.learn.harness import run_learn
    from mesa_core.learn.lessons import ALL_LESSONS
    
    # Fixture is shipped with the package
    fixture_dir = Path(__file__).parent / "learn" / "fixture"
    
    run_learn(
        lessons=ALL_LESSONS,
        fixture_dir=fixture_dir,
        reset=reset,
        jump_to=jump,
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
