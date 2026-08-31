"""
test_load_cao.py — SPEC_66 Slice 2b.

Point ``load_project`` at the REAL CAO CustomerJourney models dir (read-only
reference) and prove the format reader parses production definitions with zero
load_errors, finds all four entities, and the correct per-entity metric counts.

CAO is a fixture here — this test reads it, never writes to it, never imports
it. It is the first real proof the reader works on production definitions.
"""

import os
from pathlib import Path

from mesa_core.project import load_project


CAO_MODELS = "/Users/yennypassanante/Downloads/CAO/domains/CustomerJourney/models"


def test_load_cao_finds_all_four_entities():
    proj = load_project(CAO_MODELS)

    entity_names = {e.entity_name for e in proj.entities}
    assert entity_names == {"ChangeEvent", "Contact", "Policy", "Survey"}


def test_load_cao_zero_load_errors():
    proj = load_project(CAO_MODELS)
    assert proj.load_errors == []


def test_load_cao_metric_counts():
    proj = load_project(CAO_MODELS)

    by_entity: dict[str, int] = {}
    for m in proj.metrics:
        by_entity[m.entity_name] = by_entity.get(m.entity_name, 0) + 1

    # Non-empty per-entity counts (Contact has zero metric files — the reader
    # simply omits it, it does not fabricate an empty key).
    assert by_entity == {
        "Policy": 20,
        "Survey": 9,
        "ChangeEvent": 3,
    }
    assert len(proj.metrics) == 32

    # Contact entity exists but has no metrics.
    contact = next(e for e in proj.entities if e.entity_name == "Contact")
    assert contact.entity_name == "Contact"
    assert by_entity.get("Contact", 0) == 0


def test_load_cao_policy_metric_is_stripped():
    """A Policy metric's definition_sql must have the {{ config }} line and
    -- METRIC header stripped, leaving a bare SELECT body."""
    proj = load_project(CAO_MODELS)
    tenure = next(m for m in proj.metrics if m.metric_name == "TenureDays")
    assert "{{ config" not in tenure.definition_sql
    assert "-- METRIC:" not in tenure.definition_sql
    assert tenure.definition_sql.lstrip().startswith("SELECT")


def test_load_cao_entities_have_grain_and_sql():
    """Every entity carries its doctrine grain description and a non-empty
    definition_sql body."""
    proj = load_project(CAO_MODELS)
    for e in proj.entities:
        assert e.grain_description, f"{e.entity_name} missing grain"
        assert e.definition_sql.strip(), f"{e.entity_name} missing definition_sql"
        assert e.warehouse == "Snowflake"


def test_load_cao_sources_parsed():
    proj = load_project(CAO_MODELS)
    # At least the known source systems are declared.
    assert {"rten", "fdr", "qualtrics", "tnps"}.issubset(set(proj.sources.keys()))


def test_load_cao_views_have_entity_names():
    proj = load_project(CAO_MODELS)
    assert len(proj.views) == 10
    # A view reading {{ ref('SurveyWide') }} resolves entity "Survey".
    survey_views = [v for v in proj.views if v.entity_name == "Survey"]
    assert survey_views, "expected at least one view resolving to entity Survey"


def test_load_cao_resolves_models_dir_from_parent():
    """Passing the project root (not models/) must resolve the same entities."""
    root = os.path.dirname(CAO_MODELS)  # CustomerJourney/ — holds dbt_project.yml
    proj = load_project(root)
    entity_names = {e.entity_name for e in proj.entities}
    assert entity_names == {"ChangeEvent", "Contact", "Policy", "Survey"}
