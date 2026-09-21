# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
checks.py — the ``mesa evaluate`` check suite (SPEC_71 Slice 2-4).

Every check is a ``Callable[[Project], list[CheckResult]]`` registered in
``CHECKS``. The evaluator is an AGGREGATOR + SCORER: each check reuses existing
validation logic (mesa_verifier, core_rules, grain_guard, security_rules, and
the ref graph already implied by ``load_project``). Do not rebuild a detector a
validator already provides.

Scorecard shape: one grade per RAW ENTITY (not per metric) + one project grade.
Metric-governance checks roll their per-metric findings UP into a single line
per entity ("18/20 metrics owned"), so the mirror reads entity-by-entity.

Free/paid line: Core grades on the definitions ALONE. Any check needing a live
warehouse or cross-source suggestion is a Mesantic follow-up — in Core it shows
an ``n_a`` placeholder (e.g. the fanout-signal line), never a fabricated grade.

Severity discipline (advisory, not a gate):
  fail = a real defect (broken ref, orphaned metric, unhashed identity, secret).
  warn = a nudge (thin entity, missing owner, bare CAST, unused source).
  n_a  = not applicable (fanout needs a warehouse; no metrics to govern).
"""

from __future__ import annotations

import re
from typing import Callable

from mesa_core.evaluate.framework import CheckResult
from mesa_core.project import Project


# ── Shared helpers ───────────────────────────────────────────────────────────

def _pass(check_id: str, entity: str | None, message: str, weight: float = 1.0) -> CheckResult:
    return CheckResult(check_id=check_id, entity_name=entity, status="pass",
                       weight=weight, message=message)


def _warn(check_id: str, entity: str | None, message: str, why: str, ref: str,
          weight: float = 1.0) -> CheckResult:
    return CheckResult(check_id=check_id, entity_name=entity, status="warn",
                       weight=weight, message=message, why=why, ref=ref)


def _fail(check_id: str, entity: str | None, message: str, why: str, ref: str,
          weight: float = 1.0) -> CheckResult:
    return CheckResult(check_id=check_id, entity_name=entity, status="fail",
                       weight=weight, message=message, why=why, ref=ref)


def _n_a(check_id: str, entity: str | None, message: str, weight: float = 1.0) -> CheckResult:
    return CheckResult(check_id=check_id, entity_name=entity, status="n_a",
                       weight=weight, message=message)


_REF_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.IGNORECASE)
_SOURCE_RE = re.compile(
    r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
    re.IGNORECASE,
)
_CONFIG_RE = re.compile(r"\{\{\s*config\s*\(.*?\)\s*\}\}", re.DOTALL)


def _all_refs(sql: str) -> list[str]:
    return [m.group(1) for m in _REF_RE.finditer(sql)]


def _all_source_names(sql: str) -> list[str]:
    return [m.group(1) for m in _SOURCE_RE.finditer(sql)]


def _strip_for_security(sql: str) -> str:
    """Strip comments and the Jinja ``{{ config(...) }}`` block (but KEEP
    ``{{ ref() }}``/``{{ source() }}``) so the SEC scanners see SQL, not prose.

    Without this, doctrine-header comments and config pre_hooks false-positive:
    ``-- need to map FFQ_QUOTE_ID or phone/email`` trips the divide-by-zero
    scanner on the ``/``, and ``pre_hook="... = 14400"`` trips the case-fold
    scanner. The SEC rules were written for bare SQL, so feed them bare SQL.
    """
    sql = _CONFIG_RE.sub("", sql)
    # Block comments.
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # Line comments (but not inside string literals — acceptable approximation:
    # MESA definitions carry no '--' inside literals by convention).
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def _known_ref_names(project: Project) -> set[str]:
    """Every ref() target that can resolve: <Entity>Raw, metric names, and
    <Entity>Wide / <Entity>WideTable."""
    names: set[str] = set()
    for e in project.entities:
        names.add(f"{e.entity_name}Raw")
        names.add(f"{e.entity_name}Wide")
        names.add(f"{e.entity_name}WideTable")
    for m in project.metrics:
        names.add(m.metric_name)
    for v in project.views:
        names.add(v.view_name)
    return names


def _metrics_for(project: Project, entity_name: str) -> list:
    return [m for m in project.metrics if m.entity_name == entity_name]


# ── Group 1 — Structure & DAG integrity (project-level) ──────────────────────

def check_broken_refs(project: Project) -> list[CheckResult]:
    """STRUCT-001 — every ref()/source() resolves to a real definition."""
    known = _known_ref_names(project)
    declared = set(project.sources.keys())
    results: list[CheckResult] = []

    broken_refs: list[str] = []
    broken_sources: list[str] = []
    seen_ref: set[str] = set()
    seen_src: set[str] = set()

    for e in project.entities:
        for ref in _all_refs(e.definition_sql or ""):
            if ref not in known and ref not in seen_ref:
                broken_refs.append(f"{ref} (in {e.entity_name}Raw.sql)")
                seen_ref.add(ref)
        for src in _all_source_names(e.definition_sql or ""):
            if src not in declared and src not in seen_src:
                broken_sources.append(f"{src} (in {e.entity_name}Raw.sql)")
                seen_src.add(src)
    for m in project.metrics:
        for ref in _all_refs(m.definition_sql or ""):
            if ref not in known and ref not in seen_ref:
                broken_refs.append(f"{ref} (in {m.metric_name}.sql)")
                seen_ref.add(ref)
        for src in _all_source_names(m.definition_sql or ""):
            if src not in declared and src not in seen_src:
                broken_sources.append(f"{src} (in {m.metric_name}.sql)")
                seen_src.add(src)
    for v in project.views:
        for ref in _all_refs(v.definition_sql or ""):
            if ref not in known and ref not in seen_ref:
                broken_refs.append(f"{ref} (in {v.view_name}.sql)")
                seen_ref.add(ref)

    if not broken_refs and not broken_sources:
        results.append(_pass("STRUCT-001", None,
                             "every ref() and source() resolves to a real definition"))
    if broken_refs:
        results.append(_fail(
            "STRUCT-001", None,
            f"{len(broken_refs)} broken ref(): {', '.join(broken_refs)}",
            "a ref() that points at nothing means the metric silently depends on "
            "a definition that doesn't exist — dbt parse catches this at build "
            "time, so you don't find out at deploy time.",
            "the same DAG check fires as a hard gate in `mesa validate`",
        ))
    if broken_sources:
        results.append(_fail(
            "STRUCT-001", None,
            f"{len(broken_sources)} undeclared source(): {', '.join(broken_sources)}",
            "a source() to an undeclared source leaves a hole in the lineage graph "
            "— no one can trace where that data actually came from.",
            "declare every source in sources/*.yml",
        ))
    return results


def check_orphaned_metrics(project: Project) -> list[CheckResult]:
    """STRUCT-002 — a metric whose entity doesn't exist / won't join."""
    entity_names = {e.entity_name for e in project.entities}
    results: list[CheckResult] = []
    orphans = [m.metric_name for m in project.metrics if m.entity_name not in entity_names]
    if not orphans:
        results.append(_pass("STRUCT-002", None, "no orphaned metrics"))
    else:
        results.append(_fail(
            "STRUCT-002", None,
            f"orphaned metric(s): {', '.join(orphans)}",
            "a metric whose entity doesn't exist can never be joined into a wide "
            "table — it's an island with no key back to its entity.",
            "create the entity, or move the metric into an entity that exists",
        ))
    return results


def check_tier_crossing(project: Project) -> list[CheckResult]:
    """STRUCT-003 — a view reading raw, a metric reading another entity's raw.

    Advisory (warn, not fail): MESA allows cross-entity reads through declared
    link STRUCTs, but a metric reaching another entity's raw directly is a
    signal the relationship wasn't declared at the Raw Layer first — worth
    surfacing, not worth blocking.
    """
    results: list[CheckResult] = []
    violations: list[str] = []

    for v in project.views:
        for ref in _all_refs(v.definition_sql or ""):
            if ref.endswith("Raw"):
                violations.append(f"view {v.view_name} reads {ref} (raw) directly")
    for m in project.metrics:
        for ref in _all_refs(m.definition_sql or ""):
            if ref.endswith("Raw"):
                base = ref[: -len("Raw")]
                if base != m.entity_name:
                    violations.append(
                        f"metric {m.metric_name} ({m.entity_name}) reads {ref}")
            elif ref.endswith("Wide") or ref.endswith("WideTable"):
                violations.append(f"metric {m.metric_name} reads {ref} (wide layer)")

    if not violations:
        results.append(_pass("STRUCT-003", None,
                             "no tier-crossing — views read wide, metrics read their own raw"))
    else:
        results.append(_warn(
            "STRUCT-003", None,
            f"{len(violations)} cross-entity raw read(s): {'; '.join(violations[:5])}",
            "a metric reading another entity's raw is usually a sign the "
            "relationship wasn't declared as a link STRUCT at the Raw Layer first "
            "— declare the link, then read through it.",
            "MESA Rulebook — 'The Four Tiers' and 'Link STRUCTs & Entity Isolation'",
        ))
    return results


def check_unused_sources(project: Project) -> list[CheckResult]:
    """STRUCT-004 — a declared source no entity/metric/view reads."""
    declared = set(project.sources.keys())
    results: list[CheckResult] = []
    if not declared:
        results.append(_n_a("STRUCT-004", None, "no sources declared"))
        return results

    used: set[str] = set()
    for e in project.entities:
        used.update(_all_source_names(e.definition_sql or ""))
    for m in project.metrics:
        used.update(_all_source_names(m.definition_sql or ""))
    for v in project.views:
        used.update(_all_source_names(v.definition_sql or ""))

    unused = sorted(declared - used)
    if not unused:
        results.append(_pass("STRUCT-004", None, "every declared source is read"))
    else:
        results.append(_warn(
            "STRUCT-004", None,
            f"unused source(s): {', '.join(unused)}",
            "a declared source nothing reads is a stale contract — it tells the "
            "next analyst a system feeds this domain when it actually doesn't.",
            "remove the source from sources/*.yml, or wire it into an entity",
        ))
    return results


# ── Group 2 — Identity & grain (static, per entity) ──────────────────────────

def check_identity_hashed(project: Project) -> list[CheckResult]:
    """IDENT-001 — identity is a hashed surrogate (reuse mesa_verifier)."""
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    results: list[CheckResult] = []
    for e in project.entities:
        result = verify_raw_contract(e.definition_sql or "", identity_column=e.identity_column)
        bad = {f.code for f in result.findings
               if f.code in ("MESA_RAW_ID_UNHASHED", "MESA_RAW_ID_PASSTHROUGH",
                             "MESA_RAW_ID_NON_CANONICAL")}
        if not bad:
            results.append(_pass("IDENT-001", e.entity_name,
                                 "identity is a canonical hashed surrogate (source_system baked in)"))
        else:
            results.append(_fail(
                "IDENT-001", e.entity_name,
                f"identity is not a canonical hashed surrogate ({sorted(bad)[0]})",
                "a bare source key as ID lets two different systems with the same "
                "integer id collide and silently merge two different entities — "
                "the hashed ID is what makes a fat-finger join impossible. And a "
                "non-canonical hash (MD5/SHA1) breaks cross-warehouse joins because "
                "the same entity hashes differently per port.",
                "hash the natural key with the canonical SHA256 → base64 formula: "
                "BASE64_ENCODE(SHA2(source_system || '-' || id, 256))",
            ))
    return results


def check_grain_declared(project: Project) -> list[CheckResult]:
    """IDENT-002 — the doctrine header states a grain."""
    results: list[CheckResult] = []
    for e in project.entities:
        if e.grain_description:
            results.append(_pass("IDENT-002", e.entity_name,
                                 f"grain declared: {e.grain_description}"))
        else:
            results.append(_warn(
                "IDENT-002", e.entity_name,
                "no -- Grain: line in the doctrine header",
                "if the grain isn't written down, 'one row = one policy' is a "
                "claim nobody can check — the grain line is the first thing a "
                "reviewer reads before trusting the identity rule.",
                "add `-- Grain: one row per <entity>` to the raw header",
            ))
    return results


def check_grain_guard_clean(project: Project) -> list[CheckResult]:
    """IDENT-003 — grain-guard clean (reuse mesa_verifier's grain-risk signal)."""
    from mesa_core.validate.mesa_verifier import verify_raw_contract

    results: list[CheckResult] = []
    for e in project.entities:
        result = verify_raw_contract(e.definition_sql or "", identity_column=e.identity_column)
        risks = [f for f in result.findings
                 if f.code in ("MESA_RAW_GRAIN_RISK", "MESA_RAW_HAS_AGGREGATE")]
        if not risks:
            results.append(_pass("IDENT-003", e.entity_name,
                                 "no grain-risk signal — no uncollapsed fan-out join"))
        else:
            results.append(_warn(
                "IDENT-003", e.entity_name,
                f"grain-risk signal: {'; '.join(sorted({r.code for r in risks}))}",
                "a join with no key equality (or a cross-row aggregate in the raw "
                "layer) can silently multiply rows and corrupt the entity's grain — "
                "one row per entity is the whole contract.",
                "collapse the join (aggregate or QUALIFY/ROW_NUMBER=1), or move the "
                "aggregate to the metric layer",
            ))
    return results


def check_fanout_signal(project: Project) -> list[CheckResult]:
    """IDENT-004 — fanout/join-cost signal. Core: n_a placeholder (needs a live
    warehouse; the real grade is Mesantic Slice 6)."""
    results: list[CheckResult] = []
    for e in project.entities:
        results.append(_n_a(
            "IDENT-004", e.entity_name,
            "connect a warehouse for cost analysis — the live join-cost grade "
            "is a Mesantic enrichment, not part of the free definitions-only path",
        ))
    return results


# ── Group 3 — Metric governance (rolled up per entity) ───────────────────────

def check_one_file_one_metric(project: Project) -> list[CheckResult]:
    """GOV-001 — one file = one metric (reuse CORE-004), rolled per entity."""
    from mesa_core.validate.core_rules import validate_metric_sql

    results: list[CheckResult] = []
    for e in project.entities:
        metrics = _metrics_for(project, e.entity_name)
        if not metrics:
            results.append(_n_a("GOV-001", e.entity_name, "no metrics to govern"))
            continue
        offenders = [
            m.metric_name for m in metrics
            if any(v.rule_code == "MESA-CORE-004"
                   for v in validate_metric_sql(m.definition_sql, m.entity_name, "ID"))
        ]
        if not offenders:
            results.append(_pass("GOV-001", e.entity_name,
                                 f"{len(metrics)} metric(s), all one-metric-per-file"))
        else:
            results.append(_fail(
                "GOV-001", e.entity_name,
                f"{len(offenders)} metric(s) bundle multiple outputs: {', '.join(offenders)}",
                "one file = one metric = one owner — bundling two metrics means "
                "'which metric changed' is ambiguous and git blame can't attribute it.",
                "split each metric into its own file",
            ))
    return results


def check_owner_declared(project: Project) -> list[CheckResult]:
    """GOV-002 — every metric's -- Owner: header is filled, rolled per entity."""
    results: list[CheckResult] = []
    for e in project.entities:
        metrics = _metrics_for(project, e.entity_name)
        if not metrics:
            results.append(_n_a("GOV-002", e.entity_name, "no metrics to govern"))
            continue
        unowned = [
            m.metric_name for m in metrics
            if not (m.owner or "").strip()
            or (m.owner or "").strip().upper() in ("TODO", "TBD", "NONE", "OWNER")
        ]
        if not unowned:
            results.append(_pass("GOV-002", e.entity_name,
                                 f"{len(metrics)} metric(s), all owned"))
        else:
            results.append(_warn(
                "GOV-002", e.entity_name,
                f"{len(unowned)}/{len(metrics)} metric(s) unowned: {', '.join(unowned[:5])}",
                "an unowned metric is a metric nobody answers for — ownership is "
                "what makes 'who changed this and why' answerable in review.",
                "fill in `-- Owner:` with a real team or person",
            ))
    return results


def check_contract_declared(project: Project) -> list[CheckResult]:
    """GOV-003 — every metric's -- Contract: header is present, per entity."""
    results: list[CheckResult] = []
    for e in project.entities:
        metrics = _metrics_for(project, e.entity_name)
        if not metrics:
            results.append(_n_a("GOV-003", e.entity_name, "no metrics to govern"))
            continue
        missing = [m.metric_name for m in metrics if not (m.contract or "").strip()]
        if not missing:
            results.append(_pass("GOV-003", e.entity_name,
                                 f"{len(metrics)} metric(s), all contracts declared"))
        else:
            results.append(_warn(
                "GOV-003", e.entity_name,
                f"{len(missing)}/{len(metrics)} metric(s) missing -- Contract:",
                "the contract states the grain the metric returns (1 row per ID) — "
                "without it, a downstream join can't trust the row count.",
                "add `-- Contract: 1 row per <entity> ID = 1:1`",
            ))
    return results


# MESA naming convention (from copilot-instructions): prefix/suffix table.
_NAMING_PREFIXES = (
    "Is", "Has", "NumberOf", "NumberOfDistinct", "AverageNumberOf",
    "Previous", "Next", "First", "Last",
)
_NAMING_SUFFIXES = (
    "Days", "Flag", "Score", "Rate", "Month", "Type", "Date", "Count",
    "Number", "Code", "Indicator", "Timestamp",
)


def check_naming_convention(project: Project) -> list[CheckResult]:
    """GOV-004 — metric name matches the MESA naming table, per entity."""
    results: list[CheckResult] = []
    for e in project.entities:
        metrics = _metrics_for(project, e.entity_name)
        if not metrics:
            results.append(_n_a("GOV-004", e.entity_name, "no metrics to govern"))
            continue
        nonconforming = [
            m.metric_name for m in metrics
            if not (m.metric_name.startswith(_NAMING_PREFIXES)
                    or m.metric_name.endswith(_NAMING_SUFFIXES))
        ]
        if not nonconforming:
            results.append(_pass("GOV-004", e.entity_name,
                                 f"{len(metrics)} metric(s), all names conform"))
        else:
            results.append(_warn(
                "GOV-004", e.entity_name,
                f"{len(nonconforming)}/{len(metrics)} name(s) off the table: {', '.join(nonconforming[:5])}",
                "the naming table (Is*/NumberOf*/*Date/Has*/unit-prefix) is a type "
                "signal — an analyst can tell a binary from a count from a date "
                "just by reading the name, without opening the SQL.",
                "MESA Rulebook — 'Metric Governance: Naming Conventions'",
            ))
    return results


def check_test_coverage(project: Project) -> list[CheckResult]:
    """GOV-005 — identity column has unique+not_null in the raw sidecar."""
    results: list[CheckResult] = []
    for e in project.entities:
        tests = {t.lower() for t in (e.identity_tests or ())}
        has_unique = "unique" in tests
        has_not_null = "not_null" in tests
        if has_unique and has_not_null:
            results.append(_pass("GOV-005", e.entity_name,
                                 "ID has unique + not_null tests declared"))
        else:
            missing = []
            if not has_unique:
                missing.append("unique")
            if not has_not_null:
                missing.append("not_null")
            results.append(_warn(
                "GOV-005", e.entity_name,
                f"ID missing {', '.join(missing)} test in _raw.yml",
                "that test is the empirical proof your grain is 1-per-entity — "
                "without it the grain contract is a claim nobody verified.",
                "add unique+not_null on ID in the raw sidecar (_raw.yml)",
            ))
    return results


# ── Group 4 — Enrichment & documentation (per entity) ────────────────────────

# A "thin" entity is below this many stable business attributes. The 30-80
# benchmark is the IDEAL (SPEC_64); Core only WARNS below the floor — it never
# fabricates cross-source suggestions (that's Mesantic Slice 6).
_ENRICHMENT_FLOOR = 12

# Universal system-ID container names (dialect/client-agnostic). A client's
# OWN declared source names (e.g. CAO's "rten"/"fdr") are added dynamically
# per-project in ``check_enrichment_depth`` — never hardcoded here. Hardcoding
# one client's source slugs into free Core is a portability bug: another
# client's SystemIds sub-keys wouldn't be excluded, and a legitimate business
# field literally named "Source" would get its following struct suppressed.
_SYSTEM_CONTAINER_NAMES = {"systemids", "systemid", "systemidentifiers", "sourcesystemids"}


def _match_paren(sql: str, open_idx: int) -> int:
    """Index of the ')' matching the '(' at ``open_idx``."""
    depth = 0
    for i in range(open_idx, len(sql)):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(sql)


_KEY_RE = re.compile(r"'([A-Za-z][A-Za-z0-9]*)'\s*,", re.IGNORECASE)
_CONSTRUCT_RE = re.compile(r"OBJECT_CONSTRUCT_KEEP_NULL\s*\(", re.IGNORECASE)


def _is_link_carrier_block(block: str) -> bool:
    """True if a struct block is a pure ID passthrough (the MESA hash-only
    link-carrier doctrine: ``OBJECT_CONSTRUCT_KEEP_NULL('ID', X.ID)``) — a
    relationship pointer, not a business attribute. Its own top-level keys
    (ignoring further nesting) must be exactly ``{id}``.
    """
    own_keys = {m.group(1).lower() for m in _KEY_RE.finditer(block)}
    return own_keys == {"id"}


def _collect_struct_keys(sql: str, open_idx: int, keys: set[str], in_system: bool,
                         system_names: set[str]) -> None:
    """Recursively collect business-attribute field keys from the
    OBJECT_CONSTRUCT_KEEP_NULL(...) block whose '(' is at ``open_idx``.

    Skips the 'ID' surrogate, any key inside a system-ID container (SystemIds
    or a project-declared source-system name), and any key whose value is a
    pure-ID link-carrier struct (a relationship pointer, not an attribute).

    ``in_system`` is FIXED for the whole call — it means "every key at this
    level is inside a system container and must be excluded." It is never
    reassigned mid-loop from a single sibling key's own name. (Reassigning it
    per-key was a bug in an earlier draft: a container's first child was
    correctly suppressed, but the flag then got clobbered before the NEXT
    sibling was checked, so later system keys — e.g. FdrPlcyNum after
    RtenPlcyCntrctNum inside SystemIds — leaked back into the count.)
    """
    end = _match_paren(sql, open_idx)
    j = open_idx + 1

    while j < end:
        km = _KEY_RE.match(sql[j:])
        if km:
            key = km.group(1)
            key_end = j + km.end()
            low = key.lower()
            key_is_container = low in system_names

            # Peek ahead (skipping whitespace) to see whether the value is a
            # nested OBJECT_CONSTRUCT_KEEP_NULL(...) — needed BEFORE deciding
            # whether to add the outer key, so a link-carrier's outer key
            # (e.g. "Policy" in ``'Policy', OBJECT_CONSTRUCT_KEEP_NULL('ID', ...)``)
            # can be excluded too, not just its contents.
            rest = sql[key_end:end]
            stripped = rest.lstrip()
            skipped = len(rest) - len(stripped)
            nested = _CONSTRUCT_RE.match(stripped)

            if nested:
                inner_open = key_end + skipped + nested.end() - 1
                inner_close = _match_paren(sql, inner_open)
                inner_block = sql[inner_open + 1:inner_close]
                if not in_system and not key_is_container and _is_link_carrier_block(inner_block):
                    # Pure ID passthrough — exclude the outer key entirely and
                    # don't recurse (there's nothing but ID inside).
                    j = inner_close + 1
                    continue
                if low != "id" and not in_system and not key_is_container:
                    keys.add(key)
                # The child recursion is told "in_system" if EITHER this level
                # was already inside a container OR this key itself names one
                # — but that only affects THIS key's own children, never the
                # siblings still to come at this same level.
                _collect_struct_keys(sql, inner_open, keys, in_system or key_is_container, system_names)
                j = inner_close + 1
                continue

            if low != "id" and not in_system and not key_is_container:
                keys.add(key)
            j = key_end
            continue

        nm = _CONSTRUCT_RE.match(sql[j:])
        if nm:
            inner_open = j + nm.end() - 1
            _collect_struct_keys(sql, inner_open, keys, in_system, system_names)
            j = _match_paren(sql, inner_open) + 1
            continue
        j += 1


def _split_top_level_items(select_block: str) -> list[str]:
    """Split a SELECT block into its depth-0 comma-separated output items."""
    items: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(select_block):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(select_block[start:i])
            start = i + 1
    items.append(select_block[start:])
    return items


_TRAILING_ALIAS_RE = re.compile(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", re.IGNORECASE)
_SINGLE_FIELD_STRUCT_RE = re.compile(r"^\s*STRUCT\s*\(\s*[\w.:]+\s*\)\s*$", re.IGNORECASE)
_ID_ONLY_CONSTRUCT_RE = re.compile(
    r"^\s*OBJECT_CONSTRUCT_KEEP_NULL\s*\(\s*'ID'\s*,\s*[\w.:]+\s*\)\s*$", re.IGNORECASE)


def _flat_top_level_field_keys(sql: str, identity_column: str, system_names: set[str]) -> set[str]:
    """Fallback enrichment count for entities with NO OBJECT_CONSTRUCT_KEEP_NULL
    struct anywhere (a flat SELECT, or a non-Snowflake struct idiom like
    BigQuery's bare ``STRUCT(...)``) — count top-level SELECT output aliases
    instead, per the Slice 4 spec ("top-level SELECT aliases minus ID/
    system-STRUCT/link-carriers"). Reuses the same depth-aware final-SELECT
    extraction the metric validator already uses (STOP RULE 2 — don't rebuild
    a parser a validator already has).
    """
    from mesa_core.validate.core_rules import _extract_final_select_block

    block = _extract_final_select_block(sql)
    if not block:
        return set()

    keys: set[str] = set()
    for item in _split_top_level_items(block):
        m = _TRAILING_ALIAS_RE.search(item)
        if not m:
            continue
        alias = m.group(1)
        expr = item[:m.start()].strip()
        low = alias.lower()
        if low == identity_column.lower() or low in system_names:
            continue
        if _SINGLE_FIELD_STRUCT_RE.match(expr) or _ID_ONLY_CONSTRUCT_RE.match(expr):
            continue  # a single-field/ID-only struct is a link carrier, not an attribute
        keys.add(alias)
    return keys


def _enrichment_field_keys(sql: str, identity_column: str = "ID",
                          declared_sources: frozenset[str] = frozenset()) -> set[str]:
    """Count stable business-attribute field keys on a raw entity.

    Two modes, chosen by what the SQL actually contains:

      * Struct mode (Snowflake's ``OBJECT_CONSTRUCT_KEEP_NULL`` doctrine, incl.
        nested 1:many detail in CTEs) — walk every struct's keys, excluding the
        ID surrogate, system-ID containers, and pure-ID link carriers.
      * Flat mode (no struct anywhere — a flat SELECT, BigQuery ``STRUCT()``,
        or any dialect this heuristic doesn't recognize) — count top-level
        SELECT output aliases instead, so a non-Snowflake or flat-shape entity
        is graded on its real column count instead of silently scoring zero.

    ``declared_sources`` are the project's own declared source names (e.g.
    CAO's "rten"/"fdr") — added to the system-container exclusion set so a
    nested container named after a connected source is recognized without
    hardcoding any one client's source slugs into free Core.
    """
    system_names = _SYSTEM_CONTAINER_NAMES | {s.lower() for s in declared_sources}

    if not re.search(r"OBJECT_CONSTRUCT_KEEP_NULL\s*\(", sql, re.IGNORECASE):
        return _flat_top_level_field_keys(sql, identity_column, system_names)

    keys: set[str] = set()
    spans: list[tuple[int, int]] = []
    for cm in re.finditer(r"OBJECT_CONSTRUCT_KEEP_NULL\s*\(", sql, re.IGNORECASE):
        open_idx = cm.end() - 1
        if any(s <= open_idx < e for s, e in spans):
            continue  # nested — handled by the outer construct's recursion
        end = _match_paren(sql, open_idx)
        spans.append((open_idx, end))
        _collect_struct_keys(sql, open_idx, keys, in_system=False, system_names=system_names)
    return keys


def check_enrichment_depth(project: Project) -> list[CheckResult]:
    """ENRICH-001 — count stable business attributes; warn below the floor."""
    results: list[CheckResult] = []
    declared_sources = frozenset(project.sources.keys())
    for e in project.entities:
        count = len(_enrichment_field_keys(
            e.definition_sql or "", identity_column=e.identity_column,
            declared_sources=declared_sources))
        if count >= _ENRICHMENT_FLOOR:
            results.append(_pass("ENRICH-001", e.entity_name,
                                 f"{count} enrichment fields (well-enriched)"))
        else:
            results.append(_warn(
                "ENRICH-001", e.entity_name,
                f"only {count} enrichment field(s) — thin entity",
                "a 4-column 'Customer' is a system concept wearing a business name, "
                "not a real entity — the richer the entity, the more questions it "
                "can answer without a cross-entity join.",
                "MESA Rulebook — 'Enrichment'",
            ))
    return results


def check_doctrine_header(project: Project) -> list[CheckResult]:
    """DOC-001 — doctrine header present + non-placeholder."""
    results: list[CheckResult] = []
    for e in project.entities:
        sql = e.definition_sql or ""
        has_entity = bool(re.search(r"^\s*--\s*RAW ENTITY\s*:", sql, re.IGNORECASE))
        placeholder = bool(re.search(r"<FILL\s+IN|<source>|<table>", sql, re.IGNORECASE))
        if has_entity and not placeholder:
            results.append(_pass("DOC-001", e.entity_name,
                                 "doctrine header present and filled in"))
        else:
            results.append(_warn(
                "DOC-001", e.entity_name,
                "doctrine header missing or still has <FILL IN> placeholders",
                "the header is the five-line contract (grain, ID formula, doctrine) "
                "a reviewer checks before the query — a placeholder header means "
                "the contract was never actually stated.",
                "complete the -- RAW ENTITY / -- Grain / -- ID / -- Doctrine block",
            ))
    return results


def check_metric_descriptions(project: Project) -> list[CheckResult]:
    """DOC-002 — metric descriptions non-empty, rolled per entity."""
    results: list[CheckResult] = []
    for e in project.entities:
        metrics = _metrics_for(project, e.entity_name)
        if not metrics:
            results.append(_n_a("DOC-002", e.entity_name, "no metrics to describe"))
            continue
        undescribed = [m.metric_name for m in metrics
                       if not (m.description or "").strip()]
        if not undescribed:
            results.append(_pass("DOC-002", e.entity_name,
                                 f"{len(metrics)} metric(s), all described"))
        else:
            results.append(_warn(
                "DOC-002", e.entity_name,
                f"{len(undescribed)}/{len(metrics)} metric(s) have no description",
                "a metric with no description is a number with no story — the next "
                "analyst can't tell what it means or whether it's the one they want.",
                "add a one-line description above -- Owner: in the metric header",
            ))
    return results


def check_sidecar_column_descriptions(project: Project) -> list[CheckResult]:
    """DOC-003 — sidecar column descriptions present (ID column described)."""
    results: list[CheckResult] = []
    for e in project.entities:
        if e.identity_description and e.identity_description.strip():
            results.append(_pass("DOC-003", e.entity_name,
                                 "identity column described in sidecar"))
        else:
            results.append(_warn(
                "DOC-003", e.entity_name,
                "identity column has no description in _raw.yml",
                "a column with no description is a name with no contract — the "
                "sidecar description is where the hashed-ID rule gets documented "
                "for the next person.",
                "describe the ID column in the raw sidecar",
            ))
    return results


def check_source_completeness(project: Project) -> list[CheckResult]:
    """DOC-004 — how many connected sources feed this entity (definitions-only)."""
    results: list[CheckResult] = []
    for e in project.entities:
        srcs = sorted(set(_all_source_names(e.definition_sql or "")))
        count = len(srcs)
        if count > 0:
            results.append(_pass("DOC-004", e.entity_name,
                                 f"{count} source(s): {', '.join(srcs)}"))
        else:
            results.append(_warn(
                "DOC-004", e.entity_name,
                "no source() reference — entity reads nothing declared",
                "an entity with no source is a stub, not a definition — it has no "
                "lineage back to where its data actually lives.",
                "declare the entity's source(s) with {{ source(...) }}",
            ))
    return results


# ── Group 5 — Safety roll-up (SPEC_70, per entity) ───────────────────────────

# Map a security finding's severity to a scorecard status. Blocking → fail,
# warn/info → warn. evaluate REPORTS everything; it never gates (validate does).
_SEC_SEVERITY_TO_STATUS = {"blocking": "fail", "warn": "warn", "info": "warn"}


def check_safety_rollup(project: Project) -> list[CheckResult]:
    """SEC — roll up MESA-SEC-001..007 findings as scorecard lines, per entity.

    Runs every SPEC_70 security scan (on comment/config-stripped SQL), then
    emits one line per (rule, entity). ``evaluate`` reports all of them —
    including the blocking tier — as graded lines; ``mesa validate`` is what
    actually gates on the blocking subset.
    """
    from mesa_core.validate import security_rules as sec

    results: list[CheckResult] = []

    def scan(entity_sql: str, is_metric: bool) -> list[sec.SecFinding]:
        findings = list(sec.scan_secrets(entity_sql))
        findings.extend(sec.scan_pii_literals(entity_sql))
        findings.extend(sec.scan_safe_cast(entity_sql))
        findings.extend(sec.scan_divide_by_zero(entity_sql))
        findings.extend(sec.scan_case_insensitive_comparisons(entity_sql))
        findings.extend(sec.scan_select_distinct(entity_sql))
        if is_metric:
            findings.extend(sec.scan_metric_left_join(entity_sql, is_metric_layer=True))
        return findings

    # Accumulate findings per (rule_code, entity_name).
    per_rule: dict[str, dict[str, list[sec.SecFinding]]] = {}

    def record(entity_name: str, sql: str, is_metric: bool) -> None:
        for f in scan(_strip_for_security(sql), is_metric):
            per_rule.setdefault(f.rule_code, {}).setdefault(entity_name, []).append(f)

    for e in project.entities:
        record(e.entity_name, e.definition_sql or "", is_metric=False)
    for m in project.metrics:
        record(m.entity_name, m.definition_sql or "", is_metric=True)

    rule_names = {
        "MESA-SEC-001": "no hardcoded secrets",
        "MESA-SEC-002": "no PII literals",
        "MESA-SEC-003": "SAFE_CAST/TRY_CAST (no bare CAST)",
        "MESA-SEC-004": "divide-by-zero guarded",
        "MESA-SEC-005": "no LEFT/RIGHT JOIN to ref() in metric layer",
        "MESA-SEC-006": "text comparisons case-folded",
        "MESA-SEC-007": "no SELECT DISTINCT crutch",
    }

    for rule_code, display in rule_names.items():
        for e in project.entities:
            findings = per_rule.get(rule_code, {}).get(e.entity_name, [])
            if not findings:
                results.append(_pass(rule_code, e.entity_name, display))
                continue
            worst = max(findings, key=lambda f: 0 if f.severity == "blocking" else 1)
            status = _SEC_SEVERITY_TO_STATUS.get(worst.severity, "warn")
            message = f"{len(findings)} finding(s): {worst.message}"
            why = ("security/safety findings in the definitions are reviewable risk "
                   "— evaluate surfaces them all so you can triage, even though only "
                   "the blocking subset fails `mesa validate`.")
            ref = "MESA Rulebook — 'Safety Rules'"
            if status == "fail":
                results.append(_fail(rule_code, e.entity_name, message, why, ref))
            else:
                results.append(_warn(rule_code, e.entity_name, message, why, ref))

    return results


# ── Registry ─────────────────────────────────────────────────────────────────

CHECKS: list[Callable[[Project], list[CheckResult]]] = [
    check_broken_refs,
    check_orphaned_metrics,
    check_tier_crossing,
    check_unused_sources,
    check_identity_hashed,
    check_grain_declared,
    check_grain_guard_clean,
    check_fanout_signal,
    check_one_file_one_metric,
    check_owner_declared,
    check_contract_declared,
    check_naming_convention,
    check_test_coverage,
    check_enrichment_depth,
    check_doctrine_header,
    check_metric_descriptions,
    check_sidecar_column_descriptions,
    check_source_completeness,
    check_safety_rollup,
]
