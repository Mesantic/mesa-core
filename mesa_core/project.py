# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
project.py — the file-based front door.

SPEC_66 Slice 2: ``load_project(path)`` walks a MESA four-tier project on disk
and builds plain dataclasses (``mesa_core.model``) for the compiler to consume.

This is the net-new artifact that lets the SAME compiler core read definitions
from files instead of from the Mesantic ORM. The on-disk format IS CAO's layout
(verified 2026-08-28) — this module does not invent a competing format.

Two project-file shapes are accepted (neither is mandatory):

  * ``mesa_project.yml`` — the net-new mesa-core project file (``mesa init``).
  * ``dbt_project.yml``    — CAO's shape: ``name`` + ``model-paths``.

When neither exists, the reader degrades to directory-name + conventional
``models/`` layout and records a load_error note rather than raising. A
hard-requirement on ``mesa_project.yml`` would make Slice 6 (the CAO
acceptance gate) unwinnable, because CAO has no such file.

Discipline: NEVER raise on a malformed file. Collect every parse problem into
``Project.load_errors`` and surface them — fail loud, but don't crash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mesa_core.model import Entity, Metric, View

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover — pyyaml is a declared dependency
    _YAML_AVAILABLE = False


# ── Regexes for on-disk parsing ──────────────────────────────────────────────

# {{ config(tags=[...]) }} — Jinja config line; not SQL, must be stripped first.
_CONFIG_BLOCK_RE = re.compile(r"^\s*\{\{\s*config\s*\(.*?\)\s*\}\}", re.DOTALL)

# {{ source('name', 'table') }} → capture name + table.
_SOURCE_RE = re.compile(
    r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
    re.IGNORECASE,
)

# {{ ref('Name') }} → capture Name.
_REF_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.IGNORECASE)

# Doctrine header lines in a raw entity file.
_RAW_ENTITY_RE = re.compile(r"^\s*--\s*RAW ENTITY\s*:\s*(.+?)\s*$", re.IGNORECASE)
_GRAIN_RE = re.compile(r"^\s*--\s*Grain\s*:\s*(.+?)\s*$", re.IGNORECASE)
_ID_RE = re.compile(r"^\s*--\s*ID\s*:\s*(.+?)\s*$", re.IGNORECASE)
_NATURAL_KEY_RE = re.compile(r"^\s*--\s*Natural key\s*:\s*(.+?)\s*$", re.IGNORECASE)

DEFAULT_WAREHOUSE = "Snowflake"


@dataclass(frozen=True)
class Project:
    """A loaded MESA project — the plain-dataclass view of a four-tier dir."""

    name: str
    default_warehouse: str
    entities: list[Entity] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    views: list[View] = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    target_dir: str = "target"
    load_errors: list[str] = field(default_factory=list)


# ── Path resolution ──────────────────────────────────────────────────────────

def _find_project_root(path: Path) -> Path:
    """Return the project root (the dir that holds the project file, if any).

    ``path`` may be the project root itself, or a ``models/`` dir whose parent
    is the root. CAO's layout is ``<root>/dbt_project.yml`` + ``<root>/models/``,
    so a caller pointing straight at ``models/`` still resolves the root.
    """
    p = path.resolve()
    for candidate in (p, p.parent):
        if (candidate / "mesa_project.yml").exists() or (candidate / "dbt_project.yml").exists():
            return candidate
    return p


def _resolve_models_dir(root: Path, path: Path) -> Path:
    """Resolve the four-tier models directory from the project root.

    Honors ``model-paths`` from ``dbt_project.yml`` when present; otherwise
    falls back to a conventional ``models/`` subdir, and finally to ``path``
    itself if it already looks like a models dir (has raw_layer/ etc.).
    """
    dbt_project = root / "dbt_project.yml"
    if dbt_project.exists() and _YAML_AVAILABLE:
        try:
            cfg = yaml.safe_load(dbt_project.read_text()) or {}
            model_paths = cfg.get("model-paths")
            if model_paths:
                first = model_paths[0] if isinstance(model_paths, list) else model_paths
                resolved = (root / first).resolve()
                if resolved.is_dir():
                    return resolved
        except Exception:
            pass  # fall through to defaults — never raise on a bad project file

    for candidate in (root / "models", path):
        if (candidate / "raw_layer").is_dir() or (candidate / "metric_layer").is_dir():
            return candidate.resolve()
    return (root / "models").resolve()


# ── Header / config stripping ────────────────────────────────────────────────

def _strip_config_and_header(sql: str) -> str:
    """Strip the leading ``{{ config(...) }}`` line and any ``--`` comment
    header block, returning the bare SQL body (WITH/SELECT ...)."""
    if not sql:
        return ""

    sql = _CONFIG_BLOCK_RE.sub("", sql, count=1)

    lines = sql.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("--"):
            idx += 1
            continue
        break
    return "\n".join(lines[idx:])


def _parse_doctrine_header(sql: str) -> dict:
    """Extract the raw-layer doctrine header metadata (entity / grain / ID /
    natural key) as a dict. Missing keys are absent, not errors."""
    meta: dict = {}
    for line in sql.splitlines():
        m = _RAW_ENTITY_RE.match(line)
        if m:
            meta.setdefault("entity", m.group(1).strip())
            continue
        m = _GRAIN_RE.match(line)
        if m:
            meta.setdefault("grain", m.group(1).strip())
            continue
        m = _NATURAL_KEY_RE.match(line)
        if m:
            meta.setdefault("natural_key", m.group(1).strip())
            continue
    return meta


def _first_source_ref(sql: str) -> tuple[str, str]:
    """Return (source_name, base_table_name) from the first ``source()`` ref,
    or ("", "") if none. Deterministic; Slice 3/6 may refine the spine choice."""
    m = _SOURCE_RE.search(sql)
    if m:
        return m.group(1), m.group(2)
    return "", ""


# ── Layer loaders ────────────────────────────────────────────────────────────

def _load_entities(models_dir: Path, warehouse: str, errors: list[str]) -> list[Entity]:
    entities: list[Entity] = []
    raw_dir = models_dir / "raw_layer"
    if not raw_dir.is_dir():
        errors.append(f"raw_layer/ not found under {models_dir}")
        return entities

    for sub in sorted(raw_dir.iterdir()):
        if not sub.is_dir():
            continue
        # <Entity>/<Entity>Raw.sql
        sql_files = sorted(sub.glob("*.sql"))
        if not sql_files:
            errors.append(f"raw_layer/{sub.name}/ has no .sql definition file")
            continue
        sql_file = sql_files[0]
        try:
            sql = sql_file.read_text()
        except OSError as exc:
            errors.append(f"cannot read {sql_file}: {exc}")
            continue

        entity_name = sub.name
        header = _parse_doctrine_header(sql)
        source_name, base_table_name = _first_source_ref(sql)

        entities.append(Entity(
            entity_name=entity_name,
            base_table_name=base_table_name,
            source_name=source_name,
            warehouse=warehouse,
            identity_column="ID",
            definition_sql=sql,
            grain_description=header.get("grain"),
            grain_columns=None,
            uniqueness=None,
        ))
    return entities


def _load_metrics(models_dir: Path, errors: list[str]) -> list[Metric]:
    metrics: list[Metric] = []
    metric_dir = models_dir / "metric_layer"
    if not metric_dir.is_dir():
        errors.append(f"metric_layer/ not found under {models_dir}")
        return metrics

    for sub in sorted(metric_dir.iterdir()):
        if not sub.is_dir():
            continue
        if not sub.name.endswith("_Metrics"):
            errors.append(f"metric_layer/{sub.name}/ — expected <Entity>_Metrics naming")
            continue
        entity_name = sub.name[: -len("_Metrics")]

        for sql_file in sorted(sub.glob("*.sql")):
            try:
                sql = sql_file.read_text()
            except OSError as exc:
                errors.append(f"cannot read {sql_file}: {exc}")
                continue
            metric_name = sql_file.stem
            body = _strip_config_and_header(sql)
            if not body.strip():
                errors.append(f"{sql_file}: empty SQL body after stripping config/header")
                continue
            metrics.append(Metric(
                metric_name=metric_name,
                entity_name=entity_name,
                definition_sql=body,
            ))
    return metrics


def _load_views(models_dir: Path, errors: list[str]) -> list[View]:
    views: list[View] = []
    view_dir = models_dir / "view_layer"
    if not view_dir.is_dir():
        errors.append(f"view_layer/ not found under {models_dir}")
        return views

    for sql_file in sorted(view_dir.glob("*.sql")):
        try:
            sql = sql_file.read_text()
        except OSError as exc:
            errors.append(f"cannot read {sql_file}: {exc}")
            continue

        # Infer the entity from {{ ref('<Entity>Wide') }}.
        entity_name = ""
        for m in _REF_RE.finditer(sql):
            ref = m.group(1)
            if ref.endswith("Wide"):
                entity_name = ref[: -len("Wide")]
                break
            if ref.endswith("WideTable"):
                entity_name = ref[: -len("WideTable")]
                break

        views.append(View(
            view_name=sql_file.stem,
            entity_name=entity_name,
            definition_sql=sql,
        ))
    return views


def _load_sources(models_dir: Path, errors: list[str]) -> dict:
    sources: dict = {}
    src_dir = models_dir / "sources"
    if not src_dir.is_dir():
        errors.append(f"sources/ not found under {models_dir}")
        return sources

    if not _YAML_AVAILABLE:
        errors.append("pyyaml not available — sources/ not parsed")
        return sources

    for yml_file in sorted(src_dir.glob("*.yml")):
        try:
            doc = yaml.safe_load(yml_file.read_text()) or {}
        except Exception as exc:
            errors.append(f"cannot parse {yml_file}: {exc}")
            continue

        for src in doc.get("sources", []) or []:
            name = src.get("name")
            if not name:
                errors.append(f"{yml_file}: source entry missing 'name'")
                continue
            tables = [t.get("name") for t in (src.get("tables", []) or []) if t.get("name")]
            sources[name] = {
                "database": src.get("database"),
                "schema": src.get("schema"),
                "tables": tables,
            }
    return sources


# ── Public entry point ───────────────────────────────────────────────────────

def load_project(path: str | Path) -> Project:
    """Load a MESA four-tier project from disk.

    ``path`` may be the project root (holds a project file + ``models/``) or
    the ``models/`` dir directly. Returns a ``Project`` with any parse problems
    collected in ``.load_errors`` — this function never raises on malformed
    input.
    """
    errors: list[str] = []
    p = Path(path).expanduser().resolve()

    root = _find_project_root(p)
    models_dir = _resolve_models_dir(root, p)

    name = root.name
    warehouse = DEFAULT_WAREHOUSE

    # Read the project file for name + default warehouse (either shape).
    for proj_name in ("mesa_project.yml", "dbt_project.yml"):
        proj_file = root / proj_name
        if proj_file.exists() and _YAML_AVAILABLE:
            try:
                cfg = yaml.safe_load(proj_file.read_text()) or {}
            except Exception as exc:
                errors.append(f"cannot parse {proj_file}: {exc}")
                continue
            if cfg.get("name"):
                name = str(cfg["name"])
            if proj_name == "mesa_project.yml" and cfg.get("default_warehouse"):
                warehouse = str(cfg["default_warehouse"])
            break
        elif proj_file.exists():
            errors.append(f"pyyaml not available — cannot parse {proj_file}")

    entities = _load_entities(models_dir, warehouse, errors)
    metrics = _load_metrics(models_dir, errors)
    views = _load_views(models_dir, errors)
    sources = _load_sources(models_dir, errors)

    return Project(
        name=name,
        default_warehouse=warehouse,
        entities=entities,
        metrics=metrics,
        views=views,
        sources=sources,
        target_dir="target",
        load_errors=errors,
    )
