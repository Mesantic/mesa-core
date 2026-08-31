# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
Lesson 2 — The Silent Schema Change (explicit columns, fail loud)

The mess: The tutorial adds a new column to a source table mid-lesson. A user's
old `SELECT *`-style query silently absorbs it, shifting downstream results.

The catch: MESA's explicit-column contract fails LOUDLY with an error that names
the exact column that changed.

The aha: The failure has their name on it in the terminal now — not buried in a
dashboard three weeks later.

Vocabulary: explicit interfaces over implicit; `SELECT *` is a silent schema absorber.
"""
import duckdb
from mesa_core.learn.harness import LessonContext

number = 2
title = "The Silent Schema Change"


def run(ctx: LessonContext) -> None:
    """Execute Lesson 2 interactively."""
    
    # ─── THE MESS: SELECT * silently absorbs schema changes ──────────────────
    ctx.echo(ctx.style("THE MESS:", fg="red", bold=True))
    ctx.echo("")
    ctx.echo("You have a query that pulls customer data:")
    ctx.echo("")
    
    old_query = """
    SELECT * FROM salesforce_customers LIMIT 3;
    """
    
    ctx.echo(ctx.style("Old query (uses SELECT *):", fg="yellow"))
    ctx.echo(old_query)
    
    conn = duckdb.connect(str(ctx.db_path))
    
    # Show the original result
    result_before = conn.execute(old_query).fetchall()
    cols_before = [desc[0] for desc in conn.description]
    
    ctx.echo(ctx.style("Original columns:", fg="yellow"))
    ctx.echo(f"  {', '.join(cols_before)}")
    ctx.echo("")
    
    # Now ADD a column to the source table (simulate schema change)
    ctx.echo("Simulating a schema change: someone adds a 'tier' column to the source...")
    
    # Check if column exists (defensive against re-running in same DB)
    has_tier = conn.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = 'salesforce_customers' AND column_name = 'tier'"
    ).fetchone()[0]
    
    if not has_tier:
        conn.execute("ALTER TABLE salesforce_customers ADD COLUMN tier VARCHAR DEFAULT 'standard'")
        conn.execute("UPDATE salesforce_customers SET tier = 'premium' WHERE id IN (123, 201)")
    
    # Re-run the SELECT *
    result_after = conn.execute(old_query).fetchall()
    cols_after = [desc[0] for desc in conn.description]
    
    ctx.echo("")
    ctx.echo(ctx.style("New columns (after schema change):", fg="yellow"))
    ctx.echo(f"  {', '.join(cols_after)}")
    ctx.echo("")
    
    ctx.echo(ctx.style("PROBLEM:", fg="red", bold=True) + " The `SELECT *` silently absorbed the new")
    ctx.echo("'tier' column. If your query was parsing column positions (column 4 used")
    ctx.echo("to be 'region', now it's 'tier'), downstream results are shifted and wrong.")
    ctx.echo("Nobody gets notified. The report breaks three weeks from now when someone")
    ctx.echo("finally notices revenue is filed under the wrong region.")
    ctx.echo("")
    
    conn.close()
    ctx.pause()
    
    # ─── THE CATCH: explicit columns, fail loud ──────────────────────────────
    ctx.echo("")
    ctx.echo(ctx.style("THE CATCH:", fg="green", bold=True))
    ctx.echo("")
    ctx.echo("MESA's explicit-column contract means every column is listed individually.")
    ctx.echo("Never `SELECT *` — not even as a convenience during development.")
    ctx.echo("")
    ctx.echo("If the schema changes, MESA's validator catches it and fails LOUDLY:")
    ctx.echo("")
    ctx.echo(ctx.style("  [BLOCK] MESA-CORE-002: No SELECT *", fg="red", bold=True))
    ctx.echo("  Column 'tier' was added to salesforce_customers, but the")
    ctx.echo("  raw entity CustomerRaw.sql does not reference it explicitly.")
    ctx.echo("  Either add it to the SELECT list or document why it's excluded.")
    ctx.echo("")
    ctx.echo("The failure has YOUR name on it now — in the terminal, in CI, before")
    ctx.echo("the change ships. Not in a dashboard three weeks later.")
    ctx.echo("")
    
    ctx.pause()
    
    # ─── THE AHA ──────────────────────────────────────────────────────────────
    ctx.echo("")
    ctx.echo(ctx.style("THE AHA:", fg="cyan", bold=True))
    ctx.echo("")
    ctx.echo("`SELECT *` is a silent schema absorber. When a source table adds a column,")
    ctx.echo("`SELECT *` picks it up with no warning — and downstream consumers break in")
    ctx.echo("ways that are hard to trace.")
    ctx.echo("")
    ctx.echo("Explicit column lists mean schema changes are visible in diffs, reviewable")
    ctx.echo("in PRs, and fail CI if they break contracts. This isn't a style preference.")
    ctx.echo("It's a governance requirement.")
    ctx.echo("")
    ctx.echo(ctx.style("VOCABULARY:", fg="yellow", bold=True))
    ctx.echo("  • Explicit interfaces over implicit")
    ctx.echo("  • `SELECT *` is banned — it hides schema changes")
    ctx.echo("  • Fail loud, not quiet — the error has your name on it now")
    ctx.echo("")
