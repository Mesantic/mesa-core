# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
render.py — human-readable terminal scorecard for ``mesa evaluate``.

The default output. Groups the five check groups, entity-by-entity, with the
teaching line (``why`` + ``ref``) under every non-pass line — a bare FAIL is a
defect in this spec (STOP RULE 6). Pure text; no ANSI assumptions beyond plain
prefixes so it redirects cleanly to a file.
"""

from __future__ import annotations

from mesa_core.evaluate.framework import ProjectScore

# Group labels, in scorecard order, keyed by check-id prefix. Multiple prefixes
# may share one label (ENRICH + DOC both land under "ENRICHMENT & DOCS") — the
# renderer dedupes by label so the section header prints once.
_GROUP_ORDER = [
    ("STRUCT", "STRUCTURE & DAG"),
    ("IDENT", "IDENTITY & GRAIN"),
    ("GOV", "METRIC GOVERNANCE"),
    ("ENRICH", "ENRICHMENT & DOCS"),
    ("DOC", "ENRICHMENT & DOCS"),
    ("MESA-SEC", "SAFETY"),
]

# Ordered, de-duplicated labels in scorecard order.
_GROUP_LABELS: list[str] = []
for _p, _l in _GROUP_ORDER:
    if _l not in _GROUP_LABELS:
        _GROUP_LABELS.append(_l)

_STATUS_GLYPH = {
    "pass": "PASS",
    "warn": "WARN",
    "fail": "FAIL",
    "n_a": "N/A ",
}


def _group_for(check_id: str) -> str:
    for prefix, label in _GROUP_ORDER:
        if check_id.startswith(prefix):
            return label
    return "OTHER"


def _render_result(r) -> list[str]:
    lines = [f"    {_STATUS_GLYPH[r.status]:4}  {r.check_id:12} {r.message}"]
    if r.status != "pass" and r.why:
        lines.append(f"         -> why: {r.why}")
    if r.status != "pass" and r.ref:
        lines.append(f"         -> see: {r.ref}")
    return lines


def render_scorecard(score: ProjectScore) -> str:
    out: list[str] = []
    out.append("")
    out.append(f"MESA PROJECT HEALTH SCORECARD")
    out.append(f"  overall grade: {score.grade}  ({score.percent:.1f}%)")
    out.append("")

    # Project-level results (DAG, unused source) grouped.
    project_groups: dict[str, list] = {}
    for r in score.project_results:
        project_groups.setdefault(_group_for(r.check_id), []).append(r)
    for label in _GROUP_LABELS:
        results = project_groups.get(label)
        if not results:
            continue
        out.append(f"  {label}")
        for r in results:
            out.extend(_render_result(r))
        out.append("")

    # Entities.
    for es in score.entities:
        out.append(f"  {es.entity_name}  —  {es.grade}  ({es.percent:.1f}%)")
        groups: dict[str, list] = {}
        for r in es.results:
            groups.setdefault(_group_for(r.check_id), []).append(r)
        for label in _GROUP_LABELS:
            results = groups.get(label)
            if not results:
                continue
            out.append(f"    {label}")
            for r in results:
                out.extend(_render_result(r))
        out.append("")

    out.append("")
    return "\n".join(out)
