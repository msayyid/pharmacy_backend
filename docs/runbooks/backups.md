# Backup + Restore Runbook

## Schedule

- **Daily** 02:30 KG (20:30 UTC prev day) — `bin/backup_db.sh` runs via cron
  on the VPS host (NOT ARQ — keep DB ops off the worker so a worker outage
  doesn't kill backups).
- **Retention**: 7 daily + 4 weekly + 12 monthly snapshots in R2 under
  `backups/mysql/`.
- **Encryption**: gzip then optional `openssl enc -aes-256-cbc -salt -pass
  file:/etc/pharmacy/backup.key`. The key lives in vault; `bin/backup_db.sh`
  reads it from `BACKUP_KEY_FILE`.

## Take a backup now

```bash
bash bin/backup_db.sh /tmp/manual-$(date -u +%Y%m%d-%H%M).sql.gz
ls -lh /tmp/manual-*.sql.gz
```

The script:

1. `mysqldump --single-transaction --quick --skip-lock-tables` against the
   prod DB (single-transaction means no read-locks on InnoDB).
2. Pipes to `gzip -9`.
3. Writes to the local path (R2 upload is the Phase 12.6+ path — see
   `OPEN_QUESTIONS Q15` for why R2 is still pending).

## Restore drill (monthly — staging only)

> **Never restore to production from a backup unless an incident demands it.**
> The drill exists to prove backups are restorable + to measure restore time.

```bash
# 1. Bring up a clean MySQL on a non-production host.
docker run -d --name mysql-restore-test \
  -e MYSQL_ROOT_PASSWORD=test -p 3308:3306 mysql:8.4

# 2. Wait for it to be ready.
until docker exec mysql-restore-test mysql -uroot -ptest -e "SELECT 1" >/dev/null 2>&1; do
  sleep 1
done

# 3. Pull the most recent backup from R2 (or local snapshot for the drill).
LATEST=$(ls -1 /var/backups/pharmacy/*.sql.gz | tail -1)
echo "Restoring from $LATEST"

# 4. Restore.
docker exec mysql-restore-test mysql -uroot -ptest \
  -e "CREATE DATABASE pharmacy_restore CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"

time gunzip -c "$LATEST" | \
  docker exec -i mysql-restore-test mysql -uroot -ptest pharmacy_restore

# 5. Sanity-check row counts.
docker exec mysql-restore-test mysql -uroot -ptest pharmacy_restore -e "
  SELECT 'orders' AS t, COUNT(*) FROM orders UNION
  SELECT 'products', COUNT(*) FROM products UNION
  SELECT 'inventory_batches', COUNT(*) FROM inventory_batches UNION
  SELECT 'admin_users', COUNT(*) FROM admin_users;
"

# 6. Cleanup.
docker rm -f mysql-restore-test
```

**Expected restore time**: ~2 minutes per GB of compressed dump on the
production VPS. Capture the actual time after each drill in
`docs/runbooks/_drill_log.md` (create on first drill).

## Restore to production (emergency)

```bash
# 1. Stop the app.
docker compose -f docker-compose.production.yml stop api worker

# 2. Snapshot the corrupted DB (forensics).
bash bin/backup_db.sh /tmp/corrupted-$(date -u +%Y%m%d-%H%M).sql.gz

# 3. Drop + recreate.
docker compose exec mysql mysql -uroot -p$MYSQL_ROOT_PASSWORD -e "
  DROP DATABASE pharmacy;
  CREATE DATABASE pharmacy CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
"

# 4. Restore from the chosen backup.
gunzip -c /var/backups/pharmacy/<chosen>.sql.gz | \
  docker compose exec -T mysql mysql -upharmacy -p$MYSQL_PASSWORD pharmacy

# 5. Run any pending migrations forward.
docker compose -f docker-compose.production.yml run --rm api \
  uv run alembic upgrade head

# 6. Restart + verify health/ready.
docker compose -f docker-compose.production.yml up -d api worker
curl -fsS https://api.pharmacy.kg/health/ready
```

> **After any production restore**: orders placed between the backup time
> and the restore are LOST. Check `payments` rows with `paid_at` newer than
> the backup → reach out to those customers via support.

## What's NOT included

- Redis backups — Redis is a cache + queue, not a source of truth. A flush
  is acceptable; the worst case is rate-limit counters reset (fail-open) and
  in-flight ARQ jobs requeued (ARQ persists job state).
- File backups (R2) — R2's Cloudflare-managed durability is enough; we don't
  back up object storage.
