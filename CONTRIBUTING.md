# Contributing to MESA Core

MESA Core is the compiler for the four-tier architecture: the parser, the
validation rules, the formatter, and the warehouse dialects. It's designed to
run standalone, on one machine, with no external services.

## Keep it dependency-free

MESA Core must never import `fastapi`, `sqlalchemy`, `aiosqlite`, `pydantic`,
or anything under `api.*`. Runtime dependencies are limited to `sqlglot`,
`click`, `pyyaml`, and `duckdb`.

Check before opening a PR:

```
grep -rnE '^\s*(import|from)\s+(fastapi|sqlalchemy|aiosqlite|pydantic|api)\b|^\s*from\s+api\.' mesa_core --include='*.py'
```

It should print nothing. A PR that adds one of these will fail CI.

## Scope for PRs

- Compiler, validation rules (`grain_guard`, `core_rules`, `mesa_verifier`),
  formatter, warehouse dialects, CLI, and the `mesa new entity` scaffolder are
  all in scope here.
- `mesa new entity` only reads a column list — it doesn't parse, interpret, or
  classify an existing table's CTEs or metric logic. That kind of analysis is
  out of scope for this repo.
- This compiler was extracted from a larger internal repo, so keep changes
  behavior-preserving rather than introducing new behavior in the same PR —
  open a separate PR for behavior changes so they're easy to review on their
  own.

## Tests

```
python -m pytest tests/ -q
```

## License

MIT. Contributions are licensed under the same terms.
