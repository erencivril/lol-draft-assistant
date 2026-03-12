#!/usr/bin/env sh
set -eu

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${1:-/var/backups/lol-draft-assistant}"
db_path="${LDA_DATABASE_PATH:-/app/backend/data/lol_draft_assistant.db}"
logs_dir="${LDA_LOGS_DIR:-/app/backend/logs}"

mkdir -p "$backup_dir"

if [ -f "$db_path" ]; then
  cp "$db_path" "$backup_dir/lol_draft_assistant-$timestamp.db"
fi

if [ -d "$logs_dir" ]; then
  tar -czf "$backup_dir/logs-$timestamp.tar.gz" -C "$logs_dir" .
fi
