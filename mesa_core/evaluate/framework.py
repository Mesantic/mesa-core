# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
framework.py — the ``mesa evaluate`` scorer + check-result model (SPEC_71).

``mesa evaluate`` is the ADVISORY scorecard, not the gate. ``mesa validate``
(SPEC_66/70) refuses bad code; ``mesa evaluate`` grades how well-engineered a
project is. Every check is a ``Callable[[Project], list[CheckResult]]`` that
reuses existing validation logic — the evaluator is an aggregator + scorer,
never a pile of new detectors.

Scoring model
-------------
Each check yields one or more ``CheckResult`` rows (per entity, or project-level
with ``entity_name=None``). A result carries a ``status`` (pass / warn / fail /
n_a) and a ``weight``. The per-entity (or per-project) grade is the weighted
roll-up:

  earned = sum(weight of pass) + 0.5 * sum(weight of warn)
  total  = sum(weight of every applicable check)   [n_a is excluded entirely]
  percent = 100 * earned / total                    (0 if nothing applicable)

``warn`` earns half credit — it's a nudge, not a violation, but it still costs
you in the grade. ``n_a`` means "not applicable here" and is skipped from both
numerator and denominator (it never drags a grade down for a check that simply
doesn't apply to this entity).

The ``percent`` maps onto a letter-grade band (``grade_band``) shared by
entities and the project as a whole.

Pure and import-safe: no fastapi, no sqlalchemy, no aiosqlite, no pydantic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from mesa_core.project import Project


CheckStatus = Literal["pass", "warn", "fail", "n_a"]


@dataclass
class CheckResult:
    """One scored line on the scorecard.

    ``why`` is the teaching sentence (why this matters), ``ref`` is a pointer
    ("read here for more"). Both are mandatory for every non-pass line — a bare
    FAIL is a defect in this spec (STOP RULE 6).
    """
    check_id: str                      # "STRUCT-001", "IDENT-001", ...
    entity_name: str | None            # None = project-level finding
    status: CheckStatus
    weight: float                      # scoring weight
    message: str                       # what was found
    why: str = ""                      # one-sentence "why it matters" (teaching)
    ref: str = ""                      # "read here for more" pointer


@dataclass
class EntityScore:
    entity_name: str
    results: list[CheckResult]
    grade: str
    percent: float

    def to_dict(self) -> dict:
        return {
            "entity_name": self.entity_name,
            "grade": self.grade,
            "percent": round(self.percent, 2),
            "results": [_result_to_dict(r) for r in self.results],
        }


@dataclass
class ProjectScore:
    entities: list[EntityScore]
    project_results: list[CheckResult]
    grade: str
    percent: float

    def to_dict(self) -> dict:
        return {
            "grade": self.grade,
            "percent": round(self.percent, 2),
            "entities": [e.to_dict() for e in self.entities],
            "project": [_result_to_dict(r) for r in self.project_results],
        }

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2)


def _result_to_dict(r: CheckResult) -> dict:
    d: dict = {
        "check_id": r.check_id,
        "status": r.status,
        "weight": r.weight,
        "message": r.message,
    }
    if r.entity_name is not None:
        d["entity_name"] = r.entity_name
    if r.why:
        d["why"] = r.why
    if r.ref:
        d["ref"] = r.ref
    return d


# ── Grade bands ──────────────────────────────────────────────────────────────
# Shared by entity + project. A+..F, standard academic spacing, tuned so a
# production MESA project (all-pass + a couple of soft warns) lands in the A/B
# range, while a genuinely thin entity lands in the C/D range.

_GRADE_BANDS: list[tuple[float, str]] = [
    (97.0, "A+"),
    (93.0, "A"),
    (90.0, "A-"),
    (87.0, "B+"),
    (83.0, "B"),
    (80.0, "B-"),
    (77.0, "C+"),
    (73.0, "C"),
    (70.0, "C-"),
    (67.0, "D+"),
    (63.0, "D"),
    (60.0, "D-"),
    (0.0, "F"),
]


def grade_band(percent: float) -> str:
    """Map a 0-100 percent to its letter grade."""
    p = max(0.0, min(100.0, percent))
    for threshold, grade in _GRADE_BANDS:
        if p >= threshold:
            return grade
    return "F"


def _weighted_percent(results: list[CheckResult]) -> float:
    """Weighted pass-ratio → percent. n_a is excluded; warn earns half credit."""
    earned = 0.0
    total = 0.0
    for r in results:
        if r.status == "n_a":
            continue
        total += r.weight
        if r.status == "pass":
            earned += r.weight
        elif r.status == "warn":
            earned += 0.5 * r.weight
        # fail earns nothing
    if total <= 0:
        return 100.0  # nothing applicable → not a failing score
    return 100.0 * earned / total


def percent_for(results: list[CheckResult]) -> float:
    """Public weighted percent (used by tests + CLI)."""
    return _weighted_percent(results)


# ── Evaluation entry point ───────────────────────────────────────────────────

def evaluate(project: Project, checks: list[Callable[[Project], list[CheckResult]]] | None = None) -> ProjectScore:
    """Run every registered check against a loaded project and grade it.

    ``checks`` defaults to the full ``CHECKS`` registry (imported lazily to
    avoid a circular import between framework and checks). Pass a custom list
    in tests to register a dummy check and exercise the scorer in isolation.
    """
    if checks is None:
        from mesa_core.evaluate.checks import CHECKS
        checks = CHECKS

    all_results: list[CheckResult] = []
    for check in checks:
        all_results.extend(check(project))

    # Partition into project-level (entity_name is None) and per-entity.
    project_results = [r for r in all_results if r.entity_name is None]

    entity_names: list[str] = []
    for r in all_results:
        if r.entity_name is not None and r.entity_name not in entity_names:
            entity_names.append(r.entity_name)

    entity_scores: list[EntityScore] = []
    for name in entity_names:
        results = [r for r in all_results if r.entity_name == name]
        percent = _weighted_percent(results)
        entity_scores.append(EntityScore(
            entity_name=name,
            results=results,
            grade=grade_band(percent),
            percent=percent,
        ))

    # Project grade = weighted roll-up of ALL results (entity-level + the
    # project-level DAG/unused-source lines). A broken ref() is project-level
    # and must drag the overall grade down, so it can't be dropped here.
    project_percent = _weighted_percent(all_results)
    return ProjectScore(
        entities=entity_scores,
        project_results=project_results,
        grade=grade_band(project_percent),
        percent=project_percent,
    )
