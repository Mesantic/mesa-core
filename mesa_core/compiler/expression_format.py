# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
expression_format.py
====================
Lightweight, dependency-free SQL expression formatter.

Normalizes whitespace and pretty-prints CASE/WHEN/THEN/ELSE/END blocks
with indentation for readability in the guided authoring preview and the
generated L2 metric file.

DELIBERATE SCOPE BOUNDARY: This formats EXPRESSIONS (the right-hand side of
an AS clause), NOT full SQL statements. sqlfluff is already vendored for
full-SQL formatting (api/services/sql_formatter.py). This module is kept
dependency-free so it can run inline during every compile_from_expression
call without the overhead of a full linter pass.

Examples:
    Input:  "CASE WHEN Amount > 100 THEN 'High' WHEN Amount <= 100 THEN 'Low' END"
    Output: "CASE\n  WHEN Amount > 100 THEN 'High'\n  WHEN Amount <= 100 THEN 'Low'\nEND"

    Input:  "UPPER(StakingEvents.RewardState) = 'SETTLED'"
    Output: "UPPER(StakingEvents.RewardState) = 'SETTLED'"
"""

from __future__ import annotations

import re

# Regex to match CASE ... END blocks. CASE and END are required;
# WHEN/THEN/ELSE segments are captured for reformatting.
_CASE_BLOCK_RE = re.compile(
    r'\bCASE\b\s+(.+?)\s+\bEND\b',
    re.IGNORECASE | re.DOTALL,
)

# Tokens within a CASE block that get their own indented line.
_CASE_TOKENS_RE = re.compile(
    r'\b(WHEN|ELSE)\b',
    re.IGNORECASE,
)


def format_expression(expr: str) -> str:
    """
    Format a SQL expression for display in guided authoring previews.

    Normalizes all whitespace (collapses runs, trims) and pretty-prints
    CASE/WHEN/THEN/ELSE/END blocks with 2-space indentation.

    Args:
        expr: The raw user-authored SQL expression.

    Returns:
        The formatted expression. Single-line expressions are returned
        as a single line; CASE expressions are returned with newlines
        and indentation.
    """
    if not expr or not expr.strip():
        return expr.strip() if expr else ""

    # Step 1: Normalize whitespace — collapse all runs into single spaces.
    normalized = " ".join(expr.strip().split())

    # Step 2: Format CASE ... END blocks.
    formatted = _format_case_blocks(normalized)

    return formatted


def _format_case_blocks(expr: str) -> str:
    """
    Find and reformat CASE ... END blocks within the expression.

    Strategy:
      1. Find each CASE ... END block via regex.
      2. Within each block, split on WHEN/ELSE keywords.
      3. Reconstruct with newlines and indentation.
      4. Handle nesting by processing innermost CASE blocks first.
    """
    # We iterate — each pass formats the innermost (no nested CASE) block.
    # This handles arbitrarily nested CASE expressions.
    max_iterations = 10  # safety valve against infinite loops
    for _ in range(max_iterations):
        # Find a CASE block that does NOT contain another CASE inside it
        match = re.search(
            r'\bCASE\b\s+((?:(?!\bCASE\b).)+?)\s+\bEND\b',
            expr,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            break  # no more unformatted CASE blocks

        body = match.group(1)
        full_match = match.group(0)
        start, end = match.start(), match.end()

        formatted_block = _format_single_case_body(body)
        expr = expr[:start] + formatted_block + expr[end:]

    return expr


def _format_single_case_body(body: str) -> str:
    """
    Format the body of a single CASE block (no nested CASE).
    Inserts newlines and indentation before WHEN and ELSE tokens.

    Args:
        body: The content between CASE and END (e.g.
              "WHEN x > 1 THEN 'A' WHEN x <= 1 THEN 'B' ELSE 'C'").

    Returns:
        Formatted block including CASE and END with proper line breaks.
    """
    body = body.strip()

    # Split on WHEN/ELSE boundaries, preserving the tokens
    # We use a marker-based approach to safely split
    parts: list[str] = []
    last_end = 0

    for m in _CASE_TOKENS_RE.finditer(body):
        token = m.group(1).upper()
        # Everything from last_end to m.start() is the previous THEN value
        previous = body[last_end:m.start()].strip()
        if previous:
            parts.append(previous)
        parts.append(f"__TOKEN__{token}")
        last_end = m.end()

    # Remaining after last token
    remainder = body[last_end:].strip()
    if remainder:
        parts.append(remainder)

    # Now reconstruct with proper line breaks
    lines: list[str] = ["CASE"]
    current_line = ""

    for part in parts:
        if part.startswith("__TOKEN__WHEN"):
            # Flush any pending THEN value
            if current_line:
                lines.append(f"  {current_line.strip()}")
                current_line = ""
            current_line = "WHEN"
        elif part.startswith("__TOKEN__ELSE"):
            if current_line:
                lines.append(f"  {current_line.strip()}")
                current_line = ""
            current_line = "ELSE"
        else:
            # Part of a condition or value — append to current line
            if current_line:
                current_line += " " + part
            else:
                current_line = part

    # Flush last line (the ELSE value or final THEN value)
    if current_line:
        lines.append(f"  {current_line.strip()}")

    lines.append("END")
    return "\n".join(lines)
