# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
compiler/targets
================
Target-emitter abstraction for MESA's multi-target compile pipeline.

SPEC_39-A: Introduces the TargetEmitter protocol so the governed contract
(entity + metrics + view) can be rendered to different downstream targets
(warehouse DDL, Cube.dev YAML, dbt/MetricFlow files) without coupling the
compile logic to any one delivery mechanism.

SPEC_39-B: CubeEmitter fully enabled.
SPEC_40-A: DbtEmitter fully enabled (dbt models + MetricFlow semantic YAML → git PR).

Currently registered targets
-----------------------------
  "warehouse"  → WarehouseEmitter (executes DDL on the customer warehouse)
  "cube"        → CubeEmitter (SPEC_39-B, generates Cube.dev YAML → git PR)
  "dbt"         → DbtEmitter (SPEC_40-A, generates dbt models + MetricFlow YAML → git PR)
"""

from mesa_core.compiler.targets.base import Artifact, TargetEmitter, get_emitter

__all__ = ["Artifact", "TargetEmitter", "get_emitter"]
