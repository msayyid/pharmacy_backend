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

## Q11 — Reservation timeout cron cadence *(resolved 2026-05-03 in Phase 11)*

- **Resolution:** Adopted the proposed default. Single 5-min ARQ cron `release_pending_orders` evaluates both predicates in one query (`OrderRepository.list_pending_for_timeout` with `FOR UPDATE SKIP LOCKED`). Cancel goes through `OrderLifecycleService.cancel_by_admin` so all hooks (status_history + audit + SMS) fire identically to a manual cancel.
- **See:** DECISION_LOG `2026-05-03 — Single 5-min ARQ cron handles both reservation-timeout thresholds (resolves OPEN_QUESTIONS Q11)`.

---

## Q12 — Bishkek city-match string normalisation

- **Where it surfaced:** `PRODUCT §17.7` ("validate at order placement: city must equal 'Bishkek' (string match); other cities rejected"). User addresses are free-text per `§16.3`.
- **Why it matters:** Russian/Latin/uppercase variants exist: `Bishkek`, `bishkek`, `BISHKEK`, `Бишкек`, `бишкек`. Naive `==` fails. Edge case: `Бишкек, мкр Асанбай` — full address in `address_line` with `city` defaulted to `'Bishkek'`.
- **Proposed default:** `user_addresses.city` defaults to `'Bishkek'` (Latin) at admin/customer create. Order validation: at place-order, normalise the snapshot's city — `delivery_address["city"].strip().casefold()` — and accept membership in `{"bishkek", "бишкек"}`. If not in set and `delivery_method='delivery'`, reject with code `delivery_area_unsupported` and offer pickup. Cyrillic and Latin both accepted; everything else rejected.
- **Decider:** Backend tech lead at Phase 8.
- **Blocks:** Phase 8.

---

## Q13 — Nikita SMS contract: auth, endpoint, request envelope, status codes

- **Where it surfaced:** Phase 10. The Phase 10 research sub-agent (Nikita SMS) ran without web access and returned a memory-based reconstruction labelled "ASSUMED, must verify with vendor". The reconstruction suggests Nikita SMSPRO uses XML over `POST https://smspro.nikita.kg/api/message` with per-request `<login>` + `<pwd>` body credentials (not a header API key), `<phone>` in bare-MSISDN format `996XXXXXXXXX`, status code `11=accepted`, with `<test>1</test>` for sandbox dry-run. None of this is verified against current docs.
- **Why it matters:** The current `Settings.sms_api_key` field is the wrong shape if the reconstruction is correct (would need `sms_login` + `sms_password`). Wrong endpoint/status mapping causes silent under-delivery; wrong sender ID falls back to a generic short-code that erodes brand trust.
- **Proposed default:** Phase 10 ships `NikitaSmsClient` as scaffold-only — every call raises `NotImplementedError("OPEN_QUESTIONS Q13")`. Configured default is `sms_provider=fake`. Production deploy is blocked until: (a) email `info@nikita.kg` for current API PDF + sandbox creds + sender-ID registration; (b) reshape `Settings` if needed; (c) implement the real adapter with httpx + tenacity (retry only on 5xx / network); (d) add a unit test against captured request fixtures (`respx`); (e) close this question.
- **Decider:** Backend tech lead + ops (sender-ID registration is contractual).
- **Blocks:** Phase 12 (production readiness). Does NOT block Phase 11 (worker registration).

---

## Q14 — Freedom Pay (KG) contract: signature algorithm, amount unit, webhook shape

- **Where it surfaced:** Phase 10. The Freedom Pay research sub-agent ran without web access and refused to write a memory-based report (signature algorithm flagged as the make-or-break detail; getting the field-ordering rule wrong returns HTTP 200 but never settles a payment).
- **Why it matters:** The signature algorithm (md5 vs hmac-sha256, alphabetical vs declared-order field concatenation, where the sig field lives) is silent-fail-prone. The amount unit (KGS decimal `100.50` vs kopecks-as-integer `10050`) determines whether we under- or over-charge by 100×. The webhook event-id field name determines whether our Redis SETNX dedupe works.
- **Proposed default:** Phase 10 ships `FreedomPayClient` as scaffold-only — `create_intent`, `refund`, `verify_webhook`, `_sign` all raise `NotImplementedError("OPEN_QUESTIONS Q14")`. Configured default is `payment_provider=fake`. Production deploy is blocked until: (a) obtain current Freedom Pay (KG) developer docs (PDF / Postman collection from `developer.freedompay.kg` or via the merchant onboarding contact); (b) capture a known-input signature fixture from the docs as a unit-test vector; (c) implement adapter with httpx + tenacity; (d) verify webhook event-id field name + close the dedupe question; (e) close this question.
- **Decider:** Backend tech lead + finance (refund flow + reconciliation).
- **Blocks:** Phase 12 (production readiness). Does NOT block Phase 11 (worker registration). Does NOT block customer order placement (COD works end-to-end with no gateway involvement).

---

## Q15 — Cloudflare R2 + boto3: region naming, ACL behaviour, presigned-URL TTL ceiling

- **Where it surfaced:** Phase 10. The R2 research sub-agent ran without web access. boto3 ↔ R2 has historically had non-obvious quirks (`region_name="auto"` requirement, ACL semantics differing from S3, presigned-URL TTL ceiling at 7 days vs S3's 7 days vs Cloudflare-imposed shorter limits, multipart-upload threshold).
- **Why it matters:** Wrong client kwargs throw obscure `botocore` errors at the first upload. Wrong public-bucket pattern means the storefront fetches 404 instead of an image. Wrong presigned-URL TTL ceiling means signed admin export URLs silently fail past a threshold.
- **Proposed default:** Phase 10 ships `R2StorageClient` as scaffold-only — `upload`, `delete`, `sign_url` all raise `NotImplementedError("OPEN_QUESTIONS Q15")`. Configured default is `FakeStorageClient` whenever `storage_endpoint` is unset (so dev runs without real R2 creds). Production deploy is blocked until: (a) confirm boto3 client kwargs against `developers.cloudflare.com/r2/examples/aws/boto3/`; (b) confirm public-bucket URL pattern (`pub-<hash>.r2.dev` vs custom domain); (c) confirm presigned-URL TTL ceiling; (d) implement the three methods with `asyncio.to_thread` wrappers around the sync boto3 calls; (e) close this question.
- **Decider:** Backend tech lead + ops (R2 account + custom domain DNS).
- **Blocks:** Phase 12 (production image serving). Does NOT block Phase 11. Does NOT block dev / unit tests (FakeStorageClient covers them).

---

## Resolved questions

### Q6 — `python-jose` vs PyJWT *(resolved 2026-05-02 in Phase 4)*

**Resolution:** Keep `python-jose>=3.3,<4.0`. 3.5.0 has the historical CVE patches; swap surface is small (~30 LoC). Risk register R-7 stays open for monthly review.

**See:** DECISION_LOG `2026-05-02 — python-jose retained at Phase 4`.

---

### Q9 — Refresh token: opaque + Redis lookup, or JWT + revocation list? *(resolved 2026-05-02 in Phase 4)*

**Resolution:** JWT-encoded refresh tokens with a `jti` claim. The `jti` is stored in Redis (TTL = refresh TTL); on refresh we decode JWT, check Redis for jti, issue new pair, delete old jti, store new jti. On logout we delete the jti.

**See:** DECISION_LOG `2026-05-02 — Refresh token: JWT-encoded with jti in Redis`.
