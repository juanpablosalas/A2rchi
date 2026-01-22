# Project Context

## Purpose
A2RCHI is a retrieval-augmented generation framework for research and education
teams. It provides configurable, private, and extensible assistants with
pipeline-driven retrieval and LLM orchestration, plus containerized services and
a CLI for repeatable deployments.

## Tech Stack
- Python 3.7+ (Click CLI, Flask services, Jinja2 templating)
- LangChain integrations with model backends (HuggingFace, Ollama, vLLM)
- PyTorch for GPU-backed model execution
- ChromaDB for vector storage and PostgreSQL for service state
- Docker or Podman with compose; MkDocs for documentation

## Project Conventions

### Code Style
- PEP 8 with 4-space indentation
- `snake_case` for modules/functions, `PascalCase` for classes
- Keep imports isort-compatible when formatting is applied
- Shell scripts use `bash` with `set -euo pipefail`

### Architecture Patterns
- Core orchestration in `src/a2rchi`, pipelines under `src/a2rchi/pipelines`
- Ingestion flow: collectors -> `PersistenceService` -> `VectorStoreManager`
- Interfaces are Flask apps under `src/interfaces`; entrypoints in `src/bin`
- CLI renders container templates from `src/cli/templates` into
  `~/.a2rchi/a2rchi-<name>` (override with `A2RCHI_DIR`)
- Runtime config is loaded from `/root/A2rchi/configs/` by default

### Testing Strategy
- No formal automated test suite yet; rely on manual and `tests/smoke` checks

### Git Workflow
- Keep commit summaries short and lowercase
- PRs should include a brief summary, test results, and doc impact
- Documentation updates should go through PRs (do not edit `gh-pages` directly)

## Domain Context
- RAG pipelines combine retrieval from ingested sources with LLM responses
- Sources include web, git repos, local files, JIRA, Redmine, SSO, and more
- Services include chat, ticketing, uploader/data manager, grader, and benchmarks

## Important Constraints
- Python 3.7+ runtime requirement
- Docker 24+ or Podman 5.4+ required for containerized deployments
- GPU deployments require NVIDIA drivers and container toolkit
- Secrets and service credentials are supplied via env files

## External Dependencies
- Container runtime: Docker or Podman (compose-based deployments)
- PostgreSQL and ChromaDB services
- LLM backends (HuggingFace models, Ollama, vLLM)
- External source APIs (JIRA, Redmine, Piazza, Mattermost) when enabled
