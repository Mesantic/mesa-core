# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
compiler/l3/meta_health.py
==========================
MESA meta: completeness checker for semantic-layer artifacts.

SPEC_32 PART 1c — "Add a meta: completeness check surfaced in drift/health:
flag metrics whose meta: lacks owner/steward/sensitivity (MetricFlow allows
meta: but never requires it — this is the enforcement MetricFlow lacks)."

This module is the **public API** for the health check so that:
  - R8MetricFlowExtractor (raw_resolver.py) calls it at extraction time
  - Drift/health routes can call it independently against raw YAML dicts
  - Tests can import it without touching raw_resolver internals

SEVERITY: health finding only — never a hard failure.  The metric is still
registered and analysed; the finding surfaces in drift + entity health views.

FINDING CODE: MESA-META-001

Fields checked (MetricFlow allows meta: but never mandates any of these):
  - mesa_owner   (or legacy: owner)
  - mesa_steward (or legacy: steward)
  - mesa_sensitivity (or legacy: sensitivity)

No external dependencies — stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Finding code ─────────────────────────────────────────────────────────────

MESA_META_001 = "MESA-META-001"
"""Finding code: metric meta: block is missing required governance fields."""


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class MetaCompletenessResult:
    """
    Result of a meta: completeness check on a single semantic-layer artifact.

    Attributes:
        complete:        True when all three required fields are present.
        missing_fields:  Canonical field names that are absent / empty.
        finding_code:    ``MESA-META-001`` when incomplete, else ``""``.
        finding:         Human-readable governance finding message.
        artifact_name:   Name of the metric / semantic_model that was checked.
        artifact_type:   ``"metric"`` | ``"semantic_model"`` | ``"cube"`` | ``"unknown"``.
        source_file:     Path to the YAML file that contained this artifact.
    """
    complete: bool
    missing_fields: list[str] = field(default_factory=list)
    finding_code: str = ""
    finding: str = ""
    artifact_name: str = ""
    artifact_type: str = "unknown"
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "missing_fields": self.missing_fields,
            "finding_code": self.finding_code,
            "finding": self.finding,
            "artifact_name": self.artifact_name,
            "artifact_type": self.artifact_type,
            "source_file": self.source_file,
        }


# ── Alias map ─────────────────────────────────────────────────────────────────

# Each canonical required field may appear under multiple key names.
# mesa_* keys (MESA-native) take precedence, but legacy unqualified keys
# are also accepted (for governing EXISTING customer YAML that doesn't yet
# use the mesa_ prefix).
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "mesa_owner":       ["mesa_owner", "owner"],
    "mesa_steward":     ["mesa_steward", "steward"],
    "mesa_sensitivity": ["mesa_sensitivity", "sensitivity"],
}


# ── Public checker ────────────────────────────────────────────────────────────

def check_meta_completeness(
    meta: dict[str, Any] | None,
    *,
    artifact_name: str = "",
    artifact_type: str = "unknown",
    source_file: str | None = None,
) -> MetaCompletenessResult:
    """
    Check whether a semantic-layer ``meta:`` block satisfies MESA governance.

    Args:
        meta:           Parsed ``meta:`` dict from a MetricFlow metric or
                        semantic_model, a Cube cube block, or a mesa_meta
                        governed metric YAML.  Pass ``None`` to treat as an
                        empty dict (every field will be flagged missing).
        artifact_name:  Human-readable name of the artifact (for the finding).
        artifact_type:  ``"metric"`` | ``"semantic_model"`` | ``"cube"`` | ...
        source_file:    Absolute path to the source YAML (for the finding URL).

    Returns:
        MetaCompletenessResult.  ``complete=True`` when all three required
        fields are present and non-null/non-empty.

    This function NEVER raises.
    """
    if meta is None:
        meta = {}

    missing: list[str] = []
    for canonical, aliases in _REQUIRED_FIELDS.items():
        present = any(
            meta.get(alias) not in (None, "", [], {})
            for alias in aliases
        )
        if not present:
            missing.append(canonical)

    if not missing:
        return MetaCompletenessResult(
            complete=True,
            artifact_name=artifact_name,
            artifact_type=artifact_type,
            source_file=source_file,
        )

    # Build the finding message
    name_clause = f" for '{artifact_name}'" if artifact_name else ""
    file_clause = f" ({source_file})" if source_file else ""
    finding = (
        f"{MESA_META_001}: {artifact_type} meta: block is incomplete{name_clause}{file_clause} — "
        f"missing: {', '.join(missing)}. "
        "Add mesa_owner, mesa_steward, and mesa_sensitivity to satisfy MESA governance "
        "requirements (MetricFlow does not enforce these natively; "
        "Cube does not enforce these natively)."
    )

    return MetaCompletenessResult(
        complete=False,
        missing_fields=missing,
        finding_code=MESA_META_001,
        finding=finding,
        artifact_name=artifact_name,
        artifact_type=artifact_type,
        source_file=source_file,
    )


def check_meta_completeness_dict(result: MetaCompletenessResult) -> dict[str, Any]:
    """Convenience: convert a result to the dict shape used in CanonicalDefinition.provenance."""
    return result.to_dict()


# ── Batch scanner ─────────────────────────────────────────────────────────────

def scan_yaml_file_for_meta_findings(
    data: dict[str, Any],
    source_file: str | None = None,
) -> list[MetaCompletenessResult]:
    """
    Scan a parsed YAML document (MetricFlow or Cube) for all meta: findings.

    Handles:
      - MetricFlow ``semantic_models:`` blocks  → artifact_type='semantic_model'
      - MetricFlow ``metrics:`` blocks           → artifact_type='metric'
      - Cube        ``cubes:`` blocks            → artifact_type='cube'
      - MESA meta   ``metrics:`` blocks          → artifact_type='metric'  (same path)

    Returns a list of MetaCompletenessResult — only incomplete artifacts are
    included when ``only_incomplete=True`` (default False; returns all).

    This function NEVER raises.
    """
    findings: list[MetaCompletenessResult] = []

    # ── MetricFlow semantic_models ───────────────────────────────────────────
    for sm in data.get("semantic_models", []):
        if not isinstance(sm, dict):
            continue
        name = sm.get("name", "<unnamed>")
        meta = sm.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        findings.append(
            check_meta_completeness(
                meta,
                artifact_name=name,
                artifact_type="semantic_model",
                source_file=source_file,
            )
        )

    # ── MetricFlow / mesa_meta metrics ───────────────────────────────────────
    for metric in data.get("metrics", []):
        if not isinstance(metric, dict):
            continue
        name = metric.get("name", "<unnamed>")
        meta = metric.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        findings.append(
            check_meta_completeness(
                meta,
                artifact_name=name,
                artifact_type="metric",
                source_file=source_file,
            )
        )

    # ── Cube cubes ───────────────────────────────────────────────────────────
    for cube in data.get("cubes", []):
        if not isinstance(cube, dict):
            continue
        name = cube.get("name", "<unnamed>")
        meta = cube.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        findings.append(
            check_meta_completeness(
                meta,
                artifact_name=name,
                artifact_type="cube",
                source_file=source_file,
            )
        )

    return findings
