# Risks

> Active risks with likelihood, impact, mitigation, and trigger conditions. Pulled from `PHARMACY §24` + `PRODUCT §24` and augmented with build-specific risks surfaced during Phase 0 reading.
>
> **Scale:** Likelihood {Low, Med, High, Annually}. Impact {Low, Med, High, Critical}.
> **Owner** is the role/role-holder responsible for monitoring; mitigation is the action plan when the trigger fires.

---

## Top 10 active risks (ranked)

### R-1 — Customer receives expired item

- **Likelihood:** Low
- **Impact:** Critical (regulatory + brand)
- **Mitigation:** Three layers, all enforced.
  1. FEFO query in Phase 8 — earliest expiry first.
  2. 7-day hard block — FEFO query and `branch_products.total_quantity` reconciliation both exclude.
  3. 30-day shelf-life-at-dispatch — see `OPEN_QUESTIONS Q1` for enforcement layer.
- **Trigger:** Any customer complaint about delivery shelf life. Concurrency tests in Phase 8 must include the case "two carts, last batch is < 7 days; both cart-validates accept; place-order rejects both."
- **Owner:** Backend tech lead.

### R-2 — Stock data drifts from physical reality

- **Likelihood:** High (real ops always drift)
- **Impact:** High (overselling, stranded reservations, customer trust damage)
- **Mitigation:**
  1. `stock_movements` paired-write rule (sacred invariant in `CLAUDE.md`).
  2. Nightly `reconcile_stock_cache` job recomputes `branch_products.total_quantity` from non-expired batches and alerts on drift > 0.
  3. Weekly cycle counts (ops policy; out of code scope).
- **Trigger:** Reconcile job alert; admin reports physical-vs-system mismatch in `F-ADM-INV-002`.
- **Owner:** Backend tech lead + branch manager (Nurzat).

### R-3 — Place-order race condition (FEFO concurrency bug)

- **Likelihood:** Medium (until proven otherwise by tests)
- **Impact:** Critical (oversell, deadlock, mismatched stock movements)
- **Mitigation:**
  1. `FOR UPDATE SKIP LOCKED` on the FEFO query (MySQL 8.0+ — verified in `BACKEND §6.3`).
  2. Concurrency tests in Phase 8: `asyncio.gather` of N place-order calls against finite stock, run in CI loop ≥ 50× to catch flakes (per `CLAUDE.md` testing rules).
  3. Single transaction wraps batch decrement + `stock_movements` insert + `order_items` insert + `branch_products.reserved_quantity` increment.
- **Trigger:** Any "stock went negative" log line; any deadlock in production logs.
- **Owner:** Backend tech lead. Phase 8 is gated on this risk being demonstrably mitigated (test pass).

### R-4 — MySQL `ngram` parser quality on Cyrillic

- **Likelihood:** Medium
- **Impact:** Medium (search quality; growth bottleneck)
- **Mitigation:**
  1. Phase 7 testing against `PRODUCT §12.1` query bank ("парацетамол", "пара", "парацитамол", "от головы", etc.); zero-result rate must be < 5% on common queries.
  2. Application-side synonym dictionary (`OPEN_QUESTIONS Q8`) for known Soviet-era brand → INN mappings.
  3. Tunable: `ngram_token_size = 2` is the default; bump to `3` if false-positive rate is too high.
  4. Escape hatch: graduate to Meilisearch (`PHARMACY §10.5`) when zero-result > 5% sustained or p95 latency > 200 ms.
- **Trigger:** Phase 7 test failure on the query bank, OR `search_log.results_count = 0` rate > 5% over 7 days post-launch.
- **Owner:** Backend tech lead.

### R-5 — SMS gateway downtime

- **Likelihood:** Medium (third-party reliability)
- **Impact:** High (auth blocked; order communication blocked)
- **Mitigation:**
  1. `sms_log.status` allows `queued` → `failed` retry path; ARQ `max_tries=5` with exponential backoff.
  2. `BACKEND §17.5` "Fail loudly" — never swallow SMS failures.
  3. Phase 11 alert: > 5 minutes of sustained `sms_log.status='queued'` triggers admin SMS to super_admin (via different channel — phone direct).
  4. Phase 2 backlog: second SMS provider as fallback, configured in `integrations/sms/factory.py` to fail-over.
- **Trigger:** > 5 SMS failures in 5 minutes; OTP delivery success rate < 95% over 1 hour.
- **Owner:** Backend tech lead.

### R-6 — PII leakage in logs

- **Likelihood:** Low (with discipline)
- **Impact:** Critical (privacy / regulatory)
- **Mitigation:**
  1. structlog redaction processor catches named fields: `phone`, `code`, `otp`, `password`, `token`, `refresh_token`, `jwt`.
  2. Phone numbers logged as last 4 only per `PHARMACY §20.4` (`+996****1234`).
  3. Audit at every Phase boundary — `BACKEND §27.7` checklist gates the phase.
  4. CI test: a fixture log call with `password='hunter2'` must produce a redacted line.
- **Trigger:** Any plaintext PII surfacing in `grep` of staging logs; failed CI redaction test.
- **Owner:** Backend tech lead.

### R-7 — `python-jose` stagnation / fresh CVE

- **Likelihood:** Low (in any given quarter)
- **Impact:** High (token forgery if a vuln drops)
- **Mitigation:**
  1. Pinned `<4.0` in `BACKEND §2`; auto-update via Dependabot weekly.
  2. Phase 4 review point: re-evaluate vs PyJWT (`OPEN_QUESTIONS Q6`).
  3. JWT signing key rotation every 90 days (`PHARMACY §20.3`); key ID in token header for clean rotation.
  4. Token verify code is small + well-encapsulated in `app/core/security.py`; library swap is cheap.
- **Trigger:** New `python-jose` CVE; or no upstream commit in 6 months at Phase 4 design time.
- **Owner:** Backend tech lead.

### R-8 — Counterfeit / recalled product reaches customer

- **Likelihood:** Low (licensed-distributor policy)
- **Impact:** Critical (regulatory + safety)
- **Mitigation:**
  1. `inventory_batches.supplier_id` recorded on every batch — receiving from licensed distributors only.
  2. `order_items.inventory_batch_id` enables full customer-trace if a batch is recalled.
  3. Manual recall workflow at MVP (`OPEN_QUESTIONS Q7`) — admin marks `damaged` with reason `recall: <batch>`; queries `order_items` for affected customers.
- **Trigger:** Manufacturer recall notice; any customer report of counterfeit packaging.
- **Owner:** Branch manager (Nurzat) for ops; backend tech lead for query support.

### R-9 — Single-VPS production failure

- **Likelihood:** Medium (annual hardware/network event)
- **Impact:** Medium (full outage; bounded by RTO)
- **Mitigation:**
  1. `PHARMACY §22.2`: nightly logical backups to R2; documented 10-minute RTO from snapshot.
  2. Phase 12 backup-restore drill — "backups are only real when proven to restore."
  3. Phase-2 production roadmap: managed Postgres-style HA + replica + workers on separate VPS.
  4. Cloudflare in front of nginx provides edge cache during brief outages.
- **Trigger:** Synthetic uptime check fails > 5 min; regional cloud incident.
- **Owner:** Backend tech lead + ops.

### R-10 — Bishkek summer heat damages cold-chain stock

- **Likelihood:** Annually (June–August every year)
- **Impact:** Medium (write-off cost; customer exposure if not caught)
- **Mitigation:**
  1. Cold-chain rules in `PRODUCT §5.4` and `§10.4`: pickup-only by default in summer; same-day delivery only when refrigerated bag available.
  2. Phase 2 backlog: refrigerated delivery option with cold-chain surcharge (`OPEN_QUESTIONS Q2`).
  3. Receiving warns on cold-chain product expiry < 60 days.
  4. Branch-level fridge monitoring — out of code scope; ops policy.
- **Trigger:** First cold-chain customer complaint; any cold-chain product with `quantity_remaining > 0` and a fridge incident report.
- **Owner:** Branch manager (Nurzat).

---

## Watching but not top-10

These are tracked here so future-me sees the full landscape, but don't crack the top-10 priority list at MVP scope.

- **Search latency creep as catalog grows** — `PHARMACY §10.5` migration plan to Meilisearch already documented. Trigger: p95 > 200 ms or > 50K active products.
- **Spec ambiguity surfaces silently in code** — discipline risk. Mitigation: `OPEN_QUESTIONS.md` is the surface; review at every phase boundary.
- **Payment gateway double-charge / lost webhook** — `PRODUCT §17.6`. Hourly `payment_reconcile` job in Phase 11 + admin manual-refund flow.
- **Delivery promises broken** — `PRODUCT §24`. Conservative SLAs at MVP; honest customer communication.
- **Regulatory tightening on Rx in KG** — schema has `requires_prescription` ready; Phase 3+ enforcement flow.
- **`asyncmy` 0.3.x breaking changes** — pinned to `<0.3` in `BACKEND §2`. Read release notes before any future bump.
- **`arq` upstream maintenance lapse** — fallback is Celery per `BACKEND §17.1`. Watch at Phase 11.

---

## Risk review cadence

- Re-read this file at the start of every phase boundary.
- Add new risks as they surface; demote resolved risks to a "Resolved" section with the date and the resolution mechanism.
- A new top-10 risk requires updating the ranking and confirming the displaced risk is actually lower priority.
