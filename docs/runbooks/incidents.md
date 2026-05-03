# Common-Incident Runbook

> Concrete playbooks for the failure modes most likely to page oncall. Each
> playbook ends with "what to write up post-incident".

---

## Stuck ARQ job

**Symptom**: `worker_jobs_total{status="failed"}` keeps incrementing for a
specific job; admin reports tasks not running (e.g., expired stock not
clearing); Redis shows queue depth growing.

**Diagnose**:

```bash
docker compose logs worker --tail=200 | grep -E "(error|failed|max_tries)"
docker compose exec redis redis-cli LLEN arq:queue:default
```

**Fix**:

1. Identify which job is stuck (job name in error logs).
2. Re-run it via the CLI helper to capture the stack:
   ```bash
   docker compose exec worker uv run python -m app.workers.run_once <job_name>
   ```
3. Common causes:
   - DB row lock held by a hung transaction → kill the holder via
     `KILL <connection_id>` after confirming with `SHOW PROCESSLIST`.
   - Redis OOM → see "Redis down" below.
   - Bug → revert via `rollback.md` and open issue.

**Post-incident**: log the failure mode in `RISKS.md` if it's a class of
issue; add a unit test that reproduces it.

---

## Payment webhook missed

**Symptom**: Order placed via card, customer says they paid, but
`order.payment_status='pending'` in admin queue.

**Diagnose**:

```sql
SELECT id, order_id, status, provider_transaction_id, created_at
FROM payments
WHERE status='pending' AND is_refund=false
  AND created_at < NOW() - INTERVAL 5 MINUTE
ORDER BY created_at DESC LIMIT 20;
```

**Fix**:

1. The hourly `payment_reconcile` cron should pick this up automatically.
   Check the worker log for the `payment_reconcile_done` event in the last
   hour.
2. To force-run it now:
   ```bash
   docker compose exec worker uv run python -m app.workers.run_once payment_reconcile
   ```
3. If `payment_reconcile_done` shows `failed > 0`, the gateway returned
   an error class we don't handle yet — capture in OPEN_QUESTIONS Q14
   (real adapter still scaffolded).
4. If the customer is still pending after the cron ran, manually flip in
   admin → Order Detail → Mark Paid (Phase 12.5+ feature; currently a
   direct DB update).

**Post-incident**: confirm `KG_TO_UTC_HOUR_MAPPING` matches reality (the cron
audit test would catch this on the next deploy, but the live cron schedule is
read at worker startup — restart fixes drift).

---

## Disk full

**Symptom**: `/health/ready` reports `db: error: OperationalError`; mysql
container won't write; Sentry quiet because Sentry buffers locally too.

**Diagnose**:

```bash
df -h
du -sh /var/lib/docker/volumes/*
```

**Fix**:

1. Likely culprits (in order of typical size):
   - `pharmacy_mysql_data` — actual DB. Investigate; do NOT delete.
   - `pharmacy_logs` (if you've added a log volume) — rotate.
   - Old Docker images: `docker image prune -af --filter until=168h`.
   - Old backups in `/var/backups/pharmacy/` — keep last 7 daily, delete
     older.
2. If MySQL is the culprit, check for table bloat:
   ```sql
   SELECT table_schema, table_name,
          ROUND(data_length / 1024 / 1024, 2) AS data_mb,
          ROUND(index_length / 1024 / 1024, 2) AS index_mb
   FROM information_schema.tables
   WHERE table_schema='pharmacy'
   ORDER BY data_length DESC LIMIT 10;
   ```
   `admin_audit_log` is the fastest-growing — partition by month if it's
   over 5 GB (PHARMACY §8.1 note).
3. If `/health/ready` recovers within seconds of freeing space, no further
   action needed. Otherwise restart MySQL: `docker compose restart mysql`.

**Post-incident**: write a disk-full alert to oncall before the next time
(threshold: 80% of allocated VPS disk).

---

## Redis down

**Symptom**: `/health/ready` reports `redis: error: ConnectionError`;
rate-limit counters stop applying (fail-open is acceptable for MVP per
PRODUCT §17.8); webhook dedupe degrades to "always first-seen" (acceptable —
double-applies are idempotent at the row level).

**Diagnose**:

```bash
docker compose logs redis --tail=50
docker compose exec redis redis-cli INFO | grep -E "(used_memory|connected_clients|aof)"
```

**Fix**:

1. **OOM**: Redis hit `maxmemory`. Check eviction policy; `FLUSHDB` is
   safe for the cache namespace but blows away rate-limit + webhook
   dedupe + ARQ queue state — only do this if you're OK losing in-flight
   jobs.
2. **Network**: connectivity between the api/worker container and the
   Redis container; check `docker network inspect`.
3. **Restart**: `docker compose restart redis`. Lifespan re-init in the
   api container should reconnect on next request.

**Post-incident**: bump Redis container memory; confirm `maxmemory-policy
allkeys-lru` is set so cache pressure doesn't evict ARQ queue keys.

---

## Image upload silently fails (no admin error)

**Symptom**: admin uploads an image, gets 201 + image_id, but the URL doesn't
load (404 from CDN). Or the response says `"status":"queued"` but no record
appears within 5 minutes.

**Diagnose**:

1. Was the upload >2 MB? Then it went to the worker path. Check worker logs
   for `process_image_upload_done` with the matching `product_id`. If
   missing, the worker hasn't run the job — probably ARQ-side issue (see
   "Stuck ARQ job").
2. Was the upload ≤2 MB? Then `ProductImageService.upload` ran inline. The
   `R2StorageClient.upload` raises `NotImplementedError` (Q15 unresolved) —
   which means production is running with `FakeStorageClient` (file:// URLs
   only). The CDN can't serve `file://` URLs.

**Fix (real R2 not yet wired)**:

- Confirm `STORAGE_*` env vars are unset → factory falls back to fake →
  URLs are file://. This is expected until Q15 closes.
- For staging/dev: serve images from the local fake-storage dir via a
  separate static route. Production must wait for Q15.

**Post-incident**: add a startup check that warns if `storage_endpoint` is
unset in production env (current state is silent).
