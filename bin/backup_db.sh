#!/usr/bin/env bash
# bin/backup_db.sh — mysqldump + gzip the production DB.
#
# Usage:
#   bin/backup_db.sh                       # writes /var/backups/pharmacy/<UTC-ts>.sql.gz
#   bin/backup_db.sh /tmp/manual.sql.gz    # explicit path
#
# R2 upload is intentionally a stub (Q15 still pending — see
# OPEN_QUESTIONS.md). Uncomment + configure the `aws s3 cp` line once R2
# creds + bucket name are vendor-verified.

set -euo pipefail

OUT_PATH="${1:-/var/backups/pharmacy/$(date -u +%Y%m%dT%H%M%SZ).sql.gz}"
OUT_DIR="$(dirname "$OUT_PATH")"
mkdir -p "$OUT_DIR"

MYSQL_HOST="${MYSQL_HOST:-mysql}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-pharmacy}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?MYSQL_PASSWORD env var required}"
MYSQL_DATABASE="${MYSQL_DATABASE:-pharmacy}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Backing up ${MYSQL_DATABASE} → ${OUT_PATH}"

# --single-transaction means InnoDB tables get a consistent snapshot
# WITHOUT taking read-locks. --quick streams row-by-row so memory stays
# bounded for a multi-GB dump.
docker compose -f docker-compose.production.yml exec -T mysql \
  mysqldump \
    --host="$MYSQL_HOST" \
    --port="$MYSQL_PORT" \
    --user="$MYSQL_USER" \
    --password="$MYSQL_PASSWORD" \
    --single-transaction \
    --quick \
    --skip-lock-tables \
    --triggers \
    --routines \
    --events \
    --set-gtid-purged=OFF \
    "$MYSQL_DATABASE" \
  | gzip -9 > "$OUT_PATH"

SIZE=$(du -h "$OUT_PATH" | awk '{print $1}')
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Wrote ${SIZE} → ${OUT_PATH}"

# ─── R2 upload (Q15 pending — uncomment once R2 wiring is verified) ──────
#
# AWS_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID:?}" \
# AWS_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY:?}" \
#   aws s3 cp "$OUT_PATH" \
#     "s3://${R2_BUCKET:?}/backups/mysql/$(basename "$OUT_PATH")" \
#     --endpoint-url "${R2_ENDPOINT:?}" \
#     --no-progress
# echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Uploaded to R2: backups/mysql/$(basename "$OUT_PATH")"

# ─── Local retention pruning (keep last 7 daily) ─────────────────────────
find "$OUT_DIR" -name "*.sql.gz" -type f -mtime +7 -delete
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pruned local backups older than 7 days"
