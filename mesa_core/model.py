# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
model.py — the ORM-free, Pydantic-free plain dataclasses.

SPEC_66 Slice 1: these are the frozen input contracts consumed by the
compiler and the validation brain. They mirror ONLY the fields the compiler
(query_compiler) and the validators (grain_guard / core_rules / mesa_verifier)
actually read — not the audit/workspace/timestamp columns that live on the
Mesantic ORM rows.

The Mesantic (paid) side ADAPTS its SQLAlchemy ORM rows into these dataclasses
before calling the compiler. MESA Core itself never touches SQLAlchemy.

HARD RULE: no sqlalchemy, no pydantic, no fastapi, no api.* imports here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entity:
    """One Raw Layer business entity (Tier 1), at one grain.

    The fields below are the exact subset the compiler + validators read.
    ``grain_columns`` and ``uniqueness`` are SPEC_53 forward-compat
    placeholders — not wired in Slice 1 (``check_fanout_risk`` takes a
    ``list[RiskyRelationship]`` directly today).
    """

    entity_name: str
    base_table_name: str
    source_name: str
    warehouse: str  # "Snowflake" | "BigQuery" | "Redshift" | "Synapse" | "DuckDB"
    identity_column: str = "ID"
    definition_sql: str = ""
    grain_description: str | None = None
    grain_columns: tuple[str, ...] | None = None  # tuple, not list — frozen-hashable
    uniqueness: str | None = None  # "enforced" | "advisory" | None


@dataclass(frozen=True)
class Metric:
    """One Metric Layer definition (Tier 2) — one file = one metric."""

    metric_name: str
    entity_name: str
    definition_sql: str


@dataclass(frozen=True)
class View:
    """One View Layer definition (Tier 4) — consumer-facing SELECT."""

    view_name: str
    entity_name: str
    definition_sql: str


@dataclass(frozen=True)
class CompileResult:
    """The compiled output of one entity — mirrors the governance repo's
    ``api.models.schemas.CompileResponse`` field-for-field."""

    entity_name: str
    warehouse: str
    metric_count: int
    compiled_metric_layer_sql: str
    compiled_widetable_sql: str
