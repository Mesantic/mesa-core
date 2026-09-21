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

from dataclasses import dataclass, field


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
    warehouse: str  # "Snowflake" | "BigQuery" | "Redshift" | "Synapse" | "DuckDB" | "AzureSQLDatabase"
    identity_column: str = "ID"
    definition_sql: str = ""
    grain_description: str | None = None
    grain_columns: tuple[str, ...] | None = None  # tuple, not list — frozen-hashable
    uniqueness: str | None = None  # "enforced" | "advisory" | None
    # SPEC_71 evaluate: identity test coverage declared in the raw sidecar
    # (_raw.yml) — the empirical backstop to grain_guard. None = no sidecar.
    identity_tests: tuple[str, ...] | None = None
    identity_description: str | None = None  # doc-completeness signal
    # SPEC_72: per-entity wide-layer JOIN type (INNER vs LEFT). Default LEFT
    # (the safer default — never silently drops a row that lacks one metric).
    # Entity-config-driven: read from the entity's yml sidecar, not hardcoded.
    wide_join_type: str = "LEFT"


@dataclass(frozen=True)
class Metric:
    """One Metric Layer definition (Tier 2) — one file = one metric."""

    metric_name: str
    entity_name: str
    definition_sql: str
    # SPEC_71 evaluate: metric governance + doc-completeness metadata parsed
    # from the ``-- Owner:`` / ``-- Contract:`` doctrine header.
    owner: str | None = None
    contract: str | None = None
    description: str | None = None


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
    # SPEC_72 (combiner architecture): the per-entity metric COMBINER model
    # (Snowflake only) — "" for every other warehouse, since only Snowflake's
    # wide render needs a separate flat-columned combiner model to join
    # against. Written to models/metric_layer/<entity_snake>_metrics.sql.
    compiled_combiner_sql: str = ""
    # SPEC_72 Slice 4: metrics whose wide-layer type was inferred (no explicit
    # ``-- WIDE_TYPE:`` annotation). A caller (Mesantic) surfaces these; the
    # CLI prints them to stderr. Never silently cast to VARCHAR without notice.
    type_inference_warnings: list[str] = field(default_factory=list)
