# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""MESA raw-layer contract verifier (SPEC_36 Part A re-frame).

Pure, stdlib-only SQL contract verification. Verifies that a warehouse table's
defining SQL conforms to the MESA raw-layer contract.

The contract protects **identity + grain integrity**, NOT source count:

  - Identity MUST be a hashed surrogate (TO_BASE64(SHA256(...)), MD5(...), ...).
    A bare source key (e.g. ``p.part_id AS ID``) is NEVER a valid MESA identity.
  - NO cross-row AGGREGATION in the raw layer (SUM/AVG/COUNT/... over groups
    produce metrics -> Metric layer). BUT row-level transforms are LEGAL and
    expected: SAFE_CAST, IF(flag,1,0), CASE, COALESCE, window functions
    (ROW_NUMBER/LEAD/... OVER) for grain dedup, and nested STRUCT/ARRAY assembly.
  - Enrichment from MANY sources is LEGAL and unlimited. Real production MESA
    raw entities routinely JOIN 15+ sources (e.g. the UKG CustomerSupportCase).
    Source count is NOT a finding. The verifier warns only when the grain is at
    risk (a JOIN with no key equality and no dedup).
  - An audit column is a SOFT nudge, never a hard fail.

Rejections TEACH: every ``block`` finding carries a ``suggestion`` and, where
possible, a ``corrected_snippet`` so the caller can show the fix inline.

Verification is read-only, deterministic, and CI-lockable.

Backward compatibility (SPEC_11 / SPEC_30 drift + discovery):
``verify_raw_contract`` still returns a ``VerificationResult`` exposing the old
``status`` / ``checks{}`` / ``reasons[]`` surface. The new structured
``findings`` list is additive. A compatibility shim maps findings back to the
legacy booleans so existing callers are unaffected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


# -- Finding taxonomy (SPEC_36 Part A) ---------------------------------------

Severity = Literal["block", "warn", "info"]

# Structured finding codes. NOTE: there is intentionally NO "many sources"
# finding -- source count is not a rule.
CODE_ID_UNHASHED = "MESA_RAW_ID_UNHASHED"        # identity is not a hashed surrogate
CODE_ID_PASSTHROUGH = "MESA_RAW_ID_PASSTHROUGH"  # identity aliased from a bare source key
CODE_HAS_AGGREGATE = "MESA_RAW_HAS_AGGREGATE"    # cross-row aggregation produces a metric
CODE_GRAIN_RISK = "MESA_RAW_GRAIN_RISK"          # a JOIN may change the grain (warn)
CODE_BRONZE_NUDGE = "MESA_RAW_BRONZE_NUDGE"      # sourced from a bronze/gold layer (info)
CODE_AUDIT_MISSING = "MESA_RAW_AUDIT_MISSING"    # no audit column detected (info)


@dataclass
class Finding:
    """A single structured verifier finding.

    ``severity`` drives status:
      - ``block`` -> status "contradicted" (cannot publish / run).
      - ``warn``  -> advisory, does not block.
      - ``info``  -> informational nudge (bronze provenance, audit column).
    """
    code: str
    severity: Severity
    message: str
    suggestion: str | None = None
    corrected_snippet: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"code": self.code, "severity": self.severity, "message": self.message}
        if self.suggestion:
            d["suggestion"] = self.suggestion
        if self.corrected_snippet:
            d["corrected_snippet"] = self.corrected_snippet
        return d


@dataclass
class VerificationResult:
    """Result of verifying a table's SQL against the MESA raw-layer contract.

    Legacy surface (SPEC_11) -- kept for backward compatibility:
      - ``status``: "verified" | "shape_only" | "contradicted"
      - ``checks``: {hashed_id, no_metrics, single_source, audit_col}
      - ``reasons``: human-readable notes (derived from findings)

    New surface (SPEC_36):
      - ``findings``: list[Finding] with structured code/severity/suggestion.
    """
    status: str
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def findings_as_dicts(self) -> list[dict]:
        return [f.to_dict() for f in self.findings]

    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "block"]


# -- Heuristic constants ------------------------------------------------------
#
# IMPORTANT: We no longer block on column NAMES alone. The real UKG entity has
# perfectly legal attribute columns whose names contain metric-ish fragments
# (e.g. IdleTimeInBHDays, OverallSatisfaction). Blocking on names false-positives
# on real raw entities. The authoritative signal is a cross-row AGGREGATE
# FUNCTION, not a column name.

# True cross-row aggregate functions. When one of these is called WITHOUT an
# immediately-following OVER (...) window clause, it aggregates across rows and
# belongs in the Metric layer.
_AGGREGATE_FUNCS = (
    "sum", "avg", "average", "count", "min", "max", "stddev", "stddev_pop",
    "stddev_samp", "variance", "var_pop", "var_samp", "listagg", "string_agg",
    "approx_count_distinct", "count_distinct",
)

# NOTE: "array_agg" is deliberately ABSENT from _AGGREGATE_FUNCS. ARRAY_AGG is
# Snowflake's array-NESTING idiom (assemble 1:many child rows into a typed
# ARRAY of OBJECTs on the entity's own grain column) — it builds structure, it
# does NOT summarize across the entity's grain into a scalar metric. Flagging
# it as a cross-row aggregate false-positives every raw entity that nests
# detail the sanctioned way (SPEC_66 addendum Bug 2). string_agg / listagg stay
# listed because those DO flatten to a scalar summary.

# Bronze/gold convenience-layer name heuristics (info-only nudge).
_BRONZE_NAME_FRAGMENTS = ("bronze", "silver", "gold", "_stg_", "staging", "_curated", "curated")

_HASH_FUNC_PATTERN = (
    r"(?:to_base64\s*\(\s*sha256"      # BigQuery: TO_BASE64(SHA256(...))
    r"|base64_encode\s*\(\s*sha2"      # Snowflake: BASE64_ENCODE(SHA2(...))
    r"|sha2|sha256|md5|sha1|crc32|farm_fingerprint)"
)


# -- Identity checks ----------------------------------------------------------

def _check_hashed_identity(sql: str, identity_column: str) -> bool:
    """True if the identity column is produced by a hash function."""
    col_pattern = re.escape(identity_column)
    alias_pattern = (
        rf"(?i)"
        rf"{_HASH_FUNC_PATTERN}"
        rf".*?"
        rf"(?:\s+as\s+{col_pattern}\b|\b{col_pattern}\s*(?:,|\)|$))"
    )
    # DOTALL: the hash expression is often multi-line (Snowflake
    # BASE64_ENCODE(SHA2(<key> || '|' || ..., 256)) AS ID spans several lines),
    # so `.*?` must be allowed to cross newlines to reach the `AS ID`.
    return bool(re.search(alias_pattern, sql, re.DOTALL))


def _find_identity_passthrough(sql: str, identity_column: str) -> str | None:
    """
    Detect a raw (unhashed) source-key passthrough aliased to the identity column.

    Returns the offending expression (e.g. "p.part_id") if the identity column is
    aliased directly from a bare ``<table>.<col>`` reference with no hash wrapper;
    otherwise None. This is the ``p.part_id AS ID`` case the user called out.
    """
    col_pattern = re.escape(identity_column)
    # <alias>.<column> AS <identity_column>  (no function call around it)
    passthrough_pattern = rf"(?i)(?<![\w.])(\w+\.\w+)\s+as\s+{col_pattern}\b"
    for m in re.finditer(passthrough_pattern, sql):
        expr = m.group(1)
        # Ensure the matched expression is not itself the argument of a hash fn
        # right before the AS (that would already be caught by hashed check).
        preceding = sql[max(0, m.start() - 40):m.start()].lower()
        if re.search(_HASH_FUNC_PATTERN, preceding):
            continue
        return expr
    return None


# -- Aggregation vs row-level transform (the key refinement) ------------------

def _find_cross_row_aggregates(sql: str) -> list[str]:
    """
    Find cross-row aggregate function calls that produce standalone metrics.

    An aggregate function is a metric ONLY when it aggregates across rows. It is
    a legal window function (allowed for grain dedup / attribute shaping) when it
    is immediately followed by an ``OVER (...)`` clause.

    Returns the list of offending aggregate function names (lowercased).
    """
    offenders: list[str] = []
    func_alt = "|".join(re.escape(f) for f in _AGGREGATE_FUNCS)
    pattern = re.compile(rf"(?i)\b({func_alt})\s*\(", re.DOTALL)
    for m in pattern.finditer(sql):
        func = m.group(1).lower()
        # Walk from the '(' to its matching ')' to inspect what follows.
        open_idx = sql.index("(", m.start())
        depth = 0
        close_idx = open_idx
        for i in range(open_idx, len(sql)):
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break
        after = sql[close_idx + 1: close_idx + 40].lstrip().lower()
        if after.startswith("over"):
            # Window function -> legal row-level shaping / dedup. Not an aggregate.
            continue
        if after.startswith("within group"):
            # Snowflake ARRAY_AGG(...) WITHIN GROUP (ORDER BY ...) — the sanctioned
            # array-nesting idiom (SPEC_66 addendum Bug 2). Legal shaping, not a summary.
            continue
        offenders.append(func)
    return offenders


# -- Grain-risk heuristic -----------------------------------------------------

def _has_dedup(sql: str) -> bool:
    """True if the SQL applies a grain-dedup (ROW_NUMBER=1 / QUALIFY / DISTINCT)."""
    if re.search(r"(?i)\bqualify\b", sql):
        return True
    if re.search(r"(?i)\bdistinct\b", sql):
        return True
    # ROW_NUMBER() ... OVER (...) paired with a "= 1" filter somewhere.
    if re.search(r"(?i)row_number\s*\(\s*\)\s*over", sql) and re.search(r"(?i)=\s*1\b", sql):
        return True
    return False


def _has_join(sql: str) -> bool:
    return bool(re.search(r"(?i)\bjoin\b", sql))


def _joins_have_key_equality(sql: str) -> bool:
    """
    Rough heuristic: every JOIN has an ON <a> = <b> equality predicate.

    Returns True if all JOINs appear key-joined (grain-safe). We treat a JOIN
    with no ``ON ... = ...`` (e.g. a bare CROSS JOIN) as a grain risk. UNNEST
    fan-outs are deliberate expansions whose grain safety comes from dedup, so
    they are not flagged here.
    """
    parts = re.split(r"(?i)\bjoin\b", sql)
    for segment in parts[1:]:
        head = segment[:400].lower()
        if "unnest" in head:
            continue
        if not re.search(r"(?i)\bon\b.*?=", segment[:400], re.DOTALL):
            return False
    return True


# -- Bronze / audit nudges ----------------------------------------------------

def _detect_bronze_source(sql: str) -> str | None:
    """Return a bronze/staging-looking source name if one is referenced."""
    for kw in ("from", "join"):
        for m in re.finditer(rf"(?i)\b{kw}\s+[`\"']?([\w.$-]+)", sql):
            ref = m.group(1)
            if any(frag in ref.lower() for frag in _BRONZE_NAME_FRAGMENTS):
                return ref
    return None


def _has_audit_column(sql: str) -> bool:
    return bool(re.search(r"(?i)_loaded_at|current_timestamp\s*\(\s*\)", sql))


# -- Main entry point ---------------------------------------------------------

def verify_raw_contract(sql: str, identity_column: str = "ID") -> VerificationResult:
    """
    Verify a table's defining SQL against the MESA raw-layer contract.

    Args:
        sql: The full SQL text (SELECT or CREATE TABLE AS SELECT).
        identity_column: The expected identity column name (default "ID").

    Returns:
        VerificationResult with:
          - ``findings``: structured {code, severity, message, suggestion,
            corrected_snippet?} list (SPEC_36).
          - legacy ``status`` / ``checks`` / ``reasons`` (backward-compat shim).

    Status logic:
      - "contradicted" if ANY ``block`` finding is present.
      - "verified" if identity is hashed and there are no ``block`` findings.
      - "shape_only" if there are no ``block`` findings but identity is unclear.
    """
    findings: list[Finding] = []

    # -- Identity integrity (HARD) --------------------------------------------
    hashed = _check_hashed_identity(sql, identity_column)
    passthrough_expr = _find_identity_passthrough(sql, identity_column)

    if passthrough_expr and not hashed:
        corrected = (
            f"TO_BASE64(SHA256(CAST({passthrough_expr} AS STRING))) AS {identity_column}"
        )
        findings.append(Finding(
            code=CODE_ID_PASSTHROUGH,
            severity="block",
            message=(
                f"Identity column '{identity_column}' is aliased directly from a raw "
                f"source key ('{passthrough_expr}'). A non-MESA source key can never "
                f"be the identity."
            ),
            suggestion=(
                "Wrap the source key in a hashed surrogate so identity is stable and "
                "portable across sources."
            ),
            corrected_snippet=corrected,
        ))
    elif not hashed:
        findings.append(Finding(
            code=CODE_ID_UNHASHED,
            severity="block",
            message=(
                f"Identity column '{identity_column}' is not produced by a hash function."
            ),
            suggestion=(
                "Produce the identity as a hashed surrogate, e.g. "
                "TO_BASE64(SHA256(...)) (BigQuery) or MD5(...)."
            ),
            corrected_snippet=(
                f"TO_BASE64(SHA256(CAST(<source_key> AS STRING))) AS {identity_column}"
            ),
        ))

    # -- Cross-row aggregation (WARN — not block) ------------------------------
    # The RAW contract's HARD guarantees are (1) identity-is-hashed and (2) the
    # grain is not changed. (1) is enforced above as a block. (2) is grain_guard's
    # job, NOT a name-match on aggregate functions. A bare name-match false-positives
    # on three legal raw-layer patterns: increment-watermark MAX(...) reads inside
    # {{ if is_incremental() }} filters, campaign-grain COUNT(DISTINCT x) attributes
    # (one row per campaign), and ARRAY_AGG nesting (which is separately exempted in
    # _find_cross_row_aggregates). So this finding is advisory, never a hard fail —
    # SPEC_66 addendum Bug 2c: warn-not-block.
    aggregate_offenders = _find_cross_row_aggregates(sql)
    if aggregate_offenders:
        uniq = sorted(set(aggregate_offenders))
        findings.append(Finding(
            code=CODE_HAS_AGGREGATE,
            severity="warn",
            message=(
                f"Possible cross-row aggregation detected ({', '.join(uniq)}). Aggregates "
                f"that summarize across rows produce metrics and belong in the Metric "
                f"layer, not the raw entity — but this is a heuristic name-match and may "
                f"flag legal raw-layer patterns (watermark MAX reads, campaign-grain "
                f"COUNT DISTINCT). Confirm this is not changing the entity's grain."
            ),
            suggestion=(
                "Move a genuine summary aggregate to a Metric definition. Keep the raw "
                "entity at one row per entity with row-level attributes only. Window "
                "functions (ROW_NUMBER() OVER (...)) and ARRAY_AGG ... WITHIN GROUP "
                "nesting are allowed. Grain-change enforcement is grain_guard's job."
            ),
        ))

    # -- Grain risk (WARN, never block) ---------------------------------------
    if _has_join(sql) and not _has_dedup(sql) and not _joins_have_key_equality(sql):
        findings.append(Finding(
            code=CODE_GRAIN_RISK,
            severity="warn",
            message=(
                "A JOIN has no key equality and the query has no grain dedup. "
                "This join may change the grain (more than one row per entity)."
            ),
            suggestion=(
                "Confirm one row per entity: add an equality on the business key, or "
                "dedup with ROW_NUMBER() OVER (...) = 1 / QUALIFY / DISTINCT."
            ),
        ))

    # -- Bronze provenance (INFO, never block) --------------------------------
    bronze_ref = _detect_bronze_source(sql)
    if bronze_ref:
        findings.append(Finding(
            code=CODE_BRONZE_NUDGE,
            severity="info",
            message=(
                f"Source '{bronze_ref}' looks like a bronze/staging convenience layer."
            ),
            suggestion=(
                f"Consider sourcing from the underlying raw table rather than "
                f"'{bronze_ref}'. Informational only -- this does not affect defensibility."
            ),
        ))

    # -- Audit column (INFO/soft, never block) --------------------------------
    has_audit = _has_audit_column(sql)
    if not has_audit:
        findings.append(Finding(
            code=CODE_AUDIT_MISSING,
            severity="info",
            message="Audit column (_loaded_at or CURRENT_TIMESTAMP()) not detected.",
            suggestion="Add an audit timestamp column for lineage (soft recommendation).",
        ))

    return _to_result(findings, hashed=hashed)


def _to_result(findings: list[Finding], *, hashed: bool) -> VerificationResult:
    """
    Map structured findings back to the legacy VerificationResult surface so
    existing callers (SPEC_11 discovery scoring, SPEC_30 drift) keep working.

    Legacy checks:
      - hashed_id:      identity is hashed (no ID block finding).
      - no_metrics:     no cross-row aggregation block finding.
      - single_source:  legacy name -- now means "grain is not at risk". True
                        unless a GRAIN_RISK finding is present. (Source count is
                        NOT a finding, so many-source entities stay True.)
      - audit_col:      always True (soft); a reason is added when missing.
    """
    codes = {f.code for f in findings}
    has_block = any(f.severity == "block" for f in findings)

    hashed_id = CODE_ID_UNHASHED not in codes and CODE_ID_PASSTHROUGH not in codes and hashed
    no_metrics = CODE_HAS_AGGREGATE not in codes
    single_source = CODE_GRAIN_RISK not in codes  # legacy key: grain not at risk
    audit_col = True  # soft check never fails

    checks = {
        "hashed_id": hashed_id,
        "no_metrics": no_metrics,
        "single_source": single_source,
        "audit_col": audit_col,
    }

    # Legacy reasons: preserve wording expectations of existing tests.
    reasons: list[str] = []
    for f in findings:
        if f.code == CODE_HAS_AGGREGATE:
            # Existing tests assert a reason containing "metric".
            reasons.append(f"Contains metric-producing aggregation: {f.message}")
        elif f.code == CODE_AUDIT_MISSING:
            reasons.append(
                "Audit column (_loaded_at or CURRENT_TIMESTAMP) not detected (soft check)"
            )
        else:
            reasons.append(f.message)

    # Status.
    if has_block:
        status = "contradicted"
    elif hashed_id:
        status = "verified"
    else:
        status = "shape_only"

    return VerificationResult(
        status=status,
        checks=checks,
        reasons=reasons,
        findings=findings,
    )
