# ------------------------------------------------------------------------
# mesa-core (c) 2026 Mesantic LLC. MIT License (see LICENSE).
# MESA(tm) and Mesantic(tm) are trademarks of Mesantic LLC.
# ------------------------------------------------------------------------
"""MESA Security Rules — Versionable Security & Safety Checks.

Ported verbatim from the governance repo's ``api/services/security_rules.py``
(SPEC_70). These are versionable governance checks (MESA-SEC-*) that scan for
security and safety issues in SQL definitions. Unlike CORE rules, these can
have their severity tuned and entities can pin to older versions.

``mesa evaluate`` rolls these up as scorecard lines (Group 5). ``mesa
validate`` gates only on the blocking subset — keeping evaluate advisory and
validate the gate is the whole point of SPEC_71.

This module is pure stdlib (re + math) — no fastapi, no sqlalchemy, no
aiosqlite, no pydantic.
"""

import re
import math
from dataclasses import dataclass
from typing import Literal


@dataclass
class SecFinding:
    """A security rule finding."""
    rule_code: str
    rule_name: str
    severity: Literal["blocking", "warn", "info"]
    message: str
    match_text: str | None = None  # The actual problematic text found


# ── MESA-SEC-001: Hardcoded secrets / credentials ───────────────────────────


def scan_secrets(sql: str) -> list[SecFinding]:
    """Scan for hardcoded secrets, API keys, credentials, and high-entropy
    literals. Default severity "blocking"."""
    findings: list[SecFinding] = []

    # AWS Access Key ID pattern
    aws_key_pattern = r"AKIA[0-9A-Z]{16}"
    for match in re.finditer(aws_key_pattern, sql):
        findings.append(SecFinding(
            rule_code="MESA-SEC-001",
            rule_name="No hardcoded secrets",
            severity="blocking",
            message="AWS Access Key ID detected in SQL. Never hardcode credentials.",
            match_text=match.group(0),
        ))

    # password/secret/api_key assignment patterns
    cred_pattern = r"(?i)(password|pwd|secret|api[_-]?key)\s*[:=]\s*['\"]([^'\"]+)['\"]"
    for match in re.finditer(cred_pattern, sql):
        findings.append(SecFinding(
            rule_code="MESA-SEC-001",
            rule_name="No hardcoded secrets",
            severity="blocking",
            message=f"Credential assignment detected: {match.group(1)}. Use secret management instead.",
            match_text=match.group(0),
        ))

    # Private key blocks
    private_key_pattern = r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    if re.search(private_key_pattern, sql):
        findings.append(SecFinding(
            rule_code="MESA-SEC-001",
            rule_name="No hardcoded secrets",
            severity="blocking",
            message="Private key detected in SQL. Never embed keys in definitions.",
            match_text="[PRIVATE KEY BLOCK]",
        ))

    # JWT token pattern (eyJ... base64 segments)
    jwt_pattern = r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    for match in re.finditer(jwt_pattern, sql):
        findings.append(SecFinding(
            rule_code="MESA-SEC-001",
            rule_name="No hardcoded secrets",
            severity="blocking",
            message="JWT token detected in SQL. Tokens must not be hardcoded.",
            match_text=match.group(0)[:20] + "...",  # Truncate for display
        ))

    # High-entropy base64/hex literals (likely secrets)
    literal_pattern = r"['\"]([A-Za-z0-9+/=]{32,}|[0-9a-fA-F]{32,})['\"]"
    for match in re.finditer(literal_pattern, sql):
        literal = match.group(1)
        entropy = _shannon_entropy(literal)
        if entropy > 4.5 and len(literal) >= 32:
            findings.append(SecFinding(
                rule_code="MESA-SEC-001",
                rule_name="No hardcoded secrets",
                severity="blocking",
                message=(
                    f"High-entropy literal detected (entropy={entropy:.2f}). "
                    f"Likely a secret or token. Use secret management."
                ),
                match_text=literal[:20] + "...",
            ))

    return findings


def _shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not s:
        return 0.0
    entropy = 0.0
    for x in range(256):
        p_x = s.count(chr(x)) / len(s)
        if p_x > 0:
            entropy += - p_x * math.log2(p_x)
    return entropy


# ── MESA-SEC-002: PII literals ───────────────────────────────────────────────


def scan_pii_literals(sql: str) -> list[SecFinding]:
    """Scan for PII literals (SSN, email). Default severity "warn"."""
    findings: list[SecFinding] = []

    ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"
    for match in re.finditer(ssn_pattern, sql):
        findings.append(SecFinding(
            rule_code="MESA-SEC-002",
            rule_name="No PII literals",
            severity="warn",
            message="SSN pattern detected in SQL. Verify this is not real PII.",
            match_text=match.group(0),
        ))

    email_in_literal_pattern = r"['\"]([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})['\"]"
    for match in re.finditer(email_in_literal_pattern, sql):
        findings.append(SecFinding(
            rule_code="MESA-SEC-002",
            rule_name="No PII literals",
            severity="warn",
            message=(
                f"Email address in literal: {match.group(1)}. "
                f"If this is real PII, remove it. If it's a test/example value, consider clarifying."
            ),
            match_text=match.group(1),
        ))

    return findings


# ── Helper: combine all security scans ──────────────────────────────────────


def scan_all_security_rules(sql: str) -> list[SecFinding]:
    """Run all MESA-SEC-* scans and return combined findings."""
    findings: list[SecFinding] = []
    findings.extend(scan_secrets(sql))
    findings.extend(scan_pii_literals(sql))
    findings.extend(scan_safe_cast(sql))
    findings.extend(scan_divide_by_zero(sql))
    findings.extend(scan_case_insensitive_comparisons(sql))
    findings.extend(scan_select_distinct(sql))
    return findings


# ── MESA-SEC-003: SAFE_CAST / TRY_CAST only ─────────────────────────────────


def scan_safe_cast(sql: str) -> list[SecFinding]:
    """Check for bare CAST without SAFE_CAST/TRY_CAST. Exempts string casts
    inside a hash-ID formula. Default severity "warn"."""
    findings: list[SecFinding] = []

    cast_pattern = r"(?<![A-Z_])CAST\s*\("

    for match in re.finditer(cast_pattern, sql, re.IGNORECASE):
        pos = match.start()
        context_start = max(0, pos - 60)
        context = sql[context_start:pos + 20]

        hash_patterns = [
            r"base64_encode\s*\(\s*sha2",
            r"to_base64\s*\(\s*sha256",
            r"base64\s*\(\s*from_hex\s*\(\s*sha256",
            r"sha2\s*\(",
            r"sha256\s*\(",
            r"md5\s*\(",
        ]
        is_in_hash = any(re.search(pat, context, re.IGNORECASE) for pat in hash_patterns)

        cast_content_match = re.search(
            r"CAST\s*\([^)]+\s+AS\s+(STRING|VARCHAR)",
            sql[pos:pos + 100],
            re.IGNORECASE
        )
        is_string_cast = cast_content_match is not None

        if is_in_hash and is_string_cast:
            continue

        findings.append(SecFinding(
            rule_code="MESA-SEC-003",
            rule_name="Use SAFE_CAST / TRY_CAST, not bare CAST",
            severity="warn",
            message=(
                "Bare CAST detected. Use SAFE_CAST (BigQuery) or TRY_CAST (Snowflake) "
                "to handle dirty data gracefully. Bare CAST kills the query on type errors."
            ),
            match_text=sql[pos:pos + 40],
        ))

    return findings


# ── MESA-SEC-004: Divide-by-zero guard ──────────────────────────────────────


def scan_divide_by_zero(sql: str) -> list[SecFinding]:
    """Check for division whose denominator isn't NULLIF-protected. Warn."""
    findings: list[SecFinding] = []

    division_pattern = r"(\w[\w\s.()]+)\s*/\s*([^/\s][^\n,)]+)"

    for match in re.finditer(division_pattern, sql):
        numerator = match.group(1).strip()
        denominator = match.group(2).strip()

        if "nullif" not in denominator.lower():
            findings.append(SecFinding(
                rule_code="MESA-SEC-004",
                rule_name="Divide-by-zero guard required",
                severity="warn",
                message=(
                    f"Division without NULLIF protection: {match.group(0)}. "
                    f"Wrap denominator in NULLIF({denominator}, 0) to prevent divide-by-zero errors."
                ),
                match_text=match.group(0),
            ))

    return findings


# ── MESA-SEC-005: No LEFT/RIGHT JOIN to ref() in metric layer ───────────────


def scan_metric_left_join(sql: str, is_metric_layer: bool = True) -> list[SecFinding]:
    """Check for LEFT/RIGHT JOIN to ref() in metric layer. Blocking."""
    findings: list[SecFinding] = []

    if not is_metric_layer:
        return findings

    pattern = re.compile(
        r"(LEFT\s+JOIN|RIGHT\s+JOIN)\s+"
        r"\{\{\s*ref\(\s*['\"][\w]+['\"]\s*\)\s*\}\}",
        re.IGNORECASE,
    )

    for match in pattern.finditer(sql):
        findings.append(SecFinding(
            rule_code="MESA-SEC-005",
            rule_name="No LEFT/RIGHT JOIN to ref() in metric layer",
            severity="blocking",
            message=(
                f"{match.group(1).upper()} to ref() detected. "
                f"Metric-to-metric joins must use INNER JOIN (plain JOIN). "
                f"LEFT JOIN hides missing rows as NULLs. If you need a zero-fill pattern, "
                f"join to a local CTE, not directly to a ref()."
            ),
            match_text=match.group(0),
        ))

    return findings


# ── MESA-SEC-006: Text comparison case-folding ───────────────────────────────


def scan_case_insensitive_comparisons(sql: str) -> list[SecFinding]:
    """Check for text comparisons to literals without UPPER()/LOWER(). Warn."""
    findings: list[SecFinding] = []

    comparison_pattern = r"(\w+[\w.]*)\s*(=|!=|<>|IN)\s*\(?\s*['\"]([^'\"]+)['\"]"

    for match in re.finditer(comparison_pattern, sql, re.IGNORECASE):
        column = match.group(1)
        operator = match.group(2)
        literal = match.group(3)

        context_start = max(0, match.start() - 30)
        context = sql[context_start:match.end()]

        if "upper" not in context.lower() and "lower" not in context.lower():
            findings.append(SecFinding(
                rule_code="MESA-SEC-006",
                rule_name="Text comparisons must case-fold",
                severity="warn",
                message=(
                    f"Text comparison without case-folding: {match.group(0)}. "
                    f"Wrap both sides in UPPER() or LOWER() to avoid case-sensitivity bugs."
                ),
                match_text=match.group(0),
            ))

    return findings


# ── MESA-SEC-007: No SELECT DISTINCT as dedup crutch ────────────────────────


def scan_select_distinct(sql: str) -> list[SecFinding]:
    """Check for SELECT DISTINCT, which usually hides a grain problem. Warn."""
    findings: list[SecFinding] = []

    if re.search(r"\bSELECT\s+DISTINCT\b", sql, re.IGNORECASE):
        findings.append(SecFinding(
            rule_code="MESA-SEC-007",
            rule_name="No SELECT DISTINCT as a dedup crutch",
            severity="warn",
            message=(
                "SELECT DISTINCT detected. DISTINCT usually hides a grain problem. "
                "Use explicit GROUP BY or fix the join to produce the correct grain. "
                "grain_guard can help diagnose the real issue."
            ),
            match_text="SELECT DISTINCT",
        ))

    return findings
