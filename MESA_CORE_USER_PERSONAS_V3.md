# mesa-core — User Personas V3 (Third Fresh Set)
**Date: 2026-09-21**
**Companion to:** `MESA_CORE_USER_PERSONAS.md` and `MESA_CORE_USER_PERSONAS_V2.md`. Same
grounding rules — local CLI, MIT license, validate-is-a-gate/evaluate-is-advisory split. Ten
more distinct people/roles.

---

## PERSONA 1 — Wei Lin, Data Engineer at a company that already has a COMPETING internal standard
**Background:** 7 yrs, works at a mid-size logistics company that already has its own internal
"golden rules" doc for warehouse modeling — hand-maintained, partially enforced by a single
senior engineer's manual PR reviews.

### Step-by-step
1. **First command:** `mesa init` in a scratch directory, deliberately NOT the real company repo
   — he's testing whether mesa-core's rules are compatible with or contradictory to the existing
   internal standard before proposing anything to his team.
2. **What he specifically compares:** his company's internal doc requires a `created_at`/`updated_at`
   pair on every table (an operational concern) while MESA's Rulebook is entirely about identity/
   grain/tier separation (a semantic concern) — he realizes the two aren't actually competing, they
   overlap only partially, and mesa-core could ENFORCE the semantic half automatically while the
   internal doc's operational conventions still need the human reviewer.
3. **What convinces the senior reviewer (not modeled as a full persona, but the real blocker):**
   showing that `mesa validate`'s hard-gate failures are things the internal doc ALSO calls
   violations today, just caught two weeks later in code review instead of instantly on save — the
   pitch isn't "replace your standard," it's "automate the half of your standard that's mechanical."
4. **What doesn't fully resolve:** the company's naming conventions for the operational columns
   MESA doesn't govern at all — they keep their own doc for that half permanently, confirming
   mesa-core's scope is deliberately narrower than a full "warehouse style guide" replacement.

---

## PERSONA 2 — Fatoumata Diallo, Data Engineering Bootcamp Student
**Background:** 3 months into a career-change bootcamp, has written maybe 200 SQL queries total,
assigned mesa-core as part of a "modern data stack tools" module.

### Step-by-step
1. **First command:** `mesa init` — but she runs it AFTER `pip install mesa-core` fails silently
   once because her Python version was too old, and the actual error message (not a MESA-specific
   problem, a generic pip/Python-version incompatibility) is the first thing she has to debug,
   with zero context for what's happening — a pre-product-experience friction point that isn't
   mesa-core's fault but is still the FIRST thing that happens to her.
2. **Second attempt, successful:** works through the `quickstart/` two-entity project exactly as
   documented, typing each command manually rather than copy-pasting, specifically because her
   bootcamp instructor told the cohort "type it, don't paste it, so it sticks."
3. **What genuinely surprises her:** she expected "build a data pipeline" to mean writing a lot of
   SQL by hand — instead, most of her time is spent thinking about WHICH tier a piece of logic
   belongs in, not how to write the SQL itself; the tool front-loads a design decision she wasn't
   expecting to be the hard part.
4. **What she does when stuck:** posts in her bootcamp's private Discord, NOT a mesa-core GitHub
   issue — she doesn't yet have the confidence that her question is a "real" question worth a
   public maintainer's time, a very different threshold than Kenji (the professional contributor)
   in the second doc.
5. **What she'd want:** more worked examples at DIFFERENT difficulty levels than the single
   Customer+Order quickstart — she finished it successfully but still doesn't feel confident
   applying the same pattern to a genuinely novel entity she invents herself for her capstone.

---

## PERSONA 3 — Esteban Ruiz, Staff Engineer doing an internal "build vs. adopt" bake-off
**Background:** senior IC at a company debating whether to build a lightweight internal semantic
compiler themselves (a few weeks of internal effort) vs. adopting mesa-core wholesale.

### Step-by-step
1. **First thing he does:** reads through `mesa_core/compiler/`, `mesa_core/validate/`, and
   `mesa_core/evaluate/` end to end, estimating how many weeks of internal engineering time the
   equivalent functionality would cost to build from scratch — a very literal "buy vs. build" cost
   comparison, treating the codebase itself as the pitch deck.
2. **What tips his recommendation toward "adopt":** the WIDE-LAYER auto-generation logic
   specifically — the STRUCT-assembly mechanics for multiple warehouse dialects (Snowflake's
   `OBJECT_CONSTRUCT_KEEP_NULL` colon-access quirks vs. BigQuery's native `STRUCT`/`UNNEST`) are
   exactly the kind of "boring but easy to get subtly wrong" code his team would have under-
   invested in if building internally, and getting it wrong silently produces bad SQL rather than
   an obvious crash — the highest-leverage place to NOT reinvent the wheel.
3. **What he flags as a real risk in his bake-off memo regardless:** dependency risk on a single
   external OSS project for something that will sit at the CORE of the company's warehouse design
   — he explicitly recommends vendoring a pinned version rather than always tracking the latest
   release, treating it with the same caution Hassan's bank committee (V2) applied, just from an
   engineering angle instead of a compliance one.
4. **What he does NOT flag as a risk:** the four-tier architecture ITSELF being wrong for their
   use case — he independently arrives at the same "identity vs. interpretation" framing the
   Rulebook uses, which he takes as a strong signal the architecture is sound rather than an
   opinionated house style he'd be fighting against long-term.

---

## PERSONA 4 — Naledi Khumalo, Data Team Lead migrating FROM a competing semantic layer tool
**Background:** her team already uses a dbt-native metrics/semantic-layer setup (MetricFlow-
style) and is evaluating migrating the underlying modeling discipline to mesa-core specifically
for the stronger identity/grain enforcement, while keeping their existing BI layer on top.

### Step-by-step
1. **First thing she checks:** whether mesa-core's compiled output can sit BENEATH her existing
   semantic layer rather than replacing it wholesale — she doesn't want to rip out her BI tool's
   integration, she wants a more disciplined Raw/Metric foundation under it.
2. **What she discovers, reading the README's "why it matters" section:** mesa-core's stated
   philosophy ("most semantic layers start at meaning and assume identity was already solved") is
   almost a direct description of her CURRENT tool's blind spot — her team's metric definitions
   are solid, but nobody ever formally declared what a `Customer` IS before building metrics on
   top of whatever table had an ID column, exactly the gap the tool describes.
3. **What her actual migration looks like:** NOT a big-bang cutover — she runs `mesa new entity`
   for her most-argued-about business objects first (the ones her team has quietly redefined
   multiple times), treats those as a pilot, and leaves everything else in the existing tool
   untouched until the pilot proves out.
4. **What she'd want that doesn't exist:** an explicit "how mesa-core's Raw Layer maps onto a
   dbt/MetricFlow staging+semantic-model setup" migration guide — she has to work out the mapping
   herself by reading both tools' docs side by side, since mesa-core's docs don't address
   coexistence with a specific competing tool by name.

---

## PERSONA 5 — Petra Nováková, Independent Auditor-for-Hire, brought in specifically to review MESA compliance
**Background:** hired BY a company (not adversarially, unlike Grace in the Mesantic set) that
already adopted mesa-core internally, specifically to confirm their entities actually conform to
the Rulebook before a big customer contract requires proof of "governed data architecture."

### Step-by-step
1. **First thing she does:** runs `mesa validate` and `mesa evaluate --json` herself, fresh, on
   the client's actual repo — she doesn't trust the client's own internal claim that "we pass,"
   she reruns the tooling independently as her very first action, the same instinct Consuela (the
   internal auditor, Mesantic V4) has, but applied to a compiler's output instead of a SaaS audit
   log.
2. **What she specifically checks beyond the automated output:** whether `--strict` was ever
   actually turned on in CI, or whether the client is only running `evaluate` informationally and
   citing a good-looking but never-enforced scorecard as if it were a hard requirement — she treats
   the CLI's own strict/advisory distinction as the exact seam where a company could overstate its
   compliance without lying outright.
3. **What she produces:** a short attestation letter distinguishing "validated" (hard-gated,
   provably true) from "evaluated" (advisory, self-reported unless independently rerun) — she's
   effectively formalizing the tool's own internal split into an external-facing compliance
   vocabulary, since the tool itself doesn't produce anything client-facing like this.
4. **What she'd want that doesn't exist:** a signed/timestamped attestation output format from
   `mesa validate`/`evaluate` itself (something like a checksum + timestamp she could reference in
   her letter rather than re-running the tool and trusting her own local execution as the source of
   truth) — the closest analog to the Mesantic SaaS product's cryptographic audit chain, but
   nothing like it exists in the local-only CLI world, understandably, since there's no server to
   anchor a chain to.

---

## PERSONA 6 — Youssef Haddad, Engineering Manager deciding whether to require mesa-core team-wide
**Background:** manages 5 data engineers, doesn't write much SQL himself day-to-day anymore, has
to make a people-and-process decision, not a technical one.

### Step-by-step
1. **First thing he does:** NOT touch the CLI at all initially — asks his most senior engineer
   (a Femi-shaped persona from the first doc) to run a two-week trial and report back, delegating
   the technical evaluation entirely, which is itself the correct move for his role.
2. **What he personally cares about, once the trial report comes back:** not whether the
   architecture is "correct" in the abstract — whether requiring it team-wide will slow down his
   team's velocity in the next sprint, since he's measured on delivery, not architecture purity.
3. **What tips his decision:** the trial report's finding that `mesa validate` failures were,
   without exception, things that WOULD have caused a production bug eventually — he reframes the
   adoption decision internally from "extra process" to "catching bugs earlier, for free," which
   is an easier sell to his own skip-level than "better architecture" would have been.
4. **What he does NOT require initially:** `mesa evaluate --strict`. He greenlights the hard gate
   (`validate`) team-wide immediately but treats the advisory grading as a "let's revisit in a
   quarter once we have a baseline" — mirroring Sofia's phased-rollout recommendation (first doc)
   independently, without having read her RFC, suggesting it's a natural adoption pattern rather
   than something that has to be taught.

---

## PERSONA 7 — Zanele Mokoena, Open-Source Sponsor / Funder evaluating a sponsorship request
**Background:** works at a company that sponsors OSS infrastructure projects as part of its
engineering-brand strategy; mesa-core was nominated internally as a sponsorship candidate.

### Step-by-step
1. **First thing she checks:** NOT the code at all — the project's `LICENSE`, whether it's a
   single-maintainer or foundation-backed effort, and whether the maintainer has a sponsorship/
   funding page linked from the README — she's evaluating the PROJECT'S SUSTAINABILITY, not its
   technical merits, which she assumes her nominating engineer already vetted.
2. **What she specifically weighs:** whether sponsoring mesa-core (a component of a company's
   broader Mesantic product) blurs the line between "sponsoring open infrastructure" and
   "subsidizing a company's commercial funnel" — open-core projects always raise this exact
   question for a sponsorship committee, and she has to write up a clear position on it either way.
3. **What she'd want that doesn't exist:** a clear, written statement (not just implied by the
   MIT license) of what's permanently free vs. what's a deliberate on-ramp to the paid Mesantic
   product — the boundary is inferable from reading both projects' docs side by side, but isn't
   stated as an explicit governance/sponsorship-facing policy anywhere.
4. **Her eventual recommendation:** approves a small sponsorship specifically earmarked for
   "core compiler and validation logic maintenance," explicitly NOT for anything that reads as
   funding the commercial product's funnel — a nuanced position that required more digging than
   she expected going in.

---

## PERSONA 8 — Rurik Ivanov, Data Engineer at a company with STRICT no-outbound-network security policy
**Background:** works in a security-locked-down environment (defense-adjacent industry) where
literally any tool that phones home, even for version checks, requires a formal security exception.

### Step-by-step
1. **First thing he does, before even installing:** greps the entire `mesa_core/` source for any
   `requests`/`httpx`/socket usage — confirms (per the CLI docstring's own explicit claim, "It does
   NOT call a running server... No httpx, no fastapi, no DB") that there's genuinely zero outbound
   network capability in the tool, and personally verifies this rather than trusting the docs,
   since his job function requires exactly that level of paranoia.
2. **What this unlocks:** he can install and use it WITHOUT a security exception ticket at all,
   because it satisfies his environment's policy by construction rather than by configuration —
   this is the single reason mesa-core is usable in his environment at all when almost every SaaS
   product, including Mesantic itself, would require a lengthy exception process or be outright
   rejected.
3. **What he does with it, once cleared:** models his entities entirely offline, air-gapped, using
   a local DuckDB extract that itself was manually reviewed and cleared before being allowed onto
   his development machine — every step of his workflow assumes zero trust in outbound connectivity
   at any layer, not just mesa-core's.
4. **What he'd flag if it ever changed:** any future version that added even an opt-in telemetry
   ping or update-checker would immediately disqualify the tool from his environment without a
   fresh security review — a standing constraint worth the maintainers knowing about explicitly,
   since "add anonymous usage telemetry" is a common ask from OTHER users (see Persona 10 below)
   that would directly conflict with this persona's hard requirement.

---

## PERSONA 9 — Chiara Rossi, Product Analyst trying to use mesa-core output for her OWN reporting
**Background:** not a data engineer — a product analyst who was handed a MESA-compiled `target/`
SQL file by an engineer and told "query this View Layer table for your report," her first-ever
direct contact with anything MESA-related.

### Step-by-step
1. **What she actually does:** never touches the CLI. Opens the compiled View Layer SQL file in a
   text editor purely out of curiosity about what "governed" data actually looks like under the
   hood, understands maybe 30% of it, and just runs a `SELECT` against the resulting table in her
   BI tool like any other table — same posture as Whitney/Chidi's downstream-consumer role in the
   Mesantic set, but one step further upstream, at the compiler's own output rather than a hosted
   product's view.
2. **What she notices, that an engineer wouldn't think to mention:** the View Layer table's column
   names are noticeably cleaner and more consistent than every other table she's used at the
   company — she doesn't know WHY (she's never heard of PascalCase-aliasing-for-BI-tools as a
   deliberate rule), she just experiences it as "this one's easier to work with," which is the
   Rulebook's View Layer design goal succeeding completely invisibly, exactly as intended.
3. **What would break her workflow, hypothetically:** if the compiled output ever silently
   reshuffled column names between versions with no changelog — she'd have no way to know why her
   existing saved reports broke, since she has no visibility into the source `.sql` files or the
   tool's versioning at all, only the output table she was handed.

---

## PERSONA 10 — Automated Dependabot / Renovate Bot, non-human, opening version-bump PRs
**Background:** not a person — a dependency-update bot running against every repo that lists
`mesa-core` in a `requirements.txt`/`pyproject.toml`, opening a PR every time a new version ships.

### What it actually does, every release
1. Opens a PR bumping the pinned version, runs whatever CI the adopting repo already has wired
   (per Grzegorz/Bilal's setups from earlier docs) against the NEW version, and reports pass/fail
   — this is the mechanism by which every human persona above eventually experiences a breaking
   change in `mesa validate`'s rule set, sight-unseen, unless someone actually reads the release
   notes.
2. **What matters to this "persona" that matters to no human:** whether the project follows
   semantic versioning STRICTLY enough that a bot-opened minor-version bump can be trusted to
   auto-merge without human review — if `mesa validate` ever tightens a rule (starts flagging
   something it didn't before) inside a PATCH release, every downstream CI pipeline that
   auto-merges bot PRs would suddenly start failing builds with no human having decided to opt in
   to the stricter behavior.
3. **What this implies for the maintainers, surfaced by treating a bot as a persona:** a rule
   tightening (making `validate` MORE strict about something previously allowed) is functionally
   a BREAKING change from this persona's perspective even if it "should" be a patch/minor bump by
   normal semver logic (nothing about the public API signature changed, only enforcement behavior)
   — a real, sharp-edged versioning-philosophy question the project has to answer explicitly, or
   this exact scenario will eventually happen to someone via an unattended bot merge.

---

## Cross-Persona Pattern Summary (V3)

| Persona | Entry point | Human-, bot-, or self-driven? | Unique mechanic surfaced |
|---|---|---|---|
| Wei Lin (competing internal standard) | Scratch-dir test before proposing | Self-serve, deliberately cautious | mesa-core's scope is narrower than a full style guide — coexists, doesn't replace |
| Fatoumata (bootcamp student) | `quickstart/`, typed not pasted | Self-serve, low-confidence | Wants more worked examples at varying difficulty, beyond one quickstart |
| Esteban (staff eng, build-vs-adopt) | Reads compiler source as a cost estimate | Self-serve, analytical | Wide-Layer STRUCT-assembly is the highest-leverage "don't reinvent this" case |
| Naledi (migrating from a competing tool) | Pilots on most-argued-about entities only | Self-serve, incremental | No migration guide for coexisting with dbt/MetricFlow-style tools |
| Petra (hired compliance auditor) | Reruns `validate`/`evaluate --json` independently | Self-serve, adversarial-but-friendly | Formalizes validate/evaluate split into an external attestation vocabulary |
| Youssef (eng manager, adoption decision) | Delegates trial to a senior IC | Human-mediated, delegated | Reframes adoption as "catch bugs earlier" not "architecture purity" for his own sell-up |
| Zanele (OSS sponsor) | Checks license/sustainability, not code | Self-serve, non-technical evaluation | Wants an explicit free-vs-funnel boundary statement, not just an inferred one |
| Rurik (air-gapped security env) | Greps source for network calls himself | Self-serve, maximally paranoid | Zero-network-calls is a hard requirement, not a preference — telemetry would disqualify the tool |
| Chiara (downstream analyst) | Handed compiled View Layer SQL, never CLI | Human-mediated, fully passive | Experiences the View Layer's design goal succeeding without ever knowing the rule exists |
| Dependabot (non-human) | Opens version-bump PRs every release | Bot-driven | Rule-tightening is a breaking change to this persona even under correct semver |

## New concrete product/process gaps surfaced in this pass
1. **More worked examples at varying difficulty**, beyond the single Customer+Order quickstart,
   for learners without a mental model to extend it themselves (Fatoumata).
2. **Explicit coexistence/migration guide** for teams running a dbt/MetricFlow-style semantic
   layer on top of mesa-core's Raw/Metric foundation (Naledi).
3. **Signed/timestamped attestation output** from `validate`/`evaluate`, distinct from re-running
   the tool and trusting local execution as the source of truth — the local-CLI analog of an
   audit chain (Petra).
4. **An explicit, written free-vs.-funnel boundary statement** for the open-core model, for
   sponsorship/governance evaluators who need it stated rather than inferred (Zanele).
5. **A hard, published no-telemetry/no-network commitment**, since even an opt-in future addition
   would disqualify the tool for air-gapped/high-security environments (Rurik).
6. **A versioning philosophy for rule-tightening changes** — clarity on whether a `validate` rule
   becoming MORE strict is treated as a breaking change regardless of semver bump size, given
   fully automated dependency-bump merge flows (Dependabot persona).
