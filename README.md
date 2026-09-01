# MESA — Metric Encapsulated Semantic Architecture

**mesa-core** is the open-source compiler and standards library for MESA
(Metric Encapsulated Semantic Architecture) — a four-tier semantic data
architecture framework (Raw → Metric → Wide → View) for governed, versioned,
metric-first data warehouse design.

MESA compiles canonical entity, metric, and relationship definitions into
platform-specific SQL (Snowflake, BigQuery, and others), enforcing one
authoritative definition per business object and one file per metric.

---

The free, MIT-licensed semantic compiler. MESA Core is the dbt-Core equivalent
for the MESA architecture: it reads on-disk four-tier definition files and
compiles them into correct, dialect-specific SQL, with MESA's opinionated
validation refusing bad definitions — all locally, no account, no database, and
no data leaving your machine.

```
pip install mesa-core
mesa init my_project
cd my_project
mesa new entity Customer --from-columns cols.txt
mesa build
```

## The four tiers

MESA enforces a strict four-tier architecture. Each tier has exactly one job:

```
RAW LAYER (Tier 1)        →  METRIC LAYER (Tier 2)  →  WIDE LAYER (Tier 3)  →  VIEW LAYER (Tier 4)
  Business concept tables     One file = one metric     Pure assembly, no logic   Consumer-facing views
  Hashed PKs, PascalCase      2 columns: ID + value     SELECT full STRUCTs only  WHERE filters allowed
  No calculations             INNER JOIN only           No aliases, no CASE       ID aliased for BI
```

## Commands

| Command | What it does |
|---|---|
| `mesa init <name>` | scaffold a new four-tier project |
| `mesa new entity <name>` | mechanical four-tier stub from a column list (`--from-columns` / `--from-ddl` / `--from-duckdb`) |
| `mesa build` | compile all layers to `target/` |
| `mesa compile <entity>` | compile one entity's metric + wide layers |
| `mesa validate` | run the validation brain; non-zero exit on any violation — the "refuse bad code" gate |
| `mesa fmt` | run the MESA formatter, rewriting files |
| `mesa lint` | formatter check-mode (CI gate, non-zero exit on violation) |
| `mesa learn` | the guided tutorial (coming soon) |

## Cross-warehouse portability

One definition compiles to every warehouse. No dialect is paywalled — the
portability is the point:

- **Snowflake** — `OBJECT_CONSTRUCT_KEEP_NULL`, colon field access, `::OBJECT` casts
- **BigQuery** — `STRUCT`, `UNNEST`, `SAFE_CAST`
- **Redshift** — `dbt_utils.star()`
- **DuckDB** — local development with zero external warehouse

## The validation brain is free

The compiler is not the moat — the *refusal of bad definitions* is. `mesa
validate` runs `grain_guard`, `core_rules`, and `mesa_verifier` locally, catching
the fat-finger-join class of bug (identity collisions, grain fan-out, `SELECT *`,
raw warehouse paths) before bad SQL ever reaches a warehouse.

## Quickstart

`quickstart/` is a runnable two-entity project (Customer + Order) with DuckDB
example data:

```
cd quickstart
mesa build        # compile all four tiers to target/
```

## Why it matters

Every other semantic layer starts at *meaning* and assumes *identity* was
already solved by whatever table happens to have an ID column. MESA governs both
halves — identity in the Raw Layer, interpretation in the Metric Layer — as two
separate, separately-owned concerns. MESA Core is the free, forkable, standard
syntax for that discipline.

## License

MIT. See `LICENSE`.
