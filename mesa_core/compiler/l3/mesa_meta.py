# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
compiler/l3/mesa_meta.py
========================
Default L3 adapter — emits governed `metrics:` YAML with `meta:` block.

This is the always-valid governance artifact. It records the full generated SQL,
ownership, sensitivity, and steward — everything an auditor needs to trace a
metric from expression to deployed artifact.

Reuses compile_from_expression for mesa_generated_sql (single source of truth).
Uses pyyaml (already a project dependency) for deterministic YAML emission.
"""

from __future__ import annotations

import yaml

from mesa_core.model import Entity
from mesa_core.compiler.l3 import L3Adapter, L3Artifact, GovernanceContext
from mesa_core.compiler.query_compiler import compile_from_expression


class MesaMetaAdapter:
    """Emits the governed `metrics:` YAML artifact (§1.1)."""

    target: str = "mesa_meta"

    def emit(
        self,
        entity: Entity,
        metric_name: str,
        expression: str,
        governance: GovernanceContext,
    ) -> L3Artifact:
        generated_sql = compile_from_expression(entity, metric_name, expression)

        source_ref = (
            f"{{{{ source('{entity.source_name}', '{entity.base_table_name}') }}}}"
        )

        # Build the metric dict in deterministic key order.
        # Using an explicit dict (Python 3.7+ preserves insertion order) and
        # yaml.safe_dump with sort_keys=False to preserve our ordering.
        metric_dict = {
            "name": metric_name,
            "description": "",
            "expression": expression,
            "entity": entity.entity_name,
            "identity": entity.identity_column,
            "source": source_ref,
            "meta": {
                "mesa_authoring_path": governance.get("authoring_path", "guided"),
                "mesa_owner": governance.get("owner", ""),
                "mesa_steward": governance.get("steward"),
                "mesa_sensitivity": governance.get("sensitivity", "standard"),
                "mesa_generated_sql": generated_sql,
            },
        }

        # Emit YAML with the metrics: wrapper.
        # Use block scalar (|) for mesa_generated_sql via a custom representer.
        content = self._render_yaml(metric_dict)

        return L3Artifact(
            target=self.target,
            filename=f"{metric_name}.yml",
            content=content,
            language="yaml",
        )

    def _render_yaml(self, metric_dict: dict) -> str:
        """Render the metric dict as governed metrics: YAML.

        Uses a custom Dumper that emits the mesa_generated_sql value as a
        block scalar (|) for readability, and ensures deterministic key order.
        """

        class MesaDumper(yaml.SafeDumper):
            pass

        def str_representer(dumper, data):
            """Emit multi-line strings as block scalars (|)."""
            if "\n" in data:
                return dumper.represent_scalar(
                    "tag:yaml.org,2002:str", data, style="|"
                )
            if len(data) > 80:
                return dumper.represent_scalar(
                    "tag:yaml.org,2002:str", data, style="|"
                )
            return dumper.represent_scalar(
                "tag:yaml.org,2002:str", data
            )

        MesaDumper.add_representer(str, str_representer)

        # Wrap in the top-level metrics: list
        doc = {"metrics": [metric_dict]}

        return yaml.dump(
            doc,
            Dumper=MesaDumper,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )