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
    ossutil cp "$archive" "${OSS_URL%/}/$(basename "$archive")"
elif [[ -n ${S3_BUCKET:-} ]]; then
    aws s3 cp "$archive" "s3://$S3_BUCKET/loop-atelier/$(basename "$archive")"
fi
printf '%s\n' "$archive"
