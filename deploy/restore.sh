#!/usr/bin/env bash
# Restore to a separate named volume. Switching live service is an explicit operator step.
set -euo pipefail
cd "$(dirname "$0")/.."
archive=${1:?用法: deploy/restore.sh 备份.tar.gz 新卷名}
volume=${2:?请指定新数据卷名}
[[ -r "$archive" && "$volume" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]+$ ]]
if docker volume inspect "$volume" >/dev/null 2>&1; then
    printf '目标卷已存在，请使用新卷名\n' >&2
    exit 1
fi
STUDIO_VOLUME="$volume" docker compose run --rm --no-deps -T app python -m studio.infra.backup restore <"$archive"
printf '已校验并恢复至 %s。如需切换，请设置 STUDIO_VOLUME=%s，再执行 docker compose up -d。\n' "$volume" "$volume"
