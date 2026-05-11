#!/usr/bin/env bash
set -euo pipefail

INFRA_HOST_VALUE="${INFRA_HOST:-localhost}"
POSTGRES_HOST_VALUE="${POSTGRES_HOST:-$INFRA_HOST_VALUE}"
MINIO_ENDPOINT_VALUE="${MINIO_ENDPOINT:-http://$INFRA_HOST_VALUE:9000}"

airflow connections delete quant_postgres >/dev/null 2>&1 || true
airflow connections add quant_postgres \
  --conn-type postgres \
  --conn-host "$POSTGRES_HOST_VALUE" \
  --conn-login "${POSTGRES_USER:-quant}" \
  --conn-password "${POSTGRES_PASSWORD:-quant}" \
  --conn-port "${POSTGRES_PORT:-55432}" \
  --conn-schema "${POSTGRES_DB:-quant}"

airflow connections delete quant_minio >/dev/null 2>&1 || true
airflow connections add quant_minio \
  --conn-type aws \
  --conn-login "${MINIO_ROOT_USER:-minioadmin}" \
  --conn-password "${MINIO_ROOT_PASSWORD:-minioadmin}" \
  --conn-extra "{\"endpoint_url\": \"$MINIO_ENDPOINT_VALUE\", \"region_name\": \"${MINIO_REGION:-us-east-1}\"}"
