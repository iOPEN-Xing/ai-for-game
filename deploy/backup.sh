#!/usr/bin/env bash
# An incomplete export never replaces an existing backup.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
backup_dir=${BACKUP_DIR:-backup}
mkdir -p "$backup_dir"
partial=$(mktemp "$backup_dir/.loop-XXXXXXXX")
trap 'rm -f -- "$partial"' EXIT
docker compose exec -T app python -m studio.infra.backup export >"$partial"
archive="$backup_dir/loop-$(date -u +%Y%m%dT%H%M%SZ)-${partial##*.loop-}.tar.gz"
mv -- "$partial" "$archive"
if [[ -n ${OSS_URL:-} ]]; then
    metadata=x-oss-server-side-encryption:AES256
    if [[ -n ${BACKUP_KMS_KEY_ID:-} ]]; then
        metadata="x-oss-server-side-encryption:KMS#x-oss-server-side-encryption-key-id:$BACKUP_KMS_KEY_ID"
    fi
    ossutil cp "$archive" "${OSS_URL%/}/$(basename "$archive")" --meta="$metadata" >&2
elif [[ -n ${S3_BUCKET:-} ]]; then
    encryption=(--sse AES256)
    if [[ -n ${BACKUP_KMS_KEY_ID:-} ]]; then
        encryption=(--sse aws:kms --sse-kms-key-id "$BACKUP_KMS_KEY_ID")
    fi
    aws s3 cp "$archive" "s3://$S3_BUCKET/loop-atelier/$(basename "$archive")" "${encryption[@]}" >&2
fi
printf '%s\n' "$archive"
