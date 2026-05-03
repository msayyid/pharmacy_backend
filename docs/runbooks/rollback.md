# Rollback Runbook

> When the latest deploy is bad. Two paths: code-only rollback (cheap) +
> code-plus-DB rollback (requires migration downgrade — risky, see caveats).

## Decision tree

```
Did the new deploy add a migration?
  ├── No  → Code-only rollback (safe, fast, ≤ 2 min).
  └── Yes → Did the migration touch user-visible state (drop/rename column,
            new NOT NULL)?
            ├── No  → Code-only rollback is still safe; new schema works
            │         with old code if the migration only ADDED columns
            │         the old code ignored.
            └── Yes → Migration downgrade needed. Read the caveats below
                       BEFORE running `alembic downgrade -1`.
```

## Code-only rollback

```bash
ssh deploy@api.pharmacy.kg
cd /opt/pharmacy

# 1. Pin the previous image tag.
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=v1.0.0-rc0/' .env.production

# 2. Restart api + worker.
docker compose -f docker-compose.production.yml pull
docker compose -f docker-compose.production.yml up -d --no-deps api worker

# 3. Verify.
curl -fsS https://api.pharmacy.kg/health/ready
```

## Code + migration rollback

> ⚠ Migrations that DROP a column or RENAME a table are **destructive** on
> downgrade — old data in the dropped/renamed column is lost. Inspect the
> migration's `downgrade()` body BEFORE running.

```bash
# 1. Stop the app to prevent writes during the schema change.
docker compose -f docker-compose.production.yml stop api worker

# 2. Snapshot the DB (belt + braces — backup_db.sh runs nightly already).
bash bin/backup_db.sh /tmp/pre-rollback-$(date -u +%Y%m%d-%H%M).sql.gz

# 3. Run the downgrade with the OLD image (which knows the old migration
#    chain).
docker compose -f docker-compose.production.yml run --rm \
  -e IMAGE_TAG=v1.0.0-rc0 api \
  uv run alembic downgrade -1

# 4. Verify alembic_version matches the old revision.
docker compose -f docker-compose.production.yml exec mysql \
  mysql -upharmacy -p$MYSQL_PASSWORD pharmacy \
  -e "SELECT version_num FROM alembic_version"

# 5. Restart api + worker on the old image.
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=v1.0.0-rc0/' .env.production
docker compose -f docker-compose.production.yml up -d api worker

# 6. Verify health + smoke.
```

## Migration downgrade caveats (project-specific)

- **Phase 5 catalog migration** uses `op.execute(text(...))` for FULLTEXT
  index + generated-column trick. The autogen `downgrade()` may not
  reverse the `op.execute` calls automatically; check the migration body
  before downgrading.
- **Phase 6 inventory** writes the `chk_movement_sign` CHECK via
  `op.execute`. Same caveat — verify reverse SQL exists.
- **Phase 9 payments + courier columns** introduced columns on `orders`
  and a new `payments` table. Downgrade DROPs the columns and the table —
  any in-flight payment data is lost. Take a backup first.
- **Phase 10 sms_log + deliveries** are independent tables — safe to
  downgrade if you accept losing those rows.

## What if downgrade itself fails?

1. Restore the snapshot from step 2:
   ```bash
   gunzip -c /tmp/pre-rollback-<ts>.sql.gz | \
     docker compose exec -T mysql mysql -upharmacy -p$MYSQL_PASSWORD pharmacy
   ```
2. The DB is now in the pre-deploy state; bring up the OLD image and verify.
3. Capture what failed in `OPEN_QUESTIONS.md` so the next forward-deploy
   carries a fix.

## Communications

- Inbound from oncall: post in `#ops-incidents` with rollback start +
  finish timestamps.
- Outbound to support: "Customer-facing impact: orders placed between
  `<deploy>` and `<rollback>` may need manual reconciliation; check the
  `/admin/v1/orders` queue for `pending` orders past their threshold."
