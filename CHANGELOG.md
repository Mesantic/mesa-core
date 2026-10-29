# Changelog

All notable changes to mesa-core are recorded here. Newest first.

## Unreleased

### Fixed — ratios stop zero-filling (SPEC_101 Slice 1b)

**What was wrong.** A rate with no rows was being filled with `0`. That reads as
"0%" — a real, terrible score — when the truth is "no data." It's the same class
of bug as the 2026-10-07 "open windows shown as lost" defect.

**The correction that matters.** An earlier plan blamed bare `SUM(` and proposed
dropping it. That was wrong. A premium total with no rows genuinely *is* 0, the
same way a count is — dropping `SUM(` would have broken every money metric to fix
one rate. The defect is **division**. A metric whose terminal `SELECT` divides is
a ratio, and a ratio's NULL means "no data."

**What changes now.** `resolve_combiner_default` parses the metric with sqlglot
and checks the terminal projection for a division before it consults the
heuristic table. A ratio gets no default. Everything else — `SUM`, `COUNT`, a 0/1
`CASE` flag — keeps its `0`.

**Exactly one metric moves on the real CAO project.** Measured across all 40
metrics on 2026-10-18:

| | Before | After |
|---|---|---|
| `AgentChangeResponseRate` | `COALESCE(..., 0)` | no COALESCE — NULL passes through |
| The other 15 zero-defaults | `0` | `0` (unchanged) |
| The 24 NULL pass-throughs | NULL | NULL (unchanged) |

`AgentChangeResponseRate` is the one that flips. It's a share of survey invites
that got a response — a program with no invites sent has no response rate, and
showing 0% was wrong. **If you own a downstream view over this metric, it will
start showing blank instead of 0% for those rows.** That's the fix; if 0 is
genuinely correct for your use, add `-- COMBINER_DEFAULT: 0` to the metric file
and it goes back.

`IsLikelyMoveEvent` also divides, but only inside a CTE — its terminal `SELECT`
is a 0/1 flag, so it correctly keeps its `0`. A client×policy with no address
change really does have zero likely-move events.

**Warnings.** A ratio now prints why it got no default, so the decision is
visible rather than silent. A metric sqlglot can't parse keeps today's behavior
*and* says the parse failed — a silent parse failure would quietly restore the
zero-fill this change removes.

**Dialect-neutral on purpose.** The resolver takes the warehouse's sqlglot
dialect, so `SPEC_103` Slice 3 can extend the same chain to all six warehouses
without a rewrite.

### Fixed — one warehouse identity, and unknown names now fail loudly (SPEC_103 Slice 1)

**What was wrong.** There were four lists of warehouse names that disagreed, and
an unrecognized name did not raise. It fell through the compiler's final `else`
branch and compiled as **Redshift** output. `compile_entity(..., "AzureSynapse")`,
`"Postgres"` and `"TotallyUnknown"` all returned plausible-looking SQL for the
wrong warehouse, and nothing said a word.

**What changes now.** `mesa_core/warehouses.py` is the single source of truth: the
six canonical names, the aliases, the sqlglot dialect for each, and
`UnknownWarehouseError` for anything else. Every consumer routes through it —
the compiler, `grain_guard`, `mesa compile`, `mesa init`.

Three consequences:

1. **A typo now fails at the boundary.** `mesa compile --warehouse Postgres`
   exits with the valid list instead of emitting Redshift SQL.
2. **`AzureSynapse` is accepted, not rejected.** Governance and the migration
   console both spell Synapse that way. It normalizes to `Synapse` — the database
   keeps whatever it has, the normalizer translates at the edge.
3. **`grain_guard` parses T-SQL for every spelling.** Before, only `azuresqldb`
   mapped to `tsql`; `Synapse` and `AzureSQLDatabase` returned `None` and it
   silently fell back to probing every dialect.

`mesa init --warehouse` now validates too, and its help text lists all six.

### Added — the warehouse behavior harness (SPEC_103 Slice 8a)

`mesa conformance` runs one deliberately nasty fixture — a NULL natural key, a
trailing space, case variants, an integer ratio, a microsecond timestamp,
mixed-case struct keys, a boolean column, an all-NULL column, a constant column —
and reports each behavior as **VERIFIED** or **FALSIFIED**, with the warehouse
version and run date. It writes `docs/WAREHOUSE_BEHAVIOR.md` and exits non-zero
if anything is falsified, so CI catches a regression.

**What this settles, and what it doesn't.** This is the free half. It runs on
DuckDB, in CI, with no credentials. It is a regression suite for mesa-core's own
compiler — **not** a stand-in for cloud behavior. DuckDB's `concat` ignores NULL
and `/` returns a double, which is not what SQL Server does. Every DOCUMENTED
claim about T-SQL, Redshift and BigQuery still waits for the cloud run (Slice 8b,
about $1/hr per warehouse, approval per run). The generated report says so in its
own closing section, so an all-VERIFIED table is never read as "every warehouse
is fine."

### Fixed — metric annotations now actually apply (SPEC_101 Slice 1)

**What was wrong.** Annotations written in a metric file's header —
`-- COMBINER_DEFAULT:` and `-- WIDE_TYPE_TSQL:` — were being thrown away before
the compiler ever saw them. The loader strips every leading `--` comment line
when it reads a metric, and that stripped text is what the annotation resolvers
searched. So a metric that *did* carry an annotation looked exactly like one that
didn't, and the heuristic table always decided the value instead.

**What that looked like for you.** If your project annotates
`-- COMBINER_DEFAULT: 0`, you were still getting the heuristic guess — which is
usually the same `0`, so nothing appeared broken. If you annotate
`-- COMBINER_DEFAULT: NONE` to say "this metric's NULL is meaningful, don't
zero-fill it," you were getting a zero-fill anyway. That is the Farmers bug: a
rate for a policy with no events showed 0% instead of "no data."

**What changes now.** Annotations are read from the file header and take effect.
Two consequences worth knowing:

1. **`COMBINER_DEFAULT: NONE` stops zero-filling.** The annotation now returns a
   genuine "no COALESCE" instead of the literal string `NONE`. (The old code
   would have emitted `COALESCE(col, NONE)` — invalid SQL — if the header had
   ever survived to that point. The strip bug is the only reason it never did.
   Both fixes ship together.)

2. **Your combiner output can change.** Any metric that carries an annotation
   *and* was getting a heuristic default will now get the annotated value. If
   that differs, `mesa build --check` will report the combiner as stale — run
   `mesa build` and commit the regenerated file. This is the fix working, not a
   regression.

**What got added.** Metrics with no annotation still use the heuristic table
(removing it outright would break every existing project on the day it shipped).
To make those guesses visible, `mesa build` now prints a warning per
heuristic-sourced default on stderr, telling you exactly what to write to confirm
it. It's a nudge, not a block.

One more fix rides along: annotation lines no longer leak into a metric's
description. Before, a file whose only "description" was `-- WIDE_TYPE: FLOAT`
passed the documentation-completeness check as if it were documented. It won't now.

Nothing else changed. A project with no annotations anywhere compiles to the same
combiner SQL it did before — the only new output is the warnings.
