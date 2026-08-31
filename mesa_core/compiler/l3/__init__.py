# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
compiler/l3/__init__.py
======================
L3 Semantic Layer adapter registry.

Each adapter takes a compiled MESA metric (entity + expression) and emits the
correct L3 artifact for the target semantic layer. The SQL is always generated
by compile_from_expression — adapters reshape, never reimplement.

Adapter contract:
  L3Adapter.emit(entity, metric_name, expression, governance) -> L3Artifact

  L3Artifact = {target, filename, content, language}
"""

from __future__ import annotations

from typing import Protocol, TypedDict

from mesa_core.model import Entity


# ── L3Artifact typed dict ───────────────────────────────────────────────────

class L3Artifact(TypedDict):
    """The output of an L3 adapter — a file ready to be stored or downloaded."""
    target: str       # "mesa_meta" | "metricflow" | "cube"
    filename: str     # e.g. "IsSettledStaking.yml" or "staking_events.yml"
    content: str      # the generated YAML / SQL / template
    language: str     # "yaml" | "sql" | "python"


# ── Governance context passed to every adapter ──────────────────────────────

class GovernanceContext(TypedDict):
    """Metadata that every L3 artifact must carry for auditability."""
    owner: str
    steward: str | None
    sensitivity: str          # "standard" | "financial" | "regulatory" | "pii"
    authoring_path: str       # "guided"


# ── L3Adapter protocol ──────────────────────────────────────────────────────

class L3Adapter(Protocol):
    """Protocol for L3 semantic-layer adapters.

    Every adapter receives the same inputs and returns an L3Artifact.
    The SQL is always compiled by compile_from_expression — adapters
    reshape the output for their target, never re-derive the SQL.
    """

    @property
    def target(self) -> str:
        """The target identifier this adapter handles (e.g. 'mesa_meta')."""
        ...

    def emit(
        self,
        entity: Entity,
        metric_name: str,
        expression: str,
        governance: GovernanceContext,
    ) -> L3Artifact:
        """Emit the L3 artifact for this target."""
        ...


# ── Registry ────────────────────────────────────────────────────────────────

_registry: dict[str, L3Adapter] = {}


def register(adapter: L3Adapter) -> None:
    """Register an L3 adapter for its declared target."""
    _registry[adapter.target] = adapter


def get_adapter(target: str) -> L3Adapter | None:
    """Look up an L3 adapter by target name. Returns None if not registered."""
    return _registry.get(target)


def list_targets() -> list[str]:
    """Return all registered L3 target names."""
    return list(_registry.keys())


# ── Auto-register built-in adapters on import ───────────────────────────────

from mesa_core.compiler.l3.mesa_meta import MesaMetaAdapter      # noqa: E402
from mesa_core.compiler.l3.metricflow import MetricFlowAdapter   # noqa: E402
from mesa_core.compiler.l3.cube import CubeAdapter               # noqa: E402

register(MesaMetaAdapter())
register(MetricFlowAdapter())
register(CubeAdapter())