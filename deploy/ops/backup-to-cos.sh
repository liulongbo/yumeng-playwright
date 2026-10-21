#!/bin/sh
set -eu
umask 077

if [ "$#" -ne 2 ]; then
  echo "usage: $0 COMPOSE_ENV_FILE COS_ENV_FILE" >&2
  exit 64
fi

compose_env="$1"
cos_env="$2"
for required in "$compose_env" "$cos_env"; do
  [ -f "$required" ] || { echo "missing configuration: $required" >&2; exit 66; }
done
command -v aws >/dev/null 2>&1 || { echo "aws CLI is required" >&2; exit 69; }
command -v mc >/dev/null 2>&1 || { echo "MinIO mc is required" >&2; exit 69; }

set -a
. "$cos_env"
set +a
: "${COS_ENDPOINT_URL:?}"
: "${COS_BUCKET:?}"
: "${COS_PREFIX:?}"
: "${MINIO_ENDPOINT:?}"
: "${MINIO_ACCESS_KEY:?}"
: "${MINIO_SECRET_KEY:?}"
: "${MINIO_BUCKET:?}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
staging="$(mktemp -d "${TMPDIR:-/tmp}/yumeng-backup.XXXXXX")"
trap 'rm -rf "$staging"' EXIT HUP INT TERM

docker compose --env-file "$compose_env" -f deploy/production.compose.yaml exec -T \
  app-postgres pg_dump -U xingtu_app -d xingtu_production -Fc >"$staging/app.dump"
docker compose --env-file "$compose_env" -f deploy/production.compose.yaml exec -T \
  temporal-postgres pg_dump -U temporal -d temporal -Fc >"$staging/temporal.dump"

aws --endpoint-url "$COS_ENDPOINT_URL" s3 cp "$staging/app.dump" \
  "s3://$COS_BUCKET/$COS_PREFIX/$stamp/app.dump" --only-show-errors
aws --endpoint-url "$COS_ENDPOINT_URL" s3 cp "$staging/temporal.dump" \
  "s3://$COS_BUCKET/$COS_PREFIX/$stamp/temporal.dump" --only-show-errors

export MC_HOST_source="http://${MINIO_ACCESS_KEY}:${MINIO_SECRET_KEY}@${MINIO_ENDPOINT#http://}"
export MC_HOST_cos="https://${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}@${COS_ENDPOINT_URL#https://}"
mc mirror --overwrite --remove "source/$MINIO_BUCKET" \
  "cos/$COS_BUCKET/$COS_PREFIX/$stamp/objects/$MINIO_BUCKET"

printf '%s\n' "backup uploaded: s3://$COS_BUCKET/$COS_PREFIX/$stamp"
