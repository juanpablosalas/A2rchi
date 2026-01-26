#!/usr/bin/env bash
set -euo pipefail

info() { echo "[smoke-runner] $*"; }

DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-${1:-}}"
if [[ -z "${DEPLOYMENT_NAME}" ]]; then
  echo "Usage: $0 <deployment-name>"
  exit 1
fi

CONFIG_SRC="${CONFIG_SRC:-tests/pr_preview_config/pr_preview_config.yaml}"
CONFIG_DEST="${CONFIG_DEST:-configs/ci/ci_config.generated.yaml}"
ENV_FILE="${ENV_FILE:-.env_tmp_smoke}"
EXTRA_ENV="${EXTRA_ENV:-}"
SERVICES="${SERVICES:-chatbot}"
HOSTMODE="${HOSTMODE:-true}"
WAIT_URL="${WAIT_URL:-http://localhost:2786/api/health}"
WAIT_ATTEMPTS="${WAIT_ATTEMPTS:-60}"
WAIT_SLEEP="${WAIT_SLEEP:-2}"
BASE_URL="${BASE_URL:-http://localhost:2786}"
USE_PODMAN="${USE_PODMAN:-true}"
SMOKE_CLEANUP="${SMOKE_CLEANUP:-true}"
SMOKE_DUMP_LOGS="${SMOKE_DUMP_LOGS:-true}"
SMOKE_FORCE_CREATE="${SMOKE_FORCE_CREATE:-true}"
SMOKE_OLLAMA_MODEL="${SMOKE_OLLAMA_MODEL:-}"
SMOKE_OLLAMA_URL="${SMOKE_OLLAMA_URL:-}"
export USE_PODMAN

A2RCHI_DIR="${A2RCHI_DIR:-${HOME}/.a2rchi}"

ENV_FILE_CREATED=0
CONFIG_DEST_CREATED=0

apply_extra_env() {
  if [[ -z "${EXTRA_ENV}" ]]; then
    return
  fi
  while IFS= read -r line; do
    if [[ -z "${line}" ]]; then
      continue
    fi
    key="${line%%=*}"
    value="${line#*=}"
    if [[ -n "${key}" ]]; then
      export "${key}"="${value}"
    fi
  done <<< "${EXTRA_ENV}"
}

cleanup() {
  exit_code=$?

  if [[ "${exit_code}" -ne 0 && "${SMOKE_DUMP_LOGS,,}" == "true" ]]; then
    tool="docker"
    if [[ "${USE_PODMAN,,}" == "true" ]]; then
      tool="podman"
    fi
    echo "=== Container status ==="
    "${tool}" ps -a || true
    echo "=== Container logs ==="
    "${tool}" ps -a --format '{{.Names}}' | xargs -I{} sh -c 'echo "---- {} ----"; '"${tool}"' logs --tail 50 {} || true'
  fi

  if [[ "${SMOKE_CLEANUP,,}" != "true" ]]; then
    exit "${exit_code}"
  fi

  if [[ -n "${DEPLOYMENT_NAME}" ]]; then
    if [[ "${USE_PODMAN,,}" == "true" ]]; then
      yes | a2rchi delete --name "${DEPLOYMENT_NAME}" --podman --rmi --rmv || true
    else
      yes | a2rchi delete --name "${DEPLOYMENT_NAME}" || true
    fi
  fi

  if [[ "${ENV_FILE_CREATED}" -eq 1 ]]; then
    rm -f "${ENV_FILE}"
  fi
  if [[ "${CONFIG_DEST_CREATED}" -eq 1 ]]; then
    rm -f "${CONFIG_DEST}"
  fi

  exit "${exit_code}"
}

trap cleanup EXIT

apply_extra_env

info "Ensuring smoke scripts are executable..."
chmod +x tests/smoke/*.sh

info "Preparing config..."
mkdir -p "$(dirname "${CONFIG_DEST}")"
if [[ ! -f "${CONFIG_DEST}" ]]; then
  CONFIG_DEST_CREATED=1
fi
cp "${CONFIG_SRC}" "${CONFIG_DEST}"
if [[ -z "${SMOKE_OLLAMA_MODEL}" ]]; then
  SMOKE_OLLAMA_MODEL="$(CONFIG_DEST="${CONFIG_DEST}" python - <<'PY'
import os
import yaml

config_dest = os.environ.get("CONFIG_DEST")
with open(config_dest, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
ollama = ((cfg.get("a2rchi") or {}).get("model_class_map") or {}).get("OllamaInterface") or {}
print((ollama.get("kwargs") or {}).get("base_model", ""))
PY
)"
fi
if [[ -z "${SMOKE_OLLAMA_URL}" ]]; then
  SMOKE_OLLAMA_URL="$(CONFIG_DEST="${CONFIG_DEST}" python - <<'PY'
import os
import yaml

config_dest = os.environ.get("CONFIG_DEST")
with open(config_dest, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
ollama = ((cfg.get("a2rchi") or {}).get("model_class_map") or {}).get("OllamaInterface") or {}
print((ollama.get("kwargs") or {}).get("url", "http://localhost:11434"))
PY
)"
fi
if [[ -z "${SMOKE_OLLAMA_MODEL}" ]]; then
  echo "Unable to determine Ollama model from ${CONFIG_DEST}. Set SMOKE_OLLAMA_MODEL." >&2
  exit 1
fi
CONFIG_DEST="${CONFIG_DEST}" SMOKE_OLLAMA_MODEL="${SMOKE_OLLAMA_MODEL}" python - <<'PY'
import os
import yaml

config_dest = os.environ.get("CONFIG_DEST")
smoke_model = os.environ.get("SMOKE_OLLAMA_MODEL")
with open(config_dest, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
ollama = ((cfg.get("a2rchi") or {}).get("model_class_map") or {}).get("OllamaInterface") or {}
kwargs = ollama.get("kwargs") or {}
kwargs["base_model"] = smoke_model
ollama["kwargs"] = kwargs
model_map = (cfg.get("a2rchi") or {}).get("model_class_map") or {}
model_map["OllamaInterface"] = ollama
cfg.setdefault("a2rchi", {})["model_class_map"] = model_map
with open(config_dest, "w", encoding="utf-8") as handle:
    yaml.safe_dump(cfg, handle, sort_keys=False)
PY

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama CLI not found; install it or set a different model." >&2
  exit 1
fi
info "Ensuring Ollama model '${SMOKE_OLLAMA_MODEL}' is available..."
OLLAMA_HOST="${SMOKE_OLLAMA_URL}" ollama pull "${SMOKE_OLLAMA_MODEL}"

DEPLOYMENT_DIR="${A2RCHI_DIR}/a2rchi-${DEPLOYMENT_NAME}"
if [[ -d "${DEPLOYMENT_DIR}" ]]; then
  if [[ "${SMOKE_FORCE_CREATE,,}" == "true" ]]; then
    info "Existing deployment found; deleting ${DEPLOYMENT_NAME}..."
    if [[ "${USE_PODMAN,,}" == "true" ]]; then
      yes | a2rchi delete --name "${DEPLOYMENT_NAME}" --podman --rmi --rmv || true
    else
      yes | a2rchi delete --name "${DEPLOYMENT_NAME}" || true
    fi
  else
    echo "Deployment ${DEPLOYMENT_NAME} already exists at ${DEPLOYMENT_DIR}." >&2
    echo "Set SMOKE_FORCE_CREATE=true or delete it with: a2rchi delete --name ${DEPLOYMENT_NAME}" >&2
    exit 1
  fi
fi

info "Creating .env file with random PG password..."
if [[ ! -f "${ENV_FILE}" ]]; then
  ENV_FILE_CREATED=1
fi
echo "PG_PASSWORD=$(openssl rand -base64 32)" >> "${ENV_FILE}"
if [[ -z "${DM_API_TOKEN:-}" ]]; then
  DM_API_TOKEN="smoke-$(openssl rand -hex 16)"
fi
echo "DM_API_TOKEN=${DM_API_TOKEN}" >> "${ENV_FILE}"
export DM_API_TOKEN
if [[ -z "${DM_CATALOG_SEED_FILE:-}" ]]; then
  DM_CATALOG_SEED_FILE="$(pwd)/tests/smoke/seed.txt"
  export DM_CATALOG_SEED_FILE
fi

info "Launching deployment..."
CMD=(a2rchi create --name "${DEPLOYMENT_NAME}" --config "${CONFIG_DEST}" -v 4 --services "${SERVICES}" --env-file "${ENV_FILE}")
if [[ "${USE_PODMAN,,}" == "true" ]]; then
  CMD+=(--podman)
fi
if [[ "${HOSTMODE,,}" == "true" ]]; then
  CMD+=(--hostmode)
fi
if [[ "${SMOKE_FORCE_CREATE,,}" == "true" ]]; then
  CMD+=(--force)
fi
echo "${CMD[@]}"
"${CMD[@]}"

info "Waiting for service readiness..."
attempt=0
while true; do
  if curl -fsS "${WAIT_URL}" >/dev/null 2>&1; then
    info "Service is ready."
    break
  fi
  attempt=$((attempt + 1))
  if (( attempt >= WAIT_ATTEMPTS )); then
    echo "Service did not become ready in time" >&2
    exit 1
  fi
  info "Attempt ${attempt}/${WAIT_ATTEMPTS}..."
  sleep "${WAIT_SLEEP}"
done

CONFIG_NAME="$(CONFIG_DEST="${CONFIG_DEST}" python - <<'PY'
import os
import yaml

config_dest = os.environ.get("CONFIG_DEST")
with open(config_dest, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
print(cfg.get("name", ""))
PY
)"
if [[ -z "${CONFIG_NAME}" ]]; then
  echo "Missing config name in ${CONFIG_DEST}" >&2
  exit 1
fi

RENDERED_CONFIG="${A2RCHI_DIR}/a2rchi-${DEPLOYMENT_NAME}/configs/${CONFIG_NAME}.yaml"
if [[ ! -f "${RENDERED_CONFIG}" ]]; then
  echo "Rendered config not found at ${RENDERED_CONFIG}" >&2
  exit 1
fi

export A2RCHI_CONFIG_PATH="${RENDERED_CONFIG}"
export A2RCHI_CONFIG_NAME="${CONFIG_NAME}"
export A2RCHI_PIPELINE_NAME="$(RENDERED_CONFIG="${RENDERED_CONFIG}" python - <<'PY'
import os
import yaml

rendered = os.environ.get("RENDERED_CONFIG")
with open(rendered, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
pipelines = (cfg.get("a2rchi") or {}).get("pipelines") or []
print(pipelines[0] if pipelines else "")
PY
)"

export PGHOST="$(RENDERED_CONFIG="${RENDERED_CONFIG}" python - <<'PY'
import os
import yaml

rendered = os.environ.get("RENDERED_CONFIG")
with open(rendered, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
print(((cfg.get("services") or {}).get("postgres") or {}).get("host", "localhost"))
PY
)"
export PGPORT="$(RENDERED_CONFIG="${RENDERED_CONFIG}" python - <<'PY'
import os
import yaml

rendered = os.environ.get("RENDERED_CONFIG")
with open(rendered, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
print(((cfg.get("services") or {}).get("postgres") or {}).get("port", 5432))
PY
)"
export PGUSER="$(RENDERED_CONFIG="${RENDERED_CONFIG}" python - <<'PY'
import os
import yaml

rendered = os.environ.get("RENDERED_CONFIG")
with open(rendered, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
print(((cfg.get("services") or {}).get("postgres") or {}).get("user", "a2rchi"))
PY
)"
export PGDATABASE="$(RENDERED_CONFIG="${RENDERED_CONFIG}" python - <<'PY'
import os
import yaml

rendered = os.environ.get("RENDERED_CONFIG")
with open(rendered, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
print(((cfg.get("services") or {}).get("postgres") or {}).get("database", "a2rchi-db"))
PY
)"
export PGPASSWORD="$(ENV_FILE="${ENV_FILE}" python - <<'PY'
import os

path = os.environ.get("ENV_FILE")
if not path:
    print("")
    raise SystemExit(0)
value = ""
with open(path, "r", encoding="utf-8") as handle:
    for line in handle:
        if line.startswith("PG_PASSWORD="):
            value = line.split("=", 1)[1].strip()
            break
print(value)
PY
)"

export DM_BASE_URL="http://localhost:$(RENDERED_CONFIG="${RENDERED_CONFIG}" python - <<'PY'
import os
import yaml

rendered = os.environ.get("RENDERED_CONFIG")
with open(rendered, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
dm = (cfg.get("services") or {}).get("data_manager") or {}
print(dm.get("external_port") or dm.get("port") or 7871)
PY
)"
export CHROMA_URL="http://localhost:$(RENDERED_CONFIG="${RENDERED_CONFIG}" python - <<'PY'
import os
import yaml

rendered = os.environ.get("RENDERED_CONFIG")
with open(rendered, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
chromadb = (cfg.get("services") or {}).get("chromadb") or {}
print(chromadb.get("external_port") or chromadb.get("port") or 8000)
PY
)"

export OLLAMA_URL="$(RENDERED_CONFIG="${RENDERED_CONFIG}" python - <<'PY'
import os
import yaml

rendered = os.environ.get("RENDERED_CONFIG")
with open(rendered, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
ollama = ((cfg.get("a2rchi") or {}).get("model_class_map") or {}).get("OllamaInterface") or {}
print((ollama.get("kwargs") or {}).get("url", "http://localhost:11434"))
PY
)"
export OLLAMA_MODEL="$(RENDERED_CONFIG="${RENDERED_CONFIG}" python - <<'PY'
import os
import yaml

rendered = os.environ.get("RENDERED_CONFIG")
with open(rendered, "r", encoding="utf-8") as handle:
    cfg = yaml.safe_load(handle) or {}
ollama = ((cfg.get("a2rchi") or {}).get("model_class_map") or {}).get("OllamaInterface") or {}
print((ollama.get("kwargs") or {}).get("base_model", ""))
PY
)"
export BASE_URL

info "Running combined smoke checks..."
./tests/smoke/combined_smoke.sh "${DEPLOYMENT_NAME}"
