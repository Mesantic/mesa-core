# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
annotations.py — the metric-file annotation reader.

SPEC_101 Slice 1. Before this module, every annotation resolver
(``combiner.resolve_combiner_default``, ``wide_type.resolve_wide_type``,
``wide_type.resolve_tsql_type``) ran a regex over the metric's *stripped*
``definition_sql``. ``project._load_metrics`` had already removed the leading
comment block, so an annotation could never be found on the build path — a file
that DID annotate looked exactly like one that didn't. This module reads the
annotations from the *raw* file text instead, at the same boundary the stripper
uses, and hands them to the metric as ``Metric.annotations``.

The boundary matters. An annotation is a *leading header* directive:

    {{ config(...) }}
    -- METRIC: What this metric means
    -- Owner: Analytics
    -- COMBINER_DEFAULT: NONE
    SELECT ...

A ``-- COMBINER_DEFAULT:`` comment buried inside a CTE is NOT an annotation —
it's a comment about the SQL body. ``parse_annotations`` therefore reads only
the leading config line plus the leading blank/``--`` lines, which is exactly
the region ``project._strip_config_and_header`` discards.
"""

from __future__ import annotations

import re

# The annotations a metric file may carry in its leading header block. These are
# machine directives consumed by the compiler, never human prose:
#   COMBINER_DEFAULT  — the literal to COALESCE a combiner metric column with
#                       (or NONE/NULL for a deliberate NULL pass-through).
#   WIDE_TYPE         — Snowflake wide-layer type. Ignored by the SPEC_72
#                       combiner form, kept for the pure function + docs.
#   WIDE_TYPE_TSQL    — the flat-column CAST type on the T-SQL targets.
ANNOTATION_KEYS: frozenset[str] = frozenset({"COMBINER_DEFAULT", "WIDE_TYPE", "WIDE_TYPE_TSQL"})

# `-- KEY: value` (case-insensitive on the key). Anchored to end-of-line so a
# value can never run past its own line into the next SQL block.
ANNOTATION_LINE_RE = re.compile(
    r"^\s*--\s*(COMBINER_DEFAULT|WIDE_TYPE_TSQL|WIDE_TYPE)\s*:\s*([^\n]+?)\s*$",
    re.IGNORECASE,
)

# Same definition the project loader uses to drop the config block. Duplicated
# rather than imported to keep this module dependency-free (no import cycle with
# project.py, which imports from here).
_CONFIG_BLOCK_RE = re.compile(r"^\s*\{\{\s*config\s*\(.*?\)\s*\}\}", re.DOTALL)


def is_annotation_line(line: str) -> bool:
    """True when ``line`` is an annotation directive, not prose.

    ``line`` may carry any leading whitespace (it's tested after a ``.strip()``
    in the metric-header parser).
    """
    return bool(ANNOTATION_LINE_RE.match(line))


def parse_annotations(file_text: str) -> dict[str, str]:
    """Return the ``{KEY_UPPER: value}`` annotations from a file's leading block.

    Reads ONLY the leading header — the config line plus the leading blank and
    ``--`` comment lines, the same region ``_strip_config_and_header`` removes.
    Scanning stops at the first line that is neither blank nor a comment, so a
    ``-- COMBINER_DEFAULT`` comment inside the SQL body is ignored on purpose.

    Keys are upper-cased; the first occurrence of a key wins (a later duplicate
    is a typo, not an override). Values are returned verbatim (stripped).
    """
    if not file_text:
        return {}

    text = _CONFIG_BLOCK_RE.sub("", file_text, count=1)

    found: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "" or stripped.startswith("--"):
            m = ANNOTATION_LINE_RE.match(line)
            if m:
                key = m.group(1).upper()
                if key not in found:
                    found[key] = m.group(2).strip()
            continue
        # First non-blank, non-comment line ends the leading header block.
        break
    return found
