# Pharmacy Platform — Product Blueprint

> **Purpose.** This is the canonical product specification. It explains *what* we are building, *who* it's for, *why* it works the way it does, and *how* edge cases must behave. It encodes the pharmacy-domain knowledge that no codebase should have to rediscover.
>
> **Companion docs.** This sits alongside `PHARMACY_BLUEPRINT.md` (database & system design) and `BACKEND_BLUEPRINT.md` (FastAPI/SQLAlchemy/MySQL implementation). When the three documents disagree, **product blueprint wins on behaviour, backend blueprint wins on implementation, database blueprint wins on data shape**.
>
> **Author voice.** Senior PM with pharmacy operations experience. Decisions are opinionated and explained. Where we say "do X," we mean it.
>
> **Market.** Kyrgyzstan (Bishkek launch, Osh next). Russian-primary, Kyrgyz and English supported.

---

## Table of Contents

1. [Document Purpose & Rules for Claude Code](#1-document-purpose--rules-for-claude-code)
2. [Product Vision](#2-product-vision)
3. [What We Are NOT Building](#3-what-we-are-not-building)
4. [Target Market & Personas](#4-target-market--personas)
5. [Pharmacy Domain Primer](#5-pharmacy-domain-primer)
6. [Product Pillars](#6-product-pillars)
7. [User Journeys](#7-user-journeys)
8. [Feature Catalog](#8-feature-catalog)
9. [Order State Machine](#9-order-state-machine)
10. [Inventory & Stock Rules](#10-inventory--stock-rules)
11. [Pricing, Discounts & Payment UX](#11-pricing-discounts--payment-ux)
12. [Search & Discovery Behaviour](#12-search--discovery-behaviour)
13. [Catalog Content Standards](#13-catalog-content-standards)
14. [Notification Strategy](#14-notification-strategy)
15. [Trust & Credibility Signals](#15-trust--credibility-signals)
16. [Localization & Cultural Notes](#16-localization--cultural-notes)
17. [Edge Cases & Failure Modes](#17-edge-cases--failure-modes)
18. [Customer Support & Operations](#18-customer-support--operations)
19. [Admin Workflows](#19-admin-workflows)
20. [Compliance, Ethics & Safety](#20-compliance-ethics--safety)
21. [User-Facing Copy Library](#21-user-facing-copy-library)
22. [Success Metrics & Analytics](#22-success-metrics--analytics)
23. [Roadmap: MVP / Phase 2 / Future](#23-roadmap-mvp--phase-2--future)
24. [Risk Register](#24-risk-register)
25. [Glossary](#25-glossary)
26. [Conventions Checklist for Claude Code](#26-conventions-checklist-for-claude-code)

---

## 1. Document Purpose & Rules for Claude Code

This file gives Claude Code the *why* behind the technical specs. When you generate code:

1. **Behaviour decisions live here.** If the backend blueprint says *how* to validate a phone but doesn't say *whether* a guest cart can survive a phone change, this document does. Don't invent behaviour — ask.
2. **Every feature has an ID** (e.g. `F-CAT-003`). Reference IDs in commit messages, PR descriptions, and code comments where non-obvious behaviour is implemented.
3. **User-facing text is in §21.** Don't write copy. Don't translate copy. Use the keys and the strings provided.
4. **Edge cases in §17 must be handled.** A "happy path" implementation is incomplete.
5. **Business rules in §10–11 are non-negotiable.** They reflect pharmacy operations, not preferences. Examples: FEFO selection, never sell expired stock, batch tracking on every sale.
6. **MVP scope (§23) is the gate.** Do not build features marked Phase 2 or Future without explicit instruction, even if "easy."

---

## 2. Product Vision

> **A pharmacy that fits in your pocket — find what you need, get it the same day, and never wonder if it's safe.**

### 2.1 The job we are hired to do

When a Kyrgyzstani family member is sick — or routinely managing a chronic condition — they currently:
- Walk to the nearest pharmacy and hope it has what they need
- Phone around to find a specific medicine
- Pay whatever the closest pharmacy charges (no comparison)
- Don't always trust that what they're getting is in good condition

We replace that with: **search by symptom or name, see real stock at our pharmacy, get it delivered same-day, with confidence the product is fresh and authentic.**

### 2.2 Why now

- Smartphone penetration in Kyrgyzstan is high and growing
- Bishkek has Yandex Delivery and capable last-mile services
- Russian-language e-commerce expectations are set by Wildberries and Ozon — customers expect search, reviews (we won't do reviews on medicine; see §3), and reliable delivery
- Local pharmacy chains have basic websites but most lack inventory accuracy, search, or proper mobile UX

### 2.3 What "world-class" means for this product

| World-class is | World-class is NOT |
|---|---|
| Real-time accurate stock | Big catalog with no stock truth |
| Search that handles "у меня болит голова" → paracetamol | Search that only finds exact name matches |
| Same-day delivery in Bishkek | Two-day shipping with no tracking |
| Bilingual UI that respects how locals actually shop | English-first or Russian-only |
| FEFO inventory, recall traceability | Whatever batch happens to be on top |
| Clear "expires in X days" on listings | Hidden expiry until delivery |

---

## 3. What We Are NOT Building

Be ruthless. The success of this product depends on what we *don't* do as much as what we do.

### 3.1 Not in MVP, not in Phase 2, not in Plan
- **Telemedicine / online doctor consultation.** Different product, different regulation, different team.
- **Prescription management for controlled substances.** Kyrgyzstan is loose on Rx for most OTC; we explicitly do not handle Schedule-equivalent controlled drugs.
- **Insurance / health coverage integration.** Not a thing in this market for retail pharmacy.
- **Reviews and ratings on medicines.** Medicine isn't a restaurant. User-generated efficacy claims create liability and misinformation. Reviews on cosmetics and devices may be considered later (Phase 3+).
- **Q&A / forums / community.** Same reason.
- **Auto-substitution by AI.** A computer must not say "this is just as good as that" without a pharmacist's judgement.
- **Diagnosis or symptom-to-medicine recommendation engine that prescribes.** Symptom *navigation* (here are products commonly bought for headache) is fine. Symptom *prescription* ("you have this, take that") is not.
- **Dropshipping or marketplace model.** We sell only from our own pharmacy's stock. No third-party sellers.

### 3.2 Not in MVP — explicitly deferred (see §23)
- Multi-branch UI (data model supports it; UI hides branch selector)
- Subscriptions / auto-refill
- Loyalty points
- Promotions and coupons (one-off discounts as `discount_amount` only)
- Click-and-collect with appointment slots
- Wishlist / favourites
- Push notifications (SMS-only for now)
- Native mobile apps (responsive web only)

### 3.3 Hard limits even when requested
- **No partial-pack sales.** A "blister of 10 tablets" sells as 10, not as 4.
- **No same-day cancellation after dispatch.** Once a courier has the package, customer flow is "refuse delivery", not "cancel".
- **No stock visibility for "low" levels.** We show in-stock or out-of-stock, never "only 2 left" — that pressures customers and exposes ops data.

---

## 4. Target Market & Personas

### 4.1 Primary persona — **Aizhana, the Family Manager**

> 34, mother of two, full-time office worker in Bishkek. Manages medicine for herself, husband, kids, and her mother who lives nearby. Russian-speaking, occasionally Kyrgyz. Phone-first.

- **Buys for:** kids' fevers, husband's blood pressure meds (monthly), her own seasonal allergies, her mother's diabetes supplies
- **Pain points:** never sure if the local pharmacy has what she needs, has to make multiple stops, prices vary
- **What she values:** quick reorder of regular medicines, knowing it's authentic, delivery to her or to her mother's address
- **What she will not tolerate:** expired or near-expiry products, an order being half-fulfilled with no warning, unclear delivery times

She is **the persona we build for first.** If Aizhana's repeat-purchase flow is fast, we have a business.

### 4.2 Secondary persona — **Bekzat, the Acute Buyer**

> 27, software developer, single, Bishkek. Gets sick a few times a year. Uses our app only when something is wrong.

- **Buys for:** cold/flu symptoms, occasional headache, sometimes stomach issues after a bad lunch
- **Pain points:** when sick, doesn't want to go out; doesn't always know which medicine to buy
- **What he values:** symptom-based search ("у меня болит горло"), fast delivery, clear product info
- **What he will not tolerate:** having to register before browsing, complex checkout, unclear whether medicine is OK to take with alcohol/food/etc.

### 4.3 Tertiary persona — **Gulnara, the Caregiver**

> 52, full-time caregiver to an elderly parent with multiple chronic conditions. Less tech-confident.

- **Buys for:** parent's heart medication, blood pressure meds, vitamins, hygiene products
- **Pain points:** complex regimens, fixed-income budgeting, mobility limited
- **What she values:** large readable text, clear pricing, cash-on-delivery, ability to call a human
- **What she will not tolerate:** payment systems that confuse her, delivery times that don't fit her schedule

> **Implication for code:** font sizes, contrast ratios, and the customer-support phone link matter more than fancy animations. COD must be first-class.

### 4.4 Admin personas

| Persona | Role | What they do daily |
|---|---|---|
| **Aibek** — Owner / Super Admin | Sees everything, configures pricing rules and approves new admin users | Reviews dashboards, sets prices, approves staff |
| **Nurzat** — Branch Manager | Runs the Bishkek pharmacy day to day | Receives stock, monitors orders, handles escalations |
| **Aida** — Pharmacist | Picks orders, checks expiry, advises on substitutions | Fulfills orders, manages near-expiry inventory |
| **Marat** — Content Editor | Updates catalog, writes/translates product descriptions | Adds new products, fixes images, manages categories |

> **Implication for code:** the admin panel must be usable by Nurzat and Aida on a desktop in a back-of-store environment — not a designer's MacBook. Keyboard-first, fast, dense tables.

---

## 5. Pharmacy Domain Primer

This section exists so a developer (or AI) generating code understands what a pharmacy actually does. Skipping this is how you build the wrong thing.

### 5.1 Medicine taxonomy (top-level categories)

The catalog is organised into the following parent categories. These are the standard operating taxonomy of a Kyrgyzstani retail pharmacy and should not be invented or restructured by Claude Code.

| Russian | Kyrgyz | English | Notes |
|---|---|---|---|
| Анальгетики и жаропонижающие | Оорутту басаргычтар | Analgesics & antipyretics | Paracetamol, ibuprofen, aspirin, combos |
| Простуда, грипп и ОРВИ | Суук тийүү | Cold, flu & ARVI | Multi-symptom cold formulas, lozenges |
| Желудочно-кишечный тракт (ЖКТ) | Ичеги-карын | GI | Antacids, anti-diarrhoeal, probiotics, laxatives |
| Антибиотики | Антибиотиктер | Antibiotics | Most are technically Rx but commonly OTC in KG |
| Сердечно-сосудистые | Жүрөк-кан тамыр | Cardiovascular | BP meds, statins, antiarrhythmics |
| Эндокринология | Эндокринология | Endocrine | Diabetes (insulin, oral), thyroid |
| Витамины и БАД | Витаминдер | Vitamins & supplements | Multivitamins, single vitamins, supplements |
| Антигистаминные | Аллергияга каршы | Antihistamines | Allergy, motion sickness |
| Дерматология | Дерматология | Dermatology | Creams, ointments, antifungal, antibacterial topical |
| Глаза, уши, нос (ЛОР) | Көз, кулак, мурун | Eyes, ears, nose | Drops, sprays |
| Урология и гинекология | Урология жана гинекология | Urology & gynaecology | Vaginal preparations, UTI products, men's health |
| Нервная система | Нерв системасы | Nervous system | Mild sedatives, sleep aids, vitamins for nerves |
| Детские товары | Балдар үчүн | Baby & children | Pediatric formulations, baby food, hygiene |
| Гигиена и уход | Гигиена | Hygiene & personal care | Hand sanitizers, soaps, oral care |
| Косметика | Косметика | Cosmetics | Skincare, lip care, body care |
| Медицинские изделия | Медициналык буюмдар | Medical devices | Bandages, BP monitors, thermometers, syringes |
| Контрацепция | Контрацепция | Contraception | Condoms, hormonal contraceptives |

### 5.2 The active ingredient model

**This is the single most important concept for Claude Code to understand.** A "product" is a SKU on a shelf (e.g. "Panadol 500mg, 12 tablets"). An "active ingredient" is what's actually doing the work (paracetamol). Many products share an active ingredient. Customers often want to swap a brand for a cheaper generic with the same active ingredient.

| Brand | Active ingredient | Strength | Form | Pack |
|---|---|---|---|---|
| Panadol | Paracetamol | 500 mg | tablet | 12 |
| Efferalgan | Paracetamol | 500 mg | effervescent tablet | 16 |
| Calpol | Paracetamol | 120 mg/5ml | suspension | 100 ml |
| Generic "Парацетамол" | Paracetamol | 500 mg | tablet | 10 |

The catalog exposes active ingredients as filters and as a substitute mechanism (`F-CAT-007`).

### 5.3 Forms and what they imply

| Form | Implication for product, ops, or delivery |
|---|---|
| Tablet / capsule | Standard. Room temperature. Long shelf life. |
| Syrup / suspension | Has volume in ml. Often pediatric. Heavier — affects shipping weight. |
| Drops | Eye/ear/nose. Small bottles, sensitive to contamination. |
| Cream / ointment / gel | Topical. Tube or jar. |
| Spray / inhaler | Pressurised. Some are temperature-sensitive. |
| Injection | Most need cold chain. **Out of MVP** unless explicitly added; flag any `injection` SKU as `requires_cold_chain` until an admin overrides. |
| Suppository | Heat-sensitive. Cold-chain in summer (Bishkek summers reach 35°C). |
| Patch | Heat-sensitive adhesive. |
| Powder | Single-dose sachets common. |

### 5.4 Cold chain

Some products must be kept between 2°C and 8°C. The catalog flags these (`requires_cold_chain = true`). For MVP:
- These can be sold but only with **same-day delivery** (≤ 4 hours from order)
- During Bishkek summer (June–August), refrigerated delivery is the only option — customer is told this at checkout and a cold-chain fee may apply
- Pickup is preferred for cold-chain in summer

### 5.5 Expiry and FEFO

**Hard rule: we never sell an expired product.**

- Every batch has `expiry_date`. Stock available for sale = stock with `expiry_date > today`.
- FEFO — First Expiry, First Out — is how the system picks which batch to dispense from. The earliest-expiring stock with sufficient quantity goes first.
- Near-expiry policy:
  - 60+ days to expiry: normal sale
  - 30–60 days to expiry: still sold, optional admin discount
  - 8–30 days to expiry: admin alert daily; sold only if admin enables, with clear "best before" disclosure on product page
  - ≤ 7 days to expiry: **automatically blocked from sale**, admin sees it for write-off
- Items that ship to a customer must have at least **30 days** of shelf life remaining at dispatch time, unless the product page explicitly states a shorter window and the customer accepts.

### 5.6 Batch and recall

A batch is identified by `(branch_id, product_id, batch_number, expiry_date)`. When a manufacturer recalls a batch:
- Admin marks the batch as recalled (Phase 2 feature; for MVP, admin manually pulls stock and writes off)
- Every order line in `order_items` records `inventory_batch_id`, so we can trace which customers received recalled stock
- For MVP we surface this via the audit query, not an automated workflow

### 5.7 Substitution

Customers ask "do you have something like X but cheaper?" In a physical pharmacy, the pharmacist suggests a generic with the same active ingredient and dose. Online:
- Product detail page shows up to 4 alternatives with the **same active ingredient and same dose** (`F-CAT-007`)
- Out-of-stock product pages prominently surface in-stock alternatives (`F-CAT-008`)
- We **never** auto-replace items in a cart or order. Customer picks.

### 5.8 Common-knowledge heuristics customers expect

- Cold/flu products often combine paracetamol + decongestant + antihistamine. Surface these under "Cold & Flu," not under each ingredient.
- "Сироп от кашля" (cough syrup) splits into **dry cough** (suppressants) and **wet cough** (expectorants). Don't mix them in one filter — they're medically opposite.
- Antibiotics are *almost always* a "course" — full pack of 6, 10, 14 days. Don't show as "tablets," show as "course of N days" where the data permits.
- Pediatric medicines have **age + weight** dosing. We display age range (`min_age`, `max_age`), and if the data exists, weight range. Critical safety surface.
- Many older customers ask for medicines by Soviet-era brand names ("Анальгин," "Цитрамон"). Search must handle these as synonyms even though packaging has changed.

---

## 6. Product Pillars

Five non-negotiables. Every PR should be checkable against these:

1. **Stock truth.** What we say is in stock, *is* in stock. Fix this before anything fancy.
2. **Find-it-fast.** From open-app to product-found in under 20 seconds for a returning customer.
3. **Same-day delivery in Bishkek.** Or transparent reason why not.
4. **Explain everything.** Dosage, side effects, what it's for — visible without scrolling.
5. **Mobile-first, Russian-first.** Then Kyrgyz, then English, then desktop. In that order.

---

## 7. User Journeys

### 7.1 J-01 — First-time symptom shopper (Bekzat, the acute buyer)

**Scenario:** It's 7pm, throat hurts, hasn't used us before.

```
1. Lands on homepage (mobile, Russian by default)
2. Taps search → types "болит горло" (throat hurts)
3. Suggestions surface: lozenges, sprays, gargles
   → Each result shows: name, price, "in stock" / delivery time, primary image
4. Taps a 250 KGS lozenge product
   → Sees: name, dosage, how-to-use, what-it-treats, side-effects
   → Sees "in stock at our pharmacy", "delivery in ~2 hours"
   → Sees 3 alternatives with same active ingredient
5. Taps "Add to cart"
   → No login required up to this point
6. Taps cart → "Place order"
   → Now prompted to enter phone (auth gate)
   → Receives SMS, enters code
7. Adds delivery address (free text + landmark)
8. Picks "Cash on delivery"
9. Sees order summary with total → confirms
10. Receives SMS: "Order PH-2026-000123 received. We'll call to confirm in 10 min."
11. Pharmacy calls/SMSes to confirm → status moves to "preparing"
12. SMS: "Your order is on the way. Courier: Marat, +996…"
13. Courier arrives, customer pays cash, hands phone → marked delivered
```

**Critical UX rules for this flow:**
- Browse without account. Auth wall only at "Place order".
- Search must work for typos ("болит горло" / "болить горло") and Cyrillic prefixes.
- Product page must answer "is this for me?" without scrolling on a 6-inch screen.

### 7.2 J-02 — Repeat reorder (Aizhana, the family manager)

**Scenario:** Husband's BP medication runs out monthly.

```
1. Opens app → already logged in (refresh token)
2. Taps "My orders"
3. Sees last order with the BP meds → taps "Reorder"
   → Items added to cart, prices and stock re-validated
4. If everything still in stock at same price → straight to confirm
5. If anything out of stock → flagged inline, customer keeps or removes
6. Taps confirm → order placed
7. Total flow time: under 60 seconds
```

**Critical UX rules:**
- "Reorder" must work even if a product was deleted (snapshot-based — shows the snapshot, lets customer remove or pick alternative)
- Saved address is selected by default
- Saved payment method (COD by default) is selected

### 7.3 J-03 — Caregiver buying for a third party (Gulnara, caregiver)

**Scenario:** Mother needs medicine, daughter buys.

```
1. Logs in as herself
2. Adds items to cart
3. At delivery step → selects "Different recipient"
   → Enters mother's name, phone, address
4. Order ships to mother's address
5. Both daughter (account holder) and mother (recipient) get SMS updates
   → Daughter gets full order detail; mother gets delivery-window only
```

**Critical rules:**
- The account holder's phone is *not* the same as the recipient phone.
- We send order-status SMS to the recipient phone for "out for delivery" so they're prepared.
- Account holder can have multiple saved addresses, each with its own recipient name/phone (`F-ACC-002`).

### 7.4 J-04 — Stock receiving (Aida, pharmacist)

**Scenario:** Distributor delivers a box of products at 9am.

```
1. Aida logs into admin, scans first product barcode
2. System looks it up → existing product → opens "Receive batch" form
   - Pre-filled: product, branch
   - To enter: batch number, expiry date (DD/MM/YYYY), quantity received, cost price
3. Saves → inventory_batches row created, branch_products.total_quantity incremented,
   stock_movements 'received' row recorded
4. Repeats for ~50 SKUs
5. Closes shipment, sees daily summary: items received, total cost
```

**Critical rules:**
- Must support barcode scanning (Phase 1.5, MVP can be manual SKU lookup).
- Expiry date in DD/MM/YYYY (Kyrgyzstani convention), stored as ISO.
- Cannot save a batch with `expiry_date <= today + 7 days` without explicit "I know what I'm doing" confirmation.
- New SKU not in catalog? Aida can't sell it yet — content editor adds it first. Avoid the temptation to allow ad-hoc product creation in receiving — it produces dirty data.

### 7.5 J-05 — Order fulfillment (Aida, pharmacist)

**Scenario:** New order comes in.

```
1. Aida sees badge on "Pending orders" (or audible alert)
2. Opens order → sees:
   - Customer name, phone
   - Items, quantities
   - For each item: which batch the system picked (FEFO), shelf location if known
   - Delivery address, time slot, payment method
3. Picks each item from the shelf, ticks off in the UI
4. If a picked item doesn't match the batch the system suggested (e.g., she found
   an earlier-expiring one), she swaps → system updates the order_item.batch_id
5. Marks "Ready for delivery"
   - Stock moves from reserved → sold (movement type 'sold')
6. Hands to courier → marks "Out for delivery"
7. Courier marks "Delivered" or back-office marks based on courier confirmation
```

**Critical rules:**
- Picking screen is the single most-used admin screen. It must be fast, dense, and printable.
- Substitution within the order (different batch of *same* product) is allowed and tracked.
- Substitution to a *different* product requires customer approval — we call them.

### 7.6 J-06 — Near-expiry handling (Nurzat, branch manager)

**Scenario:** Daily 6am email arrives.

```
1. Nurzat opens email: "12 batches expiring within 60 days at Bishkek Central"
2. Clicks link → admin > inventory > expiring filter
3. For each batch decides:
   - Apply 30% discount (Phase 2: real promo; MVP: edit price directly)
   - Move to "for return to supplier" (Phase 2)
   - Donate / write-off if ≤ 7 days
4. Updates take effect on storefront within 60 seconds
```

---

## 8. Feature Catalog

> Every feature has an ID, priority (P0 = MVP must, P1 = MVP nice-to-have, P2 = Phase 2, P3 = Future), brief description, user stories, acceptance criteria, and out-of-scope notes.
>
> Reference these IDs in code comments and PRs.

### 8.1 Identity & Account

#### `F-AUTH-001` Phone-OTP login — **P0**
**Story:** As a customer, I want to log in with my phone number and a code so I don't have to remember a password.

**Acceptance:**
- POST `/auth/otp/request` accepts E.164 phone, sends 6-digit code via SMS, returns 202.
- Code valid for 5 minutes, max 5 verify attempts, then must request a new one.
- POST `/auth/otp/verify` returns access (15 min) + refresh (30 days) tokens on success.
- Rate limits per backend §16: 1/60s/phone, 3/15min/phone, 10/hour/IP.
- New phone → user auto-created with `is_phone_verified=true` and `preferred_language` from `Accept-Language`.

**Out of scope:** social login, email/password, biometric.

#### `F-AUTH-002` Token refresh — **P0**
**Story:** As a customer, I want to stay logged in across sessions.

**Acceptance:**
- POST `/auth/refresh` rotates the refresh token (old becomes invalid). New access + refresh issued.
- Logout revokes refresh token immediately.
- Lost-phone flow: user requests new OTP on a new device; on successful login, all prior refresh tokens are revoked (Phase 1.5).

#### `F-ACC-001` Account profile — **P0**
**Story:** As a customer, I want to set my name, email, and language preference.

**Acceptance:**
- GET/PATCH `/me` covers `first_name`, `last_name`, `email`, `preferred_language`.
- Email is optional; if provided, uniqueness enforced.
- Phone change is a separate guarded flow (Phase 2 — for MVP, contact support).

#### `F-ACC-002` Multiple delivery addresses — **P0**
**Story:** As a caregiver, I want to save multiple addresses with different recipients.

**Acceptance:**
- Customer can save up to 10 addresses.
- Each address: label, recipient name, recipient phone, free-text address line, city (Bishkek default), landmark, optional lat/long.
- Exactly one address can be default (DB enforces).
- Address can be selected at checkout, or a new one entered ad-hoc (saved if "save for later" toggle is on).

#### `F-ACC-003` Order history — **P0**
**Story:** As a customer, I want to see my past orders and their status.

**Acceptance:**
- GET `/me/orders` returns paginated orders newest-first (cursor-based).
- Each item shows: order number, placed date, status, total, item count, primary item names.
- GET `/me/orders/:order_number` returns full detail with line items (snapshot data).
- Order numbers are visible to the customer (`PH-2026-000123` format).

#### `F-ACC-004` Reorder — **P0**
**Story:** As Aizhana, I want to reorder my husband's BP meds in one tap.

**Acceptance:**
- "Reorder" action on past order page.
- Adds items to current cart, replacing existing items (with confirmation if cart non-empty).
- Each item validated for stock and current price; out-of-stock items flagged but not blocked.
- Snapshot product names shown if a product was deleted; user can remove or substitute manually.

### 8.2 Catalog & Discovery

#### `F-CAT-001` Browse by category — **P0**
**Story:** As a customer, I want to browse medicines by category.

**Acceptance:**
- Top-level categories from §5.1 visible on homepage and in nav.
- Category page shows products with: image, name, manufacturer, dosage, price, "in stock"/"out of stock", primary symptom tags.
- Filters: manufacturer, country of origin, price range, symptom, active ingredient, "in stock only" (default ON).
- Sort: relevance (default), price asc/desc, name, newest.
- Pagination 24 per page.

#### `F-CAT-002` Browse by symptom — **P0**
**Story:** As Bekzat, I want to find medicine for my sore throat without knowing the name.

**Acceptance:**
- Symptoms grid on homepage and dedicated `/symptoms` page.
- Each symptom (sore throat, headache, fever, cough — wet & dry separate, runny nose, allergy, stomach pain, heartburn, diarrhea, constipation, insomnia) has its own page.
- Symptom page shows products tagged for that symptom, sorted by relevance and stock.
- Symptom synonyms (e.g. "грипп" = "ОРВИ") expand search but aren't separate symptoms.

#### `F-CAT-003` Product detail page — **P0**
**Story:** As a customer, I want to know exactly what this medicine is and whether it's right for me.

**Acceptance — visible without scroll on mobile (above the fold):**
- Primary image
- Name, dosage, form, pack size
- Manufacturer + country
- Price, "in stock"/"out of stock", delivery time estimate
- Primary CTA: "Add to cart"

**Below the fold (collapsible sections, expanded by default for first-time visitors):**
- Composition (active ingredients with doses)
- Indications ("what it treats")
- Usage instructions
- Side effects
- Contraindications
- Storage requirements (if special)
- Manufacturer details

**Always visible footer:**
- Up to 4 alternatives with same active ingredient (`F-CAT-007`)

**Out of scope:** customer reviews, Q&A, "people also bought" (Phase 2).

#### `F-CAT-004` Search by name — **P0**
**Story:** As a customer, I know the medicine I want; let me find it fast.

**Acceptance:**
- Search box on every page (header sticky on mobile).
- Searches across name, short description, active ingredient name (in current language).
- Handles Cyrillic prefix matches: "пара" → "Парацетамол."
- Handles common typos via FULLTEXT ngram (mvp): "парацитамол" should still find "Парацетамол."
- Results: paginated list with same item shape as category browse.
- Empty state: "Ничего не найдено по запросу 'X'. Попробуйте: …" with up to 5 popular searches.

#### `F-CAT-005` Search suggestions / autocomplete — **P1**
**Story:** As a customer, I want suggestions while I type.

**Acceptance:**
- After 2 characters, debounced 250ms.
- Up to 8 suggestions: products (with thumbnail), categories, symptoms.
- Tap suggestion → straight to product / category / symptom page.

#### `F-CAT-006` Filter by active ingredient — **P1**
**Story:** As a returning customer, I want to find a generic version with the same ingredient.

**Acceptance:**
- Active ingredient is a chip on the product page.
- Tapping the chip leads to "All products with paracetamol" filter, sorted by price ascending.

#### `F-CAT-007` Substitutes (same active ingredient) — **P0**
**Story:** As a customer, I want to see cheaper or in-stock alternatives.

**Acceptance:**
- On product detail page, show up to 4 products with the **same primary active ingredient and dose**, in stock, sorted by price ascending.
- Excludes the current product.
- If nothing matches dose exactly, fall back to same active ingredient (different dose), labelled "different dosage."
- If the current product is out of stock, the substitutes block is **moved above the fold**, with header "Available alternatives."

#### `F-CAT-008` Out-of-stock product behaviour — **P0**
**Story:** As a customer, I want to know an item isn't available without being misled.

**Acceptance:**
- Out-of-stock products are **listed** but with disabled CTA, "Currently unavailable" label.
- "Notify when available" — Phase 2.
- Substitutes block prominently shown.
- Search and category filters default to "in stock only" but customer can toggle off.

### 8.3 Cart & Checkout

#### `F-CART-001` Cart — **P0**
**Story:** As a customer, I want to add items to my cart and review before paying.

**Acceptance:**
- Guest cart supported (via session_id) and persists 30 days.
- Login merges guest cart with user cart (additive; same product → quantities sum).
- Quantity changes re-validate stock and current price.
- Cart shows: items, quantity, line total, subtotal, estimated delivery fee, total.
- Items in cart respect `max_per_order` cap from product.

#### `F-CART-002` Stock revalidation at checkout — **P0**
**Story:** As a customer, I shouldn't be told an item is in stock and then it isn't.

**Acceptance:**
- At "Place order" click, system re-checks stock and prices.
- If anything changed:
  - Out of stock → item highlighted, customer chooses to remove or replace
  - Price changed → flagged with old/new, customer must confirm
  - Cannot proceed until conflicts resolved.

#### `F-CHECKOUT-001` Single-page checkout — **P0**
**Story:** As Bekzat, I want to check out in 30 seconds.

**Acceptance:**
- Steps on one screen, no multi-page wizard:
  1. Delivery: pick saved address or enter new; choose Delivery vs Pickup
  2. Payment: COD (default), or card online (Phase 1.5), or wallet (Phase 2)
  3. Notes (optional)
  4. Review + Confirm
- Total updates live as choices change.
- Idempotency-Key header sent automatically on confirm (UUID generated client-side, retried on network failure).

#### `F-CHECKOUT-002` Delivery options — **P0**
**Acceptance:**
- **Delivery to address** in Bishkek city limits — flat 200 KGS for MVP; free over 1500 KGS subtotal.
- **Pickup from pharmacy** — free.
- Outside Bishkek city limits — show "Not available in your area" and offer pickup.
- **Cold-chain item rules** apply (§5.4) — UI may force pickup or specify same-day delivery.

#### `F-CHECKOUT-003` Payment methods — **P0** (COD), **P1** (card)
**Acceptance:**
- COD always available except for orders > 10,000 KGS (require pre-payment).
- Card online via Freedom Pay (P1 — first card integration).
- O!Dengi, MBank wallet (Phase 2).
- Failed payment must not consume stock — reservation released after 30 minutes if payment not completed.

### 8.4 Orders

#### `F-ORD-001` Order tracking — **P0**
**Story:** As a customer, I want to know where my order is.

**Acceptance:**
- After placing an order, redirect to order-status page (`/orders/PH-2026-000123`).
- Shows current status with timeline (placed, confirmed, preparing, out for delivery, delivered).
- Shows courier name and phone when status = `out_for_delivery`.
- Auto-polls every 60 seconds while order is active; stops once delivered or cancelled.

#### `F-ORD-002` Order cancellation by customer — **P0**
**Story:** As a customer, I want to cancel an order if I change my mind.

**Acceptance:**
- Customer can cancel while status ∈ {pending, confirmed}.
- Cannot cancel once status = preparing or beyond.
- Cancellation releases stock reservations immediately.
- If paid by card, refund is initiated (manual for MVP — system creates a refund task; admin completes via gateway dashboard).

#### `F-ORD-003` Order cancellation by admin — **P0**
**Story:** As Nurzat, I need to cancel orders we can't fulfill.

**Acceptance:**
- Admin can cancel from any pre-delivered status with required `reason` field.
- Refund flow same as F-ORD-002.
- Customer is SMS-notified with the reason.

### 8.5 Admin — Catalog

#### `F-ADM-CAT-001` Product CRUD — **P0**
**Acceptance:**
- Admin can create, edit, soft-delete products.
- Required fields per backend `Product` model (§8 of backend blueprint).
- Translations required for at least RU; KY/EN optional but encouraged.
- Image upload triggers worker pipeline (resize, WebP variants, R2 upload).
- Slug auto-generated from RU name (transliterated to Latin); admin can override.
- SKU must be unique; barcode unique if provided.

#### `F-ADM-CAT-002` Bulk import (CSV/XLSX) — **P0**
**Acceptance:**
- Upload accepts CSV or XLSX up to 10 MB.
- Required columns documented in admin UI; example template downloadable.
- Dry-run validation runs first, returns row-level errors as a downloadable file.
- On confirm, runs as background job (`process_product_import`).
- Idempotent by SKU: existing rows updated, new rows inserted, missing SKUs **never deleted by import**.
- Translations imported via columns: `name_ru`, `name_ky`, `name_en`, etc.

#### `F-ADM-CAT-003` Bulk price update — **P0**
**Acceptance:**
- Admin can apply a percentage or absolute change to filtered products (by category, manufacturer, etc.).
- Always preview before apply.
- Audit log records the operation with before/after for each affected row.

#### `F-ADM-CAT-004` Categories, manufacturers, ingredients, symptoms CRUD — **P0**
**Acceptance:**
- Standard CRUD for each.
- Cannot delete a category that has products (must reassign first).
- Cannot delete a manufacturer with products (must reassign or soft-delete).

### 8.6 Admin — Inventory

#### `F-ADM-INV-001` Receive stock — **P0**
**Acceptance:**
- Search/scan to find product in catalog.
- Form: batch number, expiry date, manufacture date (optional), quantity, cost price, supplier (optional).
- Saving creates `inventory_batches` row, increments `branch_products.total_quantity`, writes `stock_movements` 'received'.
- Hard block: `expiry_date` ≤ today + 7 days unless explicit override toggle (rare — usually receiving error).
- Soft warn: `expiry_date` ≤ today + 60 days.

#### `F-ADM-INV-002` Manual stock adjustment — **P0**
**Acceptance:**
- Admin can adjust a specific batch (damage, write-off, count correction) with reason.
- Writes `stock_movements` with appropriate type and signed quantity.

#### `F-ADM-INV-003` Near-expiry & low-stock dashboards — **P0**
**Acceptance:**
- Dashboard tab with two reports:
  - Near-expiry: filter by 30/60/90 days; sortable by days-to-expiry
  - Low-stock: products at or below their threshold
- Daily scheduled email at 06:00 Asia/Bishkek to branch manager with both reports.

#### `F-ADM-INV-004` Inventory movement audit — **P0**
**Acceptance:**
- Browse `stock_movements` with filters: date range, product, branch, movement type, admin, order.
- Export to CSV.

### 8.7 Admin — Orders

#### `F-ADM-ORD-001` Order queue — **P0**
**Acceptance:**
- Default view: "Today's orders," sorted oldest first, status `pending` or `confirmed` highlighted.
- Filters: status, branch, date range, payment method, search by order number / phone / customer name.
- Bulk actions: confirm, mark preparing, mark out-for-delivery, mark delivered (Phase 1.5; MVP single-order ops are fine).

#### `F-ADM-ORD-002` Order detail / picking screen — **P0**
**Acceptance:**
- All info needed to fulfill: items, quantities, suggested batches, customer contact, delivery address.
- Per item, ability to swap batch (different batch of same product).
- "Mark ready" only enabled when all items checked off.
- Status transitions per the order state machine (§9).
- "Print picking sheet" → printable PDF.

#### `F-ADM-ORD-003` Refund/cancellation — **P0**
**Acceptance:**
- Cancel: per F-ORD-003.
- Refund (full or partial) for paid orders: admin enters amount, reason; system creates a `payments` row of type refund and surfaces to manual reconciliation list (for MVP, admin executes refund in payment gateway dashboard).

### 8.8 Admin — Users & Team

#### `F-ADM-USR-001` Customer search — **P1**
**Acceptance:**
- Search customers by phone, email, name.
- View profile: addresses, order history, total spent.
- No edit of customer data except by Super Admin (privacy).

#### `F-ADM-TEAM-001` Team management — **P0**
**Acceptance:**
- Super Admin can invite, edit, suspend, delete admin users.
- Roles: `super_admin`, `branch_manager`, `pharmacist`, `content_editor`.
- Branch Manager and below restricted to their branch (per `branch_id`).
- All actions audited.

#### `F-ADM-AUD-001` Audit log viewer — **P1**
**Acceptance:**
- Browse `admin_audit_log` with filters: actor, entity, date range.
- Diff view shows before/after JSON for updates.

### 8.9 Reports

#### `F-RPT-001` Sales report — **P0**
- Daily / weekly / monthly revenue, units, AOV, top products, top categories.
- CSV export.

#### `F-RPT-002` Inventory valuation — **P1**
- Cost-price valuation of current stock per branch.

#### `F-RPT-003` Customer cohorts — **P2**
- Repeat purchase, retention curves.

EOF
echo "Part 1 done. Lines so far:"
wc -l /home/claude/pharmacy-design/PRODUCT_BLUEPRINT.md
---

## 9. Order State Machine

The single most important state machine in the product. **Implement exactly as drawn.**

```
                  ┌────────────────────────────────────────────────────┐
                  │                                                    │
                  │    [customer cancels OR admin cancels OR auto]     │
                  │                                                    ▼
   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────┐
   │ pending  │──▶│ confirmed│──▶│ preparing│──▶│ ready_for_   │──▶│ delivered│
   │          │   │          │   │          │   │  pickup OR   │   │          │
   │          │   │          │   │          │   │ out_for_     │   │          │
   │          │   │          │   │          │   │  delivery    │   │          │
   └──────────┘   └──────────┘   └──────────┘   └──────────────┘   └──────────┘
                                                                         │
                                                                         ▼
                                                                   ┌──────────┐
                                                                   │ refunded │
                                                                   └──────────┘
                                                                   (admin only)
```

### 9.1 Allowed transitions

| From | To | Trigger | Side effects |
|---|---|---|---|
| (none) | `pending` | customer places order | reserve stock, write `stock_movements 'reserved'`, increment `branch_products.reserved_quantity` |
| `pending` | `confirmed` | admin confirms (after phone confirmation if needed) | none |
| `pending` | `cancelled` | customer or admin | release reservations, `stock_movements 'released'`, decrement `reserved_quantity` |
| `pending` | `cancelled` | **auto, after 24h** | same as above; `cancel_reason='auto_timeout_unconfirmed'` |
| `confirmed` | `preparing` | admin starts picking | none |
| `confirmed` | `cancelled` | customer or admin | release reservations |
| `preparing` | `ready_for_pickup` (pickup orders) | admin marks ready | convert reservations → sales: `stock_movements 'sold'`, decrement both `reserved_quantity` and `total_quantity` |
| `preparing` | `out_for_delivery` (delivery orders) | admin hands to courier | same as above |
| `preparing` | `cancelled` | admin only, with reason | release reservations |
| `ready_for_pickup` | `delivered` | customer picks up | none (stock already adjusted at preparing→ready) |
| `out_for_delivery` | `delivered` | courier confirms | none |
| `out_for_delivery` | `cancelled` (refused / undelivered) | admin only, with reason | restock: `stock_movements 'received'` (special case — same batch if known) |
| `delivered` | `refunded` | admin only | for MVP this is a status flip + manual refund handling; stock is **not** restocked (returned medicine is not resold) |

### 9.2 What is "auto" allowed to do

The system itself can transition:
- `pending` → `cancelled` after 24h with `cancel_reason = 'auto_timeout_unconfirmed'`. Customer + admin both notified.
- `pending` → `cancelled` after 30 minutes if **payment by card** was selected and not completed.
- Nothing else. Every other transition is admin-driven.

### 9.3 Stock reservation lifecycle

```
Order placed:        total_qty = 100, reserved = 5  (5 in this order)
Order preparing:     total_qty = 100, reserved = 5  (still reserved)
Order ready/dispatch:total_qty =  95, reserved = 0  (now sold)
```

If order is cancelled at any step before "ready/dispatch":
```
total_qty = 100, reserved = 0
```

### 9.4 Payment status is independent of order status

Two separate state machines:

**Payment status:** `pending → authorized → paid → (refunded | partially_refunded)`
**Order status:** as above.

A COD order has `payment_status = pending` until delivered, then `paid`. A card-paid order has `payment_status = paid` immediately after gateway success and stays paid through delivery.

---

## 10. Inventory & Stock Rules

These are the operational rules of the pharmacy. Encode them as code, not preferences.

### 10.1 Stock truth rules

1. **`branch_products.total_quantity` is the cached aggregate.** It must equal `SUM(quantity_remaining)` of non-expired batches. Reconciled nightly (job `reconcile_stock_cache`).
2. **Available stock = `total_quantity - reserved_quantity`.** This is what customer-facing pages and cart validation use.
3. **A product with available stock = 0 is shown as "out of stock"**, regardless of `is_available` flag. A product with `is_available = false` is hidden from the storefront entirely (not shown as out of stock).
4. **Stock changes go through `stock_movements`.** Never UPDATE `total_quantity` without a paired movement row in the same transaction.

### 10.2 FEFO selection rules

1. When fulfilling an order line, pick batches with the **earliest `expiry_date` first**, tie-break by earliest `received_at`.
2. May split across multiple batches if no single batch has enough.
3. Skip batches with `expiry_date <= CURRENT_DATE`.
4. Skip batches with `quantity_remaining = 0`.
5. Use `FOR UPDATE SKIP LOCKED` to allow concurrent orders to pick non-overlapping batches.

### 10.3 Expiry rules

| Days to expiry | What happens |
|---|---|
| > 60 | Normal sale |
| 30–60 | Normal sale; admin sees daily report; optional discount via manual price edit |
| 8–29 | **Sold only if branch manager toggles `allow_short_dated` on the batch.** Product page shows "Best before YYYY-MM-DD" prominently. |
| ≤ 7 | **Hard block** from sale. Visible in admin for write-off only. Excluded from `total_quantity`. |
| ≤ 0 | **Excluded from any stock count.** Shown only in audit/expired report. |

> The 7-day hard block is enforced in the FEFO query and in `branch_products.total_quantity` reconciliation.

### 10.4 Cold-chain rules

A product where `requires_cold_chain = true`:
- Can only be in a cart if delivery is same-day OR pickup
- Checkout shows a banner: "Этот товар требует доставки в день заказа" / "This product requires same-day delivery."
- During Bishkek summer (1 June – 31 August), pickup-only by default; delivery requires the courier to use a refrigerated bag (admin option, +X KGS fee — Phase 2)

### 10.5 Receiving rules

- Receiving a batch is the **only way new stock enters the system**. No "manual quantity edit" except as an `adjusted` movement with reason.
- Cost price is required for accounting; never shown to customers.
- Batch number can repeat across products and across branches but is unique within `(branch, product)`.

### 10.6 Reservation timeout

- Stock reserved by an order placed but not yet confirmed: held for 24 hours, then auto-released (job `release_pending_orders`).
- Stock reserved by a card-payment order awaiting gateway confirmation: held for 30 minutes, then released.

### 10.7 Recall handling (Phase 2 spec, MVP manual)

When a manufacturer recall happens:
- Admin marks the batch `recalled = true` (Phase 2 column; for MVP, admin uses notes + write-off)
- System lists all `order_items` linked to that batch — those customers are contacted manually
- Stock from recalled batch is moved out via `stock_movements 'damaged'` (or a future 'recalled' type)

---

## 11. Pricing, Discounts & Payment UX

### 11.1 Price display

- All prices in **KGS** (сом). Show as `1 250 ₸` — no, wait, KGS is `сом`, written as `1 250 сом` or `1 250 KGS`. **Use `сом` in Russian/Kyrgyz UI; `KGS` in English UI.**
- No decimals on display by default (whole сом). Use 2 decimals only on totals where fractional KGS arise.
- Compare-at price (if set) shown struck through, with new price next to it.

### 11.2 Pricing rules

- **One price per (branch, product).** No customer-segmented pricing in MVP.
- Price changes apply to **future orders only.** In-flight orders keep their snapshot price.
- Cart re-validates price at checkout — customer must confirm if price changed.
- Negative price impossible (DB constraint).

### 11.3 Discounts (MVP)

For MVP, discounts are **direct price edits** by an admin. No discount engine, no coupons.

- Admin can set `compare_at_price > price` to display "ON SALE" badge.
- Bulk price update tool (`F-ADM-CAT-003`) supports percentage discounts on a filtered set.
- A single `discount_amount` on the order is reserved for hand-applied adjustments by admin (e.g., "loyal customer, take 100 off") — UI for this is Phase 2.

### 11.4 Delivery fee

| Subtotal | Delivery fee |
|---|---|
| < 1 500 KGS | 200 KGS |
| ≥ 1 500 KGS | Free |
| Pickup | 0 (always) |
| Cold-chain summer surcharge | +100 KGS (Phase 2) |

Show the threshold to customers in cart: "Add 350 сом for free delivery."

### 11.5 Payment UX

- COD is the default radio button — Aizhana and Gulnara prefer it overwhelmingly.
- Card online is a clear second option; show payment-provider logo for trust.
- After clicking "Place order" with card payment:
  - Order is created with `status='pending'`, `payment_status='pending'`, stock reserved
  - Customer redirected to gateway page
  - On success → webhook updates `payment_status='paid'`; order can be confirmed
  - On failure → webhook flips `payment_status='failed'`; user can retry (still within 30-min window)
  - On 30-min timeout → order auto-cancelled, stock released

### 11.6 What customers see at each step

| Screen | Price summary shown |
|---|---|
| Product page | Unit price |
| Cart | Each line + subtotal + delivery preview + total |
| Checkout | Subtotal, delivery, discount (if any), total, currency |
| Confirmation | Same as checkout, frozen |
| Order detail | Same, with payment status |

---

## 12. Search & Discovery Behaviour

Search is the highest-traffic feature after the homepage. Behaviour matters.

### 12.1 What searches must return useful results

These should all find Paracetamol products in MVP (test cases for QA):

| Query (RU) | Why |
|---|---|
| `парацетамол` | Exact name |
| `пара` | Prefix |
| `парацитамол` | Common typo |
| `paracetamol` | Latin spelling |
| `от головы` | Symptom phrase |
| `жаропонижающее` | Indication |
| `панадол` | Brand for same ingredient |
| `головная боль` | Symptom |
| `температура` | Symptom |
| `анальгин` | Soviet-era brand (synonym handling) |

### 12.2 Result ranking

1. Exact name match (case- and accent-insensitive)
2. Prefix match on name
3. FULLTEXT match on name + description
4. Active ingredient match
5. Symptom-tag match
6. Manufacturer / brand match

Within the same tier: in-stock first, then `is_featured`, then by recent sales (Phase 2; MVP uses created_at desc).

### 12.3 Empty-state behaviour

- When 0 results: show top 5 popular searches + link to all categories
- Log every zero-result query (`search_log`) — this is a catalog gap signal

### 12.4 Search synonyms (admin-maintainable, application-side expansion)

Examples that must work at MVP:

```
"простуда" ↔ "ОРВИ" ↔ "грипп" ↔ "respiratory infection"
"живот болит" ↔ "боль в животе" ↔ "stomach pain"
"таблетки от головы" ↔ "головная боль" ↔ "обезболивающее"
"кашель" → without expansion (don't conflate dry/wet cough)
"анальгин" → "метамизол" (active ingredient)
"цитрамон" → "парацетамол + кофеин + ацетилсалициловая кислота"
```

Synonyms live in `symptom_translations.synonyms` (text array) and an application-level dictionary for ingredient-to-brand and brand-to-ingredient.

### 12.5 What search must never do

- Auto-suggest a medicine for a symptom in a way that looks like medical advice ("for headache, take paracetamol")
- Show out-of-stock-only results without making it obvious
- Mix search results from disabled or soft-deleted products
- Display experimental ranking that hides clear name matches in favour of fuzzy ones

---

## 13. Catalog Content Standards

What "good" looks like for a product entry. Content editors and Claude Code (when generating placeholder content) must follow these.

### 13.1 Mandatory fields per product

| Field | Required for storefront? | Standard |
|---|---|---|
| Name (RU) | Yes | Capitalised, brand first then dosage: "Панадол 500мг" |
| Name (KY) | Recommended | If absent, fallback to RU |
| Name (EN) | Optional | Latin name if commonly used |
| SKU | Yes | Internal, unique |
| Barcode | Recommended | EAN-13 |
| Manufacturer | Yes | Linked to manufacturers table |
| Category | Yes | One leaf category |
| Form | Yes | From enum |
| Pack size label | Yes | Human-readable: "20 таблеток" |
| Active ingredients (≥1) | Yes for medicine | Linked with dose |
| Primary image | Yes | Real product photo, white background, ≥ 600×600 |
| Short description (RU) | Yes | ≤ 200 chars, summarises what it's for |
| Description (RU) | Yes | Longer prose, max 2000 chars |
| Indications / what it treats | Yes for medicine | Bullet list |
| Usage instructions | Yes for medicine | Plain language, dosage by age/weight if applicable |
| Side effects | Yes for medicine | Standard SmPC text, plain language summary |
| Contraindications | Yes for medicine | Standard SmPC text |
| Symptom tags | At least one | From symptoms taxonomy |
| Storage requirements | If special | E.g. "2–8°C" |

### 13.2 Style guide (RU)

- Use **second-person plural** (вы) for instructions, not informal ты
- Avoid medical jargon when a plain word works (use "от температуры" not "антипиретик" in headlines, both acceptable in description)
- Numbers and units: digits + space + unit ("500 мг" not "500мг")
- No marketing claims like "лучший," "самый эффективный" — leads to compliance issues
- No claims of disease cure unless on the product's regulatory label

### 13.3 Image standards

- Square format, ≥ 600×600
- Real product photo, white or transparent background
- No watermarks, no text overlays
- Multiple images allowed (front, back/box, blister); first one is primary
- Generated to thumbnail (200), medium (600), large (1200) WebP variants by the worker pipeline

### 13.4 Translation policy

- RU is **mandatory** for storefront visibility — a product without RU translation does not appear.
- KY is **strongly encouraged** — if missing, RU shown with a small "RU" badge (Phase 2; MVP just falls back silently).
- EN is **optional** — primarily for the small expat market.

### 13.5 Forbidden content

- Lyrics, poems, third-party copy directly copied from manufacturer's site (rewrite in our voice)
- Customer testimonials about specific medicines (for safety — if reviews are added later, only on cosmetics/devices)
- Comparisons to competitor products
- Health advice ("if you have X, take Y")

---

## 14. Notification Strategy

### 14.1 Channels and when to use which

| Channel | Use cases | Use case rules |
|---|---|---|
| **SMS** | OTP, order milestones, urgent service messages | Short, language-matched, always includes order number |
| **Email** | Order receipt (if email on file), monthly statements (Phase 2), admin reports | Transactional only |
| **Push** | (Phase 2) | n/a in MVP |
| **In-app** | Status changes when app is open | Real-time on order detail page |

### 14.2 SMS triggers (customer)

| Event | When | Recipient | Sample (RU) |
|---|---|---|---|
| OTP request | On request | Account phone | `Pharmacy: ваш код 348721. Никому не сообщайте.` |
| Order placed | On `pending` | Account phone | `Заказ PH-2026-000123 принят. Скоро свяжемся для подтверждения.` |
| Order confirmed | On `confirmed` | Account phone | `Заказ PH-2026-000123 подтвержден. Готовим к отправке.` |
| Out for delivery | On `out_for_delivery` | Recipient phone | `Заказ PH-2026-000123 в пути. Курьер: Марат, +996700111222` |
| Delivered | On `delivered` | Account phone | `Заказ PH-2026-000123 доставлен. Спасибо!` |
| Cancelled | On `cancelled` | Account phone | `Заказ PH-2026-000123 отменен. Причина: <reason>. Если есть вопросы — +996700111111` |

### 14.3 SMS triggers (admin)

- Daily 06:00 — near-expiry + low-stock combined SMS to branch manager (only counts; details in email)
- Critical errors (job failures, payment reconcile failures) — SMS to super admin

### 14.4 Email triggers

- Order receipt with itemised total — to customer email if provided
- Daily near-expiry + low-stock report — to branch manager with full table
- Daily sales summary — to super admin
- Failed-job report — to super admin

### 14.5 SMS rules

- Max 1 SMS per status change. No marketing SMS in MVP.
- Quiet hours: do not send between 22:00 and 08:00 Asia/Bishkek **except** for OTP and `out_for_delivery` (which is happening anyway).
- If recipient phone fails delivery, retry once after 5 min; otherwise log and move on.
- Customer can opt out of non-critical SMS in account settings (Phase 2).

---

## 15. Trust & Credibility Signals

This is a regulated category in spirit if not letter. Customers trust their pharmacist's white coat. We need digital equivalents.

### 15.1 What every page should communicate

| Signal | Where | What |
|---|---|---|
| Real pharmacy | Header, footer | Real address, phone, photo of storefront |
| Pharmacist on staff | About page, footer | Named pharmacist with credentials |
| Authentic products | Product pages | "From licensed distributors" badge |
| Fresh stock | Product pages | "Best before" / "expires in X days" if < 60 |
| Real customer support | Header CTA | Phone number prominently, "Call us" tap-to-dial |
| Privacy | Footer | Link to privacy policy in 3 languages |

### 15.2 Things that destroy trust (avoid)

- Stock that turns out to be wrong on arrival
- Hidden fees revealed at checkout
- Delivery promises we can't keep
- Auto-redirects to payment without total confirmation
- Generic stock photos for medicine — looks like a knockoff site
- Excessive marketing copy ("BEST DEAL!!!")
- Asking for personal data not needed for the order

### 15.3 Things that build trust (do)

- Show pharmacy license number in footer
- Show batch and expiry on product detail (Phase 2 visible to customer; MVP visible only at order detail post-purchase)
- Tap-to-call customer support always one tap away
- Receipt and order detail pages saveable / printable
- Clear, conversational error messages — not "ERR_500"

---

## 16. Localization & Cultural Notes

### 16.1 Language priority

1. Russian — default, primary
2. Kyrgyz — promoted in cities, expected for state-aligned content
3. English — small expat audience, primarily Bishkek

### 16.2 Things that differ across languages

| Concept | RU | KY | EN |
|---|---|---|---|
| Greeting (header) | Здравствуйте | Саламатсызбы | Hello |
| Cart | Корзина | Себет | Cart |
| Search placeholder | Поиск лекарств и средств | Дары жана каражаттарды издөө | Search medicines |
| Currency suffix | сом | сом | KGS |
| Decimal separator | comma | comma | period |
| Date format | DD.MM.YYYY | DD.MM.YYYY | DD/MM/YYYY (or YYYY-MM-DD in admin) |
| Phone format display | +996 700 12 34 56 | same | same |

### 16.3 Address conventions

A real Bishkek address looks like:

> Бишкек, мкр Асанбай, дом 12, кв 45, ориентир: напротив школы №42

Key elements:
- City (mostly "Бишкек" for MVP; sometimes a district name)
- Microdistrict (`мкр X`) **OR** street (`улица Y`) — both common, never both
- Building (`дом N`) and apartment (`кв M`) when relevant
- Landmark (`ориентир: …`) — frequently the most useful field for couriers

> **Implication:** address is a free-text `address_line` plus optional `landmark` field. Don't try to structure street/building/apartment as separate fields — Kyrgyz addresses don't fit that mold.

### 16.4 Names

- First name + last name; patronymic optional, common in older generations
- Order: First Last (Russian default), but admin records may show Last First in some legacy data
- Honorifics not used in transactional UX

### 16.5 Phone numbers

- All KG mobile numbers: `+996` followed by 9 digits
- Operators: 700 (Megacom), 770 (O!), 550 (Beeline), 778 (FoneX), 558 (Beeline new), and a few others
- Display grouped: `+996 700 12 34 56`
- Store as E.164 in DB

### 16.6 Working week

- Pharmacy is open 7 days; deliveries run 7 days
- Working hours typical: 09:00 – 22:00
- Public holidays may reduce delivery (Phase 2: mark blackout dates)

---

## 17. Edge Cases & Failure Modes

> The point of this section: the system must do something specific in every one of these. "Default behaviour" is not a plan.

### 17.1 Cart & checkout edge cases

| Case | Behaviour |
|---|---|
| Customer has cart with 5 items; one goes out of stock between cart-load and place-order | Block place-order, show "These items are no longer available" with each affected line; customer chooses to remove or pick alternative |
| Customer has cart; price of item changed | Show old price → new price diff; require explicit confirm |
| Guest cart, customer logs in with existing user cart | Merge: same product → quantity sums (capped at `max_per_order`); other items added |
| Customer adds quantity > available | Cap at available; show inline "X available" |
| Customer cart is older than 30 days | Cart expired; redirect to homepage with a message |
| Customer adds cold-chain item to cart, then selects "Standard delivery" | Banner: "This item requires same-day delivery; pickup is also available." Block standard-delivery option for this cart. |
| Customer in cart > `max_per_order` for a product | Cap and tell them why ("Лимит на одну покупку: 3") |

### 17.2 Order edge cases

| Case | Behaviour |
|---|---|
| Order placed, but stock disappears (corrupt data, manual write-off) | Admin gets a flagged order; option to substitute another batch, or cancel with refund |
| Customer wants to cancel after dispatch | Tell them to refuse delivery; courier returns to pharmacy; admin marks `cancelled` with `cancel_reason='customer_refused_at_door'`; if paid, refund |
| Courier reports customer didn't answer | Order returns to pharmacy; admin marks `cancelled`; SMS to customer with "Please call us to reschedule"; restock |
| Customer reports they didn't receive | Admin investigates; if confirmed, mark `cancelled` and refund; if dispute, escalate |
| Order has 3 items, only 2 in stock at picking | Admin calls customer; customer chooses partial fulfillment (with refund of missing item) OR full cancellation |
| Wrong item in delivery (picking error) | Admin creates a corrective order with no charge; customer keeps wrong item or arranges return; audit logs the picking error against the staff member |
| Customer paid online but order cancelled | Refund flow; SMS to customer; customer might wait 3–5 business days for funds to return |
| Card payment authorised but app crashed before order created | The 30-min timeout releases; payment auto-voided by gateway; if not, manual reconciliation finds it |

### 17.3 Auth edge cases

| Case | Behaviour |
|---|---|
| User loses phone, gets new SIM (same number) | Can log in normally on new device; no special flow needed |
| User changes phone number | For MVP: contact support, admin verifies and updates manually; Phase 2: in-app flow with old + new OTP |
| OTP not received | Customer sees a "Resend after 60s" countdown; if still nothing, fallback message: "Please check signal or contact support" |
| User enters wrong OTP 5 times | Lockout for 15 min; suggest waiting and requesting a new code |
| Multiple devices logged in | Allowed; refresh tokens are independent. Logout from one device doesn't affect others. |
| Suspicious activity (many OTP requests from one IP) | Rate-limit at IP level (per backend §16); admin alerted if > 50 OTPs/hour from one IP |

### 17.4 Catalog edge cases

| Case | Behaviour |
|---|---|
| Product has multiple active batches with different expiry | FEFO picks earliest; customer doesn't know about batches at MVP |
| Product has 0 RU translation | Hidden from storefront entirely; admin sees a "translations missing" warning |
| Product image upload fails | Admin sees error inline; product saved without image; cannot be activated until ≥ 1 image present |
| Two products have same name (different doses) | Distinguished by dose in UI: "Парацетамол 500мг" vs "Парацетамол 200мг" |
| Active ingredient renamed | Existing products keep their reference; admin sees historic name in audit log |
| Manufacturer goes out of business | Products keep manufacturer linkage; admin can hide or transfer manually |

### 17.5 Inventory edge cases

| Case | Behaviour |
|---|---|
| Two pharmacists try to receive same shipment simultaneously | Each batch entry is independent; conflict only if same `batch_number` — second insert fails uniquely; UX shows "this batch already received" |
| Counted physical stock differs from system | Admin uses "adjustment" movement with reason; never silently overwrite |
| Batch expires mid-day | Daily 02:00 job marks it expired; same-day adjustment by admin if needed |
| Product deleted while in active orders | Product `deleted_at` set; existing orders still show name/SKU via snapshot; no new orders allowed |
| Cold-chain failure (fridge broke) | Out of system scope — admin pulls affected batches via "damaged" adjustments |

### 17.6 Payment edge cases

| Case | Behaviour |
|---|---|
| Gateway returns success but webhook never arrives | Hourly `payment_reconcile` job catches it |
| Gateway double-charges | Reconciliation flags duplicate; admin issues refund manually |
| COD customer pays but courier doesn't mark delivered | Admin reconciles end-of-day; status corrected |
| COD customer doesn't pay courier | Order marked `cancelled` with reason `unpaid_on_delivery`; restock; customer flagged in admin (Phase 2: restrict COD for repeat offenders) |

### 17.7 Delivery edge cases

| Case | Behaviour |
|---|---|
| Customer not home at delivery | Courier calls; if no answer, returns to pharmacy; one re-attempt within 2 hours; otherwise cancel |
| Wrong address entered | If unreachable, cancel; if customer corrects via phone, courier re-routes (no system change) |
| Courier accident / order lost | Admin handles: refund + apology + (optional) re-ship; full audit trail |
| Address outside service area but somehow accepted | Validate at order placement: city must equal "Bishkek" (string match); other cities rejected with "Pickup available, delivery coming soon" |

### 17.8 System edge cases

| Case | Behaviour |
|---|---|
| Database read replica lag | Reads from primary on all checkout paths; replica only for catalog browse (Phase 2) |
| Redis down | App degrades: rate limits stop counting (fail-open is acceptable for MVP given low volume); cache misses go to DB |
| SMS gateway down | OTPs queued in `sms_log` with `status='queued'`; if down > 5 min, alert; customers see "Code sent" but it isn't — Phase 2: detect and tell them |
| Image storage (R2) down | Existing images served from CDN cache; new uploads fail with retry banner |

---

## 18. Customer Support & Operations

### 18.1 Support channels (MVP)

- **Phone** — primary. Pharmacy phone displayed in header, footer, every transactional SMS, every order detail page. Tap-to-call on mobile.
- **WhatsApp** — secondary (Phase 1.5). Same number.
- **Email** — listed but not primary.
- **In-app chat** — Phase 3+.

### 18.2 Common support scenarios

| Scenario | First-line response | Empowered to |
|---|---|---|
| "Where's my order?" | Look up by phone; share status | n/a |
| "Cancel my order" | Verify identity; cancel if status allows | Cancel orders pre-dispatch |
| "Wrong item delivered" | Apologise; create corrective order; offer pickup of wrong item | Issue partial/full refund |
| "Item expired/damaged" | Apologise; refund and replacement | Issue refund up to order total |
| "Can't login" | Reset by phone change (manual KYC) | Phone change |
| "What does this medicine do?" | Read product page aloud; for medical advice, defer to pharmacist | Transfer to pharmacist |

### 18.3 Operations cadence

- **Daily 09:00** — branch manager opens app, reviews near-expiry/low-stock email, addresses anything urgent
- **Throughout day** — pharmacist picks orders as they come in; aim to confirm within 15 min, dispatch within 1–2 hours
- **Daily 21:00** — close-of-day reconciliation: count physical cash, check COD totals, write off any spoilage

### 18.4 SLAs (internal targets, not customer commitments at MVP)

| SLA | Target |
|---|---|
| Order confirmation | < 15 min during business hours |
| Order ready (delivery) | < 60 min from confirm |
| Delivery (Bishkek) | < 3 hours from confirm |
| Customer support response (phone) | < 30 sec wait during business hours |
| Catalog updates published | < 60 sec after admin save |

---

## 19. Admin Workflows

This section is for Claude Code to understand the *flow* admins go through, not just the screens.

### 19.1 Daily flow — Pharmacist (Aida)

```
09:00  Open admin → "Pending orders" tab → pick anything from overnight
09:30  Receive deliveries → use "Receive batch" for each shipment
10:30  Continue picking orders as they arrive
12:30  Lunch
13:30  Pick orders, take customer support calls
17:00  Final picking pass for same-day delivery cutoff (18:00)
21:00  Close-of-day: confirm all delivered orders are marked, count cash
22:00  Close
```

### 19.2 Weekly flow — Branch Manager (Nurzat)

```
Monday      Review weekly sales report; plan stock reorders with supplier
Tuesday     Reorder process; receive POs into "incoming" (manual until Phase 2)
Wednesday   Mid-week review; near-expiry handling
Thursday    Staff scheduling
Friday      Weekly cash reconciliation
Saturday    Light day; customer support coverage
Sunday      Light day
```

### 19.3 Onboarding flow — New admin user

```
1. Super Admin creates admin_users row (email, role, branch)
2. System sends invitation email with magic link
3. Admin clicks link → sets password (argon2id) → optional TOTP
4. First login lands on role-appropriate dashboard
```

For MVP, MFA optional. Strongly recommended for `super_admin` and `branch_manager`. Required (Phase 2) for super admin.

### 19.4 Picking screen — design notes

This is the screen Aida uses 50× a day. Optimise for speed.

- Dense table: Item, Qty, Suggested batch (with expiry), Shelf location (Phase 2), Picked checkbox
- Keyboard navigation: ↓/↑ to move row, Space to check, Enter to "next order"
- Bold visual cue when an item's suggested batch differs from what's most recently received (rare but happens)
- Print button → PDF picking sheet for offline picking

### 19.5 Permissions matrix

| Action | super_admin | branch_manager | pharmacist | content_editor |
|---|---|---|---|---|
| View any order | ✓ | own branch | own branch | — |
| Confirm/cancel order | ✓ | own branch | own branch | — |
| Refund | ✓ | own branch | — | — |
| Receive stock | ✓ | own branch | own branch | — |
| Adjust stock | ✓ | own branch | own branch (with reason) | — |
| CRUD products | ✓ | — | — | ✓ |
| Bulk price update | ✓ | own branch (price only) | — | — |
| Bulk import | ✓ | — | — | ✓ |
| Manage admins | ✓ | — | — | — |
| View reports | ✓ | own branch | own branch (subset) | — |
| View audit log | ✓ | own branch | — | — |

---

## 20. Compliance, Ethics & Safety

Even with looser regulation than Western markets, we hold ourselves to high standards. This is a pharmacy, not a marketplace.

### 20.1 Hard product rules

- **No expired sales, ever.** Enforced by FEFO + 7-day hard block.
- **No counterfeit knowingly accepted.** Receiving from licensed distributors only; recorded in `suppliers`.
- **No medical advice given.** Symptom navigation OK. Diagnosis or "take this for that" not OK.
- **No prescription drugs sold without prescription where law requires it.** MVP scope is OTC; if a controlled drug is added, the system must support prescription verification (Phase 3+).
- **No selling to under-age for age-restricted products.** Schema has `min_age`; enforcement for Phase 2 (currently OTC scope doesn't include strictly age-gated items).

### 20.2 Privacy & data handling

- Phone numbers, addresses are PII — encrypted in transit, hashed for OTP, restricted access.
- Order history is private to the customer and audit-loggable to admins.
- No selling, sharing, or analytics-export of customer-identifiable data to third parties.
- "Right to be forgotten" — Phase 2 feature: customer requests deletion → soft-delete user (orders retained without name/phone, replaced with hashes).

### 20.3 Marketing ethics

- No SMS marketing in MVP. Transactional only.
- No push notifications about discounts.
- No "scarcity" UX patterns ("Only 2 left!" — we explicitly don't show this; see §3.3).
- No fake countdowns or fake reviews.

### 20.4 What we tell users when something goes wrong

- Plain language. No "Error 500."
- Specific where possible: "We couldn't reserve all items in your cart. Item X is now out of stock."
- Always offer the next action: "Remove and continue" or "Pick alternative."
- Apology in tone, not in length.

### 20.5 Legal pages required at launch

- Terms of Service
- Privacy Policy
- Delivery Terms
- Return/Refund Policy
- Pharmacy License & Contact

All in RU, KY, EN. Static content, served from `/content/pages/:slug`.

---

## 21. User-Facing Copy Library

> **Use these strings.** Don't paraphrase, don't translate ad-hoc. Add new keys here when needed. Translation files in `/app/i18n/<lang>.json` mirror this structure.

### 21.1 Key naming

```
<surface>.<context>.<intent>
```

Examples: `cart.empty.title`, `auth.otp.sent`, `order.status.delivered`, `error.out_of_stock`

### 21.2 Sample copy table — RU primary

| Key | RU | KY | EN |
|---|---|---|---|
| `auth.otp.title` | Введите номер телефона | Телефон номериңизди жазыңыз | Enter your phone number |
| `auth.otp.send_button` | Получить код | Код алуу | Get code |
| `auth.otp.sent` | Код отправлен. Действителен 5 минут. | Код жөнөтүлдү. 5 мүнөт жарактуу. | Code sent. Valid for 5 minutes. |
| `auth.otp.code_label` | Код из SMS | SMSтен код | Code from SMS |
| `auth.otp.verify_button` | Войти | Кирүү | Sign in |
| `auth.otp.invalid` | Неверный код. Попробуйте ещё раз. | Туура эмес код. Кайра аракет кылыңыз. | Wrong code. Try again. |
| `auth.otp.too_many` | Слишком много попыток. Запросите новый код. | Аракет көп. Жаңы код сураныз. | Too many attempts. Request a new code. |
| `auth.rate_limited` | Слишком много запросов. Подождите немного. | Сурам көп. Бир аз күтө туруңуз. | Too many requests. Please wait a moment. |
| `cart.empty.title` | Ваша корзина пуста | Себетиңиз бош | Your cart is empty |
| `cart.empty.cta` | Перейти к покупкам | Дүкөнгө барыңыз | Continue shopping |
| `cart.out_of_stock` | Нет в наличии | Сатууда жок | Out of stock |
| `cart.price_changed` | Цена изменилась | Баасы өзгөрдү | Price has changed |
| `checkout.delivery.address_label` | Адрес доставки | Жеткирүү дареги | Delivery address |
| `checkout.delivery.recipient_label` | Получатель | Алуучу | Recipient |
| `checkout.delivery.landmark_hint` | Например: напротив школы №42 | Мисалы: №42 мектептин жанында | E.g. opposite school №42 |
| `checkout.payment.cod` | Оплата при получении | Алууда төлөө | Cash on delivery |
| `checkout.payment.card` | Картой онлайн | Карта менен онлайн | Card online |
| `checkout.totals.subtotal` | Товары | Товарлар | Subtotal |
| `checkout.totals.delivery` | Доставка | Жеткирүү | Delivery |
| `checkout.totals.discount` | Скидка | Арзандатуу | Discount |
| `checkout.totals.total` | Итого | Жалпы | Total |
| `checkout.free_delivery_hint` | До бесплатной доставки {amount} сом | Акысыз жеткирүүгө {amount} сом | {amount} KGS to free delivery |
| `checkout.confirm_button` | Подтвердить заказ | Буйрутманы тастыктоо | Place order |
| `order.status.pending` | Ожидает подтверждения | Тастыктоону күтүүдө | Awaiting confirmation |
| `order.status.confirmed` | Подтвержден | Тастыкталды | Confirmed |
| `order.status.preparing` | Готовится | Даярдалууда | Being prepared |
| `order.status.ready_for_pickup` | Готов к выдаче | Алууга даяр | Ready for pickup |
| `order.status.out_for_delivery` | В пути | Жолдо | Out for delivery |
| `order.status.delivered` | Доставлен | Жеткирилди | Delivered |
| `order.status.cancelled` | Отменен | Жокко чыгарылды | Cancelled |
| `order.status.refunded` | Возврат | Кайтаруу | Refunded |
| `error.out_of_stock` | К сожалению, этого товара нет в наличии | Тилекке каршы, бул товар сатууда жок | Sorry, this item is out of stock |
| `error.cold_chain_delivery` | Этот товар требует доставки в день заказа или самовывоза | Бул товар буйрутма берилген күнү жеткирилиши же өзү алуу керек | This item requires same-day delivery or pickup |
| `error.cart_expired` | Ваша корзина устарела. Начните заново. | Себетиңиз эскирди. Кайрадан баштаңыз. | Your cart has expired. Please start over. |
| `error.delivery_area` | Доставка пока только в Бишкек. Доступен самовывоз. | Жеткирүү азырынча Бишкекте гана. Өзү алуу болот. | Delivery available only in Bishkek. Pickup is available. |
| `error.network` | Проблема с подключением. Попробуйте ещё раз. | Туташтырууда көйгөй. Кайра аракет кылыңыз. | Connection problem. Please try again. |
| `error.generic` | Что-то пошло не так. Попробуйте позже или позвоните нам. | Бир нерсе туура эмес. Кийин аракет кылыңыз же чалыңыз. | Something went wrong. Try again later or call us. |
| `product.unavailable` | Товар временно недоступен | Товар убактылуу жок | Product temporarily unavailable |
| `product.alternatives.heading` | Похожие препараты | Окшош дары-дармектер | Similar products |
| `product.same_ingredient.heading` | С тем же действующим веществом | Бирдей таасир этүүчү зат менен | Same active ingredient |
| `search.no_results.title` | Ничего не найдено по запросу «{q}» | «{q}» боюнча эч нерсе табылган жок | No results for "{q}" |
| `search.no_results.suggestion` | Попробуйте: {suggestions} | Аракет кылыңыз: {suggestions} | Try: {suggestions} |
| `search.placeholder` | Поиск лекарств и средств | Дары жана каражаттарды издөө | Search medicines |

### 21.3 SMS templates

| Key | Template (RU) |
|---|---|
| `sms.otp` | `Pharmacy: ваш код {code}. Никому не сообщайте.` |
| `sms.order_placed` | `Заказ {order_no} принят. Скоро свяжемся для подтверждения. Pharmacy` |
| `sms.order_confirmed` | `Заказ {order_no} подтвержден. Готовим к отправке. Pharmacy` |
| `sms.order_dispatched` | `Заказ {order_no} в пути. Курьер: {courier_name}, {courier_phone}. Pharmacy` |
| `sms.order_delivered` | `Заказ {order_no} доставлен. Спасибо! Pharmacy` |
| `sms.order_cancelled` | `Заказ {order_no} отменен. Причина: {reason}. Вопросы: {support_phone}` |

KY and EN versions live in the same i18n files.

### 21.4 Tone

- Russian/Kyrgyz: friendly-formal, vy-form, no slang
- English: friendly-neutral, contractions OK
- All languages: short sentences. Single clear next action.

---

## 22. Success Metrics & Analytics

### 22.1 North Star

**Weekly active customers placing at least one order.** Anything we ship should plausibly increase this number.

### 22.2 Acquisition

| Metric | Definition | MVP target (3 months) |
|---|---|---|
| New visitors / week | unique sessions, no auth needed | n/a (track) |
| Signup conversion | % of visitors who complete OTP signup | 8% |
| First-order conversion | % of signups placing an order within 7 days | 35% |

### 22.3 Engagement

| Metric | Definition | MVP target |
|---|---|---|
| Search→PDP rate | % of searches that lead to a product detail view | 60% |
| Zero-result rate | % of searches with no results | < 5% |
| Cart→checkout rate | % of carts that reach checkout | 40% |
| Checkout→order rate | % of checkouts that place an order | 75% |

### 22.4 Retention

| Metric | Definition | MVP target |
|---|---|---|
| 30-day repeat rate | % of customers placing 2+ orders in 30 days | 25% |
| 90-day retention | % of customers active 90 days after first order | 35% |

### 22.5 Operational quality

| Metric | Definition | Target |
|---|---|---|
| Stock accuracy | (orders fulfilled in full) ÷ (orders placed) | > 97% |
| Cancellation rate | (cancelled by us) ÷ (placed) | < 3% |
| Order confirmation time | median time pending → confirmed | < 15 min in business hours |
| Delivery time | median time confirmed → delivered | < 3 hrs in Bishkek |
| Return / complaint rate | flagged orders ÷ delivered orders | < 2% |

### 22.6 Health metrics (system, not product)

| Metric | Target |
|---|---|
| API p95 latency | < 300 ms catalog, < 500 ms checkout |
| Search p95 | < 200 ms |
| Error rate | < 0.5% of requests |
| SMS delivery success | > 98% |
| Payment success rate (when chosen) | > 95% |

### 22.7 Events to track (for Claude Code: emit these)

```
visitor_landed                {source}
search_executed               {query, lang, results_count}
search_zero_result            {query, lang}
product_viewed                {product_id, source}
add_to_cart                   {product_id, quantity}
remove_from_cart              {product_id}
checkout_started              {cart_value, items_count}
checkout_address_entered
checkout_payment_selected     {method}
order_placed                  {order_id, value, items_count, payment_method}
order_confirmed               {order_id, time_to_confirm_seconds}
order_delivered               {order_id, time_to_deliver_minutes}
order_cancelled               {order_id, reason, by}
otp_requested                 {phone_hash}
otp_verified                  {phone_hash, success}
admin_action                  {admin_id, action, entity_type, entity_id}
```

Events go to a structured log channel for now (Phase 2: warehouse pipeline).

---

## 23. Roadmap: MVP / Phase 2 / Future

### 23.1 MVP — what ships at launch

| Area | Features (IDs) |
|---|---|
| Auth | F-AUTH-001, F-AUTH-002 |
| Account | F-ACC-001, F-ACC-002, F-ACC-003, F-ACC-004 |
| Catalog | F-CAT-001, F-CAT-002, F-CAT-003, F-CAT-004, F-CAT-007, F-CAT-008 |
| Cart & checkout | F-CART-001, F-CART-002, F-CHECKOUT-001, F-CHECKOUT-002, F-CHECKOUT-003 (COD) |
| Orders | F-ORD-001, F-ORD-002, F-ORD-003 |
| Admin | F-ADM-CAT-001, F-ADM-CAT-002, F-ADM-CAT-003, F-ADM-CAT-004, F-ADM-INV-001, F-ADM-INV-002, F-ADM-INV-003, F-ADM-INV-004, F-ADM-ORD-001, F-ADM-ORD-002, F-ADM-ORD-003, F-ADM-TEAM-001 |
| Reports | F-RPT-001 |

**Languages at launch:** RU complete, KY for top categories and key flows, EN for legal pages.

**Payment at launch:** COD only.

### 23.2 Phase 1.5 — within 60 days of launch

- Card online via Freedom Pay (F-CHECKOUT-003)
- Search suggestions / autocomplete (F-CAT-005)
- Filter by active ingredient (F-CAT-006)
- WhatsApp customer support
- Customer search (F-ADM-USR-001)
- Audit log viewer (F-ADM-AUD-001)
- Phone change flow
- Bulk admin actions in order queue

### 23.3 Phase 2 — within 6 months

- Notify when available (out-of-stock email/SMS opt-in)
- Promotions engine (coupons, BOGO, loyalty discount tiers)
- Phone number change flow self-serve
- Customer SMS opt-out granularity
- Cold-chain refrigerated delivery option
- Wishlist / favourites
- Native mobile apps (iOS/Android)
- Push notifications
- Multi-branch UI (with branch selector and per-branch stock)
- Inventory transfers between branches
- Inventory valuation report
- Customer-facing order receipt PDF
- Address book improvements (saved landmarks, maps)
- Recall workflow

### 23.4 Phase 3 — beyond

- Subscriptions / auto-refill for chronic medications
- Loyalty program with points
- Reviews and Q&A — only on cosmetics and devices
- "Find nearest pharmacy" with maps
- Pickup appointment slots
- Click-and-collect lockers
- Live chat with pharmacist
- A/B testing framework
- Customer cohort analytics (F-RPT-003)
- Right-to-be-forgotten flow

### 23.5 Out of plan
- Telemedicine
- Prescription / Rx workflow
- Insurance integration
- Marketplace / third-party sellers
- Reviews on medicines

---

## 24. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Stock data drifts from physical reality | High | High | Daily reconciliation job; cycle counts weekly; FEFO selection forces accuracy |
| Customer receives expired item | Low | Critical | 30-day shelf-life-at-dispatch rule; FEFO; 7-day hard block |
| SMS gateway downtime | Medium | High | Queue with retry; alert at 5 min; second provider in Phase 2 |
| Payment gateway issue | Medium | High | Hourly reconciliation; admin manual refund flow |
| Counterfeit product reaches customer | Low | Critical | Receive only from licensed distributors; record supplier on every batch |
| Recall of a batch already shipped | Low | High | `inventory_batch_id` on every order item; manual recall workflow at MVP |
| Search quality declines as catalog grows | High | Medium | Zero-result tracking; synonym dictionary maintained by content editor; Meilisearch in Phase 2 |
| Delivery promises broken | Medium | Medium | Conservative SLAs; honest communication; courier reliability tracking |
| Rapid scale beyond single-VPS capacity | Medium | Medium | Scaling roadmap in PHARMACY_BLUEPRINT §23 |
| Regulatory tightening on Rx in KG | Low | High | Schema supports `requires_prescription`; can flip on with verification flow |
| Bishkek summer heat damages stock | Annually | Medium | Cold-chain handling rules; refrigerated delivery in Phase 2 |
| Competitor enters with lower prices | High | Medium | Compete on stock truth and delivery speed, not price wars |

---

## 25. Glossary

| Term | Definition |
|---|---|
| **Active ingredient** | The pharmacological substance in a medicine (e.g. paracetamol) |
| **AOV** | Average Order Value |
| **ARVI / ОРВИ** | Acute Respiratory Viral Infection — common term for cold/flu in RU |
| **Batch** | Specific manufactured lot of a product, identified by `batch_number` and `expiry_date` |
| **BAD / БАД** | Биологически Активная Добавка — biologically active supplement; commonly sold in pharmacies |
| **Branch** | Physical pharmacy location |
| **COD** | Cash on Delivery |
| **Cold chain** | Refrigerated supply chain for products requiring 2–8°C storage |
| **Compare-at-price** | Original / "was" price displayed alongside discounted price |
| **FEFO** | First Expiry, First Out — inventory rotation strategy |
| **GA** | General Availability — production launch |
| **INN** | International Nonproprietary Name (Latin standard for active ingredients) |
| **KGS** | Kyrgyzstani som (currency code) |
| **OTC** | Over The Counter (no prescription needed) |
| **Picking** | Pharmacist's act of selecting and preparing items for an order |
| **PDP** | Product Detail Page |
| **PIL** | Patient Information Leaflet (the paper inside the box) |
| **Rx** | Prescription |
| **SmPC** | Summary of Product Characteristics — official medical document for a drug |
| **SKU** | Stock Keeping Unit — unique identifier for a product |
| **Snapshot** | Denormalised copy of data captured at a moment in time (e.g. order item snapshots product name) |
| **Substitute** | Alternative product with the same active ingredient |
| **TOTP** | Time-based One-Time Password (e.g. Google Authenticator) |
| **WAU** | Weekly Active Users |

---

## 26. Conventions Checklist for Claude Code

Before declaring a product-related task complete:

### 26.1 Behaviour
- [ ] Feature ID referenced in PR title and code comments where non-trivial
- [ ] Acceptance criteria from §8 met
- [ ] Edge cases from §17 relevant to this feature handled
- [ ] State transitions match §9 (for order-related changes)
- [ ] Stock rules from §10 honoured (for inventory changes)

### 26.2 Copy
- [ ] All user-facing text comes from the i18n keys in §21 (or new keys added there)
- [ ] No hardcoded RU/KY/EN strings in code
- [ ] Error messages are specific and offer next action
- [ ] No marketing-grade adjectives ("BEST!", "AMAZING!")

### 26.3 Domain correctness
- [ ] FEFO observed for stock allocation
- [ ] Expiry hard block (≤ 7 days) enforced
- [ ] No expired stock can ever reach a customer
- [ ] Cold-chain rules (§5.4, §10.4) enforced for flagged products
- [ ] Reservation lifecycle (§9.3) correct: reserve → sell, or reserve → release

### 26.4 Privacy & ethics
- [ ] No PII logged or returned unnecessarily
- [ ] No medical advice rendered
- [ ] No marketing SMS sent
- [ ] No "scarcity" UX (hidden in §3.3)

### 26.5 Trust
- [ ] Customer support phone visible / tap-to-call
- [ ] Order numbers always shown in transactional touchpoints
- [ ] Status changes always trigger an SMS per §14.2
- [ ] Errors written for a person, not a programmer

### 26.6 Reporting
- [ ] Analytics events from §22.7 emitted on the relevant flows
- [ ] Audit log written for every admin mutation

### 26.7 Roadmap discipline
- [ ] Feature is in MVP (§23.1) — or has explicit instruction to build ahead of plan
- [ ] No accidental Phase 2/3 features bleeding into MVP

---

*Document version 1.0 — Pharmacy Platform product blueprint. Companion to `PHARMACY_BLUEPRINT.md` and `BACKEND_BLUEPRINT.md`.*
