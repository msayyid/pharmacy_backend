# Open Questions

> Spec ambiguities, conflicts, and judgement calls surfaced during Phase 0 reading. Each entry has a proposed default so the build can proceed; resolved questions move to `DECISION_LOG.md` with the final call.
>
> **Format:** `Q<id> — <one-liner>` / context (with spec section refs) / proposed default / decider / blocking phase.

---

## Q1 — Where is the 30-day shelf-life-at-dispatch rule enforced?

- **Where it surfaced:** `PRODUCT §5.5` ("items shipped to a customer must have at least 30 days of shelf life remaining at dispatch time, unless the product page explicitly states a shorter window and the customer accepts"); `CLAUDE.md` §"Sacred invariants" ("FEFO + 7-day hard block + 30-day shelf-life-at-dispatch. All three apply, always."); `PHARMACY §5.5` and `BACKEND` are silent on the 30-day specifically — only the 7-day hard block is encoded.
- **Why it matters:** Two enforcement options have different implications. (a) FEFO query excludes batches with `expiry_date <= CURRENT_DATE + INTERVAL '30 days'` for delivery orders → easy, blunt, may oversell-as-out-of-stock when only short-dated stock remains. (b) Admin enforces at pick time → late-stage enforcement, customer may already be promised the order.
- **Proposed default:** Layer enforcement. FEFO query gets a `min_shelf_life_days` parameter — `30` for delivery orders, `7` for pickup. The 7-day hard block remains the absolute floor for both. If FEFO yields insufficient stock under the 30-day rule for a delivery order, return `OutOfStockError` with code `out_of_stock_min_shelf_life` so the frontend can prompt the customer to switch to pickup.
- **Decider:** Product owner (behaviour decision). Confirm before Phase 8.
- **Blocks:** Phase 8 (FEFO place-order).

---

## Q2 — Does the schema need a column for the cold-chain summer surcharge now?

- **Where it surfaced:** `PRODUCT §11.4` ("Cold-chain summer surcharge | +100 KGS (Phase 2)"); `PHARMACY §7.3` `orders.delivery_fee` is a single column; `BACKEND` is silent.
- **Why it matters:** If we need to itemise the surcharge separately on receipts or reports, a separate column avoids a future migration.
- **Proposed default:** No new column. The Phase 2 surcharge folds into `delivery_fee`. If the product team wants line-item visibility later, add an `order_line_charges` table at that time. Don't preemptively schema-bloat for a deferred feature.
- **Decider:** Product owner (data shape). Low urgency.
- **Blocks:** None at MVP.

---

## Q3 — Does MVP block COD on orders > 10,000 KGS, or allow them anyway?

- **Where it surfaced:** `PRODUCT §8.3 F-CHECKOUT-003` ("COD always available except for orders > 10,000 KGS (require pre-payment)"); `PRODUCT §23.1` MVP launches with COD only — card is Phase 1.5.
- **Why it matters:** If MVP is COD-only AND we enforce the 10K floor, customers with > 10K carts cannot check out at all. If we waive the floor for MVP, large COD orders create courier cash-handling and reconciliation risk.
- **Proposed default:** Enforce the floor. Carts with subtotal > 10,000 KGS cannot select COD; pickup-with-cash-at-pickup is offered as a fallback (no courier cash exposure). Show error code `cod_unavailable_high_value`. Check via storefront cart UX before checkout. Card-online lifts the constraint when Phase 1.5 ships.
- **Decider:** Product owner + ops lead. Settle before Phase 8.
- **Blocks:** Phase 8 (checkout).

---

## Q4 — Which order events trigger an email vs SMS?

- **Where it surfaced:** `PRODUCT §14` notification strategy; `PRODUCT §14.4` mentions "Order receipt with itemised total — to customer email if provided" but `§14.2` covers all status transitions via SMS only.
- **Why it matters:** If email mirrors SMS, MVP needs an email integration in Phase 10. If email is receipt-only, we can defer email integration entirely — receipts can be a saveable PDF at Phase 2.
- **Proposed default:** SMS for all status transitions per `§14.2`. Email = receipt only, sent on first transition into `confirmed` status, only if `users.email IS NOT NULL`. Email integration is a Phase 10 / 11 thin job; if email service isn't ready by launch, ship without email — SMS covers the lifecycle.
- **Decider:** Product owner. Affects integration scope at Phase 10.
- **Blocks:** Phase 10 (only if email is required for launch).

---

## Q5 — `PHARMACY_BLUEPRINT_2.md` filename — is this a versioning artifact or a different file?

- **Where it surfaced:** Repo has `/specs/PHARMACY_BLUEPRINT_2.md`; `CLAUDE.md`, `CLAUDE_CODE_PROMPTS.md` (Phase 0 prompt), and `BUILD_PLAN.md` cite `PHARMACY_BLUEPRINT.md` (no `_2`).
- **Why it matters:** Citation drift. Code comments and ADRs that reference `PHARMACY §X.Y` should point to one canonical filename. Subtle but the kind of thing that bites during search/replace.
- **Proposed default:** Rename `PHARMACY_BLUEPRINT_2.md` → `PHARMACY_BLUEPRINT.md`. **CLAUDE.md states `/specs/*` files are read-only during build phases and edits require explicit human decision** — so I will NOT rename without approval. If user prefers to keep `_2`, update `CLAUDE.md` and the Phase 0 prompt's citation to match.
- **Decider:** User. Cosmetic but should be settled now.
- **Blocks:** None functionally; affects spec-ref discipline going forward.

---

## Q6 — Use `python-jose` (per `BACKEND §2`) or migrate to PyJWT?

- **Where it surfaced:** `BACKEND §2` pins `python-jose[cryptography]>=3.3,<4.0`. `python-jose` upstream maintenance has been slow; the library has had open security concerns historically. PyJWT is the actively maintained alternative.
- **Why it matters:** JWT signing is a security primitive. Stagnant crypto libraries are a known vector.
- **Proposed default:** Keep `python-jose` for Phase 1 install, but at Phase 4 design (auth) re-evaluate against current upstream activity and known CVEs. If switch is warranted, swap to PyJWT, update `BACKEND §2`, and log in `DECISION_LOG.md`. The token-issue and verify code is small and well-encapsulated in `app/core/security.py`, so the switch is cheap.
- **Decider:** Backend tech lead at Phase 4. Default direction: PyJWT unless `python-jose` shows fresh activity.
- **Blocks:** None for Phase 1. Settles at Phase 4.

---

## Q7 — Inventory `recalled` column at MVP?

- **Where it surfaced:** `PRODUCT §5.6` ("Phase 2 column; for MVP, admin uses notes + write-off"); `PHARMACY §6.4` `inventory_batches` schema has no `recalled` field.
- **Why it matters:** Adding the column later is a tiny migration. Not adding it now means the recall workflow at MVP relies on `stock_movements 'damaged'` with `reason` text.
- **Proposed default:** Defer. MVP recall = pharmacist files a `damaged` adjustment with `reason='recall: <batch_number>: <ref>'`. The `inventory_batch_id` on `order_items` already gives the customer-trace. Add the boolean column when the Phase 2 recall workflow ships.
- **Decider:** Backend tech lead. Default acceptable.
- **Blocks:** None.

---

## Q8 — Search synonym storage shape (MySQL has no array type)

- **Where it surfaced:** `PHARMACY §10.3` ("synonyms text[]" — Postgres array); `PRODUCT §12.4` ("Synonyms live in `symptom_translations.synonyms`"). MySQL does not have native array type.
- **Why it matters:** Two viable shapes — `JSON NOT NULL DEFAULT (JSON_ARRAY())` (denormalised, fast read, harder admin UI) or normalised junction table `symptom_synonyms (symptom_translation_id, synonym, sort_order)` (proper FK, can index synonyms separately, easier admin CRUD).
- **Proposed default:** `JSON NOT NULL DEFAULT (JSON_ARRAY())`. Read into Python list at the application layer. Search expansion happens application-side per `PHARMACY §10.3`. Junction table is overkill for the synonym set's size (dozens per symptom). If admin UI demands per-row management later, migrate then.
- **Decider:** Backend tech lead. Default acceptable.
- **Blocks:** Phase 5 (catalog schema design); Phase 7 (search behaviour).

---

## Q9 — Refresh token: opaque + Redis lookup, or JWT + revocation list?

- **Where it surfaced:** `BACKEND §14.1` says "Refresh token: 30 days, opaque, stored hashed in Redis (allows revocation)" — but the spec is ambiguous in places about whether refresh is a JWT with a `jti` referenced in Redis, or an opaque random token whose hash is the Redis key.
- **Why it matters:** Different implementations, different revocation guarantees, different testability.
- **Proposed default:** Opaque random token (`secrets.token_urlsafe(32)`); store SHA-256 hash as Redis key `v1:session:refresh:<hash>` with TTL = 30 days, value = JSON `{user_id, issued_at, parent_jti}`. On refresh, generate new token, delete old key (rotation). On logout, delete current key. JWT is for the access token only. Reject any "refresh" attempt that decodes as JWT — explicit kind discrimination.
- **Decider:** Backend tech lead at Phase 4.
- **Blocks:** Phase 4.

---

## Q10 — How is "refund task" surfaced to admin without a new table?

- **Where it surfaced:** `PRODUCT §17.2` ("if paid by card, refund is initiated (manual for MVP — system creates a refund task; admin completes via gateway dashboard)"); `PHARMACY §7.6` `payments` table doesn't have an explicit "refund queue" projection.
- **Why it matters:** "Refund task" implies a list admin can view. Without a dedicated table, we derive it from `payments`.
- **Proposed default:** No new table. Admin "Refunds to process" view is a query: `SELECT * FROM payments p JOIN orders o ON o.id = p.order_id WHERE o.status='cancelled' AND o.payment_status IN ('paid','partially_refunded') AND NOT EXISTS (SELECT 1 FROM payments p2 WHERE p2.order_id = o.id AND p2.amount < 0 AND p2.status='paid')`. The refund row itself, when admin processes it, is a `payments` row with `amount < 0` (sign convention) and `status='paid'`.
- **Decider:** Backend tech lead. Default acceptable.
- **Blocks:** Phase 9 (admin order lifecycle).

---

## Q11 — Reservation timeout cron cadence

- **Where it surfaced:** `PRODUCT §10.6` (24h for unconfirmed pending; 30 min for card-payment timeout); `BACKEND §17.2` shows `release_pending_orders` as `cron(..., minute=0)` — hourly.
- **Why it matters:** Hourly cadence misses the 30-min card timeout by up to 1 hour. Stock stays reserved unnecessarily.
- **Proposed default:** Single ARQ cron job runs every 5 minutes. Inside, evaluate two predicates: `pending && payment_method='card_online' && placed_at < now-30min` → cancel + release; `pending && placed_at < now-24h` → cancel + release. 5-min granularity is responsive for both thresholds, low load (~12 runs/hour against `orders WHERE status='pending'` index), and idempotent.
- **Decider:** Backend tech lead at Phase 11.
- **Blocks:** Phase 11.

---

## Q12 — Bishkek city-match string normalisation

- **Where it surfaced:** `PRODUCT §17.7` ("validate at order placement: city must equal 'Bishkek' (string match); other cities rejected"). User addresses are free-text per `§16.3`.
- **Why it matters:** Russian/Latin/uppercase variants exist: `Bishkek`, `bishkek`, `BISHKEK`, `Бишкек`, `бишкек`. Naive `==` fails. Edge case: `Бишкек, мкр Асанбай` — full address in `address_line` with `city` defaulted to `'Bishkek'`.
- **Proposed default:** `user_addresses.city` defaults to `'Bishkek'` (Latin) at admin/customer create. Order validation: at place-order, normalise the snapshot's city — `delivery_address["city"].strip().casefold()` — and accept membership in `{"bishkek", "бишкек"}`. If not in set and `delivery_method='delivery'`, reject with code `delivery_area_unsupported` and offer pickup. Cyrillic and Latin both accepted; everything else rejected.
- **Decider:** Backend tech lead at Phase 8.
- **Blocks:** Phase 8.

---

## Resolved questions

> When a question is answered, move it here with the resolution and the date. Mirror the decision in `DECISION_LOG.md`.

(none yet)
