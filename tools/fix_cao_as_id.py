#!/usr/bin/env python3
"""Apply the mechanical MESA-CORE-003 fix to CAO metric files.

Adds ``AS ID`` to the identity column (the first ``<Entity>.ID`` in each metric's
OUTERMOST SELECT block), matching guided-authoring's canonical form. Leaves JOIN
ON clauses and GROUP BY untouched — those ``.ID`` references live AFTER the
outer FROM, outside the SELECT column list.

This is the ONLY genuinely-CAO edit from the SPEC_66 addendum; the three
verifier dialect bugs are fixed in mesa_core/validate/, not here.

Only touches ``<Entity>.ID`` with no following ``AS ID``; is idempotent and
prints a summary of every file changed.
"""

from __future__ import annotations

import re
from pathlib import Path

METRIC_DIR = Path(
    "/Users/yennypassanante/Downloads/CAO/domains/CustomerJourney/models/metric_layer"
)


def _final_select_block(sql: str) -> tuple[int, int] | None:
    """Return (select_end, from_start) of the OUTERMOST (depth-0) SELECT block.

    Mirrors core_rules._extract_final_select_block — skip depth>=1 (CTE inner
    selects)."""
    n = len(sql)
    # Find last depth-0 SELECT.
    depth = 0
    select_end = None
    i = 0
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and sql[i:i + 6].upper() == "SELECT" \
                and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            select_end = i + 6  # just past the SELECT keyword
        i += 1

    if select_end is None:
        return None

    # Walk forward from select_end to next depth-0 FROM.
    depth = 0
    i = select_end
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and sql[i:i + 4].upper() == "FROM" \
                and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            return (select_end, i)
        i += 1
    # No FROM — block runs to end.
    return (select_end, n)


_ID_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.ID\b")

# Guard: an ".ID" that is already part of "AS ID" — i.e. preceded by "AS ".
_ALREADY_AS_ID_RE = re.compile(r"\bAS\s+(?:[A-Za-z_][A-Za-z0-9_]*\.)?ID\b", re.IGNORECASE)


def fix_file(path: Path) -> bool:
    sql = path.read_text()
    block = _final_select_block(sql)
    if block is None:
        return False
    start, end = block
    head = sql[:start]
    body = sql[start:end]
    tail = sql[end:]

    # If the identity is already written "<Entity>.ID AS ID", skip.
    if re.search(r"\.ID\s+AS\s+ID\b", body, re.IGNORECASE):
        return False

    m = _ID_RE.search(body)
    if m is None:
        return False

    entity = m.group(1)
    new_body = body[:m.end()] + " AS ID" + body[m.end():]
    path.write_text(head + new_body + tail)
    return True


def main() -> None:
    changed = []
    for sql_file in sorted(METRIC_DIR.rglob("*.sql")):
        if fix_file(sql_file):
            changed.append(str(sql_file.relative_to(METRIC_DIR.parent)))
    print(f"Changed {len(changed)} metric files:")
    for c in changed:
        print(f"  {c}")


if __name__ == "__main__":
    main()