# mesa-core — User Personas V2 (Second Fresh Set)
**Date: 2026-09-21**
**Companion to:** `MESA_CORE_USER_PERSONAS.md`. Same grounding rules apply — local CLI, MIT
license, no server/account. Read that file's intro for the validate-is-a-hard-gate vs.
evaluate-is-advisory split; not repeated in full below. Ten different people this time.

---

## PERSONA 1 — Jonas Berg, Solo Indie SaaS Founder, technical, building his own product's analytics
**Background:** builds and ships his own SaaS product single-handedly, wants a real semantic
layer for internal metrics without adopting a hosted governance product he'd have to pay for.

### Step-by-step
1. **First command:** `mesa init` inside his existing app's monorepo, in a `data/` subfolder —
   he deliberately colocates it with his application code rather than a separate repo, since
   he's the only person who will ever touch either.
2. **First entity:** `mesa new entity Subscription --from-duckdb` — pointed directly at a local
   DuckDB export of his production Postgres subscriptions table, skipping the column-list/DDL
   paths entirely because DuckDB is already his local dev database of choice.
3. **What he does with `mesa build`:** wires it into his own deploy script as a pre-deploy step —
   if `mesa validate` fails, his OWN deploy pipeline (not a CI service, just a bash script) refuses
   to push, a hand-rolled version of Grzegorz's CI wiring in the first doc, but entirely self-built
   with no DevOps team to hand it to.
4. **What he never does:** run `mesa evaluate --strict`. He doesn't have a team to hold to a
   standard beyond his own judgment, so the advisory scorecard is genuinely optional for him in
   a way it might not be for a multi-person org — he checks it maybe once a month out of curiosity.
5. **What he'd want:** a single-command "explain this one violation to me" mode — when `validate`
   fails on something unfamiliar, he currently has to open the Rulebook doc in a browser tab; a
   `mesa explain <rule-code>` that prints the relevant Rulebook section inline would keep him in
   the terminal, which matters more to a solo, terminal-native builder than to a team with Slack.

---

## PERSONA 2 — Ingrid Solberg, Compliance-Adjacent Data Engineer at an EU fintech
**Background:** her company is small (18 people) but regulated (EU payments), so she needs
governance discipline without the headcount or budget for an enterprise SaaS governance contract.

### Step-by-step
1. **How she found it:** searching specifically for a FREE, LOCAL semantic governance tool because
   her company's small size means an enterprise-tier SaaS contract (like the Mesantic Enterprise
   tier) is financially out of reach even though her compliance NEEDS are enterprise-shaped.
2. **First real use:** models her core `Payment` and `Account` entities with hashed IDs specifically
   BECAUSE she needs to demonstrate to an eventual regulator that identity collisions across her
   two banking-rail integrations (different source systems, potentially overlapping raw IDs)
   are structurally impossible, not just carefully avoided — the hashed-ID rule's exact justification
   from the Rulebook is, for her, not an abstraction but a literal regulatory risk she's closing.
3. **What she treats as a compliance artifact:** the `target/` compiled SQL output itself,
   committed to git with a signed commit — she uses git history (not an audit log, since there
   isn't one in mesa-core) as her de facto change-history evidence for an eventual audit.
4. **What she'd want that doesn't exist:** an OWNERSHIP field enforced at the file level (mesa-core
   has no `owner_id`/`steward_id` concept the way the Mesantic SaaS product's `MetricExpressionCreate`
   does — that governance metadata lives in the paid product, not the open compiler) — she ends up
   hand-writing owner comments in doctrine headers as a workaround, which `mesa validate` neither
   requires nor checks.
5. **Her eventual path:** once her company grows past ~40 people, she expects to migrate the
   metadata/ownership/audit layer to the Mesantic SaaS product while KEEPING mesa-core as the
   underlying compiler — she's using the free tool now as a bridge to a paid relationship later,
   which is exactly the funnel the open-core model is designed to create.

---

## PERSONA 3 — Kenji Watanabe, Contributor fixing a bug in the compiler itself
**Background:** professional backend engineer, uses mesa-core at his day job, hit an actual bug
in the `compiler/` module and decided to fix it upstream rather than work around it.

### Step-by-step
1. **First action:** NOT `mesa init` — clones the repo, runs the test suite locally to confirm
   he can reproduce the bug before touching anything (a different first move than every user-tier
   persona; he's operating on the source tree, not a generated project).
2. **What he actually found:** a specific warehouse dialect (Redshift) mishandling a link STRUCT
   compilation edge case — traced it into `mesa_core/compiler/`, wrote a minimal failing test case
   modeled on the existing test fixtures' style before writing the fix itself.
3. **What he does with the fix:** opens a PR, and specifically checks whether the project has a
   CONTRIBUTING.md with expectations before submitting (it does — `CONTRIBUTING.md` at repo root)
   — reads it fully rather than guessing at conventions, since he wants the PR merged on the first
   pass, not bounced for style reasons.
4. **What determines whether he keeps contributing:** how the maintainer responds to the FIRST PR
   — a fast, specific, technically substantive review turns him into a repeat contributor; a slow
   or generic response and he goes back to privately patching his own vendored copy instead, the
   same "silent fork" outcome Persona 10 in the first doc represents, except HE started as an
   engaged contributor and could have stayed one.
5. **What he'd want:** a documented "good first bug" or architecture-overview doc distinct from
   the user-facing README/Rulebook — something oriented at people reading the COMPILER source, not
   people compiling entities, since right now the onboarding material is 100% end-user-facing.

---

## PERSONA 4 — Louise Fontaine, Data Modeling Consultant Standardizing a Client's Legacy Warehouse
**Background:** senior consultant, hired specifically to clean up 6 years of inconsistent naming
and ad-hoc joins in a mid-size retailer's Snowflake warehouse — no active governance tool in place
at all before her engagement.

### Step-by-step
1. **First command:** `mesa new entity` run against EVERY major legacy table using `--from-ddl`,
   essentially treating the whole exercise as a reverse-engineering pass — she's not designing a
   greenfield model, she's DISCOVERING what entities already implicitly exist inside 6 years of
   accumulated SQL and forcing each one through the four-tier stub for the first time.
2. **What immediately surfaces, at volume:** dozens of `mesa validate` failures, almost all the
   SAME two root causes repeated across different tables — bare un-hashed IDs, and business logic
   embedded directly in what should be Raw Layer tables — she uses the SHEER REPETITION of the
   same violation as evidence in her final report that this wasn't a one-off mistake, it's a
   systemic pattern in how the org has always modeled data.
3. **What she does differently from a greenfield persona:** she can't just "fix" the violations —
   many of the underlying legacy tables have DOWNSTREAM consumers (existing BI dashboards) she'd
   break by changing the physical table. Her actual deliverable is a NEW parallel MESA-compliant
   layer that coexists with the legacy tables during a migration window, not an in-place rewrite.
4. **What she'd want that doesn't exist:** a bulk/batch mode — today she runs `mesa new entity`
   and `mesa validate` per-table, dozens of times, scripting the loop herself in bash rather than
   the CLI offering a "scan this whole DDL export and stub every table" batch command.
5. **What ultimately sells the client on continuing past her contract:** the fact that `mesa
   validate`'s refusals are the SAME whether she runs them or a junior engineer runs them next
   year — enforcement doesn't depend on her personally remembering the standard, which is exactly
   what she's being paid to make true.

---

## PERSONA 5 — Bilal Chaudhry, Site Reliability Engineer wiring a nightly compile-and-diff job
**Background:** infra-focused, doesn't care about the semantics at all — was asked to make sure
the compiled `target/` SQL never silently drifts from what's actually deployed in the warehouse.

### Step-by-step
1. **First thing he does:** treats `mesa build` as just another artifact-producing build step,
   wires it into a nightly cron/CI job that runs `mesa build` fresh and diffs `target/` against
   what's checked into git — if they differ, someone edited the compiled output by hand instead of
   the source files, which is exactly the kind of drift he's paid to prevent.
2. **What he explicitly does NOT do:** read a single line of the Rulebook. His entire relationship
   with mesa-core is "does this command exit 0 and does this output match," full stop — the same
   posture as Haruto (the SRE in the Mesantic V4 set) but one layer earlier in the pipeline, before
   anything reaches a live warehouse or a scheduled monitor at all.
3. **What breaks his job once, memorably:** a well-meaning analyst manually tweaked a `target/`
   SQL file to hotfix a production issue over a weekend without regenerating it from source — his
   diff job caught it Monday morning, and it became the org's cautionary story for why `target/`
   should arguably be gitignored entirely rather than committed, or at minimum branch-protected.
4. **What he'd want:** a `mesa build --verify` mode that does the diff-against-checked-in-output
   check natively, so he's not hand-rolling the comparison logic himself in a shell script.

---

## PERSONA 6 — Renata Silva, Non-Technical Product Manager forced to read a `mesa validate` error
**Background:** PM, not an engineer, was CC'd on a broken CI build because her ticket ("add a
`RefundRate` field") turned into an engineer opening a PR that failed validation, and she got
pulled into the thread.

### Step-by-step
1. **Her only interaction with the CLI, ever:** none directly — she never runs a command herself.
   She reads a GitHub Actions failure log an engineer pasted into a ticket comment, trying to
   understand why "add a field" turned into "architecture violation."
2. **What confuses her:** the error output is written for someone who already knows what "Metric
   Layer" and "grain" mean — she has zero context, and unlike Ola (the junior engineer in the
   first doc) she has no expectation of ever learning the vocabulary herself; she just wants to
   know if her ticket is blocked and for how long.
3. **What actually resolves it for her:** the engineer, not the tool, translates: "we can't put a
   calculation directly on the raw table, it has to be a separate metric file — 20 minute fix."
   She never opens the Rulebook, never runs `mesa learn`. Her resolution path is 100% human-
   mediated.
4. **What this persona proves, structurally:** the tool's error messages and even `mesa learn`
   are scoped to PRACTITIONERS. There is no "explain this to a non-technical stakeholder in one
   sentence" surface anywhere in the product, and building one would be solving a real but
   currently entirely human-patched gap — every PM-adjacent persona in every persona doc so far
   (Nadia, Camille, Renata) hits some version of this same wall.

---

## PERSONA 7 — Dmitri Kovalenko, Warehouse Migration Engineer moving Redshift → Snowflake
**Background:** tasked with a straight lift-and-shift warehouse migration; mesa-core enters the
picture because his company ALREADY has MESA-modeled entities targeting Redshift and needs them
recompiled for Snowflake without redefining anything from scratch.

### Step-by-step
1. **First command:** not `mesa init` — the project already exists. He runs `mesa build` with
   the warehouse target flag changed from Redshift to Snowflake and is testing, essentially,
   whether "one definition compiles to every supported warehouse" (the README's core cross-
   warehouse promise) actually holds under a real migration, not just a marketing claim.
2. **What actually happens:** most entities recompile cleanly — the abstraction genuinely holds
   for the identity/grain/link-STRUCT layer. But a handful of Metric Layer files have warehouse-
   specific SQL functions hand-written directly into them (someone previously wrote a Redshift-
   specific date function inline instead of using a portable expression) — these fail or produce
   silently wrong SQL on the Snowflake target, since dialect-specific raw SQL isn't something
   `mesa validate` is designed to catch (it enforces STRUCTURE, not portability of arbitrary
   expressions inside a metric file).
3. **What he does about it:** manually audits every Metric Layer file for warehouse-specific
   syntax before trusting the Snowflake recompile — the exact kind of manual verification the
   whole tool is supposed to make unnecessary, and doesn't, for this one category of risk.
4. **What he'd want:** a lint rule specifically flagging warehouse-specific SQL functions used
   inside a portable Metric Layer file, since it undermines the cross-warehouse promise in a way
   that's currently invisible until a real migration surfaces it.

---

## PERSONA 8 — Amara Nwosu, Technical Writer hired to overhaul the docs
**Background:** freelance technical writer, hired by whoever maintains mesa-core's open-source
project (not a data person by training) specifically to make the Rulebook and README more
approachable for non-expert first-time users.

### Step-by-step
1. **First thing she does:** runs `mesa learn` herself, cold, with zero prior data-engineering
   background, deliberately treating herself as the least-informed possible user to find every
   place the tutorial assumes knowledge it hasn't yet taught.
2. **What she documents as friction:** the exact same gap Ola (Persona 9, first doc) hit and Renata
   (Persona 6, this doc) hit from different angles — vocabulary introduced before it's defined.
   Her professional read: the README's four-tier diagram is excellent for someone who already
   has a mental model to hang it on, and nearly useless for someone who doesn't yet.
3. **What she proposes:** NOT rewriting the Rulebook's content (she defers to the maintainers on
   correctness) but adding a "if you're new, start here" onboarding path that sequences `mesa learn`
   BEFORE the README's own quickstart snippet, inverting the current order where the pip-install-
   and-go snippet appears first and the tutorial is mentioned as an aside.
4. **What she'd want from the maintainers that's a process gap, not a doc gap:** a changelog or
   versioning discipline for the Rulebook itself — she notices rule wording has quietly drifted
   between versions with no visible diff history, which makes writing ACCURATE docs harder than
   it should be for a project that otherwise cares this much about explicit contracts.

---

## PERSONA 9 — Hassan Al-Farsi, Data Governance Committee Member evaluating OSS tools for a bank
**Background:** works for a large regulated bank; part of a committee evaluating whether ANY
open-source tool can be approved for use given the bank's vendor/dependency risk policies —
never touches the CLI personally, evaluates the PROJECT as an artifact.

### Step-by-step
1. **First thing he checks:** the license (`LICENSE`, MIT) — confirmed permissive and compatible
   with the bank's OSS usage policy, a hard requirement before anything else is even considered.
2. **Second thing he checks:** commit history, contributor count, and whether there's a single-
   maintainer bus-factor risk — a large bank's risk committee treats "what happens if the
   maintainer disappears" as seriously as any feature question, and an OSS project with one
   committer reads very differently to this persona than one with an active contributor base
   (directly relevant to whether Kenji's PR, Persona 3, gets merged and multiplies visible activity).
3. **Third thing he checks:** whether the compiled SQL output could be audited by the bank's OWN
   internal security review without needing to trust Mesantic LLC's infrastructure at all — the
   fact that mesa-core runs 100% locally with no network calls is the single fact from the README
   that gets highlighted, underlined, and quoted directly in his committee memo.
4. **What he ultimately approves:** mesa-core for INTERNAL, offline use by the bank's own data
   engineers, explicitly NOT as a vendor relationship (there's no vendor to have one with) — his
   approval memo treats it more like approving a compiler or a linter than approving a SaaS tool,
   which is the correct category for it and validates the open-core packaging choice.
5. **What he'd flag as an open question for later:** whether the bank's engineers, once dependent
   on mesa-core internally, would need a supported/paid fallback if they ever wanted enterprise
   support — surfacing the same "graduates to Mesantic SaaS later" path Ingrid (Persona 2) already
   represents, but from a risk-committee's forward-looking lens rather than a practitioner's.

---

## PERSONA 10 — A GitHub Actions Bot, technically not a person, but the most frequent "user"
**Background:** not a human at all — included because in terms of raw INVOCATION COUNT, automated
CI runs almost certainly dwarf every human persona above combined, and design decisions that look
irrelevant to a human (exit codes, stdout format, run duration) are this "persona's" entire
experience.

### What it actually does, every single PR, across every adopting org
1. Checks out the repo, runs `mesa fmt --check` (or `mesa lint`), then `mesa validate`, then
   optionally `mesa evaluate` in informational mode — exactly the sequence Grzegorz (first doc)
   and Bilal (this doc) each independently wired by hand, replayed mechanically thousands of times
   a day across every org that adopted the pattern.
2. **What matters to this "persona" that matters to no human persona:** total wall-clock runtime
   per invocation, at scale — a CLI that's fast for one entity but scales poorly across a 500-entity
   monorepo becomes an organizational tax multiplied by every PR, every day, forever; performance
   at scale is a persona-shaped concern even though no individual human ever personally experiences
   the aggregate cost, only the finance/infra team eventually questioning the CI bill.
3. **What would materially change this "persona's" experience:** incremental/changed-files-only
   validation (only re-validate entities whose files actually changed in a given PR, rather than
   the whole project every time) — not asked for by any human persona above, but implied directly
   by treating "the CI bot" as a first-class persona with its own distinct needs.

---

## Cross-Persona Pattern Summary (V2)

| Persona | Entry point | Human-mediated or self-serve? | Unique mechanic surfaced |
|---|---|---|---|
| Jonas (indie founder) | `mesa init` in his own monorepo | Fully self-serve, solo | Wants `mesa explain <rule>` to stay terminal-native |
| Ingrid (EU fintech eng) | Modeling `Payment`/`Account` for regulatory reasons | Self-serve, compliance-motivated | No file-level ownership metadata exists — hand-writes it as a workaround |
| Kenji (code contributor) | Clones repo, fixes a compiler bug | Self-serve, becomes maintainer-dependent | First-PR response quality determines contributor retention |
| Louise (legacy consultant) | Bulk `--from-ddl` reverse-engineering | Self-serve, at volume | No batch/bulk stub-and-validate mode exists |
| Bilal (SRE) | Nightly `mesa build` diff job | Fully self-serve, zero semantic interest | Wants native `mesa build --verify` diff mode |
| Renata (non-technical PM) | Reads a pasted CI error log | 100% human-mediated | No non-technical-stakeholder explanation surface exists anywhere |
| Dmitri (Redshift→Snowflake migration) | Recompiles existing entities for a new dialect | Self-serve, discovers a real gap | Cross-warehouse promise doesn't cover hand-written dialect-specific SQL inside metric files |
| Amara (technical writer) | Runs `mesa learn` cold, as a naive user | Self-serve, professionally analytical | Onboarding sequencing (tutorial-first) vs. current README order (install-first) |
| Hassan (bank governance committee) | Reviews the OSS project as an artifact | Never touches the CLI at all | License + bus-factor + zero-network-calls are the entire evaluation |
| CI Bot (non-human) | Every PR, every adopting org | N/A | Performance-at-scale and incremental validation matter only in aggregate |

## New concrete product gaps surfaced in this pass
1. **`mesa explain <rule-code>`** — print the relevant Rulebook section inline, keeping a
   terminal-native solo user from context-switching to a browser (Jonas).
2. **File-level ownership/steward metadata** in the open compiler itself, distinct from the paid
   Mesantic product's governance metadata — currently forces hand-written workarounds (Ingrid).
3. **A contributor/architecture-overview doc** distinct from end-user docs, to support people
   reading the compiler source rather than compiling entities (Kenji).
4. **Bulk/batch entity-stub-and-validate mode** for reverse-engineering an existing legacy
   warehouse at volume, rather than one table at a time (Louise).
5. **`mesa build --verify`** — native diff-against-checked-in-output mode, so teams stop
   hand-rolling drift detection in their own CI scripts (Bilal).
6. **A non-technical-stakeholder explanation surface** — every PM-adjacent persona across every
   persona doc so far hits this same wall with no in-product answer (Renata).
7. **A lint rule for warehouse-specific SQL functions inside portable Metric Layer files** — the
   cross-warehouse promise currently doesn't cover hand-written dialect leakage (Dmitri).
8. **Tutorial-first onboarding sequencing** — `mesa learn` surfaced before the install-and-go
   snippet, not after (Amara).
9. **Incremental/changed-files-only validation** for CI performance at scale — a need implied by
   treating automated CI invocation volume as its own persona (the CI Bot).
