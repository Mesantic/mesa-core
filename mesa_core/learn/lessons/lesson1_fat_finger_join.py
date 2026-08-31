# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
Lesson 1 — The Fat-Finger Join (IS vs MEANS, hashed identity)

The mess: Two sources (Salesforce, NetSuite) both have customer id=123, but they're
DIFFERENT customers. A naive LEFT JOIN on just `id` silently merges them, doubling
revenue or corrupting aggregates.

The catch: MESA's hashed ID (hash of source_system + id) makes the collision
structurally impossible — two hashes, two customers, no merge.

The aha: "I've done this exact join a hundred times and never known it could
silently double revenue."

Vocabulary: IS vs MEANS — identity vs conclusion. The collision happened because
two systems disagreed on what the identity WAS.
"""
from pathlib import Path
import duckdb
import subprocess
import sys

from mesa_core.learn.harness import LessonContext

number = 1
title = "The Fat-Finger Join"


def run(ctx: LessonContext) -> None:
    """Execute Lesson 1 interactively."""
    
    # ─── Setup: load the DuckDB fixture ──────────────────────────────────────
    _setup_database(ctx)
    
    # ─── THE MESS: naive join that causes collision ──────────────────────────
    ctx.echo(ctx.style("THE MESS:", fg="red", bold=True))
    ctx.echo("")
    ctx.echo("You have two source systems — Salesforce and NetSuite. Both have a")
    ctx.echo("customer with id=123. Let's do what everyone does: LEFT JOIN on id.")
    ctx.echo("")
    
    naive_query = """
    SELECT 
        c.id,
        c.name AS customer_name,
        c.source_system,
        SUM(o.amount) AS total_revenue
    FROM (
        SELECT id, name, 'salesforce' AS source_system FROM salesforce_customers
        UNION ALL
        SELECT id, name, 'netsuite' AS source_system FROM netsuite_customers
    ) AS c
    LEFT JOIN orders AS o 
        ON c.id = o.customer_id  -- WRONG: ignores source_system!
    WHERE c.id = 123
    GROUP BY c.id, c.name, c.source_system
    ORDER BY c.source_system;
    """
    
    ctx.echo(ctx.style("Running naive join:", fg="yellow"))
    ctx.echo(naive_query)
    
    conn = duckdb.connect(str(ctx.db_path))
    result = conn.execute(naive_query).fetchall()
    conn.close()
    
    ctx.echo("")
    ctx.echo(ctx.style("RESULT:", fg="red", bold=True))
    ctx.echo("id  | customer_name        | source_system | total_revenue")
    ctx.echo("----+----------------------+---------------+--------------")
    for row in result:
        ctx.echo(f"{row[0]:<4}| {row[1]:<20} | {row[2]:<13} | ${row[3]:,.2f}")
    
    ctx.echo("")
    ctx.echo(ctx.style("PROBLEM:", fg="red", bold=True) + " The orders from BOTH customers")
    ctx.echo("got summed together — Acme West's $3,700 + Cyberdyne's $9,700 = $13,400")
    ctx.echo("per row. That's silently doubled revenue. Or worse: the two customers")
    ctx.echo("might be shown as one merged entity. Either way, the report is wrong.")
    ctx.echo("")
    ctx.echo("You've probably done this exact join a hundred times and never known")
    ctx.echo("it could silently corrupt your data.")
    ctx.echo("")
    
    ctx.pause()
    
    # ─── THE CATCH: MESA's hashed ID prevents collision ──────────────────────
    ctx.echo("")
    ctx.echo(ctx.style("THE CATCH:", fg="green", bold=True))
    ctx.echo("")
    ctx.echo("Now let's see how MESA prevents this. Run `mesa build` on the Customer")
    ctx.echo("entity and look at the compiled SQL.")
    ctx.echo("")
    
    # Run mesa build
    models_dir = ctx.fixture_dir / "models"
    result = subprocess.run(
        [sys.executable, "-m", "mesa_core.cli", "compile", "Customer", 
         "--models-dir", str(models_dir), "--out", str(ctx.working_dir / "customer_compiled.sql")],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        ctx.echo(ctx.style(f"mesa build failed: {result.stderr}", fg="red"))
        return
    
    # Show the hashed ID construction
    ctx.echo(ctx.style("MESA's Customer entity (compiled):", fg="yellow"))
    ctx.echo("")
    ctx.echo("  base64(sha256(source_system || '-' || CAST(source_id AS VARCHAR))) AS ID")
    ctx.echo("")
    ctx.echo("source_system is MANDATORY in the hash input. Without it:")
    ctx.echo("  • Salesforce customer 123 → hash('salesforce-123') → ID_A")
    ctx.echo("  • NetSuite customer 123  → hash('netsuite-123')   → ID_B")
    ctx.echo("")
    ctx.echo("Two DIFFERENT hashes. Two DIFFERENT customers. No collision possible.")
    ctx.echo("")
    
    ctx.pause()
    
    # ─── THE AHA: IS vs MEANS ─────────────────────────────────────────────────
    ctx.echo("")
    ctx.echo(ctx.style("THE AHA:", fg="cyan", bold=True))
    ctx.echo("")
    ctx.echo("This is the difference between IS and MEANS.")
    ctx.echo("")
    ctx.echo("Think of building a bridge deck. Before you pour anything, you gather")
    ctx.echo("the materials: Portland cement powder, water, gravel, sand. Every one")
    ctx.echo("of those materials just IS what it is — cement is cement, water is water.")
    ctx.echo("Nobody asks 'what does this bag of cement mean?' It has an identity,")
    ctx.echo("and that identity is stable and uninterpreted.")
    ctx.echo("")
    ctx.echo("That materials list is the Raw Layer. Customer, Policy, Order — they're")
    ctx.echo("cement, water, gravel. Enriched enough to be identifiable (hashed ID,")
    ctx.echo("clean business name), but never answering a question.")
    ctx.echo("")
    ctx.echo("The mixing calculation — water-cement ratio, aggregate proportions, the")
    ctx.echo("PSI rating the mix cures to — that's the Metric Layer. That's where IS")
    ctx.echo("becomes MEANS. The materials didn't change, but a calculation produced")
    ctx.echo("a conclusion, with an owner and a version.")
    ctx.echo("")
    ctx.echo(ctx.style("Nobody confuses a bag of cement with the PSI rating of the mix.", 
                       fg="cyan", bold=True))
    ctx.echo("")
    ctx.echo("The fat-finger join happened because two systems disagreed on what the")
    ctx.echo("identity WAS. MESA's hashed ID makes identity collision structurally")
    ctx.echo("impossible — the IS is settled before any MEANS gets computed.")
    ctx.echo("")
    ctx.echo(ctx.style("VOCABULARY:", fg="yellow", bold=True))
    ctx.echo("  • IS vs MEANS — identity vs conclusion, never confuse them")
    ctx.echo("  • The fat-finger join — same ID, different customer, silently corrupted")
    ctx.echo("  • Hashed identity — hash(source_system + id) prevents collision by design")
    ctx.echo("")


def _setup_database(ctx: LessonContext) -> None:
    """Load the tutorial seed data into DuckDB."""
    if ctx.db_path.exists():
        return  # already loaded
    
    seed_sql = ctx.fixture_dir / "seeds" / "tutorial_data.sql"
    conn = duckdb.connect(str(ctx.db_path))
    conn.execute(seed_sql.read_text())
    conn.close()
