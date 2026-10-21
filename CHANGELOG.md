# Changelog

All notable changes to mesa-core are recorded here. Newest first.

## Unreleased

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
it. It's a nudge, not a block. Annotations from your docs-completeness check no
longer leak into a metric's description prose, so a file whose only "description"
was `-- WIDE_TYPE: FLOAT` no longer passes as documented.

Nothing else changed. A project with no annotations anywhere compiles to the same
combiner SQL it did before — the only new output is the warnings.
