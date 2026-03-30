#!/usr/bin/env bash
set -euo pipefail

# Generates a TypeScript client (Axios) from FastAPI OpenAPI spec.
#
# Usage:
#   ./scripts/generate_ts_client.sh [output_dir] [base_url]
#
# Default output_dir (relative to repo layout): <repo>/frontend/src/api
#
# Example:
#   ./scripts/generate_ts_client.sh ../frontend/src/api http://localhost:8000

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_OUT="${ROOT_DIR}/../frontend/src/api"
OUT_DIR="${1:-$DEFAULT_OUT}"
BASE_URL="${2:-http://localhost:8000}"

if [[ -z "${1:-}" ]]; then
  echo "Using default output directory: ${OUT_DIR}"
fi

SPEC_PATH="${ROOT_DIR}/openapi.json"

# Prefer the project venv at backend/.venv (see README: python -m venv .venv).
PY="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "${PY}" ]]; then
  PY="$(command -v python3 || command -v python || true)"
fi
if [[ -z "${PY}" ]]; then
  echo "No Python found. Create a venv: python -m venv .venv" >&2
  exit 1
fi

echo "Exporting OpenAPI spec..."
PYTHONPATH="${ROOT_DIR}/.." "${PY}" "${ROOT_DIR}/scripts/export_openapi.py" "${SPEC_PATH}"

echo "Generating TypeScript Axios client into: ${OUT_DIR}"
npx -y @openapitools/openapi-generator-cli generate \
  -i "${SPEC_PATH}" \
  -g typescript-axios \
  -o "${OUT_DIR}" \
  --additional-properties="npmName=@finance-tracker/api,supportsES6=true,withSeparateModelsAndApi=true,apiPackage=api,modelPackage=models" \
  --global-property apis,models,supportingFiles,modelDocs=false,apiDocs=false

echo "Done."
echo "Note: This client imports 'axios'. Ensure your frontend has it: npm i axios"
echo "Note: Set the Axios baseURL to '${BASE_URL}' in your React app."

