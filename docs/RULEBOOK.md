# The MESA Rulebook

This is the reference every `mesa evaluate` pointer sends you to. It documents the
rules MESA grades against, grouped the same way the scorecard groups them, so a
"read the MESA Rulebook — 'Hashed Identity'" line lands you in the right place.

MESA's whole bet is that a semantic layer has to govern two halves that every other
tool treats as one: **identity** (what a `Customer` *is*) and **interpretation**
(what a `Customer` *means*). Most tools start at meaning and assume identity was
already solved by whatever table happened to have an ID column. MESA makes both
halves explicit, owned, and reviewable. Every rule below traces back to closing one
silent assumption the rest of the industry tolerates.

---

## 1. The four tiers

Data flows one direction, and each tier has exactly one job. No layer is skipped,
no logic lives outside its tier.

```
RAW LAYER (Tier 1)      →  METRIC LAYER (Tier 2)  →  WIDE LAYER (Tier 3)  →  VIEW LAYER (Tier 4)
  Business concepts          One file = one metric    Pure assembly           Consumer-facing views
  Hashed IDs, PascalCase     2 columns: ID + value   SELECT whole STRUCTs    WHERE filters allowed
  No calculations            INNER JOIN only         No logic, no CASE       ID aliased for BI
```

If you find yourself writing logic from one tier into another, stop — that's the
moment you're about to break the contract.

### What "entity" means

An entity is a raw material, not a metaphor for one. Think of a materials list for
a bridge deck: cement, water, gravel, sand. Each one *just is* what it is — nobody
asks "what does this bag of cement mean?" It has an identity, and that identity is
stable and uninterpreted. That's the Raw Layer. The mixing ratio — water-cement,
aggregate proportions, the psi the mix cures to — is the Metric Layer. Nobody
confuses the bag of cement with the psi rating. That one sentence is the entire
Raw/Metric boundary.

---

## 2. Hashed identity

Every Raw Layer table carries a **hashed surrogate key** built from the source
system and the source ID together:

```sql
-- Snowflake
BASE64_ENCODE(SHA2(CONCAT(source_system, '-', source_id), 256)) AS ID

-- BigQuery
TO_BASE64(SHA256(CONCAT(source_system, '-', source_id))) AS ID
```

The `source_system` prefix is load-bearing. Without it, source-system-1's ID `123`
and source-system-2's ID `123` hash to the same value and silently merge two
different entities. This is the fat-finger join the hashed ID exists to make
impossible — it has happened in production.

A bare source key (`p.part_id AS ID`) is never a valid MESA identity.

---

## 3. Grain

One Raw Layer table = one business entity = one grain. "One row = one policy." If
the reality is "one row per policy per month," that's a snapshot, and it belongs in
the Metric Layer, not here.

The grain is stated in the doctrine header's `-- Grain:` line, and it is *proven*
by the `unique` + `not_null` tests on the ID column in the sidecar. A grain that's
written down but never tested is a claim nobody verified — the test is the
empirical backstop.

A join with no key equality, or a cross-row aggregate in the Raw Layer, can
silently multiply rows and corrupt the grain. Collapse it (aggregate, or
`QUALIFY` / `ROW_NUMBER() = 1`), or move the aggregate up to the Metric Layer.

---

## 4. Link STRUCTs & entity isolation

A relationship between entities is **declared once, at the Raw Layer**, as a link
STRUCT — never as a join between two Raw Layer tables:

```sql
STRUCT(Person.ID) AS Person                          -- one link
STRUCT(AccountManagerPerson.ID AS AccountManagerID,
       ServiceAgentPerson.ID AS ServiceAgentID) AS Persons  -- many links
```

The linked entity carries *only* the hashed ID (hash-only doctrine): a Reference
Carrier "holds an address, doesn't make the trip." The actual join happens at the
View Layer, keyed on that declared ID.

This is why cross-entity reads get flagged on the scorecard: a metric reaching
another entity's raw directly usually means the relationship was never declared as
a link STRUCT first. Declare the link, then read through it.

**The exception:** the scorecard flags a second Raw Layer entity sitting in the
terminal `FROM`/`JOIN` of a metric — not a second entity read anywhere in the file.
A metric may pull a second entity into a `WITH` CTE, aggregate it down to the
anchor entity's grain, and join that CTE onto the anchor using a key the two
entities already share (a real FK, an account number, a policy number — not an
invented join). The anchor's Raw Layer table stays the only thing in the terminal
`FROM`; the second entity never appears outside its CTE. A production example of
this shape (an AO Calc_Shared file, `AccountCalc/NumberOfSalesOpportunities`):
aggregate `SalesOpportunity` to one row per `AccountId` in a CTE, then `LEFT JOIN`
that onto `Account` on the real `AccountId` FK. That passes. Joining two
entity-scoped CTEs that only line up because both filter on the same literal value
— with no shared key — is not this pattern; that is the violation the rule exists
to catch.

---

## 5. Metric governance

**One file = one metric = one owner.** Each metric file returns exactly two
columns — `ID` and the metric value — and carries a header that names its owner,
its contract (the grain it returns), and what it means:

```sql
-- METRIC: TenureDays
-- Days since inception, as of today.
-- Owner: Retention Analytics
-- Contract: 1 row per policy ID = 1:1
```

Bundling two metrics into one file makes "which metric changed" ambiguous and
undoes git blame. An unowned metric is a metric nobody answers for. A missing
contract means a downstream join can't trust the row count.

### Naming conventions

Metric names are a type signal — an analyst should be able to tell a binary from
a count from a date just by reading the name. The table:

| Pattern | Prefix/Suffix | Example |
|---|---|---|
| Binary/boolean | `Is` / `Has` | `IsLive`, `HasPended` |
| Count | `NumberOf` | `NumberOfCasesLast30Days` |
| Distinct count | `NumberOfDistinct` | `NumberOfDistinctProducts` |
| Average | `AverageNumberOf` | `AverageNumberOfEmployees` |
| Date | `Date` suffix | `FirstContractDate` |
| Timeframe | include exact days | `NumberOfCasesClosedLast30Days` |
| Previous / next | `Previous` / `Next` prefix | `NextRenewalDate` |
| Unit of measure | prefix with unit | `MonthsToLive`, `SecondsToAnswer` |

---

## 6. Enrichment

A "thin" entity is a system concept wearing a business name — a 4-column
"Customer" is not a real entity, because it can't answer questions without a
cross-entity join. A well-enriched entity carries 30–80 stable business attributes
(name, address, industry, tenure, tier) so it can answer more questions on its own
grain.

`mesa evaluate` counts the attributes *you've declared* and warns when an entity is
thin. The cross-source *suggestions* for fields you haven't mapped yet — "25
candidate fields found across 3 connected sources" — are a Mesantic feature, not
part of the free definitions-only check.

---

## 7. Documentation

Three things make a definition reviewable without reading the SQL line by line:

1. **The doctrine header** — the five-line block at the top of a Raw Layer file
   (`-- RAW ENTITY`, `-- Grain`, `-- ID`, `-- Doctrine`) that states the grain,
   the ID formula, and any doctrine notes. A reviewer checks the header before the
   query.
2. **Metric descriptions** — a one-line "what this means" above `-- Owner:`.
   A metric with no description is a number with no story.
3. **Sidecar column descriptions** — the `_raw.yml` description on the ID column is
   where the hashed-ID rule gets documented for the next person.

---

## 8. Safety rules

MESA-SEC-001 through -007 scan for security and safety issues in the SQL itself.
`mesa evaluate` reports all of them as scorecard lines; `mesa validate` gates on
the blocking subset.

| Rule | What it catches | Severity |
|---|---|---|
| SEC-001 | Hardcoded secrets (AWS keys, credentials, private keys, JWTs, high-entropy literals) | blocking |
| SEC-002 | PII literals (SSNs, email addresses) | warn |
| SEC-003 | Bare `CAST` — use `SAFE_CAST` / `TRY_CAST` | warn |
| SEC-004 | Division without `NULLIF(..., 0)` | warn |
| SEC-005 | `LEFT/RIGHT JOIN` to a `ref()` in the metric layer — use `INNER JOIN` | blocking |
| SEC-006 | Text comparisons without `UPPER()`/`LOWER()` case-folding | warn |
| SEC-007 | `SELECT DISTINCT` as a dedup crutch | warn |

`evaluate` is the mirror; `validate` is the gate. The two are deliberately
different commands: `evaluate` grades everything and never fails a build by
default, `validate` refuses bad code and exits non-zero.

---

## 9. The wide layer is a required artifact, not a scaffold nicety

Every warehouse needs "join the raw entity to its metrics and hand the result to
the View Layer" solved somehow. The shape of that solution is warehouse-dependent:

- **BigQuery** — native and zero-maintenance: `SELECT Entity, EntityMetric` as
  plain typed STRUCTs. No cast wrapper, no combiner needed.
- **Snowflake** — needs an explicit typed cast per metric
  (`OBJECT_CONSTRUCT_KEEP_NULL(...)::OBJECT(<TYPE>)`), which is why the Snowflake
  path assembles the wide table as one typed OBJECT per metric.
- **Redshift / DuckDB** — a qualified wildcard with no typed cast, closer to
  BigQuery's zero-maintenance shape than Snowflake's.

Whatever the dialect, one rule does not change: **a new raw entity is not done
until it has a wide-layer file.** `mesa new entity` stamps a wide-layer *stub*
automatically — a placeholder that references the raw table but joins no metrics,
because at scaffold time there are none to join. That stub is not the finished
artifact. Once the entity has its first metric file, regenerate the wide layer:

```
mesa compile <Entity>    # or: mesa build
```

and again every time a metric file is added or removed. `mesa build --check` (and
`mesa validate`'s wide-layer drift check) is the automated way to confirm the
committed wide file still matches what the compiler produces today — but a human
adding a new entity has to run the regeneration locally; the check only fires when
you ask it to, not when you edit a metric file.

---

## 10. mesa-core compiles Snowflake SQL — it never connects to Snowflake

mesa-core emits Snowflake-dialect SQL (the `BASE64_ENCODE(SHA2(...))` hashed-ID
idiom in section 2, the `OBJECT_CONSTRUCT_KEEP_NULL(...)::OBJECT(...)` wide-layer
cast in section 9) but it never opens a live connection to a Snowflake account.
Connection and authentication — username/password, key-pair, RSA passphrases,
environment-variable and secrets-manager references — is a Mesantic concern, not a
mesa-core one. It lives in `mesa-governance-api`; see its
`docs/WAREHOUSE_CONNECTIONS.md` for the connection reference.

This is a boundary, not a gap. A solo developer who forks mesa-core can compile
and validate every dialect on one laptop with no account and no credentials — which
is exactly the boundary that keeps mesa-core MIT and freely forkable. Adding
connection or auth code here would pull in live-credential handling and break that
boundary. If a future contributor reaches for a connector while working on
mesa-core, the answer is: that code belongs in Mesantic, not here.
