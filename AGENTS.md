# Repository Guidelines

## Project Structure & Module Organization
- `src/conf/`: environment loading and settings (`env.py` reads `.env`).
- `src/db/`: database engine/session setup, SQLAlchemy models, and data mappers.
- `src/service/`: business workflows (for example, KB ingestion and hybrid retrieval).
- `src/utils/`: file parsing and embedding API helpers.
- `scripts/`: local helper scripts (for example, `run_vdb.sh` for pgvector).
- `examples/`: ad-hoc usage examples.
- `tests/`: currently present but empty. Note: `pyproject.toml` points pytest to `src/tests`.

## Build, Test, and Development Commands
- `uv sync --dev`: install runtime + dev dependencies into the project environment.
- `docker compose up -d pgvector`: start local Postgres with pgvector (mapped to `localhost:45132`).
- `uv run pytest`: run tests with configured options (`-v -s`).
- `uv run python -m src.conf.env`: validate `.env` loading and required settings.
- `uv run python -m src.service.kb_service`: run service smoke path (requires valid `.env` and database).

## Coding Style & Naming Conventions
- Target Python `>=3.11`; use 4-space indentation and PEP 8 spacing/import style.
- Use `snake_case` for functions/variables/modules, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.
- Keep async boundaries explicit: DB and embedding calls should remain `async` and typed.
- Prefer small, focused modules under existing folders (`conf`, `db`, `service`, `utils`) instead of cross-cutting utilities.

## Testing Guidelines
- Framework: `pytest` (configured in `pyproject.toml`).
- Test files should be named `test_*.py`; test functions should be `test_<behavior>()`.
- Place new tests under `src/tests/` (or update `tool.pytest.ini_options.testpaths` if standardizing on `tests/`).
- Cover critical paths: file loading, chunk processing, DB upsert/retrieval, and failure-state handling.

## Commit & Pull Request Guidelines
- Current repo has no commit history yet; adopt a consistent format now: `type(scope): summary` (e.g., `feat(db): add hybrid retrieval mapper`).
- Keep commits atomic and message subjects imperative.
- PRs should include:
  - what changed and why,
  - how it was tested (commands run),
  - any `.env`/database migration impact,
  - linked issue or task ID when available.

## Security & Configuration Tips
- Do not commit `.env` or secrets.
- Required settings are defined in `src/conf/env.py` (DB URLs and API keys must be present before running services/tests).
