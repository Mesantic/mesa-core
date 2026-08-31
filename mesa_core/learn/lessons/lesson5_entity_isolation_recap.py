# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
Lesson 5 — Entity Isolation + The Preach Moment (the quotable recap)

The mess: A Policy entity reaches across and joins straight into a different
entity's raw table "because it was convenient." Shows hidden dependency.

The catch: MESA's entity isolation — you declare the relationship once (a
Reference Carrier / link STRUCT), you never hand-join across entities at raw layer.

The aha + send-off: The vocabulary recap — the exact phrases to repeat to a
coworker. This is where a user becomes someone who PREACHES.

Vocabulary: entity isolation, Reference Carrier ("holds an address, doesn't make
the trip"), and the full recap of all 5 lessons.
"""
from mesa_core.learn.harness import LessonContext

number = 5
title = "Entity Isolation + The Preach Moment"


def run(ctx: LessonContext) -> None:
    """Execute Lesson 5 (entity isolation + the quotable recap)."""
    
    # ─── THE MESS: reach-across join creates hidden dependency ───────────────
    ctx.echo(ctx.style("THE MESS:", fg="red", bold=True))
    ctx.echo("")
    ctx.echo("You have an Order entity that needs customer information. The old way:")
    ctx.echo("reach across and join straight into the Customer raw table.")
    ctx.echo("")
    
    messy_join = """
-- Order entity (the WRONG way)
SELECT
    O.order_id AS ID,
    O.order_date,
    O.amount,
    C.name AS customer_name,  -- reached across from Customer raw table
    C.region AS customer_region
FROM orders AS O
LEFT JOIN customer AS C ON O.customer_id = C.id;
"""
    
    ctx.echo(ctx.style("Messy cross-entity join:", fg="yellow"))
    ctx.echo(messy_join)
    ctx.echo("")
    ctx.echo(ctx.style("PROBLEM:", fg="red", bold=True) + " Order now has a hidden dependency on Customer's")
    ctx.echo("internal structure. If Customer's raw table changes (column renamed,")
    ctx.echo("grain shifted), Order breaks. The relationship is ad-hoc, undeclared,")
    ctx.echo("and unreviewable.")
    ctx.echo("")
    
    ctx.pause()
    
    # ─── THE CATCH: Reference Carrier pattern ────────────────────────────────
    ctx.echo("")
    ctx.echo(ctx.style("THE CATCH:", fg="green", bold=True))
    ctx.echo("")
    ctx.echo("MESA's entity isolation: you declare the relationship ONCE, at the raw")
    ctx.echo("layer, using a Reference Carrier (link STRUCT). Look at OrderRaw.sql:")
    ctx.echo("")
    
    order_raw_snippet = """
SELECT
    base64(sha256('order-' || CAST(O.order_id AS VARCHAR))) AS ID,
    O.order_date AS OrderDate,
    O.amount AS Amount,
    -- Reference Carrier: holds Customer's identity, declares the relationship
    STRUCT(
        base64(sha256(O.source_system || '-' || CAST(O.customer_id AS VARCHAR)))
    ) AS Customer
FROM orders AS O;
"""
    
    ctx.echo(ctx.style("MESA way (Reference Carrier):", fg="yellow"))
    ctx.echo(order_raw_snippet)
    ctx.echo("")
    ctx.echo("The STRUCT holds the Customer's ID — an address, not the trip. Order")
    ctx.echo("never reaches into Customer's raw table. The relationship is declared")
    ctx.echo("once, here, and the compiler enforces it. No ad-hoc cross-entity joins.")
    ctx.echo("")
    ctx.echo("If you need customer NAME or REGION in a downstream view, you bring in")
    ctx.echo("CustomerWide via the declared link — never by hand-joining raw tables.")
    ctx.echo("")
    
    ctx.pause()
    
    # ─── THE PREACH MOMENT: vocabulary recap ─────────────────────────────────
    ctx.echo("")
    ctx.echo(ctx.style("═" * 70, fg="cyan", bold=True))
    ctx.echo(ctx.style("  THE PREACH MOMENT", fg="cyan", bold=True))
    ctx.echo(ctx.style("═" * 70, fg="cyan", bold=True))
    ctx.echo("")
    ctx.echo("You now have the vocabulary to explain MESA to a coworker. Here's what")
    ctx.echo("you learned across all 5 lessons:")
    ctx.echo("")
    
    ctx.echo(ctx.style("1. IS vs MEANS", fg="yellow", bold=True))
    ctx.echo("   Identity vs conclusion. Never confuse them. A Customer table IS an")
    ctx.echo("   identity; a retention metric MEANS something computed FROM that identity.")
    ctx.echo("   The cement-vs-psi analogy: nobody confuses a bag of cement with the")
    ctx.echo("   PSI rating of the mix.")
    ctx.echo("")
    
    ctx.echo(ctx.style("2. The fat-finger join", fg="yellow", bold=True))
    ctx.echo("   Same ID, different customer, silently doubled revenue. You watched it")
    ctx.echo("   happen. MESA's hashed ID (hash of source_system + id) makes collision")
    ctx.echo("   structurally impossible.")
    ctx.echo("")
    
    ctx.echo(ctx.style("3. Entity isolation / Reference Carrier", fg="yellow", bold=True))
    ctx.echo("   Declare relationships once. A Reference Carrier holds an address, it")
    ctx.echo("   doesn't make the trip. No ad-hoc cross-entity joins at the raw layer.")
    ctx.echo("")
    
    ctx.echo(ctx.style("4. Metric encapsulation", fg="yellow", bold=True))
    ctx.echo("   One file, one owner. Point at a line, name the owner. `git blame` proof.")
    ctx.echo("   Impossible with a Tableau calc field or a 400-line gold script.")
    ctx.echo("")
    
    ctx.echo(ctx.style("5. Compile once, ship everywhere", fg="yellow", bold=True))
    ctx.echo("   Same metric definition → Snowflake SQL, BigQuery SQL, Cube, MetricFlow.")
    ctx.echo("   Semantic compilation. The warehouse is a commodity compute target.")
    ctx.echo("")
    
    ctx.echo(ctx.style("═" * 70, fg="cyan", bold=True))
    ctx.echo("")
    ctx.echo("That's the whole pitch. Go tell someone.")
    ctx.echo("")
    ctx.echo(ctx.style("Next steps:", fg="green", bold=True))
    ctx.echo("  • mesa init my-project — scaffold your own four-tier project")
    ctx.echo("  • mesa new entity Customer --from-ddl schema.sql — onboard a table")
    ctx.echo("  • Read the docs: https://github.com/Mesantic/mesa-core")
    ctx.echo("")
