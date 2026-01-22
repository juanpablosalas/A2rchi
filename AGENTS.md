# Repository Guidelines

## Project Structure & Module Organization
- `src/` holds core (`src/a2rchi`), CLI (`src/cli`), ingestion (`src/data_manager`), interfaces (`src/interfaces`), and utilities (`src/utils`).
- `tests/` includes `smoke/` and `pr_preview_config/`.
- `docs/` contains the mkdocs site; `requirements/` and `src/cli/templates/dockerfiles/` store base image requirements; `examples/` has sample configs.

## Codebase Map
- CLI entrypoint is `src/cli/cli_main.py`, with registries in `src/cli/service_registry.py` and `src/cli/source_registry.py`, and managers in `src/cli/managers/`.
- Service entrypoints live in `src/bin/` and wire Flask apps from `src/interfaces/`.
- Runtime config is loaded from `/root/A2rchi/configs/` by `src/utils/config_loader.py`; CLI deployments render under `~/.a2rchi/a2rchi-<name>` (override with `A2RCHI_DIR`).
- Core orchestration lives in `src/a2rchi/a2rchi.py` with pipelines in `src/a2rchi/pipelines/`; ingestion is in `src/data_manager/`.

## Build, Test, and Development Commands
- `pip install -e .` installs the package in editable mode for local development.
- `a2rchi --help` verifies the CLI entrypoint defined in `pyproject.toml`.
- `cd docs && mkdocs serve` previews documentation locally.

## Coding Style & Naming Conventions
- Python 3.7+; follow PEP 8 with 4-space indentation.
- Use `snake_case` for modules/functions and `PascalCase` for classes; keep filenames descriptive (e.g., `test_interfaces.py`).
- Import ordering is generally maintained with `isort` when formatting is applied.
- Shell scripts under `scripts/` and `tests/smoke/` use `bash` with `set -euo pipefail`.

## Testing Guidelines
No testing is set up yet.

## Commit & Pull Request Guidelines
- Recent history uses short, lowercase summaries (e.g., `fix bug`, `split data manager...`); keep commits concise and descriptive.
- PRs should include: a brief summary, test results, and documentation impact; link related issues and include screenshots/logs when UI or API changes are involved.

## Agent Workflow
- When changing user-facing behavior, CLI flags, configuration, or public APIs, update the relevant docs in `docs/` and/or `README.md` in the same change.
- If no docs change is needed, note the reason briefly in the PR description or commit message.
