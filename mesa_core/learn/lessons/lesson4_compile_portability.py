# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
Lesson 4 — Compile Once, Ship Everywhere (semantic compilation, portability)

The reveal (POSITIVE, not break-first): The SAME metric definition compiles to
dialect-correct SQL for Snowflake, BigQuery, and DuckDB. Same source file,
warehouse as a commodity.

The aha: "I wrote a metric once and it ran on two warehouses AND fed a BI semantic
layer — I've never been able to do that."

Vocabulary: semantic compilation; cross-platform portability; warehouse as commodity.
"""
import subprocess
import sys

from mesa_core.learn.harness import LessonContext

number = 4
title = "Compile Once, Ship Everywhere"


def run(ctx: LessonContext) -> None:
    """Execute Lesson 4 interactively (the positive reveal)."""
    
    # ─── THE REVEAL: same metric, multiple targets ───────────────────────────
    ctx.echo(ctx.style("THE REVEAL:", fg="green", bold=True))
    ctx.echo("")
    ctx.echo("This lesson is different — there's no mess to watch break. This is the")
    ctx.echo("POSITIVE reveal: the same MESA metric definition compiles to multiple")
    ctx.echo("warehouse dialects. Watch:")
    ctx.echo("")
    
    models_dir = ctx.fixture_dir / "models"
    mesa_cmd = [sys.executable, "-m", "mesa_core.cli", "compile", "Customer",
                "--models-dir", str(models_dir)]
    
    # Compile for BigQuery
    ctx.echo(ctx.style("═" * 72, fg="cyan"))
    ctx.echo(ctx.style("  TARGET: BigQuery", fg="cyan", bold=True))
    ctx.echo(ctx.style("═" * 72, fg="cyan"))
    ctx.echo("")
    
    _compile_and_show(ctx, mesa_cmd + ["--warehouse", "bigquery"], "BigQuery")
    
    ctx.pause("Press Enter to compile for Snowflake...")
    
    # Compile for Snowflake
    ctx.echo("")
    ctx.echo(ctx.style("═" * 72, fg="cyan"))
    ctx.echo(ctx.style("  TARGET: Snowflake", fg="cyan", bold=True))
    ctx.echo(ctx.style("═" * 72, fg="cyan"))
    ctx.echo("")
    
    _compile_and_show(ctx, mesa_cmd + ["--warehouse", "snowflake"], "Snowflake")
    
    ctx.pause("Press Enter to compile for DuckDB...")
    
    # Compile for DuckDB (default)
    ctx.echo("")
    ctx.echo(ctx.style("═" * 72, fg="cyan"))
    ctx.echo(ctx.style("  TARGET: DuckDB (local dev)", fg="cyan", bold=True))
    ctx.echo(ctx.style("═" * 72, fg="cyan"))
    ctx.echo("")
    
    _compile_and_show(ctx, mesa_cmd + ["--warehouse", "duckdb"], "DuckDB")
    
    ctx.pause()
    
    # ─── THE AHA ──────────────────────────────────────────────────────────────
    ctx.echo("")
    ctx.echo(ctx.style("THE AHA:", fg="cyan", bold=True))
    ctx.echo("")
    ctx.echo("You just watched the same metric definition compile to three different")
    ctx.echo("warehouse SQL dialects. Look at the Wide Layer SELECT statements:")
    ctx.echo("")
    ctx.echo(ctx.style("  BigQuery:", fg="yellow") + "   SELECT Customer, CustomerMetric")
    ctx.echo(ctx.style("  Snowflake:", fg="yellow") + "  SELECT {{ as_struct('Customer') }}, {{ as_struct('CustomerMetric') }}")
    ctx.echo(ctx.style("  DuckDB:", fg="yellow") + "     SELECT {{ dbt_utils.star(...) }}")
    ctx.echo("")
    ctx.echo("Same source file. Dialect-correct output every time. Warehouse as a")
    ctx.echo("commodity compute target. This is semantic compilation.")
    ctx.echo("")
    ctx.echo("Most semantic layers sit ON TOP of ONE warehouse and assume the SQL is")
    ctx.echo("already written. MESA compiles TO the warehouse — you write once, ship")
    ctx.echo("everywhere.")
    ctx.echo("")
    ctx.echo(ctx.style("VOCABULARY:", fg="yellow", bold=True))
    ctx.echo("  • Semantic compilation — compile TO the warehouse, not just ON TOP")
    ctx.echo("  • Cross-platform portability — write once, run anywhere")
    ctx.echo("  • Warehouse as commodity — Snowflake vs BigQuery is a config change")
    ctx.echo("")


def _compile_and_show(ctx: LessonContext, cmd: list[str], warehouse_name: str) -> None:
    """Compile and display the Wide Layer snippet."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        # Extract just the Wide Layer section
        output = result.stdout
        if "-- CustomerWide" in output:
            lines = output.split("\n")
            wide_start = next(i for i, l in enumerate(lines) if "-- CustomerWide" in l)
            wide_section = lines[wide_start:wide_start + 12]  # Show ~12 lines
            
            for line in wide_section:
                ctx.echo(line)
            ctx.echo("")
        else:
            ctx.echo(output[:500])  # Fallback: show first 500 chars
    else:
        ctx.echo(ctx.style(f"Compilation failed: {result.stderr}", fg="red"))
