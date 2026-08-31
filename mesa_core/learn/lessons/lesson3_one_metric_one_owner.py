# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
Lesson 3 — One Metric, One Owner (metric encapsulation)

The mess: A user writes "retention" the old way — buried inside a big multi-CTE
query alongside two other calculations, no clear owner.

The catch: The MESA way — one metric file, `git log`/`git blame` shows exactly
who owns and last changed that one definition.

The aha: You can point at a line and say who owns it — impossible with a Tableau
calc field or a 400-line gold script.

Vocabulary: metric encapsulation — one file, one owner, one truth; single
responsibility applied to a business calculation.
"""
import subprocess
import sys
from pathlib import Path

from mesa_core.learn.harness import LessonContext

number = 3
title = "One Metric, One Owner"


def run(ctx: LessonContext) -> None:
    """Execute Lesson 3 interactively."""
    
    # ─── THE MESS: metric buried in a multi-CTE blob ─────────────────────────
    ctx.echo(ctx.style("THE MESS:", fg="red", bold=True))
    ctx.echo("")
    ctx.echo("You need a 'customer retention' metric. The old way: bury it inside a")
    ctx.echo("big multi-CTE query alongside two other calculations.")
    ctx.echo("")
    
    # Create a messy "gold layer" style query
    messy_query_path = ctx.working_dir / "messy_gold_customer_metrics.sql"
    messy_query = """
-- Gold layer customer metrics (the old way)
-- Written by: ??? | Last modified by: ??? | Owned by: ???

WITH customer_orders AS (
    SELECT 
        customer_id,
        COUNT(*) AS order_count,
        SUM(amount) AS total_spent,
        MAX(order_date) AS last_order_date
    FROM orders
    GROUP BY customer_id
),

retention AS (
    SELECT
        customer_id,
        CASE 
            WHEN DATEDIFF('day', last_order_date, CURRENT_DATE) <= 90 THEN 1
            ELSE 0
        END AS is_retained
    FROM customer_orders
),

lifetime_value AS (
    SELECT
        customer_id,
        total_spent / NULLIF(order_count, 0) AS avg_order_value
    FROM customer_orders
)

SELECT
    c.customer_id,
    c.order_count,
    c.total_spent,
    r.is_retained,
    ltv.avg_order_value
FROM customer_orders c
LEFT JOIN retention r ON c.customer_id = r.customer_id
LEFT JOIN lifetime_value ltv ON c.customer_id = ltv.customer_id;
"""
    
    messy_query_path.write_text(messy_query)
    
    ctx.echo(ctx.style(f"File: {messy_query_path.name}", fg="yellow"))
    ctx.echo("")
    ctx.echo("  • 'retention' is buried inside a CTE alongside two other metrics")
    ctx.echo("  • If 'retention' changes, you can't easily see who changed it or why")
    ctx.echo("  • `git blame` on this file shows... everyone who touched ANY metric here")
    ctx.echo("  • No clear owner. Unownable.")
    ctx.echo("")
    
    ctx.pause()
    
    # ─── THE CATCH: MESA's one-file-one-metric contract ──────────────────────
    ctx.echo("")
    ctx.echo(ctx.style("THE CATCH:", fg="green", bold=True))
    ctx.echo("")
    ctx.echo("The MESA way: one metric = one file. Let's look at the fixture's")
    ctx.echo("TotalRevenue metric:")
    ctx.echo("")
    
    metric_file = ctx.fixture_dir / "models" / "metric_layer" / "Customer_Metrics" / "TotalRevenue.sql"
    
    if metric_file.exists():
        ctx.echo(ctx.style(f"File: metric_layer/Customer_Metrics/TotalRevenue.sql", fg="yellow"))
        ctx.echo("")
        ctx.echo(metric_file.read_text())
        ctx.echo("")
    
    ctx.echo("One file. One metric. One owner (in the header comment).")
    ctx.echo("")
    ctx.echo("Now imagine running `git log TotalRevenue.sql` or `git blame` on it.")
    ctx.echo("Every change to THIS metric shows up. No noise from unrelated changes.")
    ctx.echo("Point at a line, name the owner. That's the whole point.")
    ctx.echo("")
    
    ctx.pause()
    
    # ─── THE AHA ──────────────────────────────────────────────────────────────
    ctx.echo("")
    ctx.echo(ctx.style("THE AHA:", fg="cyan", bold=True))
    ctx.echo("")
    ctx.echo("This is metric encapsulation — single responsibility applied to a")
    ctx.echo("business calculation. One file, one metric, one owner, one truth.")
    ctx.echo("")
    ctx.echo("Compare the two approaches:")
    ctx.echo("")
    ctx.echo(ctx.style("OLD WAY (gold layer multi-CTE):", fg="red"))
    ctx.echo("  • Retention buried alongside 2 other metrics")
    ctx.echo("  • `git blame` shows... everyone who touched anything in this file")
    ctx.echo("  • No clear owner")
    ctx.echo("  • Impossible to audit one metric's change history")
    ctx.echo("")
    ctx.echo(ctx.style("MESA WAY (one file per metric):", fg="green"))
    ctx.echo("  • Retention = one file = TotalRevenue.sql")
    ctx.echo("  • `git log TotalRevenue.sql` shows ONLY changes to this metric")
    ctx.echo("  • Owner in the file header")
    ctx.echo("  • Point at a line, name the owner — impossible with a Tableau calc")
    ctx.echo("    field or a 400-line gold script")
    ctx.echo("")
    ctx.echo(ctx.style("VOCABULARY:", fg="yellow", bold=True))
    ctx.echo("  • Metric encapsulation — one file, one owner")
    ctx.echo("  • Git blame proof — every change has a name on it")
    ctx.echo("  • Single responsibility — applied to business calculations")
    ctx.echo("")
