# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
compiler/targets/base.py
=========================
Core abstractions for the MESA multi-target compile pipeline.

SPEC_39-A: Defines Artifact, TargetEmitter, and the get_emitter() registry.

Design contract
---------------
* Artifact  — an immutable, typed result produced by an emitter.  kind="ddl"
  artifacts are executed on a warehouse; kind="file" artifacts are written to a
  git repo.  The split is deliberate: warehouse execution stays in deployment.py;
  git writing lives in integrations/definitions/git_writer.py (SPEC_39-B).

* TargetEmitter — a Protocol (structural subtype) so emitters can be defined in
  their own modules without forced inheritance.  Duck-typed: any class with a
  conforming emit() signature qualifies.

* get_emitter() — the runtime registry lookup.  Unknown targets raise ValueError
  with the full allowed list.  Future targets (cube, dbt) are listed here as
  NOT_YET_ENABLED so the 400 surface is discoverable without branching logic in
  the route.

Wire-label preservation
-----------------------
  Artifact.object_type uses the same canonical MESA tier labels that _build_ddl_objects
  has always produced: "raw", "metric", "widetable", "view".  These values are persisted
  in DeployedObject.object_type and MUST NOT be renamed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


# ── Artifact ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Artifact:
    """
    One logical unit produced by a TargetEmitter.

    Attributes
    ----------
    kind         : "ddl"  → execute on warehouse connector
                   "file" → write to a git repo (SPEC_39-B / SPEC_40)
    object_type  : MESA tier wire label: "raw" | "metric" | "widetable" | "view".
                   Preserved verbatim from legacy _build_ddl_objects dict keys.
                   CRITICAL: stored in DeployedObject.object_type — do not alter.
    name         : Human-readable object name (e.g. "CustomerWideTable").
                   Corresponds to legacy dict key "object_name".
    path         : Fully-qualified warehouse path for kind="ddl"
                   (e.g. "mesa_wide.Customer").
                   Repo-relative file path for kind="file"
                   (e.g. "model/cubes/customer.yml").
                   Corresponds to legacy dict key "warehouse_path".
    body         : DDL string (kind="ddl") or file contents (kind="file").
                   Corresponds to legacy dict key "ddl".
    health_issues: Empty list → object is healthy and may be deployed.
                   Non-empty  → deploy is BLOCKED; these messages surface to the
                   caller as errors.  Carried verbatim from check_object_health().
    """

    kind: Literal["ddl", "file"]
    object_type: str         # "raw" | "metric" | "widetable" | "view"
    name: str                # object_name / logical name
    path: str                # warehouse_path (ddl) OR repo-relative file path (file)
    body: str                # DDL string OR file contents
    health_issues: list[str] = field(default_factory=list)

    def to_legacy_dict(self) -> dict:
        """
        Back-compat bridge: return the dict shape that the legacy deploy loop
        expects so callers can adopt Artifact incrementally.

        Returned keys match the shape produced by _build_ddl_objects() exactly:
          object_type, object_name, warehouse_path, ddl, health_issues
        """
        return {
            "object_type":    self.object_type,
            "object_name":    self.name,
            "warehouse_path": self.path,
            "ddl":            self.body,
            "health_issues":  list(self.health_issues),
        }


# ── TargetEmitter Protocol ────────────────────────────────────────────────────

@runtime_checkable
class TargetEmitter(Protocol):
    """
    Structural protocol for all compile targets.

    A TargetEmitter turns a governed contract (entity + metrics + optional view)
    into a list of Artifacts.  It MUST NOT perform I/O — no warehouse DDL
    execution, no git writes.  Side effects belong in the route handler or in
    integrations/definitions/git_writer.py.

    Attributes
    ----------
    target_name : Registered identifier string (e.g. "warehouse", "cube", "dbt").

    emit() contract
    ---------------
    * Pure and deterministic — same inputs → same outputs.
    * Never raises unless inputs are structurally invalid (missing required fields).
    * Returns [] for empty metric/view combinations (callers must handle gracefully).
    * health_issues on any Artifact do not raise — the route handler enforces the gate.
    """

    target_name: str

    def emit(
        self,
        entity,
        metrics,
        view,
        *,
        layers: list[str] | None = None,
        metric_names: list[str] | None = None,
        location_overrides: dict | None = None,
    ) -> list[Artifact]:
        """
        Produce Artifacts from the governed contract.

        Parameters
        ----------
        entity           : Entity ORM instance.
        metrics          : list[Metric] ORM instances for this entity.
        view             : Optional View ORM instance (published, authored view).
                           May be None when no view has been authored.
        layers           : Tier wire labels to include (None = all four tiers).
                           Already closed by close_layers() — caller guarantees deps.
        metric_names     : SPEC_38 — restrict the metric tier to these names.
                           None = all metrics (back-compat).  Widetable fold invariant
                           still uses the full metrics list regardless.
        location_overrides: Optional dict from TargetLocationOverrides for per-request
                           path overrides (SPEC_NEXT_33 Part D).
        """
        ...


# ── Registry ─────────────────────────────────────────────────────────────────

# Targets that exist in the registry but are not yet enabled.
# get_emitter() surfaces this as a clear ValueError rather than a silent 500.
# SPEC_39-B: "cube" removed from this set — it is now fully enabled.
# SPEC_40:   "dbt" removed from this set — it is now fully enabled.
_NOT_YET_ENABLED: frozenset[str] = frozenset()


def get_emitter(
    target_name: str,
    *,
    connector=None,
    code_connection=None,
) -> TargetEmitter:
    """
    Return the TargetEmitter for the given target name.

    MESA Core registers the pure, file-emitting targets: "cube" and "dbt".
    The "warehouse" target (DDL execution on a live connector) is Mesantic-only —
    it depends on ``api.routes.deployment`` and a WarehouseConnector, so it is
    intentionally absent here. Requesting "warehouse" raises a clear ValueError.

    Parameters
    ----------
    target_name      : "cube" | "dbt".
    connector        : ignored (accepted for API parity with Mesantic).
    code_connection  : optional context object; the emitters are pure and never
                       read it, so MESA Core callers may pass None.

    Raises
    ------
    ValueError  : Unknown target, or "warehouse" (not available in MESA Core).
    """
    from mesa_core.compiler.targets.cube import CubeEmitter
    from mesa_core.compiler.targets.dbt import MesaDbtEmitter

    _REGISTRY: dict[str, type] = {
        "cube": CubeEmitter,
        "dbt": MesaDbtEmitter,
    }
    _ALLOWED = sorted(_REGISTRY.keys())

    if target_name == "warehouse":
        raise ValueError(
            "target='warehouse' is not available in MESA Core — warehouse DDL "
            "execution requires a live connector and lives in Mesantic. "
            f"Allowed targets: {', '.join(_ALLOWED)}"
        )

    if target_name not in _REGISTRY:
        raise ValueError(
            f"Unknown deploy_target '{target_name}'. "
            f"Allowed targets: {', '.join(_ALLOWED)}"
        )

    if target_name == "cube":
        return CubeEmitter(code_connection=code_connection)

    if target_name == "dbt":
        # MesaDbtEmitter is the active "dbt" target (SPEC_41-A gold-standard layout).
        return MesaDbtEmitter(code_connection=code_connection)

    # Future targets not yet registered.
    raise ValueError(f"Cannot instantiate target '{target_name}': no constructor branch.")
