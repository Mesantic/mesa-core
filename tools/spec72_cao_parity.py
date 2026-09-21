"""SPEC_72 Slice 6 — CAO wide-layer + combiner byte-identical parity gate.

Loads CAO CustomerJourney, compiles each entity's wide layer AND (Snowflake)
metric combiner with mesa-core, and diffs both against the checked-in
models/wide_layer/*.sql + models/metric_layer/<entity_snake>_metrics.sql.
Writes the result (per-file diff + PASS/FAIL) to /tmp/spec72_cao_wide_parity.txt.
"""

import sys
from pathlib import Path

from mesa_core.project import load_project
from mesa_core import build as _build
from mesa_core.compiler.combiner import combiner_model_name

CAO_MODELS = "/Users/yennypassanante/Downloads/CAO/domains/CustomerJourney/models"
OUT = Path("/tmp/spec72_cao_wide_parity.txt")


def _check(lines: list[str], label: str, committed_path: Path, generated: str) -> bool:
    if not committed_path.exists():
        lines.append(f"{label}: MISSING checked-in file ({committed_path.name})")
        return False

    committed = committed_path.read_text()
    if committed == generated:
        lines.append(f"{label}: PASS (byte-identical)")
        return True

    lines.append(f"{label}: FAIL — diff below")
    import difflib
    diff = list(difflib.unified_diff(
        committed.splitlines(),
        generated.splitlines(),
        fromfile=f"committed/{committed_path.name}",
        tofile=f"generated/{committed_path.name}",
        lineterm="",
    ))
    lines.extend(diff)
    return False


def main() -> int:
    proj = load_project(CAO_MODELS)
    lines = []
    all_pass = True

    wide_dir = Path(CAO_MODELS) / "wide_layer"
    metric_dir = Path(CAO_MODELS) / "metric_layer"

    for entity in proj.entities:
        metrics = _build.metrics_for_entity(proj, entity)
        result = _build.compile_entity(entity, metrics, entity.warehouse)

        ok = _check(
            lines, f"{entity.entity_name}Wide",
            wide_dir / f"{entity.entity_name}Wide.sql",
            result.compiled_widetable_sql,
        )
        all_pass = all_pass and ok

        if result.compiled_combiner_sql:
            ok = _check(
                lines, f"{entity.entity_name} combiner",
                metric_dir / f"{combiner_model_name(entity.entity_name)}.sql",
                result.compiled_combiner_sql,
            )
            all_pass = all_pass and ok
        lines.append("")

    lines.append("PASS" if all_pass else "FAIL")
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all_pass else 1

if __name__ == "__main__":
    sys.exit(main())
