# mesa-core — User Personas V4 (Fourth Fresh Set)
**Date: 2026-09-21**
**Companion to:** `MESA_CORE_USER_PERSONAS.md`, `MESA_CORE_USER_PERSONAS_V2.md`,
`MESA_CORE_USER_PERSONAS_V3.md`. Same grounding rules — local CLI, MIT license, validate-is-a-
gate/evaluate-is-advisory split. Ten more distinct people/roles; this set leans toward edge-case
and adjacent-role personas to round out the full picture.

---

## PERSONA 1 — Ana Beatriz Lima, Data Engineer at a company running mesa-core across THREE dialects at once
**Background:** works at a company that grew by acquisition — inherited a Redshift warehouse,
a BigQuery warehouse from an acquired team, and is actively migrating pilot workloads to
Snowflake. All three are live simultaneously, not sequentially.

### Step-by-step
1. **First command, repeated three times with different flags:** `mesa build --warehouse Redshift`,
   `--warehouse BigQuery`, `--warehouse Snowflake`, all from the SAME source entity definitions —
   she's the most literal real-world test of the "one definition compiles to every supported
   warehouse" promise, since for her it's not hypothetical portability, it's a daily operational
   requirement across three live systems.
2. **What she discovers:** the identity/grain/link-STRUCT layer recompiles identically in spirit
   across all three (same logical guarantee, different dialect-specific syntax as expected), but
   she has to maintain THREE separate deployment pipelines downstream of `mesa build`, since the
   tool compiles per-target but doesn't orchestrate a multi-target deploy in one invocation.
3. **What she'd want:** a `mesa build --warehouse Redshift,BigQuery,Snowflake` (or a config-file-
   driven multi-target list) that produces three separate `target/<dialect>/` output trees in one
   invocation, rather than three manual re-runs she currently scripts herself in a Makefile.
4. **What she does NOT worry about:** the actual business logic diverging between warehouses —
   she trusts the compiler to keep semantics identical across dialects precisely because the
   Metric Layer's 2-column contract is dialect-agnostic by design; her risk surface is entirely
   in orchestration, not correctness.

---

## PERSONA 2 — Tobias Reinholt, Solo Maintainer of a SIMILAR internal tool his company built years ago
**Background:** built and has maintained, for 4 years, his company's own bespoke internal
semantic-modeling script — smaller in scope than mesa-core but philosophically similar, born from
the same pain, entirely independently.

### Step-by-step
1. **First thing he does on discovering mesa-core:** feels a mix of validation and dread — someone
   else built a more polished, better-tested version of the thing he's been privately maintaining
   for years with zero external contributors and increasingly reluctant internal support for his
   time spent on it.
2. **What he actually does about it:** spends a weekend doing a genuine feature-by-feature
   comparison against his own tool, specifically checking whether mesa-core covers every case his
   internal tool handles — finds it covers MOST cases better (multi-warehouse support especially,
   which his tool never got to) but is missing one or two company-specific quirks his tool has
   accumulated as undocumented tribal knowledge.
3. **What he recommends to his own leadership:** migrate to mesa-core as the base layer, and
   either contribute the missing company-specific quirks upstream as a PR (if they're genuinely
   general) or keep a thin internal wrapper script for the truly company-specific 5% — explicitly
   choosing NOT to keep maintaining a full parallel tool now that a better-resourced OSS
   alternative exists, a decision that quietly retires years of his own accumulated maintenance
   burden.
4. **What this persona reveals, structurally:** mesa-core's real competition in many companies
   isn't a competing commercial product — it's exactly this: a tired internal script one engineer
   has been solo-maintaining forever, and the switching decision hinges on migration cost + ego
   more than feature comparison.

---

## PERSONA 3 — Priya Subramaniam, Data Engineer localizing mesa-core docs for a non-English-speaking team
**Background:** works at a company where the data team's working language is NOT English; she's
translating internal onboarding material and hits the English-only Rulebook/README as a wall.

### Step-by-step
1. **First thing she does:** translates the Rulebook's core concepts (the "materials list" analogy,
   the four-tier diagram) into her team's working language for an internal wiki page, NOT by
   filing an issue asking the project to internationalize itself — she treats it as her own
   problem to solve locally rather than expecting upstream support.
2. **What's hardest to translate faithfully:** the specific English wordplay in phrases like
   "identity vs. interpretation" and "IS vs. MEANS" — some of the Rulebook's persuasive force
   depends on English phrasing choices that don't map cleanly onto her team's language, and she
   has to find analogous local idioms rather than translating literally.
3. **What she keeps in English deliberately:** all actual CLI commands and error output, since
   translating those would create a permanent maintenance burden keeping her team's docs in sync
   with upstream CLI behavior — she draws a clear line between "concepts we explain in our
   language" and "commands/errors we leave in English and explain around."
4. **What she'd want, if it existed:** even a lightweight, community-contributed translation of
   just the Rulebook's core concepts (not the full CLI) — she'd contribute her own translation
   back if there were an established place/format for it, but doesn't currently see one, so her
   work stays purely internal.

---

## PERSONA 4 — Marcus Aurelius Silva, Data Platform Architect Designing a company-wide TEMPLATE repo
**Background:** senior architect tasked with creating the "golden template" every new data
project at his company should be forked from, rather than each team running `mesa init` fresh.

### Step-by-step
1. **First command:** `mesa init` once, then heavily customizes the output — adds his company's
   own CI config, a pre-filled `CONTRIBUTING`-style internal doc, example entities modeled on
   his company's actual domain vocabulary (not generic Customer/Order) — and commits THIS as the
   company's internal template repo that new projects fork from instead of running `mesa init`
   themselves.
2. **What this changes about every downstream team's experience:** they never see the vanilla
   `mesa init` scaffold or its default README at all — their first contact with MESA concepts is
   entirely mediated through Marcus's customized template, meaning his choices about what to
   include/exclude/emphasize become the DE FACTO onboarding experience for his entire company,
   silently overriding the upstream project's own onboarding design.
3. **What breaks when mesa-core ships a new version:** his template drifts from upstream scaffold
   changes over time (a new default file, a changed doctrine-header format) — he has to manually
   track upstream `mesa init` changes and decide whether to backport them into his template, a
   maintenance relationship the tool doesn't help him manage at all, since there's no "diff my
   customized init against the current default init" tooling.
4. **What he'd want:** a documented, stable "what does `mesa init` scaffold, exactly, and how does
   it change between versions" changelog specifically for people who've forked/customized the
   init output, distinct from the general project changelog aimed at CLI users.

---

## PERSONA 5 — Delphine Girard, Data Steward at a French research institute (public sector, not corporate)
**Background:** works at a publicly funded research institute, manages sensitive research
participant data, operates under different institutional pressures than any corporate persona in
any prior doc — grant compliance and academic data-sharing agreements, not SOX/GDPR-as-commercial-
risk.

### Step-by-step
1. **How she found mesa-core:** a data engineering colleague at another research institute
   mentioned it at an academic conference — the OSS/free/local-only nature is specifically what
   made it viable for her institution, since procurement for a commercial SaaS tool at a public
   research institute can take the better part of a year and require a grant-specific budget line
   that doesn't exist.
2. **What she specifically needs it to prove:** that participant-identifying source IDs, once
   hashed into the Raw Layer's `ID` column, are genuinely NOT reversible without the original
   `source_system`+`source_id` pair — she reads the hashing formula in the Rulebook line by line
   with a cryptography-literate colleague to independently verify the one-way property before
   she'll certify the modeled data as suitable for a lower-sensitivity data-sharing tier.
3. **What she does that's unusual:** treats the "no calculations in the Raw Layer" rule as a
   RESEARCH INTEGRITY concern, not just an architectural one — for her, keeping identity totally
   separate from any derived/interpreted value is directly analogous to pre-registering a study's
   raw measurements before any analysis touches them, and she explains the tool to her own
   institutional review board using that analogy rather than the tool's own "materials list" one.
4. **What she'd want:** documentation or a worked example specifically addressing research-data/
   PII-adjacent use cases (the existing examples are all commercial: Customer, Order, Policy) —
   she has to translate every example mentally into a research-participant context herself.

---

## PERSONA 6 — Kwabena Osei, Data Engineer Discovering mesa-core WAS ALREADY silently adopted by a predecessor
**Background:** joined a company 2 months ago; discovered mid-onboarding that a previous
engineer (long departed, unreachable) had quietly adopted mesa-core for a subset of the warehouse
before leaving, with zero documentation of WHY or how it fits into the rest of the stack.

### Step-by-step
1. **First contact:** not `mesa init` — stumbling across a `models/raw_layer/` folder structure
   and doctrine-header comments in existing SQL files that don't match anything else in the
   company's warehouse, with no README explaining what's going on, no Slack history (predecessor
   used a personal account, now deactivated), no onboarding doc mentioning it at all.
2. **What he does to reverse-engineer the situation:** installs mesa-core himself, runs
   `mesa validate` against the mystery folder, and the tool's own PASSING validation (it's
   correctly structured!) is his first real evidence that this wasn't abandoned mid-thought — it's
   a genuinely completed, compliant piece of work that simply never got documented or socialized
   to the rest of the team.
3. **What he does next:** runs `mesa evaluate` for the health scorecard, treats a good grade as
   further confirmation this is worth preserving and extending rather than ripping out, and starts
   quietly writing the missing onboarding doc himself so the NEXT new hire doesn't have this exact
   disorienting experience.
4. **What this persona demonstrates, structurally:** the tool's own validation output functions as
   a form of ARCHAEOLOGICAL evidence about a predecessor's intent, independent of any human
   documentation — a use case the tool wasn't designed for but which its hard-gate design makes
   possible: "if it passes validate, someone finished this correctly, even if they never told
   anyone."

---

## PERSONA 7 — Winnie Chikodi, QA/Test Engineer writing tests AGAINST mesa-compiled output
**Background:** dedicated QA engineer (not a data engineer) assigned to write data-quality tests
against the warehouse tables mesa-core compiles, treating them the same way she'd test any other
software artifact.

### Step-by-step
1. **First thing she does:** does not touch `mesa` commands herself at all initially — asks the
   data engineering team for the `target/` compiled SQL and the doctrine headers' stated grain
   claims (`-- Grain: one row per policy`), and writes independent tests (row-count uniqueness
   checks, null checks on the ID column) that DUPLICATE what the Rulebook says `mesa validate`
   already enforces — she doesn't yet trust that the tool's internal claim of "grain is proven by
   unique+not_null tests" is actually wired up correctly in HER company's specific setup, so she
   verifies independently rather than taking the doctrine header's claim on faith.
2. **What she discovers:** the tool's enforcement is in fact solid — her independent tests never
   catch a violation `mesa validate` missed — and after a few sprints of parallel verification she
   scales back her own duplicate test suite, keeping only tests for things OUTSIDE MESA's scope
   entirely (data freshness/staleness, volume anomalies), explicitly trusting the compiler for
   structural correctness going forward.
3. **What she'd want:** a documented "here's exactly what `mesa validate` guarantees and here's
   what it explicitly does NOT guarantee (freshness, volume, distributional correctness)" scope
   statement — so a QA engineer coming in cold doesn't have to spend several sprints empirically
   rediscovering the boundary the way she did.

---

## PERSONA 8 — Rahim Chowdhury, Freelance Course Creator building a paid Udemy-style course
**Background:** creates and sells online courses on data engineering topics, considering a course
specifically on "the MESA architecture with mesa-core" as a paid offering, distinct from Chen
Wei's free university-instructor use in the first doc.

### Step-by-step
1. **First thing he checks, commercially:** whether the MIT license and trademark notice
   (`MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC`, per the CLI file header) permit
   him to build and SELL paid educational content using the tool and its name — code license and
   trademark usage are different questions, and he specifically researches both before investing
   production time in a course, unlike Chen Wei's free/internal use which never raised the
   question.
2. **What he decides:** the code itself (MIT) is clearly fine to teach from and demonstrate; using
   "MESA" prominently in his course TITLE/marketing as if it were his own brand is the part he's
   cautious about, and he resolves it by framing the course as "Data Modeling with mesa-core (an
   open-source tool)" rather than implying any official partnership or endorsement.
3. **What he builds that goes beyond Chen Wei's use case:** a structured, paid curriculum with
   graded exercises and a private Discord for paying students — commercializing the SAME quickstart
   project Chen Wei uses for free, which is entirely legitimate under the license but means the
   project's own free `quickstart/` becomes raw material for a commercial product he doesn't share
   revenue from and has no relationship with the maintainers about.
4. **What this reveals structurally:** an MIT-licensed project with genuinely good pedagogy baked
   into its docs (the Rulebook's analogies, the guided `mesa learn` tutorial) creates real
   secondary-market value that the maintainers neither capture nor necessarily even know is
   happening — a predictable but easy-to-overlook consequence of the license choice.

---

## PERSONA 9 — Ingrid Kowalczyk, Accessibility Consultant auditing the CLI's usability
**Background:** specializes in accessibility auditing, was brought in by an ADOPTING COMPANY
(not by the mesa-core project itself) to audit whether the company's internal tooling, including
CLI tools like mesa-core that engineers use daily, meets the company's own internal accessibility
standards for engineers using screen readers or other assistive tech.

### Step-by-step
1. **First thing she checks:** whether `mesa`'s CLI output (colored text via `click.style`, per
   the CLI source) degrades gracefully for a screen reader or in a non-color terminal — colored
   warning/error text (`fg="yellow"`) needs a plain-text equivalent that conveys the same meaning
   without relying on color alone, a standard accessibility requirement she checks against every
   CLI tool she's asked to review, not something specific to data tooling.
2. **What she finds:** the CLI's actual TEXT content (the word "Warnings," explicit rule-code
   pointers) carries the meaning independently of color in most cases she tests, which is a pass —
   but she flags that she can't fully verify large/complex `mesa evaluate` scorecard output
   (which may rely more heavily on visual table/grid layout to convey grade groupings) without a
   deeper structural review of that specific command's output formatting.
3. **What she recommends to the adopting company, not to the mesa-core project directly:** flag
   the `evaluate` scorecard output as a follow-up review item, and in the meantime, use
   `mesa evaluate --json` (which already exists) as the accessible-tooling-friendly path for any
   engineer who needs a screen-reader-compatible or programmatically-consumable version instead of
   the human-formatted table.
4. **What this persona reveals:** the `--json` flag that Grzegorz (second doc) wanted purely for
   CI-pipeline ergonomics turns out to ALSO be the accessibility answer for a completely different
   persona — a single design decision (structured machine-readable output) serving two unrelated
   needs nobody originally designed it for together.

---

## PERSONA 10 — A Future Version of mesa-core Itself, Compiling ITS OWN Example Fixtures (a meta-persona)
**Background:** not a person or even a bot acting on behalf of a person — the project's own test
suite and `quickstart/`/fixture files, which are themselves subject to `mesa validate`/`build` on
every CI run of the mesa-core PROJECT (not a downstream adopter's project) — included because
"does the tool's own example content stay compliant with the tool's own evolving rules" is a real,
distinct maintenance surface.

### What this reveals, structurally
1. Every time a maintainer tightens or adds a rule to `mesa validate` or `mesa evaluate`, the
   project's OWN `quickstart/` and test fixtures have to still pass (or be deliberately updated) —
   the project is, in effect, its own most demanding long-term user, dogfooding every rule change
   against real example content before any external adopter ever sees the new version.
2. **What this implies for release discipline:** a rule change that breaks the project's own
   quickstart is caught immediately, in-house, before release — but a rule change that's
   TECHNICALLY compatible with the quickstart while still being a meaningful behavior change for
   external adopters (exactly the Dependabot persona's concern in the third doc) would sail
   through this internal check without anyone noticing the external-facing impact, since the
   quickstart is necessarily a small, curated example and can't represent every real-world
   pattern an adopter might have.
3. **Why this belongs in a persona doc at all:** it's a useful discipline to explicitly name "our
   own examples passing" as INSUFFICIENT evidence that a release is safe for the Dependabot-style
   auto-merge personas out in the world — the fixture suite proves internal consistency, not
   external non-breaking-ness, and conflating the two is an easy mistake for a small maintainer
   team to make under release-day time pressure.

---

## Cross-Persona Pattern Summary (V4)

| Persona | Entry point | Human/bot/meta | Unique mechanic surfaced |
|---|---|---|---|
| Ana Beatriz (three live dialects) | `mesa build` re-run per warehouse flag | Self-serve | Wants multi-target build-in-one-invocation; orchestration, not correctness, is her risk |
| Tobias Reinholt (retiring his own internal tool) | Feature-by-feature weekend comparison | Self-serve, emotionally loaded | Real competition is often a tired internal script, not a commercial rival |
| Priya Subramaniam (localizing docs) | Translates Rulebook concepts internally | Self-serve, community-adjacent | Wordplay-heavy analogies resist literal translation; no upstream i18n home exists |
| Marcus Aurelius Silva (golden template) | Customizes `mesa init` once, forks forever | Self-serve, becomes a silent gatekeeper | No "diff my customized init against upstream" tooling exists |
| Delphine Girard (research institute) | Verifies hash one-wayness by hand | Self-serve, mission-driven | Treats Raw Layer purity as research-integrity, not just architecture |
| Kwabena Osei (inherited mystery folder) | `mesa validate` as archaeological evidence | Self-serve, forensic | Passing validation proves prior intent even with zero documentation |
| Winnie Chikodi (QA engineer) | Duplicates validate's checks independently at first | Self-serve, initially distrustful | Wants an explicit "what validate does/doesn't guarantee" scope statement |
| Rahim Chowdhury (paid course creator) | Builds commercial content from free docs | Self-serve, commercial secondary market | MIT license + trademark are separate questions; pedagogy becomes uncaptured value |
| Ingrid Kowalczyk (accessibility auditor) | Checks color-reliant CLI output | Self-serve, compliance-adjacent | `--json` flag doubles as an accessibility answer nobody designed for that purpose |
| Future mesa-core (meta, its own fixtures) | CI running validate against its own quickstart | Meta/self-referential | Internal example-passing is insufficient evidence of external non-breaking-ness |

## New concrete product/process gaps surfaced in this pass
1. **Multi-target build in one invocation** (`--warehouse A,B,C` or config-driven), for
   organizations running multiple live dialects simultaneously, not sequentially (Ana Beatriz).
2. **A documented, versioned diff of what `mesa init` scaffolds**, for teams who fork/customize
   the init output into their own internal templates (Marcus Aurelius Silva).
3. **Research-data/PII-adjacent worked examples**, distinct from the existing commercial-only
   example set (Customer/Order/Policy), for public-sector and academic adopters (Delphine).
4. **An explicit "what `validate` guarantees vs. does not guarantee" scope statement**
   (structural correctness vs. freshness/volume/distributional correctness), so QA-adjacent roles
   don't have to empirically rediscover the boundary (Winnie).
5. **A community-contributed translation home** for the Rulebook's core concepts, distinct from
   the CLI/commands themselves, which should stay English for maintenance-sync reasons (Priya).
6. **Explicit trademark-usage guidance for commercial secondary content** (paid courses, content
   built on the free docs/tutorial), separate from the MIT code license (Rahim).
7. **A release-discipline principle distinguishing "internal fixtures still pass" from "external
   adopters won't experience a breaking change"** — connects directly to the versioning-philosophy
   gap already raised by the Dependabot persona in the third doc (meta-persona).
