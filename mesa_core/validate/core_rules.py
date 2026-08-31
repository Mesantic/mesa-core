# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""
MESA Core Rules — Immutable Architectural Invariants
=====================================================

These rules define what MESA IS. They cannot be versioned, disabled, or bypassed.
They are enforced in code, not in the database, so no DB manipulation can remove them.

Two paths into MESA metric authoring:

  Path A — Guided authoring (POST /v1/metrics/guided):
      User provides entity + metric_name + expression only.
      The API generates canonical SQL. Core rule violations are structurally impossible
      because the user never writes the FROM clause, identity column, or source path.

  Path B — Raw SQL authoring (POST /v1/metrics):
      User provides full definition_sql. Core rules are validated before saving.
      Any violation returns HTTP 422 with the specific rule violated.
      There is no override.

The distinction between the two rule tiers:

  MESA-CORE-*   Immutable. Define the architectural contract.
                Cannot be versioned, disabled, or sandboxed.
                Violations block the API call — hard stop.

  MESA-007+     Governance rules. Define best practices.
                Can be versioned via Rule Lab, severity can escalate,
                new rules can be added, entities can pin to older versions
                during grace periods.
"""

import re
from dataclasses import dataclass


# ── Core Rule Definitions ───────────────────────────────────────────────────
# These are Python constants. They live in code, not in any database table.
# No API endpoint can modify them. No migration can drop them.

CORE_RULES: dict[str, dict] = {
    "MESA-CORE-001": {
        "name": "No raw warehouse paths",
        "description": (
            "Metric SQL must not contain three-part warehouse paths (e.g. raw_db.prod.orders, "
            "RAW.SCHEMA.TABLE). Metrics must reference the registered entity's semantic base table — "
            "which the guided authoring path injects automatically via dbt source() references. "
            "Hardcoding a warehouse path bypasses entity isolation, breaks portability across warehouses, "
            "and removes the audit link between the metric and its registered entity."
        ),
        "why_immutable": (
            "If this rule could be disabled, any metric could point to any raw table anywhere. "
            "Entity isolation collapses. The Wide table compiler cannot guarantee correctness. "
            "MESA ceases to be MESA."
        ),
        "detection": {
            "type": "regex",
            # Three-part paths: word.word.word in a FROM or JOIN clause
            # Also catches two-part paths with known raw prefixes
            "pattern": r"(?:FROM|JOIN)\s+\w+\.\w+\.\w+",
            "flags": re.IGNORECASE,
        },
        "error_message": (
            "Raw warehouse path detected (e.g. raw_db.prod.table). "
            "Use guided authoring (POST /v1/metrics/guided) — the entity's canonical source "
            "reference is injected automatically. Hardcoded warehouse paths violate entity isolation."
        ),
        "bypassed_by_guided_authoring": True,
        "severity": "blocking",
    },

    "MESA-CORE-002": {
        "name": "No SELECT *",
        "description": (
            "Metric SQL must SELECT explicit columns — never SELECT *. "
            "The Wide table compiler relies on deterministic column lists to assemble the struct. "
            "SELECT * produces non-deterministic output: column order changes when the source table "
            "schema changes, the compiler cannot verify identity column presence, and the Wide table "
            "may silently include or drop columns across recompilations."
        ),
        "why_immutable": (
            "SELECT * makes assembly non-deterministic. MESA's core promise is that "
            "compile_from_entity() always produces the same output for the same inputs. "
            "SELECT * breaks that contract unconditionally."
        ),
        "detection": {
            "type": "regex",
            "pattern": r"SELECT\s+\*",
            "flags": re.IGNORECASE,
        },
        "error_message": (
            "SELECT * is not allowed in metric definitions. "
            "Explicitly list all columns. The Wide table compiler requires a deterministic column list."
        ),
        "bypassed_by_guided_authoring": True,
        "severity": "blocking",
    },

    "MESA-CORE-003": {
        "name": "Identity column required",
        "description": (
            "Every metric definition must SELECT the entity's identity column (e.g. StakingEvents.ID AS ID) "
            "as its first output column. The Wide table JOIN is keyed on this column. "
            "Without it, the compiler cannot assemble the entity's Wide table — the metric becomes "
            "an island with no way to join back to the entity."
        ),
        "why_immutable": (
            "The Wide table join requires every metric to carry the entity key. "
            "A metric without an identity column output cannot be included in Wide table assembly. "
            "This is the structural contract that makes MESA's join-free consumption possible."
        ),
        "detection": {
            "type": "callable",  # needs entity context — checked in validate_metric_sql()
        },
        "error_message": (
            "Metric SQL must SELECT the entity's identity column as its first output. "
            "Example: SELECT StakingEvents.ID AS ID, <expression> AS <MetricName> FROM ..."
        ),
        "bypassed_by_guided_authoring": True,
        "severity": "blocking",
    },

    "MESA-CORE-004": {
        "name": "Single metric output column",
        "description": (
            "Each metric definition file must produce exactly one metric column (plus the identity column). "
            "One file = one metric = one owner. This is the encapsulation principle that prevents "
            "metric sprawl, enables per-metric ownership, and makes the audit log meaningful. "
            "Bundling multiple metrics into one file defeats all three."
        ),
        "why_immutable": (
            "Ownership, versioning, and governance in MESA are per-metric, not per-file. "
            "If a file produces 5 metrics, ownership of 'which metric changed' is ambiguous. "
            "The audit log cannot attribute a specific metric change to a specific owner decision."
        ),
        "detection": {
            "type": "callable",  # needs entity context — checked in validate_metric_sql()
        },
        "error_message": (
            "Metric definitions must produce exactly one metric column plus the identity column. "
            "Split each metric into its own definition. Use guided authoring to enforce this structurally."
        ),
        "bypassed_by_guided_authoring": True,
        "severity": "blocking",
    },

    "MESA-CORE-005": {
        "name": "Expression must not alias to or collide with the identity column",
        "description": (
            "The expression provided in guided authoring must not produce an alias of 'ID' "
            "(e.g. `SUM(amount) AS ID`) and must not BE the bare identity column itself (e.g. just `ID`). "
            "The identity column is injected automatically by the compiler. "
            "Aliasing a metric output to 'ID' produces a duplicate column in the generated SQL, "
            "which breaks Wide table assembly and downstream joins."
        ),
        "why_immutable": (
            "The Wide table join key is the identity column. If a metric aliases its output to ID, "
            "the compiled SELECT has two ID columns. Every downstream join is ambiguous. "
            "This cannot be tolerated; the identity contract is non-negotiable."
        ),
        "detection": {
            "type": "regex",
            # Catches: anything AS ID (case-insensitive), OR expression that IS just the bare word ID
            "pattern": r"(?:\bAS\s+ID\b)|(?:^\s*ID\s*$)",
            "flags": re.IGNORECASE,
        },
        "error_message": (
            "Expression must not alias to or be the identity column (ID). "
            "The identity column is injected automatically. "
            "Example: write `SUM(Amount)` not `SUM(Amount) AS ID`."
        ),
        "bypassed_by_guided_authoring": False,  # enforced ON the guided expression itself
        "severity": "blocking",
    },

    "MESA-CORE-006": {
        "name": "Expression must be a non-trivial transformation",
        "description": (
            "The expression field in guided authoring must not be empty, whitespace-only, or a bare "
            "column reference with no transformation (e.g. just `Amount` or `events.Amount`). "
            "A metric encapsulates a business-rule computation. A bare column passthrough is not a "
            "metric — it provides no governance value, duplicates the raw layer, and pollutes the "
            "Wide table with redundant columns."
        ),
        "why_immutable": (
            "Allowing bare column passthroughs as metrics defeats MESA's semantic contract. "
            "Every column in the Metric layer must represent a named, owner-attributed business rule. "
            "A raw column copy has no owner, no rule, and no audit significance."
        ),
        "detection": {
            "type": "callable",  # checked procedurally in validate_expression()
        },
        "error_message": (
            "Expression is empty or is a bare column reference with no transformation. "
            "Write a SQL expression that computes a metric value — e.g. `SUM(Amount)`, "
            "`COUNT(CASE WHEN Status = 'settled' THEN 1 END)`, or `MAX(EventDate)`."
        ),
        "bypassed_by_guided_authoring": False,
        "severity": "blocking",
    },
}


# ── Validation Engine ────────────────────────────────────────────────────────

@dataclass
class CoreRuleViolation:
    rule_code: str
    rule_name: str
    error_message: str


def validate_metric_sql(
    definition_sql: str,
    entity_name: str,
    identity_column: str,
) -> list[CoreRuleViolation]:
    """
    Run all applicable core rules against a raw metric SQL definition.
    Returns a list of violations. Empty list = SQL is MESA-compliant.

    Called on POST /v1/metrics (raw SQL path).
    NOT called on POST /v1/metrics/guided — guided authoring is structurally safe by construction.
    """
    violations: list[CoreRuleViolation] = []

    # MESA-CORE-001: No raw warehouse paths
    rule = CORE_RULES["MESA-CORE-001"]
    pattern = rule["detection"]["pattern"]
    flags = rule["detection"]["flags"]
    if re.search(pattern, definition_sql, flags):
        violations.append(CoreRuleViolation(
            rule_code="MESA-CORE-001",
            rule_name=rule["name"],
            error_message=rule["error_message"],
        ))

    # MESA-CORE-002: No SELECT *
    rule = CORE_RULES["MESA-CORE-002"]
    if re.search(rule["detection"]["pattern"], definition_sql, rule["detection"]["flags"]):
        violations.append(CoreRuleViolation(
            rule_code="MESA-CORE-002",
            rule_name=rule["name"],
            error_message=rule["error_message"],
        ))

    # MESA-CORE-003: Identity column required
    # The metric SQL must SELECT <prefix>.<IdentityColumn> AS <IdentityColumn>
    # <prefix> can be the entity name OR a parent metric name (for derived metrics).
    identity_pattern = re.compile(
        rf"\b\w+\s*\.\s*{re.escape(identity_column)}\s+AS\s+{re.escape(identity_column)}\b",
        re.IGNORECASE,
    )
    if not identity_pattern.search(definition_sql):
        violations.append(CoreRuleViolation(
            rule_code="MESA-CORE-003",
            rule_name=CORE_RULES["MESA-CORE-003"]["name"],
            error_message=(
                f"Metric SQL must include '{entity_name}.{identity_column} AS {identity_column}' "
                f"in its SELECT list. This is the join key for Wide table assembly."
            ),
        ))

    # MESA-CORE-004: Single metric output column
    # Heuristic: count the depth-0 AS aliases in the SELECT list, subtract the
    # identity column. Scalar-subquery FROM aliases and type casts (CAST(... AS
    # TYPE)) sit inside parentheses and are skipped, so only true output columns
    # count. More than 1 non-identity alias = multiple metrics in one file.
    select_block = _extract_select_block(definition_sql)
    if select_block:
        non_identity_aliases = _count_select_output_aliases(select_block, identity_column)
        if len(non_identity_aliases) > 1:
            violations.append(CoreRuleViolation(
                rule_code="MESA-CORE-004",
                rule_name=CORE_RULES["MESA-CORE-004"]["name"],
                error_message=(
                    f"Found {len(non_identity_aliases)} metric columns: {non_identity_aliases}. "
                    f"Each metric definition must produce exactly one metric column. "
                    f"Split into separate metric definitions."
                ),
            ))

    return violations


def validate_expression(expression: str) -> list[CoreRuleViolation]:
    """
    Validate a guided-authoring expression (the right-hand side of `<expression> AS <MetricName>`).

    Enforces:
      MESA-CORE-001: No embedded three-part raw warehouse paths.
      MESA-CORE-005: Expression must not alias to or be the identity column (AS ID / bare ID).
      MESA-CORE-006: Expression must not be empty, whitespace-only, or a bare column reference.

    Since guided authoring generates the FROM clause and SELECT structure, CORE-002 / 003 / 004
    are structurally impossible and are not re-checked here.
    """
    violations: list[CoreRuleViolation] = []

    # Normalise None → empty string so all guards can operate on a string type.
    if expression is None:
        expression = ""

    # ── MESA-CORE-001: No raw warehouse paths embedded in the expression ────
    rule_001 = CORE_RULES["MESA-CORE-001"]
    if re.search(rule_001["detection"]["pattern"], expression, rule_001["detection"]["flags"]):
        violations.append(CoreRuleViolation(
            rule_code="MESA-CORE-001",
            rule_name=rule_001["name"],
            error_message=rule_001["error_message"],
        ))

    # ── MESA-CORE-005: Expression must not produce an ID alias or be bare ID ─
    rule_005 = CORE_RULES["MESA-CORE-005"]
    if re.search(rule_005["detection"]["pattern"], expression, rule_005["detection"]["flags"]):
        violations.append(CoreRuleViolation(
            rule_code="MESA-CORE-005",
            rule_name=rule_005["name"],
            error_message=rule_005["error_message"],
        ))

    # ── MESA-CORE-006: Expression must be a non-trivial transformation ───────
    # Empty / whitespace-only
    stripped = expression.strip() if expression else ""
    if not stripped:
        rule_006 = CORE_RULES["MESA-CORE-006"]
        violations.append(CoreRuleViolation(
            rule_code="MESA-CORE-006",
            rule_name=rule_006["name"],
            error_message=rule_006["error_message"],
        ))
    else:
        # Bare column reference: an identifier (optionally table-qualified, e.g. entity.col)
        # with no function call, operator, CASE, or arithmetic.
        # Pattern: optional "word." prefix + word + optional whitespace = entire expression.
        # We also allow "entity.col" as two-part (which is fine syntactically but is a passthrough).
        _bare_col = re.compile(
            r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?$",
            re.IGNORECASE,
        )
        if _bare_col.match(stripped):
            rule_006 = CORE_RULES["MESA-CORE-006"]
            violations.append(CoreRuleViolation(
                rule_code="MESA-CORE-006",
                rule_name=rule_006["name"],
                error_message=rule_006["error_message"],
            ))

    return violations


def _extract_select_block(sql: str) -> str | None:
    """
    Extract the text between the OUTERMOST (depth-0) SELECT and its FROM for
    single-metric analysis.

    This is CTE-aware: a metric written ``WITH X AS (SELECT ... ) SELECT ID,
    expr AS M FROM X`` returns only the final ``ID, expr AS M`` block. A naive
    "first SELECT ... FROM" grab would return the CTE's inner columns (and even
    ``CAST(... AS VARCHAR)`` inside a CTE), miscounting a single-output metric
    as multi-output (SPEC_66 addendum Bug 3).

    Returns None if the structure can't be parsed.
    """
    block = _extract_final_select_block(sql)
    return block


def _extract_final_select_block(sql: str) -> str | None:
    """Return the slice between the last depth-0 ``SELECT`` and the next
    depth-0 ``FROM``, tracking parenthesis depth so CTE inner-SELECTs (depth >= 1)
    are skipped.

    Uses the same balanced-paren walk as mesa_verifier._find_cross_row_aggregates
    and CAO's _extract_object_casts — copy that pattern, don't reinvent it.
    """
    if not sql:
        return None

    select_pos = None
    from_pos = None
    depth = 0
    i = 0
    n = len(sql)
    # Track the last depth-0 SELECT.
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and sql[i:i + 6].upper() == "SELECT" \
                and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            select_pos = i
        i += 1

    if select_pos is None:
        # No depth-0 SELECT found — fall back to the first SELECT anywhere.
        m = re.search(r"\bSELECT\b(.*?)\bFROM\b", sql, re.IGNORECASE | re.DOTALL)
        return m.group(1) if m else None

    # Walk forward from select_pos to find the next depth-0 FROM.
    depth = 0
    i = select_pos
    while i < n:
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and sql[i:i + 4].upper() == "FROM" \
                and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            from_pos = i
            break
        i += 1

    if from_pos is None:
        # No FROM after the final SELECT — return everything after SELECT.
        return sql[select_pos + len("SELECT"):].strip() or None

    return sql[select_pos + len("SELECT"):from_pos]


def _count_select_output_aliases(select_block: str, identity_column: str) -> list[str]:
    """Return the top-level (depth-0) ``AS <alias>`` names in a SELECT block,
    excluding the identity column.

    Depth-awareness is what makes this correct: a scalar subquery's FROM alias
    (``... FROM TABLE(FLATTEN(...)) AS Response``) and a type cast
    (``TRY_CAST(... AS NUMBER)``) both sit inside parentheses (depth >= 1), so
    they are skipped. Only aliases at the SELECT's own top level count as output
    columns — which is exactly what "one metric output column" means
    (SPEC_66 addendum Bug 3, residual scalar-subquery case).
    """
    aliases: list[str] = []
    depth = 0
    i = 0
    n = len(select_block)
    while i < n:
        ch = select_block[i]
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0 and select_block[i:i + 2].upper() == "AS":
            # Word boundary: "AS" must not be part of a larger identifier.
            before_ok = i == 0 or not (select_block[i - 1].isalnum() or select_block[i - 1] == "_")
            after_ok = i + 2 >= n or select_block[i + 2].isspace()
            if before_ok and after_ok:
                m = re.match(r"AS\s+([A-Za-z_][A-Za-z0-9_]*)", select_block[i:], re.IGNORECASE)
                if m:
                    aliases.append(m.group(1))
                    i += m.end()
                    continue
        i += 1

    return [a for a in aliases if a.upper() != identity_column.upper()]


def is_core_rule(rule_code: str) -> bool:
    """Returns True if the code refers to an immutable MESA core rule."""
    return rule_code.upper().startswith("MESA-CORE-")


def get_all_core_rules() -> dict[str, dict]:
    """Return the full core rule registry. Read-only — never mutate this dict."""
    return {k: {**v, "is_versionable": False, "is_disableable": False} for k, v in CORE_RULES.items()}


# ── View Core Rules (SPEC_17) ────────────────────────────────────────────────
# VIEW-CORE rules are as immutable as MESA-CORE rules.
# They enforce the strict 4-tier DAG: a View may ONLY read from a widetable tier.

# Regex to detect {{ ref('Name') }} references in Jinja SQL
_VIEW_REF_RE = re.compile(
    r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
    re.IGNORECASE,
)

# Regex to detect {{ source('src', 'tbl') }} — raw-source references are banned in Views
_VIEW_SOURCE_RE = re.compile(
    r"\{\{\s*source\s*\(",
    re.IGNORECASE,
)

# A widetable ref must end with "WideTable" (MESA naming convention)
_WIDETABLE_SUFFIX = "widetable"

# Aggregation functions that define new metrics — banned in Views
_AGG_FUNCTIONS = re.compile(
    r"\b(SUM|AVG|COUNT|MIN|MAX|STDDEV|VARIANCE|MEDIAN|PERCENTILE)\s*\(",
    re.IGNORECASE,
)

# Pattern: entity ID aliased as <EntityName>ID (required by Business Views standard)
# We check that ID is present in the SELECT; exact alias validation done via entity context.
_ID_PRESENCE_RE = re.compile(r"\bID\b", re.IGNORECASE)


def validate_view_sql(
    select_sql: str,
    entity_name: str,
) -> list[CoreRuleViolation]:
    """
    Validate a View SQL definition against View core rules.

    View core rules (immutable, same weight as MESA-CORE-*):
      VIEW-CORE-001: May only ref() a widetable — no raw sources, no metric refs, no view refs.
      VIEW-CORE-002: No new metric definitions (no top-level aggregate expressions).
      VIEW-CORE-003: Must carry the entity ID aliased as <EntityName>ID.
      VIEW-CORE-004: No {{ source(...) }} calls — Views sit above the widetable tier.

    Called on POST /v1/views (raw SQL path) and POST /v1/views/{id}/test.
    NOT called on POST /v1/views/guided — guided authoring is structurally safe by construction.

    Returns a list of violations. Empty list = SQL is compliant.
    """
    violations: list[CoreRuleViolation] = []

    # VIEW-CORE-004: No {{ source(...) }} — raw-source access forbidden in Views
    if _VIEW_SOURCE_RE.search(select_sql):
        violations.append(CoreRuleViolation(
            rule_code="VIEW-CORE-004",
            rule_name="No raw source references in Views",
            error_message=(
                "Views may not use {{ source(...) }}. "
                "Views sit at tier 4 of the MESA stack and must read only from a Widetable. "
                "Raw source references bypass entity isolation and the metric governance layer."
            ),
        ))

    # VIEW-CORE-001: Every ref() must point to a widetable (ends with 'WideTable')
    non_widetable_refs: list[str] = []
    for m in _VIEW_REF_RE.finditer(select_sql):
        ref_name = m.group(1)
        if not ref_name.lower().endswith(_WIDETABLE_SUFFIX):
            non_widetable_refs.append(ref_name)

    if non_widetable_refs:
        violations.append(CoreRuleViolation(
            rule_code="VIEW-CORE-001",
            rule_name="Views may only ref() a widetable",
            error_message=(
                f"View SQL references non-widetable object(s): {non_widetable_refs}. "
                f"Views may only read from a Widetable (names ending in 'WideTable'). "
                f"You may not ref() raw entities, metrics, or other views — "
                f"doing so breaks the strict 4-tier DAG contract."
            ),
        ))

    # VIEW-CORE-002: No new metric definitions (aggregate expressions)
    agg_match = _AGG_FUNCTIONS.search(select_sql)
    if agg_match:
        violations.append(CoreRuleViolation(
            rule_code="VIEW-CORE-002",
            rule_name="No new metric definitions in Views",
            error_message=(
                f"View SQL contains an aggregation function ({agg_match.group(0).strip()}). "
                f"Views are flat SELECT / filter / rename / period aggregation only — "
                f"they must not define new metrics. "
                f"New aggregations belong in the Metrics (calc) tier."
            ),
        ))

    # VIEW-CORE-003: Entity ID must be present (as <EntityName>ID)
    # We check for the aliased form: <anything> AS <EntityName>ID
    entity_id_alias = f"{entity_name}ID"
    id_alias_pattern = re.compile(
        rf"\bAS\s+{re.escape(entity_id_alias)}\b",
        re.IGNORECASE,
    )
    if not id_alias_pattern.search(select_sql):
        violations.append(CoreRuleViolation(
            rule_code="VIEW-CORE-003",
            rule_name="Entity ID must be aliased as <EntityName>ID",
            error_message=(
                f"View SQL must include the entity ID aliased as '{entity_id_alias}' "
                f"(e.g. `CustomerWideTable.ID AS {entity_id_alias}`). "
                f"This is required by the MESA Business Views standard for consumer joins."
            ),
        ))

    return violations
