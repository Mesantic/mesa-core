# Contributing to MESA Core

MESA Core is the free, stateless compiler — the forkable standard syntax for the
four-tier architecture. Mesantic is the paid, stateful hosted layer that sits on
top of the same compiler.

## The line (non-negotiable)

MESA Core is **pure, stateless, one-shot** — same input always yields the same
output, no memory of the past, no watching of the future, no human coordination.

That means, concretely, the package must NEVER import `fastapi`, `sqlalchemy`,
`aiosqlite`, `pydantic`, or anything under `api.*`. The only runtime dependencies
are `sqlglot`, `click`, `pyyaml`, and `duckdb`.

Before a PR, run the import-purity gate:

```
grep -rnE '^\s*(import|from)\s+(fastapi|sqlalchemy|aiosqlite|pydantic|api)\b|^\s*from\s+api\.' mesa_core --include='*.py'
```

It must print nothing.

## What goes where

- **Free (here):** the compiler, the validation brain (`grain_guard`,
  `core_rules`, `mesa_verifier`), the formatter, all warehouse dialects, the CLI,
  and the mechanical `mesa new entity` scaffolder.
- **Paid (Mesantic, not here):** drift, discovery, ontology, gold-table
  decomposition, approvals, audit chains, RBAC, billing, the hosted server.

## Hard boundaries

1. All warehouse dialects ship free — never paywall one.
2. `mesa new entity` reads a **column list only**. It must never parse,
   interpret, or classify an existing gold table's CTEs or metric logic — that
   is Mesantic's job (SPEC_63), permanently out of scope.
3. Behavior-preserving extraction. The compiler is extracted from Mesantic's
   governance repo; don't "improve" it while extracting it. Parity is proven by
   the CAO acceptance diff.

## Tests

```
python -m pytest tests/ -q
```

## License

MIT. Contributions are licensed under the same terms.
