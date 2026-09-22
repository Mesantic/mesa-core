# mesa-core — User Personas
**Date: 2026-09-21**
**Product: mesa-core (the open-source, MIT-licensed MESA compiler — the dbt-Core equivalent)**

---

## Why this is a different persona set than Mesantic's

`mesa-core` is not the SaaS app (`Mesantic`/`mesa-governance-api`). It's a **local CLI**:
`pip install mesa-core`, no account, no server, no data leaves the machine. There's no `/try`
page, no drift scan against a live warehouse, no workspace, no RBAC, no audit log, no billing
tier. The entire product surface is: `mesa init`, `mesa new entity`, `mesa build`, `mesa compile`,
`mesa validate`, `mesa evaluate`, `mesa fmt`, `mesa lint`, `mesa learn`. Every persona below is
grounded in THAT surface — the Mesantic SaaS personas (V2/V3/V4 in `../Mesantic/`) do not apply
here except as a later-stage "graduates into the paid product" hook for a couple of them.

The core tension every persona lives inside: **`mesa validate` is a hard gate (non-zero exit,
refuses bad code) but `mesa evaluate` is deliberately advisory** (never fails a build unless
`--strict`). That split — "refuse the fat-finger join" vs. "grade the health, don't block it" —
is the single most important design decision to trace through every journey below.

---

## PERSONA 1 — Marisol Vega, Solo Analytics Engineer at a seed-stage startup
**Background:** 3 yrs experience, self-taught, already runs a small dbt project, has never heard
of MESA before this week.

### How she found mesa-core
Saw a Hacker News comment referencing "the dbt-Core equivalent for semantic governance" — clicked
through to the GitHub repo, read the README's four-tier diagram.

### Step-by-step
1. **First command:** `pip install mesa-core`, then `mesa init my_project` — no signup, no
   account, she's compiling something on her laptop within 90 seconds of finishing the README.
2. **Second command:** `cd my_project && mesa new entity Customer --from-columns cols.txt` — she
   pastes a column list copied straight out of her existing Snowflake `DESCRIBE TABLE` output.
   This is the moment the tool either clicks or doesn't: the stub it generates already has the
   hashed-ID pattern, PascalCase columns, and a doctrine header — she didn't have to know the
   hashing convention existed before seeing it demonstrated in generated code.
3. **What she does next:** opens the generated Raw Layer file, tries to add a `SUM()` calculation
   directly into it because that's how she'd have written it in her own dbt project — this is the
   exact mistake the architecture exists to prevent.
4. **What catches it:** `mesa validate` — non-zero exit, refuses the build, points her at the
   Rulebook's Raw/Metric boundary section (`docs/RULEBOOK.md`) via a `-> see:` pointer in the
   error output. She reads the "materials list" analogy for the first time from the error message
   itself, not the README.
5. **What she does after fixing it:** runs `mesa build`, sees SQL she didn't have to hand-write
   in `target/`, then runs `mesa evaluate` out of curiosity — gets a health scorecard grading her
   one entity, notices it's advisory (doesn't fail anything) and initially assumes that means it
   doesn't matter, skims past a warning about a missing `grain_description`.
6. **What eventually gets her to fix the warning:** nothing forces her to — she moves on with a
   B-grade entity for weeks until she runs `mesa learn` (the guided tutorial) out of boredom on a
   slow Friday and the tutorial explains why the field she skipped actually matters.

---

## PERSONA 2 — Femi Adeyemi, Senior Data Engineer standardizing a 40-person data org
**Background:** 8 yrs, leads a platform team, evaluating mesa-core to REPLACE a patchwork of
internal naming conventions and a stale Confluence page nobody follows.

### How he found mesa-core
Actively searching for "enforce data modeling standards" tooling — found it via a comparison
blog post pitting it against dbt's own project conventions and Cube/LookML.

### Step-by-step
1. **First thing he does:** does NOT run `mesa init` on a real project. Clones the repo, reads
   `mesa_core/validate/` and `mesa_core/evaluate/` source directly — he needs to know exactly what
   "refuse bad code" means at the AST/rule level before he'll recommend rolling this out to 40
   engineers, and the open-source nature is precisely why he can do this at all (closed SaaS tools
   don't let him read the enforcement logic before buying in).
2. **What he tests deliberately:** hand-writes a Raw Layer file with a bare, un-hashed
   `p.part_id AS ID` — confirms `mesa validate` catches it (per the Rulebook's explicit "never a
   valid MESA identity" rule) — then hand-writes a cross-entity join directly inside a Raw Layer
   file to confirm entity isolation is enforced too, not just documented.
3. **What convinces him to roll it out:** `mesa validate`'s exit code integrates trivially into
   his team's existing CI (any non-zero exit fails the pipeline) — he doesn't need a new CI
   product, just a new step, which is the entire "dbt-Core equivalent" pitch landing correctly.
4. **What he does with `--strict` on `mesa evaluate`:** turns it ON in CI for new entities but
   leaves it OFF for the org's existing legacy models during a migration window — deliberately
   using the advisory/gate split as a phased-rollout lever rather than an all-or-nothing switch.
5. **What he'd want that doesn't exist yet:** a way to set `--strict` per-directory rather than
   repo-wide, so new entities can be held to the full bar while a legacy folder is graded but not
   blocked — today it's binary at the CLI invocation level.

---

## PERSONA 3 — Priyanka Shah, dbt Package Maintainer evaluating interop
**Background:** maintains a moderately popular open-source dbt package (analogous to Tobias in
the Mesantic V4 set, but her question is architectural compatibility, not reputational risk).

### Step-by-step
1. **First command:** `mesa init` inside a throwaway directory, immediately followed by copying
   HER package's actual model SQL into the scaffolded Raw Layer folder structure to see if it fits
   without a rewrite.
2. **What she discovers:** her package's models mix Raw and Metric concerns in the SAME file (a
   very common dbt pattern — a staging model with a `CASE WHEN` business rule baked in) — `mesa
   validate` flags this immediately, and she realizes MESA's split isn't just a naming convention,
   it's a structurally different mental model than the one her package assumes.
3. **What she does about it:** doesn't try to force-fit her existing package. Instead she writes
   a short doc for her own package's users: "if you want to run this through MESA, split your
   staging model's business logic out into a Metric Layer file first" — she becomes an unofficial
   bridge between the two ecosystems rather than fighting the tool.
4. **What she'd want:** an automated "split this file" suggestion mode — today `mesa validate`
   tells her SOMETHING is wrong (mixed concerns) but doesn't propose the specific split; she has
   to do it by hand and re-run validate iteratively until clean.

---

## PERSONA 4 — Tomasz Wilk, Solo Consultant billing hourly across multiple small clients
**Background:** freelance data consultant, price- and time-sensitive, needs to stand up a clean
semantic layer FAST for clients too small to justify a SaaS governance contract.

### Step-by-step
1. **Why mesa-core specifically, not the Mesantic SaaS product:** no account needed, no per-seat
   pricing to negotiate with a client who has a total data budget of maybe $200/month — the local,
   free, MIT-licensed tool is the only thing that fits his engagement economics.
2. **First real session, per client:** `mesa init <client_name>`, then `mesa new entity` for each
   of the client's 4-6 real business objects, using `--from-ddl` against their actual Postgres
   schema rather than typing column lists by hand — the DDL-import path is the one he uses almost
   exclusively, since hand-typing columns for a new client every engagement would eat his billable
   margin.
3. **What he does with `mesa evaluate`:** runs it right before handing off the project, screenshots
   the scorecard, and includes it in his final deliverable email as evidence of quality — same
   instinct as the SaaS product's shareable drift scorecard, just self-generated from a local CLI
   run instead of a hosted feature.
4. **What breaks his workflow across clients:** DuckDB is his default warehouse target for local
   dev/demo purposes (per the README's "local development with zero external warehouse" note), but
   his clients' actual production warehouses are a mix of Snowflake and Redshift — he has to
   remember to re-target the dialect before final handoff, and has been burned once shipping a
   DuckDB-flavored artifact to a client expecting Snowflake SQL.

---

## PERSONA 5 — Dr. Anika Desai, Data Science Team Lead wanting stable feature definitions
**Background:** PhD, leads a small ML team inside a mid-size company; her team's biggest recurring
bug class is "the feature we trained on doesn't match the feature we're serving in production"
— a version of Yuki's problem in the Mesantic V3 set, but at the LOCAL/pre-warehouse-deploy stage.

### Step-by-step
1. **First command:** `mesa new entity` for the exact tables her team's feature pipeline reads
   from, treating the Metric Layer files as the canonical feature definitions BEFORE they ever get
   materialized to a warehouse — she's using mesa-core earlier in the lifecycle than most personas,
   as a design-time contract rather than a warehouse-facing compiler only.
2. **What she does that's unusual:** commits the `target/` compiled SQL output into her team's own
   feature-pipeline repo as a build artifact, version-pinned, so a training run and a serving run
   can both point at the EXACT same compiled SQL by git SHA — turning MESA's one-file-one-metric
   discipline into a reproducibility guarantee for ML, not just a data-governance one.
3. **What she'd want that doesn't exist:** a `mesa build --diff <old_sha> <new_sha>` mode that
   tells her exactly which compiled metric SQL changed between two commits — today she diffs the
   `target/` output manually with `git diff`, which works but isn't purpose-built for "did my
   feature definition silently change" review the way she'd want for an ML-specific workflow.

---

## PERSONA 6 — Chen Wei, University Data Engineering Instructor
**Background:** teaches a graduate data engineering course, looking for a teaching tool that
demonstrates real architectural discipline without requiring students to provision cloud warehouse
accounts.

### Step-by-step
1. **First thing he checks:** whether the whole thing runs against DuckDB with zero external
   accounts — confirmed by the README — this is the SINGLE deciding factor for whether he can
   assign it as coursework to 60 students without a cloud-billing nightmare.
2. **What he actually assigns:** `mesa learn` (the guided ~20-minute tutorial) as WEEK ONE
   homework, before any lecture — he's using the tutorial as a self-serve onboarding tool for an
   audience (students) who have never heard the word "grain" before in a data context.
3. **Second assignment:** students run `mesa init`, build the two-entity quickstart
   (`quickstart/` — Customer + Order with DuckDB example data) themselves, then deliberately BREAK
   the grain (duplicate a row) and are asked to explain, in a short writeup, why `mesa validate`
   catches it and what the underlying risk would have been in production.
4. **What he'd want that doesn't exist:** a "solutions" or "answer key" mode that shows the
   correctly-fixed version of a broken quickstart file for grading purposes — today he manually
   maintains his own answer key outside the repo.
5. **Unexpected side effect:** several students, per his own account, end up more interested in
   why `mesa evaluate` is advisory while `mesa validate` is a hard gate than in the SQL output
   itself — the enforcement PHILOSOPHY becomes the actual lesson, which he now leans into
   deliberately in lecture.

---

## PERSONA 7 — Grzegorz Nowak, DevOps/Platform Engineer wiring mesa-core into CI
**Background:** not a data person at all — owns the CI/CD pipeline infrastructure company-wide,
was handed a ticket: "add `mesa validate` and `mesa lint` as required checks on the data repo."

### Step-by-step
1. **First thing he does:** treats it exactly like any other linter/formatter pairing he's wired
   before (eslint+prettier, black+flake8) — `mesa fmt` rewrites, `mesa lint` is the check-mode
   twin that exits non-zero without rewriting, which maps cleanly onto a pattern he already knows,
   so onboarding for HIM personally takes about 15 minutes.
2. **What he actually configures:** a pre-commit hook running `mesa fmt` locally (so diffs are
   already clean before push) and a CI job running `mesa lint` + `mesa validate` as two SEPARATE
   required checks, deliberately kept apart so a lint-only failure (style) doesn't get confused
   with a validate-only failure (a real architectural violation) in the PR status UI.
3. **What he does NOT touch:** `mesa evaluate` — he was explicitly told it's advisory and not a
   merge gate, so he doesn't wire it into required checks at all, though he does add it as a
   NON-blocking informational CI comment (posts the scorecard grade in the PR, doesn't fail
   anything) — a middle path between fully wiring it and ignoring it entirely.
4. **What he'd want:** a machine-readable exit code or JSON summary distinguishing WHICH rule
   category failed (`mesa validate --json`, if it doesn't already emit structured output) so his
   pipeline can post a more specific PR comment than a raw stdout dump — a small ergonomics gap
   for someone building tooling ON TOP of the CLI rather than running it interactively.

---

## PERSONA 8 — Sofia Ramirez, Data Architect writing the company's internal "why MESA" RFC
**Background:** senior IC, tasked with writing the internal proposal to adopt mesa-core company-
wide, competing against the do-nothing option and against a competing internal proposal to just
"write better documentation" instead.

### Step-by-step
1. **First thing she does:** reads `docs/RULEBOOK.md` cover to cover, specifically extracting the
   "silent assumption every rule closes" framing — she reuses this EXACT rhetorical structure in
   her RFC, because it's the most effective argument against the "we already have naming
   conventions" objection she knows she'll get in review.
2. **What she builds as a proof-of-concept for the RFC:** takes THREE real, messy existing models
   from her company's actual dbt project, runs them (or attempts to) through `mesa new entity`
   and `mesa validate`, and documents every violation surfaced as a bullet point of "here's a bug
   this would have caught before it shipped" — using the tool's own error output as her RFC's
   primary evidence, rather than describing the architecture abstractly.
3. **What she anticipates as pushback and pre-answers in the RFC:** "this will slow us down" —
   she addresses it directly by pointing at the `mesa evaluate`/`mesa validate` split: hard gate
   only on the things that are provably dangerous (identity collisions, `SELECT *`, grain fan-out),
   advisory grading on everything else, so the RFC isn't proposing an all-or-nothing culture shift.
4. **What she recommends for rollout sequencing:** start with `mesa lint`/`fmt` (zero behavioral
   risk, pure style), THEN `mesa validate` on NEW entities only, THEN `mesa evaluate --strict` much
   later once the org has a baseline of scored entities to know what "good" looks like internally
   — a phased adoption curve she designs herself, since the tool doesn't prescribe one.

---

## PERSONA 9 — Ola Bergström, Junior Engineer's first real task
**Background:** 6 months into their first data job, assigned "add the `Shipment` entity" as an
onboarding task, has never seen MESA or any semantic layer discipline before.

### Step-by-step
1. **First command, typed almost verbatim from a teammate's Slack message:** `mesa new entity
   Shipment --from-columns cols.txt` — they don't yet understand WHY the output looks the way it
   does; they're pattern-matching off an existing entity in the repo, not the Rulebook.
2. **First real confusion:** tries to add a `NumberOfDaysInTransit` calculation directly to the
   Raw Layer file because that's the most natural place to put it conceptually (it's "about"
   Shipment) — gets blocked by `mesa validate`, and the error message's Rulebook pointer is the
   FIRST time they encounter the Raw/Metric distinction at all — same moment Marisol (Persona 1)
   hits, but Ola has far less context to interpret it with.
3. **What actually resolves their confusion:** not the error message alone — a teammate points
   them at `mesa learn` specifically because the error message assumes they already know what a
   "tier" is, and the tutorial is the only artifact in the whole toolchain that starts from zero.
4. **What they do after finishing the tutorial:** goes back and fixes the Shipment entity
   correctly, and — notably — the fix takes them 10 minutes once they understand the model, versus
   the 45 minutes they spent confused beforehand — validating (for the team, informally) that the
   tutorial should be MANDATORY first-day onboarding, not an optional "if you get stuck" resource.
5. **What they'd want:** the CLI's own error output to at least mention `mesa learn` by name when
   it detects a Raw/Metric violation from what looks like a first-time user pattern — today the
   pointer goes straight to the Rulebook doc, assuming a reader who can self-serve from prose,
   which wasn't true for Ola on day one.

---

## PERSONA 10 — The Silent Fork: Anonymous GitHub user who forks mesa-core and never engages
**Background:** unknown identity, unknown company — included because this behavior is REAL and
measurable (fork count, no issues filed, no PRs, no community post) and represents a large,
invisible slice of any OSS project's actual usage.

### What's knowable about this persona
1. **What they did:** forked the repo, likely ran `mesa init` and `mesa build` locally at least
   once (inferred, not confirmed — OSS analytics can't see private local usage at all), then
   silently adapted the code for an internal, closed-source semantic layer inside their own
   company, deriving value without ever appearing in any community channel.
2. **Why this matters for planning, even without concrete detail:** any OSS-strategy roadmap that
   only counts GitHub stars, issues, and PRs as "usage" is undercounting real adoption by an
   unknown but probably significant margin — the MIT license explicitly permits exactly this
   silent-fork behavior, and it's a feature of open-source distribution, not a measurement bug to
   fix.
3. **What this persona implies about product decisions:** documentation and error messages need
   to be self-sufficient (no assumption that a user will ever file an issue or ask a question
   anywhere) — Ola's Persona 9 gap ("mention `mesa learn` in the error output") matters MORE
   because of this persona, not less: for the silent fork, the in-tool guidance IS the entire
   support relationship, with no human backstop possible.

---

## Cross-Persona Pattern Summary

| Persona | Entry command | Validate vs. Evaluate behavior | Unique mechanic surfaced |
|---|---|---|---|
| Marisol (solo eng) | `mesa init` → `mesa new entity` | Hits `validate` gate immediately; ignores advisory `evaluate` warning for weeks | Advisory grading is easy to under-value until `mesa learn` explains it |
| Femi (platform lead, 40-person org) | Reads source before running anything | Deliberately phases `--strict` per rollout stage | OSS transparency lets him audit enforcement logic pre-adoption |
| Priyanka (dbt package maintainer) | Copies existing package code in | `validate` flags mixed Raw/Metric concerns immediately | No automated "split this file" suggestion — manual iteration required |
| Tomasz (consultant) | `--from-ddl` per client | Uses `evaluate` output as a client deliverable | DuckDB-default-vs-client-warehouse dialect mismatch risk |
| Anika (DS lead) | `mesa new entity` pre-warehouse | Uses compiled `target/` SQL as a pinned ML artifact | Wants a `build --diff` mode; none exists |
| Chen Wei (instructor) | `mesa learn` assigned as homework | Leans into the validate/evaluate PHILOSOPHY as the lesson itself | No "solutions key" mode for grading |
| Grzegorz (DevOps, non-data) | Wires `fmt`/`lint`/`validate` into CI | Explicitly does NOT gate on `evaluate`; posts it as info only | Wants structured JSON exit detail for pipeline tooling |
| Sofia (architect, RFC author) | Reads Rulebook, runs real messy models through it | Uses the validate/evaluate split to pre-answer "too rigid" pushback | Designs her own phased-adoption curve; tool doesn't prescribe one |
| Ola (junior eng, day one) | Copies a Slack command verbatim | Confused by `validate` error until sent to `mesa learn` | Error output doesn't mention `mesa learn` by name |
| Silent Fork (anonymous) | Unknown, inferred only | Unknown | No human backstop possible — docs/errors ARE the whole support relationship |

## Concrete product gaps this pass surfaced
1. **Per-directory `--strict` scoping** for `mesa evaluate`, so new entities can be held to a
   higher bar than a legacy folder during a phased migration (Femi).
2. **Automated "split this file" suggestion** when `validate` detects mixed Raw/Metric concerns
   in one file, rather than just flagging that something's wrong (Priyanka).
3. **Dialect-mismatch guardrail** — a warning when the compiled target dialect (e.g., DuckDB
   default) doesn't match an explicitly-declared production target, to catch the
   dev-artifact-shipped-to-a-client mistake (Tomasz).
4. **`mesa build --diff <sha1> <sha2>`** — purpose-built compiled-SQL diffing across commits, for
   reproducibility-sensitive consumers like ML feature pipelines (Anika).
5. **A "solutions key" / answer-key mode** for the quickstart project, useful for instructional
   settings (Chen Wei).
6. **Structured JSON output for `mesa validate`/`lint`** distinguishing rule categories, so CI
   tooling built on top of the CLI doesn't have to scrape stdout (Grzegorz).
7. **`mesa learn` referenced by name directly in `validate` error output** when the violation
   pattern looks like a first-time-user mistake — most important precisely because of Persona 10's
   silent-fork reality: for many real users, the tool's own text is the only support they'll ever get.
