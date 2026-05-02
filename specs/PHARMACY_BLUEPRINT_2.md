# Pharmacy Platform — Database Blueprint & System Design

> **Context:** Single-pharmacy MVP in Kyrgyzstan, designed to scale to multi-branch. Thousands of OTC products, bilingual (Russian/Kyrgyz/English), customer storefront + admin panel, phone-first authentication, cash-on-delivery + card payments.

> **Engine:** PostgreSQL 16+ assumed. All DDL is Postgres-flavoured. The schema is normalised where it matters (catalog, inventory) and denormalised where it pays off (order snapshots, cached stock counters).

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Conventions](#2-conventions)
3. [Domain Map](#3-domain-map)
4. [Schema — Identity & Access](#4-schema--identity--access)
5. [Schema — Catalog](#5-schema--catalog)
6. [Schema — Branches & Inventory](#6-schema--branches--inventory)
7. [Schema — Cart, Orders & Payments](#7-schema--cart-orders--payments)
8. [Schema — Operations & Audit](#8-schema--operations--audit)
9. [Indexing Strategy](#9-indexing-strategy)
10. [Search Architecture (PostgreSQL FTS)](#10-search-architecture-postgresql-fts)
11. [Common Query Patterns](#11-common-query-patterns)
12. [Data Integrity & Constraints Summary](#12-data-integrity--constraints-summary)
13. [Migration & Seeding Strategy](#13-migration--seeding-strategy)
14. [System Architecture](#14-system-architecture)
15. [API Design](#15-api-design)
16. [Authentication & Authorization](#16-authentication--authorization)
17. [Caching Strategy](#17-caching-strategy)
18. [Background Jobs](#18-background-jobs)
19. [File & Image Pipeline](#19-file--image-pipeline)
20. [Security](#20-security)
21. [Observability](#21-observability)
22. [Deployment Topology](#22-deployment-topology)
23. [Scaling Roadmap](#23-scaling-roadmap)
24. [Backups & Disaster Recovery](#24-backups--disaster-recovery)
25. [Open Questions & Future Work](#25-open-questions--future-work)

---

## 1. Design Principles

These are the non-negotiable rules every schema and architecture decision below follows.

1. **Multi-branch from day one, single-branch in UI.** Stock, prices, and orders are all keyed by `branch_id` even though only one branch exists at launch. This avoids a brutal migration later.
2. **Money is `NUMERIC(12,2)` in `KGS`.** Never floats. Currency is explicit on every monetary column even though there's only one currency today.
3. **Time is `TIMESTAMPTZ` in UTC.** Application converts to `Asia/Bishkek` for display.
4. **Soft delete catalog entities, hard delete operational ones.** Products and categories use `deleted_at` (because order history must remain valid). OTPs, sessions, and carts are hard-deleted.
5. **Snapshot anything that lives in an order.** Product names, prices, addresses — all denormalised at order time. The catalog can change; history cannot.
6. **i18n via translation tables, not JSON columns.** `product_translations`, `category_translations`, etc. — proper rows, proper indexes, proper FTS.
7. **Inventory is per-batch.** Total stock per (branch, product) is a *cached aggregate*, not the source of truth. Batches with `expiry_date` and `quantity_remaining` are.
8. **FEFO (First Expiry, First Out)** is the default fulfillment rule. The schema and queries are built around this.
9. **Audit everything an admin touches.** Pharmacy staff edit prices, stock, and orders — those edits are evidence.
10. **UUIDv7 for public-facing IDs, `BIGSERIAL` for internal lookups.** UUIDs for `users`, `orders`, `products`. BIGSERIAL for `categories`, `symptoms`, `manufacturers` etc.

---

## 2. Conventions

| Topic | Convention |
|---|---|
| Table names | `snake_case`, plural (`products`, `order_items`) |
| Primary key | `id` |
| Foreign key | `<entity>_id` (e.g. `product_id`) |
| Booleans | `is_*` or `has_*` (`is_active`, `requires_cold_chain`) |
| Timestamps | `created_at`, `updated_at`, `deleted_at`, plus event-specific (`placed_at`, `delivered_at`) |
| Money | `NUMERIC(12,2) NOT NULL` |
| Currency | `CHAR(3) NOT NULL DEFAULT 'KGS'` |
| Phone | `VARCHAR(20)` E.164 format (`+996700123456`) |
| Language code | `CHAR(2)` ISO 639-1 (`ru`, `ky`, `en`) |
| Country code | `CHAR(2)` ISO 3166-1 alpha-2 |
| Enums | Postgres `ENUM` types for stable sets, `VARCHAR` + `CHECK` for evolving sets |
| Indexes | `idx_<table>_<columns>` |
| Unique indexes | `uq_<table>_<columns>` |
| FK constraints | `fk_<table>_<referenced_table>` |

**Required extensions:**

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";       -- gen_random_uuid(), hashing
CREATE EXTENSION IF NOT EXISTS "pg_trgm";         -- trigram fuzzy search
CREATE EXTENSION IF NOT EXISTS "unaccent";        -- diacritic-insensitive search
CREATE EXTENSION IF NOT EXISTS "btree_gin";       -- composite GIN indexes
CREATE EXTENSION IF NOT EXISTS "citext";          -- case-insensitive text (emails)
```

For UUIDv7, either upgrade to Postgres 18 (native `uuidv7()`), use a small SQL function, or generate them application-side. Examples below assume `gen_random_uuid()` for portability.

---

## 3. Domain Map

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   IDENTITY      │     │     CATALOG      │     │ BRANCHES & STOCK │
├─────────────────┤     ├──────────────────┤     ├──────────────────┤
│ users           │     │ categories       │     │ branches         │
│ user_addresses  │     │ symptoms         │     │ branch_products  │
│ otp_codes       │     │ manufacturers    │     │ inventory_batches│
│ admin_users     │     │ active_ingredients│    │ stock_movements  │
│ admin_sessions  │     │ products         │     │ suppliers        │
└─────────────────┘     │ product_*        │     └──────────────────┘
                        │ (translations,   │              │
                        │  images,         │              │
                        │  ingredients,    │              ▼
                        │  symptoms)       │     ┌──────────────────┐
                        └──────────────────┘     │ ORDERS & PAYMENT │
                                 │                ├──────────────────┤
                                 │                │ carts            │
                                 ▼                │ cart_items       │
                        ┌──────────────────┐     │ orders           │
                        │   OPERATIONS     │     │ order_items      │
                        ├──────────────────┤     │ order_status_log │
                        │ admin_audit_log  │     │ payments         │
                        │ sms_log          │     │ deliveries       │
                        │ search_log       │     └──────────────────┘
                        └──────────────────┘
```

---

## 4. Schema — Identity & Access

### 4.1 `users` — End customers

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone           VARCHAR(20) NOT NULL,
    email           CITEXT,
    first_name      VARCHAR(80),
    last_name       VARCHAR(80),
    date_of_birth   DATE,
    preferred_language CHAR(2) NOT NULL DEFAULT 'ru'
                    CHECK (preferred_language IN ('ru', 'ky', 'en')),
    is_phone_verified BOOLEAN NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,

    CONSTRAINT uq_users_phone UNIQUE (phone),
    CONSTRAINT chk_users_phone_format CHECK (phone ~ '^\+\d{10,15}$')
);
```

**Notes:**
- `phone` is the primary identifier — there is no `username`.
- `email` is optional and `CITEXT` for case-insensitive uniqueness (when present).
- `date_of_birth` exists for age-restricted products even though no age check is enforced at MVP.
- Soft-deleted users keep their orders intact.

### 4.2 `user_addresses` — Delivery addresses

```sql
CREATE TABLE user_addresses (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label           VARCHAR(40),                 -- "Home", "Work", "Mom"
    recipient_name  VARCHAR(160),
    recipient_phone VARCHAR(20),
    city            VARCHAR(80) NOT NULL DEFAULT 'Bishkek',
    address_line    TEXT NOT NULL,               -- free-text: street, building, apt
    landmark        TEXT,                        -- "напротив школы №42"
    latitude        NUMERIC(9,6),
    longitude       NUMERIC(9,6),
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Notes:** Free-text address with optional lat/long. Most KG addresses are not in any clean structured format — courier-readable text + a phone number is what actually works.

### 4.3 `otp_codes` — Phone verification & login

```sql
CREATE TABLE otp_codes (
    id              BIGSERIAL PRIMARY KEY,
    phone           VARCHAR(20) NOT NULL,
    code_hash       VARCHAR(255) NOT NULL,         -- never store plaintext
    purpose         VARCHAR(20) NOT NULL
                    CHECK (purpose IN ('login', 'signup', 'phone_change')),
    attempts        SMALLINT NOT NULL DEFAULT 0,
    max_attempts    SMALLINT NOT NULL DEFAULT 5,
    consumed_at     TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ NOT NULL,
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Notes:**
- Codes are hashed (bcrypt or HMAC) — never plaintext.
- A nightly job purges rows with `expires_at < NOW() - INTERVAL '7 days'`.
- Rate limiting (max 3 codes per phone per 15 min) is enforced at the application layer with Redis, not in this table.

### 4.4 `admin_users` — Pharmacy staff

```sql
CREATE TYPE admin_role AS ENUM (
    'super_admin',     -- full access, manages other admins
    'branch_manager',  -- runs one branch
    'pharmacist',      -- inventory + orders
    'content_editor'   -- catalog only, no orders/inventory
);

CREATE TABLE admin_users (
    id              BIGSERIAL PRIMARY KEY,
    email           CITEXT NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    first_name      VARCHAR(80) NOT NULL,
    last_name       VARCHAR(80) NOT NULL,
    role            admin_role NOT NULL,
    branch_id       BIGINT REFERENCES branches(id),  -- NULL for super_admin
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    mfa_secret      VARCHAR(64),                     -- TOTP secret, optional
    last_login_at   TIMESTAMPTZ,
    failed_login_count SMALLINT NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_admin_users_email UNIQUE (email),
    CONSTRAINT chk_admin_branch_required
        CHECK (role = 'super_admin' OR branch_id IS NOT NULL)
);
```

**Notes:**
- Password hashed with **argon2id** (preferred) or **bcrypt** (cost ≥12).
- Account lockout after N failed logins via `locked_until`.
- TOTP MFA optional but recommended for `super_admin` and `branch_manager`.

### 4.5 `admin_sessions` — Server-side admin sessions

```sql
CREATE TABLE admin_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id   BIGINT NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    token_hash      VARCHAR(255) NOT NULL,
    ip_address      INET,
    user_agent      TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Notes:** Server-side sessions for admin (more revocable than JWT). Customer side uses short JWT + refresh token.

---

## 5. Schema — Catalog

### 5.1 `categories` — Tree (2 levels at MVP, n-level capable)

```sql
CREATE TABLE categories (
    id              BIGSERIAL PRIMARY KEY,
    parent_id       BIGINT REFERENCES categories(id) ON DELETE RESTRICT,
    slug            VARCHAR(120) NOT NULL,
    icon_url        TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,

    CONSTRAINT uq_categories_slug UNIQUE (slug),
    CONSTRAINT chk_categories_no_self_parent CHECK (parent_id IS NULL OR parent_id <> id)
);
```

### 5.2 `category_translations`

```sql
CREATE TABLE category_translations (
    id              BIGSERIAL PRIMARY KEY,
    category_id     BIGINT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    language_code   CHAR(2) NOT NULL CHECK (language_code IN ('ru', 'ky', 'en')),
    name            VARCHAR(160) NOT NULL,
    description     TEXT,
    meta_title      VARCHAR(160),
    meta_description VARCHAR(320),

    CONSTRAINT uq_cat_trans UNIQUE (category_id, language_code)
);
```

### 5.3 `manufacturers`

```sql
CREATE TABLE manufacturers (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(160) NOT NULL,
    country_code    CHAR(2),
    website         VARCHAR(255),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_manufacturers_name UNIQUE (name)
);
```

### 5.4 `active_ingredients`

```sql
CREATE TABLE active_ingredients (
    id              BIGSERIAL PRIMARY KEY,
    inn_name        VARCHAR(160) NOT NULL,         -- INN / Latin standard name
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_active_ingredients_inn UNIQUE (inn_name)
);

CREATE TABLE active_ingredient_translations (
    id                      BIGSERIAL PRIMARY KEY,
    active_ingredient_id    BIGINT NOT NULL REFERENCES active_ingredients(id) ON DELETE CASCADE,
    language_code           CHAR(2) NOT NULL CHECK (language_code IN ('ru', 'ky', 'en')),
    name                    VARCHAR(160) NOT NULL,
    synonyms                TEXT[],

    CONSTRAINT uq_ai_trans UNIQUE (active_ingredient_id, language_code)
);
```

### 5.5 `symptoms` — Symptom-based browsing

```sql
CREATE TABLE symptoms (
    id              BIGSERIAL PRIMARY KEY,
    slug            VARCHAR(120) NOT NULL,
    icon_url        TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT uq_symptoms_slug UNIQUE (slug)
);

CREATE TABLE symptom_translations (
    id              BIGSERIAL PRIMARY KEY,
    symptom_id      BIGINT NOT NULL REFERENCES symptoms(id) ON DELETE CASCADE,
    language_code   CHAR(2) NOT NULL CHECK (language_code IN ('ru', 'ky', 'en')),
    name            VARCHAR(120) NOT NULL,
    synonyms        TEXT[],                        -- "простуда","ОРВИ","грипп"

    CONSTRAINT uq_sym_trans UNIQUE (symptom_id, language_code)
);
```

### 5.6 `products` — The main catalog table

```sql
CREATE TYPE product_form AS ENUM (
    'tablet', 'capsule', 'syrup', 'drops', 'cream', 'ointment', 'gel',
    'spray', 'inhaler', 'injection', 'suppository', 'patch', 'powder',
    'solution', 'suspension', 'lozenge', 'other'
);

CREATE TABLE products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku                 VARCHAR(40) NOT NULL,
    barcode             VARCHAR(40),
    slug                VARCHAR(160) NOT NULL,
    manufacturer_id     BIGINT REFERENCES manufacturers(id) ON DELETE RESTRICT,
    category_id         BIGINT NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,

    form                product_form NOT NULL DEFAULT 'other',
    pack_size_label     VARCHAR(60),               -- display: "20 tablets", "100 ml"
    pack_quantity       NUMERIC(10,3),             -- 20, 100
    pack_unit           VARCHAR(16),               -- 'tab','ml','g','ampoule'

    requires_prescription BOOLEAN NOT NULL DEFAULT FALSE,
    min_age             SMALLINT,
    max_per_order       SMALLINT,                  -- legal/safety cap

    storage_temp_min_c  SMALLINT,
    storage_temp_max_c  SMALLINT,
    requires_cold_chain BOOLEAN NOT NULL DEFAULT FALSE,
    weight_grams        INTEGER,                   -- for shipping calc

    attributes          JSONB NOT NULL DEFAULT '{}'::jsonb,  -- flexible extra fields

    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    is_featured         BOOLEAN NOT NULL DEFAULT FALSE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,

    CONSTRAINT uq_products_sku UNIQUE (sku),
    CONSTRAINT uq_products_slug UNIQUE (slug),
    CONSTRAINT chk_products_temp_range
        CHECK (storage_temp_min_c IS NULL
               OR storage_temp_max_c IS NULL
               OR storage_temp_min_c <= storage_temp_max_c)
);
```

**Notes:**
- `attributes JSONB` is the escape hatch for the long tail (e.g. `{"skin_type":"oily"}` for cosmetics, `{"flavor":"orange"}` for syrups). GIN index on it.
- `requires_prescription` exists even though Kyrgyzstan is loose — some controlled substances may still need flagging, and the column makes the design portable.
- **No price column here.** Price lives on `branch_products` (next section) so different branches can price differently.

### 5.7 `product_translations`

```sql
CREATE TABLE product_translations (
    id                  BIGSERIAL PRIMARY KEY,
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    language_code       CHAR(2) NOT NULL CHECK (language_code IN ('ru', 'ky', 'en')),

    name                VARCHAR(255) NOT NULL,
    short_description   VARCHAR(500),
    description         TEXT,
    usage_instructions  TEXT,
    side_effects        TEXT,
    contraindications   TEXT,
    composition         TEXT,                      -- formatted full composition

    -- Generated tsvector for full-text search (per language)
    search_vector       tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', coalesce(name, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(short_description, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(description, '')), 'C')
    ) STORED,

    CONSTRAINT uq_product_translations UNIQUE (product_id, language_code)
);
```

**Notes:** `'simple'` config is used because Kyrgyz has no built-in dictionary and Russian dictionary applied to Kyrgyz text would mangle it. We rely on `simple` + `unaccent` + `pg_trgm`. Russian-specific stemming can be added per-language at query time with a second `tsvector` column if needed.

### 5.8 `product_images`

```sql
CREATE TABLE product_images (
    id              BIGSERIAL PRIMARY KEY,
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,                 -- original
    thumbnail_url   TEXT,                          -- 200x200 webp
    medium_url      TEXT,                          -- 600x600 webp
    large_url       TEXT,                          -- 1200x1200 webp
    alt_text        VARCHAR(255),
    width           INTEGER,
    height          INTEGER,
    sort_order      SMALLINT NOT NULL DEFAULT 0,
    is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Only one primary image per product
CREATE UNIQUE INDEX uq_product_images_primary
    ON product_images (product_id) WHERE is_primary = TRUE;
```

### 5.9 `product_active_ingredients` — M:N with dosage

```sql
CREATE TABLE product_active_ingredients (
    product_id              UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    active_ingredient_id    BIGINT NOT NULL REFERENCES active_ingredients(id) ON DELETE RESTRICT,
    dosage_amount           NUMERIC(10,3) NOT NULL,
    dosage_unit             VARCHAR(8) NOT NULL CHECK (dosage_unit IN ('mg','g','mcg','ml','IU','%')),
    PRIMARY KEY (product_id, active_ingredient_id)
);
```

### 5.10 `product_symptoms` — M:N

```sql
CREATE TABLE product_symptoms (
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    symptom_id      BIGINT NOT NULL REFERENCES symptoms(id) ON DELETE CASCADE,
    PRIMARY KEY (product_id, symptom_id)
);
```

---

## 6. Schema — Branches & Inventory

### 6.1 `branches`

```sql
CREATE TABLE branches (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(20) NOT NULL,          -- 'BISHKEK_CENTRAL'
    name            VARCHAR(160) NOT NULL,
    address         TEXT NOT NULL,
    city            VARCHAR(80) NOT NULL DEFAULT 'Bishkek',
    phone           VARCHAR(20),
    latitude        NUMERIC(9,6),
    longitude       NUMERIC(9,6),
    timezone        VARCHAR(40) NOT NULL DEFAULT 'Asia/Bishkek',
    opens_at        TIME,
    closes_at       TIME,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_branches_code UNIQUE (code)
);
```

### 6.2 `suppliers`

```sql
CREATE TABLE suppliers (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(160) NOT NULL,
    contact_phone   VARCHAR(20),
    contact_email   CITEXT,
    address         TEXT,
    notes           TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 6.3 `branch_products` — Per-branch availability & pricing

```sql
CREATE TABLE branch_products (
    branch_id           BIGINT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,

    price               NUMERIC(12,2) NOT NULL CHECK (price >= 0),
    compare_at_price    NUMERIC(12,2) CHECK (compare_at_price IS NULL OR compare_at_price >= price),
    currency            CHAR(3) NOT NULL DEFAULT 'KGS',

    is_available        BOOLEAN NOT NULL DEFAULT TRUE,    -- can be toggled off without removing stock
    -- Cached aggregate of inventory_batches.quantity_remaining where not expired
    -- Maintained by application via stock_movements
    total_quantity      INTEGER NOT NULL DEFAULT 0 CHECK (total_quantity >= 0),
    reserved_quantity   INTEGER NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),

    low_stock_threshold INTEGER NOT NULL DEFAULT 10,

    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (branch_id, product_id),
    CONSTRAINT chk_bp_reserved_le_total CHECK (reserved_quantity <= total_quantity)
);
```

**Notes:**
- `total_quantity` is **denormalised** for read performance. It is recomputed/incremented on every `stock_movement`. We accept the eventual-consistency risk and add a nightly reconciliation job.
- `reserved_quantity` covers items in pending orders (placed, not yet shipped). Available = `total_quantity - reserved_quantity`.
- A nightly job `SELECT SUM(quantity_remaining)` from non-expired batches and compares to `total_quantity` — alerts on drift.

### 6.4 `inventory_batches` — Source of truth for stock

```sql
CREATE TABLE inventory_batches (
    id                  BIGSERIAL PRIMARY KEY,
    branch_id           BIGINT NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    supplier_id         BIGINT REFERENCES suppliers(id) ON DELETE SET NULL,

    batch_number        VARCHAR(60) NOT NULL,
    expiry_date         DATE NOT NULL,
    manufacture_date    DATE,

    quantity_received   INTEGER NOT NULL CHECK (quantity_received > 0),
    quantity_remaining  INTEGER NOT NULL CHECK (quantity_remaining >= 0),
    cost_price          NUMERIC(12,2) NOT NULL CHECK (cost_price >= 0),
    currency            CHAR(3) NOT NULL DEFAULT 'KGS',

    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_inventory_batch UNIQUE (branch_id, product_id, batch_number),
    CONSTRAINT chk_remaining_le_received
        CHECK (quantity_remaining <= quantity_received)
);
```

**FEFO query** (used to pick which batch fulfills an order line):

```sql
SELECT id, expiry_date, quantity_remaining
FROM inventory_batches
WHERE branch_id = $1 AND product_id = $2
  AND quantity_remaining > 0
  AND expiry_date > CURRENT_DATE
ORDER BY expiry_date ASC, received_at ASC
FOR UPDATE SKIP LOCKED;
```

`FOR UPDATE SKIP LOCKED` lets concurrent orders pick non-overlapping batches without deadlocks.

### 6.5 `stock_movements` — Immutable inventory log

```sql
CREATE TYPE stock_movement_type AS ENUM (
    'received',     -- new batch arrived
    'sold',         -- order fulfillment
    'reserved',     -- order placed, stock held
    'released',     -- order cancelled, reservation released
    'expired',      -- batch passed expiry
    'damaged',      -- write-off
    'adjusted',     -- manual correction
    'transferred_in', -- inter-branch
    'transferred_out'
);

CREATE TABLE stock_movements (
    id                  BIGSERIAL PRIMARY KEY,
    inventory_batch_id  BIGINT NOT NULL REFERENCES inventory_batches(id) ON DELETE RESTRICT,
    branch_id           BIGINT NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    movement_type       stock_movement_type NOT NULL,
    quantity_change     INTEGER NOT NULL,           -- signed: +received, -sold
    quantity_after      INTEGER NOT NULL,           -- snapshot of remaining

    order_id            UUID REFERENCES orders(id) ON DELETE SET NULL,
    admin_user_id       BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
    reason              TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_movement_sign CHECK (
        (movement_type IN ('received','released','transferred_in','adjusted') AND quantity_change >= 0)
        OR
        (movement_type IN ('sold','reserved','expired','damaged','transferred_out','adjusted') AND quantity_change <= 0)
        OR (movement_type = 'adjusted')
    )
);
```

**Notes:**
- This table is **append-only**. Never UPDATE or DELETE rows here.
- Every change to `inventory_batches.quantity_remaining` and `branch_products.total_quantity` must be paired with a `stock_movements` insert in the same transaction.
- This is the audit trail regulators (and your own future self) will be glad you kept.

---

## 7. Schema — Cart, Orders & Payments

### 7.1 `carts`

```sql
CREATE TABLE carts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    session_id      VARCHAR(64),                   -- for guest carts
    branch_id       BIGINT NOT NULL REFERENCES branches(id),
    currency        CHAR(3) NOT NULL DEFAULT 'KGS',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '30 days',

    CONSTRAINT chk_carts_owner CHECK (user_id IS NOT NULL OR session_id IS NOT NULL)
);
```

### 7.2 `cart_items`

```sql
CREATE TABLE cart_items (
    id              BIGSERIAL PRIMARY KEY,
    cart_id         UUID NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    price_snapshot  NUMERIC(12,2) NOT NULL,        -- price at add-to-cart time
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_cart_items UNIQUE (cart_id, product_id)
);
```

### 7.3 `orders`

```sql
CREATE TYPE order_status AS ENUM (
    'pending',          -- placed, awaiting confirmation
    'confirmed',        -- pharmacy accepted
    'preparing',        -- being assembled
    'ready_for_pickup',
    'out_for_delivery',
    'delivered',
    'cancelled',
    'refunded'
);

CREATE TYPE payment_status AS ENUM (
    'pending', 'authorized', 'paid', 'failed', 'refunded', 'partially_refunded'
);

CREATE TYPE payment_method AS ENUM (
    'cash_on_delivery', 'card_online', 'mbank', 'elsom', 'odengi', 'balance_kg', 'bank_transfer'
);

CREATE TYPE delivery_method AS ENUM ('delivery', 'pickup');

CREATE TABLE orders (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number        VARCHAR(20) NOT NULL,           -- "PH-2026-000123"
    user_id             UUID REFERENCES users(id) ON DELETE SET NULL,
    branch_id           BIGINT NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,

    status              order_status NOT NULL DEFAULT 'pending',
    payment_status      payment_status NOT NULL DEFAULT 'pending',
    payment_method      payment_method NOT NULL,
    delivery_method     delivery_method NOT NULL,

    -- Snapshots of contact / delivery details (denormalised on purpose)
    recipient_name      VARCHAR(160) NOT NULL,
    recipient_phone     VARCHAR(20) NOT NULL,
    delivery_address    JSONB,                          -- full snapshot of address
    delivery_latitude   NUMERIC(9,6),
    delivery_longitude  NUMERIC(9,6),

    -- Money
    subtotal            NUMERIC(12,2) NOT NULL CHECK (subtotal >= 0),
    delivery_fee        NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (delivery_fee >= 0),
    discount_amount     NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    total               NUMERIC(12,2) NOT NULL CHECK (total >= 0),
    currency            CHAR(3) NOT NULL DEFAULT 'KGS',

    customer_notes      TEXT,
    internal_notes      TEXT,                           -- staff only
    cancel_reason       TEXT,

    placed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at        TIMESTAMPTZ,
    delivered_at        TIMESTAMPTZ,
    cancelled_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_orders_order_number UNIQUE (order_number),
    CONSTRAINT chk_orders_total
        CHECK (total = subtotal + delivery_fee - discount_amount)
);
```

**Notes:**
- `order_number` is human-friendly and shown to customers; `id` (UUID) is the primary key used internally.
- `delivery_address` as `JSONB` is intentional — addresses change in `user_addresses` and we do not want to follow the FK to render an old order.
- `placed_at` is the canonical "order time" for reporting; `created_at` is row insert time (usually identical).

### 7.4 `order_items`

```sql
CREATE TABLE order_items (
    id                      BIGSERIAL PRIMARY KEY,
    order_id                UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id              UUID REFERENCES products(id) ON DELETE SET NULL,
    inventory_batch_id      BIGINT REFERENCES inventory_batches(id) ON DELETE SET NULL,

    -- Snapshots
    product_name_snapshot   VARCHAR(255) NOT NULL,
    product_sku_snapshot    VARCHAR(40) NOT NULL,
    batch_number_snapshot   VARCHAR(60),
    expiry_date_snapshot    DATE,

    quantity                INTEGER NOT NULL CHECK (quantity > 0),
    unit_price              NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    line_total              NUMERIC(12,2) NOT NULL CHECK (line_total >= 0),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_order_items_total CHECK (line_total = unit_price * quantity)
);
```

**Notes:**
- Snapshots survive product deletion (`ON DELETE SET NULL` on `product_id`).
- `inventory_batch_id` records which batch this item drew from — important for recalls.

### 7.5 `order_status_history`

```sql
CREATE TABLE order_status_history (
    id              BIGSERIAL PRIMARY KEY,
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    from_status     order_status,
    to_status       order_status NOT NULL,
    changed_by_admin_id BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
    changed_by_system BOOLEAN NOT NULL DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 7.6 `payments`

```sql
CREATE TABLE payments (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id                UUID NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
    provider                VARCHAR(40) NOT NULL,   -- 'freedom_pay','mbank','cash', ...
    provider_transaction_id VARCHAR(120),           -- their reference
    amount                  NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    currency                CHAR(3) NOT NULL DEFAULT 'KGS',
    status                  payment_status NOT NULL DEFAULT 'pending',
    raw_request             JSONB,                  -- what we sent
    raw_response            JSONB,                  -- what they returned
    failure_reason          TEXT,
    paid_at                 TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Notes:** One order can have multiple payment rows (e.g., failed retry, then success). The order's `payment_status` is a derived projection of these rows.

### 7.7 `deliveries`

```sql
CREATE TABLE deliveries (
    id                  BIGSERIAL PRIMARY KEY,
    order_id            UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    provider            VARCHAR(40),               -- 'in_house','yandex'
    courier_name        VARCHAR(160),
    courier_phone       VARCHAR(20),
    tracking_number     VARCHAR(80),
    estimated_at        TIMESTAMPTZ,
    assigned_at         TIMESTAMPTZ,
    picked_up_at        TIMESTAMPTZ,
    delivered_at        TIMESTAMPTZ,
    delivery_fee_actual NUMERIC(12,2),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_deliveries_order UNIQUE (order_id)
);
```

---

## 8. Schema — Operations & Audit

### 8.1 `admin_audit_log`

```sql
CREATE TABLE admin_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    admin_user_id   BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
    action          VARCHAR(40) NOT NULL,           -- 'create','update','delete','login','export'
    entity_type     VARCHAR(60) NOT NULL,           -- 'product','order','inventory_batch'
    entity_id       VARCHAR(60),                    -- stringified PK
    changes         JSONB,                          -- {before:{}, after:{}}
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Note:** This table grows fast. Plan to partition by `created_at` (monthly) once it crosses ~10M rows.

### 8.2 `sms_log`

```sql
CREATE TABLE sms_log (
    id              BIGSERIAL PRIMARY KEY,
    phone           VARCHAR(20) NOT NULL,
    purpose         VARCHAR(40) NOT NULL,           -- 'otp','order_confirmed','out_for_delivery'
    body            TEXT,
    provider        VARCHAR(40),
    provider_message_id VARCHAR(120),
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
    cost            NUMERIC(8,4),
    error           TEXT,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 8.3 `search_log` — Anonymised search analytics

```sql
CREATE TABLE search_log (
    id              BIGSERIAL PRIMARY KEY,
    query           VARCHAR(255) NOT NULL,
    language_code   CHAR(2),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    results_count   INTEGER NOT NULL,
    clicked_product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Why this matters:** Tells you what people search for and *find nothing* — those are catalog gaps and synonym misses to fix.

---

## 9. Indexing Strategy

The principle: index for the **read paths the application actually uses**, not "every column might be searched". Every index slows down writes and consumes RAM.

### 9.1 `users`

```sql
CREATE UNIQUE INDEX uq_users_phone ON users(phone);
CREATE UNIQUE INDEX uq_users_email ON users(email) WHERE email IS NOT NULL;
CREATE INDEX idx_users_created_at ON users(created_at DESC);
CREATE INDEX idx_users_active ON users(is_active) WHERE deleted_at IS NULL;
```

### 9.2 `user_addresses`

```sql
CREATE INDEX idx_user_addresses_user ON user_addresses(user_id);
CREATE UNIQUE INDEX uq_user_addresses_default
    ON user_addresses(user_id) WHERE is_default = TRUE;
```

### 9.3 `otp_codes`

```sql
CREATE INDEX idx_otp_phone_active
    ON otp_codes(phone, expires_at) WHERE consumed_at IS NULL;
CREATE INDEX idx_otp_expires_at ON otp_codes(expires_at);  -- cleanup
```

### 9.4 `admin_users` / `admin_sessions`

```sql
CREATE INDEX idx_admin_users_branch ON admin_users(branch_id) WHERE branch_id IS NOT NULL;
CREATE INDEX idx_admin_sessions_admin ON admin_sessions(admin_user_id);
CREATE INDEX idx_admin_sessions_token ON admin_sessions(token_hash);
CREATE INDEX idx_admin_sessions_expires ON admin_sessions(expires_at);
```

### 9.5 `categories` / `category_translations`

```sql
CREATE INDEX idx_categories_parent ON categories(parent_id);
CREATE INDEX idx_categories_active ON categories(is_active, sort_order)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_cat_trans_lang ON category_translations(language_code);
-- Trigram on category names for autocomplete
CREATE INDEX idx_cat_trans_name_trgm
    ON category_translations USING GIN (name gin_trgm_ops);
```

### 9.6 `products`

```sql
-- Lookup by SKU (admin scanning, imports)
-- Already covered by uq_products_sku
-- Lookup by barcode (admin scanning)
CREATE INDEX idx_products_barcode ON products(barcode) WHERE barcode IS NOT NULL;

-- Storefront browsing: by category, active, featured
CREATE INDEX idx_products_category_active
    ON products(category_id, is_active)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_products_featured
    ON products(is_featured, created_at DESC)
    WHERE is_active = TRUE AND deleted_at IS NULL AND is_featured = TRUE;

CREATE INDEX idx_products_manufacturer
    ON products(manufacturer_id) WHERE deleted_at IS NULL;

-- Flexible attribute queries (e.g. {"flavor":"orange"})
CREATE INDEX idx_products_attributes ON products USING GIN (attributes jsonb_path_ops);

-- Recently added (admin "new arrivals" list)
CREATE INDEX idx_products_created_at ON products(created_at DESC) WHERE deleted_at IS NULL;
```

### 9.7 `product_translations`

```sql
-- Fetch by product+lang
-- Already covered by uq_product_translations

-- Full-text search per language
CREATE INDEX idx_pt_search_vector ON product_translations USING GIN (search_vector);

-- Trigram for typo tolerance and autocomplete on names
CREATE INDEX idx_pt_name_trgm
    ON product_translations USING GIN (name gin_trgm_ops);

-- Language-scoped name lookups (autocomplete prefix)
CREATE INDEX idx_pt_lang_name ON product_translations(language_code, name varchar_pattern_ops);
```

### 9.8 `product_images` / `product_active_ingredients` / `product_symptoms`

```sql
CREATE INDEX idx_product_images_product
    ON product_images(product_id, sort_order);

CREATE INDEX idx_pai_ingredient ON product_active_ingredients(active_ingredient_id);
-- product_id covered by PK leading column

CREATE INDEX idx_psy_symptom ON product_symptoms(symptom_id, product_id);
-- product_id, symptom_id PK already serves "products by symptom" via reverse, but
-- explicit symptom-leading index makes "all products for symptom X" a fast scan.
```

### 9.9 `branches` / `suppliers`

```sql
-- branches.code uniquely indexed via constraint
CREATE INDEX idx_branches_active ON branches(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_suppliers_active ON suppliers(is_active) WHERE is_active = TRUE;
```

### 9.10 `branch_products`

```sql
-- PK (branch_id, product_id) already covers most lookups

-- Reverse: which branches stock product X?
CREATE INDEX idx_bp_product ON branch_products(product_id);

-- Storefront: available products at a branch (the most common query)
CREATE INDEX idx_bp_branch_available
    ON branch_products(branch_id, is_available, product_id)
    WHERE is_available = TRUE AND total_quantity > 0;

-- Admin low-stock dashboard
CREATE INDEX idx_bp_low_stock
    ON branch_products(branch_id, total_quantity)
    WHERE total_quantity <= low_stock_threshold;
```

### 9.11 `inventory_batches` — The hottest table for ops

```sql
-- FEFO selection (the most performance-sensitive query in the system)
CREATE INDEX idx_ib_fefo
    ON inventory_batches(branch_id, product_id, expiry_date, received_at)
    WHERE quantity_remaining > 0;

-- Near-expiry dashboard
CREATE INDEX idx_ib_expiry
    ON inventory_batches(expiry_date)
    WHERE quantity_remaining > 0;

-- Branch-scoped expiry
CREATE INDEX idx_ib_branch_expiry
    ON inventory_batches(branch_id, expiry_date)
    WHERE quantity_remaining > 0;

-- Lookup by batch number (recall, supplier query)
CREATE INDEX idx_ib_batch_number ON inventory_batches(batch_number);

-- Supplier reporting
CREATE INDEX idx_ib_supplier ON inventory_batches(supplier_id, received_at DESC)
    WHERE supplier_id IS NOT NULL;
```

### 9.12 `stock_movements`

```sql
-- Per-batch history
CREATE INDEX idx_sm_batch_created
    ON stock_movements(inventory_batch_id, created_at DESC);

-- Per-product, per-branch history (sales reports)
CREATE INDEX idx_sm_branch_product_created
    ON stock_movements(branch_id, product_id, created_at DESC);

-- Order traceability
CREATE INDEX idx_sm_order ON stock_movements(order_id) WHERE order_id IS NOT NULL;

-- Time-range reports
CREATE INDEX idx_sm_created_type
    ON stock_movements(created_at DESC, movement_type);
```

### 9.13 `carts` / `cart_items`

```sql
CREATE INDEX idx_carts_user ON carts(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_carts_session ON carts(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX idx_carts_expires ON carts(expires_at);  -- cleanup job

-- cart_items.cart_id covered by uq_cart_items
CREATE INDEX idx_cart_items_product ON cart_items(product_id);
```

### 9.14 `orders`

```sql
-- order_number unique constraint already an index

-- Customer order history
CREATE INDEX idx_orders_user_placed
    ON orders(user_id, placed_at DESC) WHERE user_id IS NOT NULL;

-- Admin: open orders queue per branch
CREATE INDEX idx_orders_branch_status_placed
    ON orders(branch_id, status, placed_at DESC);

-- Admin: payment reconciliation
CREATE INDEX idx_orders_payment_status
    ON orders(payment_status, placed_at DESC);

-- Reporting time ranges
CREATE INDEX idx_orders_placed_at ON orders(placed_at DESC);

-- Phone lookup for support ("the customer says +996700...")
CREATE INDEX idx_orders_recipient_phone ON orders(recipient_phone);
```

### 9.15 `order_items` / `order_status_history` / `payments` / `deliveries`

```sql
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product
    ON order_items(product_id, created_at DESC) WHERE product_id IS NOT NULL;
CREATE INDEX idx_order_items_batch
    ON order_items(inventory_batch_id) WHERE inventory_batch_id IS NOT NULL;

CREATE INDEX idx_osh_order ON order_status_history(order_id, created_at DESC);

CREATE INDEX idx_payments_order ON payments(order_id, created_at DESC);
CREATE INDEX idx_payments_provider_txn
    ON payments(provider, provider_transaction_id)
    WHERE provider_transaction_id IS NOT NULL;
CREATE INDEX idx_payments_status_created
    ON payments(status, created_at DESC);

CREATE INDEX idx_deliveries_tracking
    ON deliveries(tracking_number) WHERE tracking_number IS NOT NULL;
```

### 9.16 `admin_audit_log` / `sms_log` / `search_log`

```sql
CREATE INDEX idx_audit_admin ON admin_audit_log(admin_user_id, created_at DESC)
    WHERE admin_user_id IS NOT NULL;
CREATE INDEX idx_audit_entity
    ON admin_audit_log(entity_type, entity_id, created_at DESC);
CREATE INDEX idx_audit_created ON admin_audit_log(created_at DESC);

CREATE INDEX idx_sms_phone_created ON sms_log(phone, created_at DESC);
CREATE INDEX idx_sms_status ON sms_log(status, created_at DESC)
    WHERE status IN ('queued','failed');

CREATE INDEX idx_search_query_trgm ON search_log USING GIN (query gin_trgm_ops);
CREATE INDEX idx_search_zero_results
    ON search_log(created_at DESC) WHERE results_count = 0;
```

### 9.17 Index Maintenance Notes

| Concern | Action |
|---|---|
| Bloat | `pg_repack` monthly on hot tables (`stock_movements`, `admin_audit_log`, `orders`) |
| Unused indexes | Run `pg_stat_user_indexes` quarterly; drop indexes with `idx_scan = 0` |
| Slow queries | `pg_stat_statements` enabled; review top 20 queries weekly |
| Vacuum | Tune `autovacuum_vacuum_scale_factor` lower (0.05) on `inventory_batches`, `branch_products` |
| Statistics | `ANALYZE` after bulk imports; consider raising `default_statistics_target` to 200 on `products`, `product_translations` |
| Partial index `WHERE` cost | Where used, the predicate must match query exactly to be picked. Add a comment in code referencing the index. |

---

## 10. Search Architecture (PostgreSQL FTS)

For thousands of products, Postgres full-text search is more than enough at MVP scale. Reach for Meilisearch / Elasticsearch only when you have measured a real bottleneck.

### 10.1 Layered search

The customer search bar handles three intents — they are layered, not branched:

1. **Exact / prefix** — typing `парацет` should bubble up "Парацетамол 500мг" instantly. Solved by trigram + `varchar_pattern_ops` index on `name`.
2. **Full-text** — multi-word, stemmed across name + description. Solved by `tsvector` GIN index.
3. **Fuzzy** — typos like `парацитамол`. Solved by `similarity()` from `pg_trgm`.

A single ranked query combines all three:

```sql
WITH q AS (SELECT $1::text AS term, $2::char(2) AS lang, $3::bigint AS branch)
SELECT
    p.id,
    pt.name,
    pt.short_description,
    bp.price,
    bp.total_quantity - bp.reserved_quantity AS available_qty,
    -- composite ranking
    GREATEST(
        ts_rank(pt.search_vector, plainto_tsquery('simple', q.term)) * 4,    -- FTS
        similarity(pt.name, q.term) * 2,                                      -- fuzzy
        CASE WHEN pt.name ILIKE q.term || '%' THEN 3 ELSE 0 END               -- prefix
    ) AS score
FROM q
JOIN product_translations pt ON pt.language_code = q.lang
JOIN products p ON p.id = pt.product_id AND p.is_active AND p.deleted_at IS NULL
JOIN branch_products bp ON bp.product_id = p.id AND bp.branch_id = q.branch
WHERE bp.is_available = TRUE
  AND (
      pt.search_vector @@ plainto_tsquery('simple', q.term)
      OR pt.name % q.term                  -- pg_trgm similarity
      OR pt.name ILIKE q.term || '%'
  )
ORDER BY score DESC, bp.total_quantity DESC
LIMIT 50;
```

### 10.2 Multilingual handling

- Two languages, one column per translation row, separate index per row — no special config needed.
- For Russian stemming specifically, keep a parallel `search_vector_ru` using `to_tsvector('russian', ...)` if precision becomes an issue. At MVP, `'simple'` + trigram is good enough and avoids mangling Kyrgyz.
- `unaccent()` is wrapped in queries when comparing names (e.g. `unaccent(name) ILIKE unaccent($1) || '%'`) — useful for inconsistent diacritic use.

### 10.3 Synonyms

The product team maintains a `symptom_translations.synonyms text[]` column. The search service expands the user's query against this dictionary before hitting Postgres:

```
"простуда" → ["простуда", "ОРВИ", "грипп", "насморк"]
```

This is application-side, not in SQL. It keeps SQL simple and lets non-engineers edit synonyms.

### 10.4 Autocomplete

- Endpoint: `GET /api/v1/search/suggest?q=пара&lang=ru`
- Backed by the trigram + prefix index, returns 8 results in < 30 ms.
- Results cached in Redis keyed by `(q, lang)` for 60 seconds.

### 10.5 When to graduate to Meilisearch / Typesense

Switch when **any one** is true:
- Search latency p95 > 200 ms with proper indexing
- > 50K active products
- Need for typo-tolerance better than `pg_trgm` provides (Meili's is significantly better)
- Need for facet aggregation on every search (price ranges, manufacturer counts) at scale

Until then: stay in Postgres.

---

## 11. Common Query Patterns

A few representative queries the application executes regularly. Each maps to specific indexes above.

### 11.1 Storefront — category page (with stock filter)

```sql
SELECT p.id, p.slug, pt.name, pt.short_description,
       bp.price, bp.compare_at_price,
       (bp.total_quantity - bp.reserved_quantity) AS available,
       pi.thumbnail_url
FROM products p
JOIN branch_products bp
  ON bp.product_id = p.id AND bp.branch_id = $branch_id
JOIN product_translations pt
  ON pt.product_id = p.id AND pt.language_code = $lang
LEFT JOIN product_images pi
  ON pi.product_id = p.id AND pi.is_primary
WHERE p.category_id = $category_id
  AND p.is_active AND p.deleted_at IS NULL
  AND bp.is_available
  AND (bp.total_quantity - bp.reserved_quantity) > 0
ORDER BY p.is_featured DESC, pt.name
LIMIT 24 OFFSET $offset;
```

Hits: `idx_products_category_active`, `idx_bp_branch_available`, `uq_product_translations`, `uq_product_images_primary`.

### 11.2 Product detail page

Single round-trip via JOIN; a second query fetches images and ingredients in parallel.

### 11.3 Add-to-cart with stock validation

```sql
-- Inside a single transaction
SELECT total_quantity - reserved_quantity AS available
FROM branch_products
WHERE branch_id = $1 AND product_id = $2
FOR UPDATE;

-- If available >= requested:
INSERT INTO cart_items(cart_id, product_id, quantity, price_snapshot)
VALUES ($cart_id, $product_id, $qty, $price)
ON CONFLICT (cart_id, product_id) DO UPDATE
SET quantity = cart_items.quantity + EXCLUDED.quantity,
    updated_at = NOW();
```

### 11.4 Place order (the critical transaction)

Pseudocode — must be wrapped in a single SERIALIZABLE or REPEATABLE READ transaction:

```
BEGIN;

INSERT INTO orders (...) RETURNING id;

FOR EACH cart_item:
    -- Allocate stock from batches in FEFO order
    SELECT id, quantity_remaining
    FROM inventory_batches
    WHERE branch_id = ... AND product_id = ...
      AND quantity_remaining > 0 AND expiry_date > CURRENT_DATE
    ORDER BY expiry_date ASC, received_at ASC
    FOR UPDATE SKIP LOCKED;

    -- Possibly split across multiple batches
    FOR EACH batch consumed:
        UPDATE inventory_batches
        SET quantity_remaining = quantity_remaining - $consumed
        WHERE id = $batch_id;

        INSERT INTO stock_movements (..., 'reserved', -$consumed, ...);

        INSERT INTO order_items (
            order_id, product_id, inventory_batch_id,
            product_name_snapshot, batch_number_snapshot, expiry_date_snapshot,
            quantity, unit_price, line_total
        ) VALUES (...);

UPDATE branch_products
SET reserved_quantity = reserved_quantity + $total_consumed
WHERE branch_id = ... AND product_id = ...;

INSERT INTO order_status_history (order_id, from_status, to_status, ...);

COMMIT;
```

On `delivered`, reservations are converted to sales (movement type `sold`, decrement `total_quantity`). On `cancelled`, reservations are released back.

### 11.5 Near-expiry report (daily admin job)

```sql
SELECT b.name AS branch, p.sku, pt.name, ib.batch_number,
       ib.expiry_date, ib.quantity_remaining,
       (ib.expiry_date - CURRENT_DATE) AS days_left
FROM inventory_batches ib
JOIN products p ON p.id = ib.product_id
JOIN product_translations pt ON pt.product_id = p.id AND pt.language_code = 'ru'
JOIN branches b ON b.id = ib.branch_id
WHERE ib.quantity_remaining > 0
  AND ib.expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '60 days'
ORDER BY ib.expiry_date ASC;
```

Hits `idx_ib_expiry`.

### 11.6 Low-stock report

```sql
SELECT p.sku, pt.name, bp.total_quantity, bp.low_stock_threshold
FROM branch_products bp
JOIN products p ON p.id = bp.product_id
JOIN product_translations pt ON pt.product_id = p.id AND pt.language_code = 'ru'
WHERE bp.branch_id = $1
  AND bp.total_quantity <= bp.low_stock_threshold
ORDER BY (bp.total_quantity - bp.low_stock_threshold);
```

Hits `idx_bp_low_stock`.

---

## 12. Data Integrity & Constraints Summary

| Concern | Mechanism |
|---|---|
| One default address per user | Partial unique index `uq_user_addresses_default` |
| One primary image per product | Partial unique index `uq_product_images_primary` |
| Prices never negative | `CHECK (price >= 0)` |
| Order total = subtotal + delivery − discount | `CHECK chk_orders_total` |
| Line total = unit_price × qty | `CHECK chk_order_items_total` |
| Reserved ≤ total stock | `CHECK chk_bp_reserved_le_total` |
| Batch remaining ≤ received | `CHECK chk_remaining_le_received` |
| Stock movement signs match type | `CHECK chk_movement_sign` |
| Phone E.164 format | `CHECK chk_users_phone_format` |
| Storage temperature range valid | `CHECK chk_products_temp_range` |
| Categories don't self-parent | `CHECK chk_categories_no_self_parent` |
| Admin must have branch unless super | `CHECK chk_admin_branch_required` |
| Cart must have owner | `CHECK chk_carts_owner` |

**Application-enforced (not in DB):**
- FEFO selection logic
- Reservation/release transitions
- Translation completeness (every product has at least one `ru` translation)
- Image processing (resize, WebP)
- `total_quantity` cache reconciliation

---

## 13. Migration & Seeding Strategy

### 13.1 Tooling
- **Django migrations** if backend is Django
- **Alembic** if SQLAlchemy / FastAPI
- **node-pg-migrate** or **Prisma migrate** for Node
- One migration per logical change, never edit applied migrations

### 13.2 Migration order

```
1. extensions
2. branches
3. users + user_addresses + otp_codes
4. admin_users + admin_sessions
5. categories + category_translations
6. manufacturers
7. active_ingredients + active_ingredient_translations
8. symptoms + symptom_translations
9. suppliers
10. products + product_translations + product_images
11. product_active_ingredients + product_symptoms
12. branch_products + inventory_batches + stock_movements
13. carts + cart_items
14. orders + order_items + order_status_history
15. payments + deliveries
16. admin_audit_log + sms_log + search_log
17. all indexes (one migration per table or one combined)
```

Note: `admin_users.branch_id` references `branches`, so `branches` must come first.

### 13.3 Seed data

Required for any fresh environment:

- **One branch** (`BISHKEK_CENTRAL`)
- **Top-level categories** (Analgesics, Cold & Flu, GI, Vitamins, Cosmetics, Baby, etc.)
- **Top-level symptoms** (Headache, Sore Throat, Cough, Fever, Stomach Pain, Allergy, ...) with RU/KY/EN translations and synonyms
- **Common manufacturers** (Bayer, GSK, Sun Pharma, Pharmstandard, Sopharma, Hemofarm, ...)
- **Common active ingredients** (Paracetamol, Ibuprofen, Amoxicillin, ...)
- **One super_admin user** (created via management command, not migration)

### 13.4 Bulk product import

Pharmacies will not hand-type 3000 products. The admin panel must support:

- CSV / XLSX upload with column mapping UI
- Validation pass (dry-run): show row-level errors
- Idempotent by `sku`: existing SKUs are updated, new ones inserted
- Translations imported in same file with column suffixes (`name_ru`, `name_ky`, `name_en`)
- Images by URL or zip upload (referenced by SKU in CSV)

The import runs as a background job (Celery/BullMQ), writes a result file, emails the admin when done.


---

## 14. System Architecture

### 14.1 High-level diagram

```
                           Internet / Mobile
                                  │
                                  ▼
                       ┌──────────────────┐
                       │   Cloudflare     │   ← DDoS, WAF, CDN, TLS, image cache
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │  Nginx (LB+TLS)  │   ← static assets, gzip, rate limit
                       └────┬───────┬─────┘
                            │       │
                ┌───────────┘       └────────────┐
                ▼                                 ▼
        ┌────────────────┐               ┌────────────────┐
        │ Customer API   │               │   Admin API    │
        │  (Django/      │               │  (Django/      │
        │  FastAPI/      │               │  FastAPI/      │
        │  NestJS)       │               │  NestJS)       │
        │ Gunicorn x N   │               │ Gunicorn x N   │
        └──┬───────┬─────┘               └─┬──────┬───────┘
           │       │                       │      │
           │       ▼                       ▼      │
           │   ┌─────────────────────────────┐    │
           │   │    Redis (cache + queue)    │    │
           │   └────────────┬────────────────┘    │
           │                │                     │
           │       ┌────────▼─────────┐           │
           │       │ Celery / BullMQ  │           │
           │       │     Workers      │  ← SMS, emails, imports, reports
           │       └────────┬─────────┘           │
           │                │                     │
           ▼                ▼                     ▼
        ┌────────────────────────────────────────────┐
        │           PostgreSQL (primary)             │
        │  + read replica (when needed)              │
        └─────────────────────┬──────────────────────┘
                              │
                              ▼
                  ┌────────────────────┐
                  │  Cloudflare R2     │   ← product images, exports
                  │  (S3-compatible)   │
                  └────────────────────┘

External:
  ─ SMS provider (Nikita / Megacom API / regional aggregator)
  ─ Payment gateway (Freedom Pay / Kassa24 / MBank API)
  ─ Yandex Delivery API (later)
  ─ Sentry, log aggregator, uptime monitoring
```

### 14.2 Component Responsibilities

| Component | Responsibility |
|---|---|
| **Cloudflare** | TLS termination at edge, DDoS, WAF rules, CDN for static + images, bot protection |
| **Nginx** | Reverse proxy, gzip/brotli, rate limit by IP, serve uploaded files via signed URLs |
| **Customer API** | Storefront API: catalog, search, cart, checkout, account |
| **Admin API** | Admin panel API: CRUD, inventory, orders, reports, audit |
| **Next.js (storefront)** | SSR'd pages for SEO, hydrated React for interactivity |
| **Admin SPA** | If using Django admin: server-rendered. If custom: Next.js or Vite SPA |
| **PostgreSQL** | Source of truth |
| **Redis** | Session cache, rate-limit counters, search/catalog cache, Celery broker |
| **Celery / BullMQ workers** | Async jobs (see §18) |
| **Celery beat / cron** | Scheduled jobs (near-expiry, low-stock, batch expiry, cart cleanup, OTP cleanup) |
| **Cloudflare R2** | Object storage for images and admin export files |
| **SMS gateway** | Outbound SMS for OTP and order updates |
| **Payment gateway** | Card and wallet payments |
| **Sentry** | Error tracking |

### 14.3 Tech Stack Recommendation

For this domain, team size, and requirements:

| Layer | Choice | Why |
|---|---|---|
| Backend | **Django + DRF** | Built-in admin gives 70% of the pharmacy admin panel for free; ORM + migrations are mature; team can iterate fast. Alternative: **FastAPI** if the team strongly prefers async Python. **NestJS** if it's a TS shop. |
| Database | **PostgreSQL 16+** | FTS, JSONB, partial indexes, generated columns, mature operationally |
| Cache / queue | **Redis 7+** | Fits sessions, rate limiting, search cache, and Celery broker |
| Storefront | **Next.js (App Router)** | SSR for SEO ("парацетамол Бишкек"), great mobile performance, image optimisation |
| Admin UI | **Django admin (customised)** for MVP; custom Next.js admin in Phase 2 | Saves weeks of work; revisit when admin needs complex UX |
| Object storage | **Cloudflare R2** | S3-compatible, no egress fees, cheap |
| CDN / DNS | **Cloudflare** | Free tier covers MVP, integrates with R2 |
| SMS | **Local KG aggregator** (Nikita, etc.) | Twilio is expensive for KG numbers |
| Payments | **Freedom Pay** + **MBank API** | Cover most KG card and wallet flows |
| Hosting | **Single Hetzner / DigitalOcean VPS** for MVP | Cheap, fast, easy to back up. Move to managed Postgres when stable. |
| CI/CD | **GitHub Actions** | Standard, free tier sufficient |
| Monitoring | **Sentry + Better Stack** (or Grafana Cloud free tier) | Errors + uptime + log search |

### 14.4 Service boundaries

For MVP, this is a **modular monolith**, not microservices. Two deployable Django/FastAPI apps share the same database:

- `pharmacy.api.customer` — public API
- `pharmacy.api.admin` — admin API
- `pharmacy.workers` — Celery workers
- All share `pharmacy.core` (models, services, utils)

Why monolith:
- One database, one migration story
- One team, one deploy
- Microservices solve org problems; we don't have those problems yet

When to split: when one of these becomes true — > 5 engineers per service boundary, deploy contention, or one service has radically different scaling needs.

---

## 15. API Design

### 15.1 Conventions

- REST + JSON over HTTPS
- Versioned: `/api/v1/...`
- Customer endpoints: `/api/v1/...`
- Admin endpoints: `/api/admin/v1/...`
- Pagination: cursor-based for lists that grow (orders, audit log); offset for catalog (cacheable)
- Errors: RFC 7807 Problem Details (`{type, title, status, detail, errors}`)
- All requests log a request ID; responses echo `X-Request-ID`
- Idempotency on POSTs that create money-relevant resources via `Idempotency-Key` header

### 15.2 Customer API surface

```
Auth
  POST   /auth/otp/request        { phone }
  POST   /auth/otp/verify         { phone, code } -> { access_token, refresh_token }
  POST   /auth/refresh            { refresh_token }
  POST   /auth/logout

Account
  GET    /me
  PATCH  /me                      { first_name, last_name, email, language }
  GET    /me/addresses
  POST   /me/addresses
  PATCH  /me/addresses/:id
  DELETE /me/addresses/:id
  GET    /me/orders               (cursor paginated)
  GET    /me/orders/:order_number

Catalog
  GET    /categories              (tree)
  GET    /categories/:slug
  GET    /categories/:slug/products?sort=&page=
  GET    /symptoms
  GET    /symptoms/:slug/products

Products
  GET    /products?category=&symptom=&manufacturer=&price_min=&price_max=&page=&sort=
  GET    /products/:slug
  GET    /products/:slug/related

Search
  GET    /search?q=&lang=&page=
  GET    /search/suggest?q=&lang=

Cart
  GET    /cart
  POST   /cart/items              { product_id, quantity }
  PATCH  /cart/items/:id          { quantity }
  DELETE /cart/items/:id
  POST   /cart/clear

Checkout
  POST   /checkout/quote          { address_id, delivery_method } -> totals
  POST   /checkout/place          (Idempotency-Key)
                                  { address_id, payment_method, notes }
                                  -> { order_number, payment_redirect_url? }
  GET    /checkout/orders/:order_number/status

Misc
  GET    /branches                (for "find a pharmacy")
  GET    /content/pages/:slug     (about, terms, privacy — CMS-lite)
  POST   /support/contact         { name, phone, message }
```

### 15.3 Admin API surface

```
Auth
  POST   /admin/auth/login        { email, password, totp_code? }
  POST   /admin/auth/logout

Catalog management
  GET    /admin/products?q=&category=&page=
  POST   /admin/products
  GET    /admin/products/:id
  PATCH  /admin/products/:id
  DELETE /admin/products/:id      (soft delete)
  POST   /admin/products/import   (multipart CSV/XLSX, async)
  GET    /admin/imports/:job_id   (status)

  Categories, manufacturers, ingredients, symptoms — same CRUD shape

Inventory
  GET    /admin/branches/:id/inventory?low_stock=&expiring=
  POST   /admin/branches/:id/inventory/batches    (receive stock)
  PATCH  /admin/inventory/batches/:id             (correct, write-off)
  GET    /admin/inventory/movements?from=&to=&product=

Orders
  GET    /admin/orders?status=&branch=&from=&to=&q=
  GET    /admin/orders/:id
  PATCH  /admin/orders/:id        { status, internal_notes }
  POST   /admin/orders/:id/cancel { reason }
  POST   /admin/orders/:id/refund { amount, reason }

Reports
  GET    /admin/reports/sales?from=&to=&branch=
  GET    /admin/reports/expiring?days=
  GET    /admin/reports/low-stock
  GET    /admin/reports/top-products

Users (read-mostly)
  GET    /admin/users?q=
  GET    /admin/users/:id

Admin team management (super_admin only)
  GET    /admin/team
  POST   /admin/team
  PATCH  /admin/team/:id

Audit
  GET    /admin/audit?actor=&entity=&from=&to=
```

### 15.4 Versioning policy

- Breaking changes → bump to `/v2`
- Additive changes (new fields, new endpoints) ship under `/v1`
- Deprecated endpoints respond with `Deprecation` and `Sunset` headers for at least 90 days

---

## 16. Authentication & Authorization

### 16.1 Customer auth — SMS OTP

```
1. POST /auth/otp/request {phone}
   - Rate limit: 1 req per phone per 60s; 3 per phone per 15 min; 10 per IP per hour (Redis)
   - Generate 6-digit code, hash, INSERT into otp_codes (expires_at = now + 5 min)
   - Enqueue SMS job

2. POST /auth/otp/verify {phone, code}
   - Look up active OTP for phone
   - bcrypt-compare; increment attempts on miss
   - On success: mark consumed, find or create user, issue tokens

3. Tokens
   - Access JWT: 15 min, signed RS256, contains user_id + role
   - Refresh token: 30 days, opaque, stored hashed in Redis (allows revocation)
   - Refresh rotation on each refresh; old refresh becomes invalid
```

### 16.2 Admin auth — Password + optional TOTP

- Email + password (argon2id) + optional TOTP for `super_admin` and `branch_manager`
- Server-side sessions (`admin_sessions`) for revocability
- Session cookie: `HttpOnly; Secure; SameSite=Lax`
- CSRF tokens on every mutating request
- Account lockout after 5 failed attempts for 15 min
- All admin actions audited

### 16.3 Authorization model

Role-based with branch scoping:

| Role | Catalog | Inventory | Orders | Admin team |
|---|---|---|---|---|
| `super_admin` | All branches, all CRUD | All branches | All branches | Full |
| `branch_manager` | Read all, write own branch availability/price | Own branch | Own branch | None |
| `pharmacist` | Read | Own branch | Own branch (status only) | None |
| `content_editor` | Full CRUD on products/categories | None | None | None |

Enforced by a single decorator/middleware checking `(role, resource, action, branch_id)`. Tested with a permissions matrix unit test.

---

## 17. Caching Strategy

### 17.1 What to cache and where

| Data | Where | TTL | Invalidation |
|---|---|---|---|
| Categories tree (per language) | Redis | 1 hour | On any category mutation, bump version key |
| Featured products (homepage) | Redis | 10 min | Time-based + on `is_featured` toggle |
| Product detail page (read model) | Redis | 5 min | On product/translation/image/inventory update for that product |
| Search suggestions (autocomplete) | Redis | 60 sec | Time-based only |
| Price + availability for hot products | Redis | 30 sec | Time-based; UI re-validates at add-to-cart |
| User session (JWT refresh state) | Redis | matches token lifetime | On logout |
| Rate limit counters | Redis | sliding window | n/a |

### 17.2 Cache key conventions

```
v1:cat:tree:ru                          → categories tree, RU
v1:product:read:<uuid>:ru               → product detail read model
v1:product:price:<branch_id>:<uuid>     → branch-specific price + qty
v1:search:suggest:<lang>:<query>        → autocomplete results
v1:rl:otp:phone:+996700123456           → rate limit counter
v1:session:refresh:<jti>                → refresh token state
```

The leading `v1:` lets us bump the entire cache namespace by changing the prefix on deploy if a serialization format changes.

### 17.3 What NOT to cache

- Inventory `total_quantity` for cart/checkout — always read fresh
- Admin endpoints — fresh data is the whole point
- Order status — customers re-check, must reflect reality

### 17.4 Stale-while-revalidate

For storefront category pages and product details, return the cached value and trigger an async refresh if the entry is older than half its TTL. Better p99 latency for free.

---

## 18. Background Jobs

| Job | Trigger | Purpose |
|---|---|---|
| `send_sms` | Enqueued by API | OTP, order status, delivery updates |
| `send_email_receipt` | Order status → `confirmed` | Email receipt to customer |
| `process_product_import` | Admin upload | Parse + validate + upsert thousands of rows |
| `process_image_upload` | Image uploaded | Resize variants (200/600/1200), WebP, upload to R2 |
| `generate_admin_report` | Admin requests export | CSV/XLSX assembly, store in R2, email link |
| `near_expiry_report` | Daily 06:00 Asia/Bishkek | Email branch managers list of batches expiring in 60d |
| `low_stock_report` | Daily 06:00 | Email branch managers items at/below threshold |
| `expire_batches` | Daily 02:00 | Mark batches with `expiry_date < CURRENT_DATE`, write `stock_movements` of type `expired`, recompute `branch_products.total_quantity` |
| `reconcile_stock_cache` | Daily 03:00 | Recompute `branch_products.total_quantity` from batches; alert on drift |
| `cleanup_otps` | Daily | Delete OTPs older than 7 days |
| `cleanup_carts` | Daily | Delete carts past `expires_at` |
| `release_pending_orders` | Hourly | Auto-cancel `pending` orders older than 24h, release reservations |
| `payment_reconcile` | Hourly | Reconcile `payments.pending` against gateway API |
| `refresh_search_suggestions` | Hourly | Recompute popular searches from `search_log` |

All jobs are idempotent: re-running a job must produce the same end state.

---

## 19. File & Image Pipeline

### 19.1 Upload flow

```
Admin browser
   │ multipart/form-data
   ▼
Admin API
   │ validate (mime, size ≤ 5MB, dimensions)
   ▼
Temp upload to local disk
   │
   ▼
Enqueue process_image_upload(temp_path, product_id)
   │
Worker:
   1. Load with Pillow / sharp
   2. Strip EXIF (privacy + smaller size)
   3. Generate variants:
        - thumb_200.webp  (q=80)
        - medium_600.webp (q=82)
        - large_1200.webp (q=85)
        - original.webp   (lossless or q=92)
   4. Upload all to R2 under products/<uuid>/<image_id>/<variant>.webp
   5. INSERT product_images row with all URLs
   6. Delete temp file
```

### 19.2 Serving

- Public URL form: `https://cdn.pharmacy.kg/products/<uuid>/<image_id>/medium_600.webp`
- Cloudflare in front of R2 → effectively free CDN
- Storefront uses `<picture>` with `srcset` for responsive images
- Lazy load below the fold

### 19.3 Storage layout in R2

```
products/<product_uuid>/<image_id>/{original,thumb_200,medium_600,large_1200}.webp
imports/<job_id>/{input.csv,errors.csv}
exports/<report_id>/<filename>
backups/postgres/<date>.sql.gz
```

---

## 20. Security

### 20.1 Network & transport
- HTTPS everywhere; HTTP redirects to HTTPS
- HSTS with `max-age=31536000; includeSubDomains; preload`
- Strict CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`
- Cloudflare WAF rules + bot fight mode

### 20.2 Application security
- Parameterised queries only (no string concat) — ORM enforces
- Output escaping by default in templates (Django auto-escapes)
- File upload: validate magic bytes, restrict mime, size limit, never serve from same origin as app (use CDN subdomain)
- Open redirects: whitelist redirect targets after login
- Mass assignment: explicit serializer fields, never `**request.data`

### 20.3 Secrets
- Never in repo. `.env` ignored. Production secrets in a vault (Doppler, AWS Secrets Manager, HashiCorp Vault)
- DB credentials rotated on incident
- Payment gateway secrets scoped to a single service account
- Signing keys for JWT rotated on schedule (90 days), with key ID in token header

### 20.4 PII handling
- Phone numbers are PII. Logged with last 4 only (`+996****1234`)
- OTP codes hashed at rest, never logged
- Passwords argon2id, never logged
- Card data never touches our servers — payment gateway hosted page or tokenization
- DB backups encrypted at rest

### 20.5 Rate limiting (Redis)

| Endpoint | Limit |
|---|---|
| `POST /auth/otp/request` | 1 / 60s / phone, 3 / 15m / phone, 10 / hour / IP |
| `POST /auth/otp/verify` | 5 / 5m / phone |
| `POST /auth/refresh` | 60 / hour / token |
| `GET /search` | 60 / minute / IP |
| `POST /support/contact` | 5 / hour / IP |
| Default authenticated | 600 / minute / user |
| Default unauthenticated | 120 / minute / IP |

### 20.6 OWASP Top 10 mapping
- A01 Broken Access Control → role+branch matrix tested in CI
- A02 Cryptographic Failures → TLS, argon2, encrypted backups
- A03 Injection → ORM, parameterised queries, bleach for HTML fields
- A04 Insecure Design → threat model reviewed at each milestone
- A05 Misconfiguration → infra as code, pinned base images
- A06 Vulnerable Components → Dependabot + weekly `pip-audit`/`npm audit`
- A07 Auth Failures → MFA for admin, lockout, OTP rate limiting
- A08 Software & Data Integrity → signed deploys, checksum on imports
- A09 Logging Failures → structured JSON logs, retained 90d, request IDs
- A10 SSRF → outbound HTTP through allowlist (image fetch, etc.)

---

## 21. Observability

### 21.1 Logs
- Structured JSON
- Every line has `request_id`, `user_id` (or `null`), `branch_id` (when applicable)
- Sensitive fields redacted by formatter
- Shipped to a log aggregator (Better Stack / Grafana Loki / self-hosted)
- 90-day retention; `admin_audit_log` retained 7 years

### 21.2 Metrics
Prometheus-format, scraped by Grafana Cloud or self-hosted Grafana.

Key metrics:
- HTTP request count / latency / error rate per route
- DB query count / slow query count
- Celery queue depth, job duration
- Cache hit ratio per key prefix
- Inventory drift (cache vs computed), reported daily by reconcile job
- OTP delivery success rate, payment success rate
- Search latency p50 / p95 / p99
- Active sessions, daily/weekly active users

### 21.3 Tracing
OpenTelemetry SDK in API and workers; trace ID equals `X-Request-ID`. Sample 10% of normal traffic, 100% of errors.

### 21.4 Errors
- Sentry for both backend and frontend
- Source maps uploaded on each deploy
- PII scrubbing in Sentry SDK config
- On-call rotation alerted on > 5 errors/min sustained for 5 min

### 21.5 Uptime
- Synthetic check on `/api/v1/health` every 60s from two regions
- Synthetic checkout flow run every 15 min in staging-like prod project
- Status page (statuspage.io free tier) for transparency

---

## 22. Deployment Topology

### 22.1 Environments
- **local** — docker-compose
- **staging** — single VPS, mirrors production config, anonymised data
- **production** — see below

### 22.2 MVP production (single VPS)

One Hetzner CCX23 (or DO equivalent), ~€30/mo:
- Nginx, app servers (gunicorn ×N), Celery workers, Postgres, Redis on the same box
- Backups to R2 nightly
- Monitored, but if this box dies recovery is ~10 min from snapshot

This is genuinely fine until you have a few thousand orders/month.

### 22.3 Phase-2 production

When traffic justifies it:
- App servers behind nginx LB (2× small VPS, autoscaled later)
- Managed Postgres (DO Managed Postgres / Aiven) with daily backups + PITR + read replica
- Managed Redis (DO / Upstash)
- Workers on their own small VPS
- Object storage already on R2

### 22.4 Deploy pipeline

```
git push → GitHub Actions
   ├─ lint
   ├─ test (unit + integration with ephemeral Postgres)
   ├─ build container images
   ├─ push to registry
   ├─ deploy to staging (auto on main)
   ├─ run smoke tests against staging
   └─ manual approval → deploy to production
```

Production deploy:
- Run migrations (`migrate --plan` first; abort if destructive)
- Roll new app containers behind LB
- Health check; rollback automatically if unhealthy
- Cache version bump if needed

---

## 23. Scaling Roadmap

What to do **when**, not before.

### 23.1 < 1k orders / month (MVP)
Single VPS, Django admin, PG full-text search, R2 for images. Don't optimise.

### 23.2 1k–10k orders / month
- Move Postgres to managed service with daily backups + PITR
- Add a Postgres read replica; route catalog reads to replica
- Move workers to a separate VPS
- Add CDN-side caching headers on catalog endpoints
- Profile slow queries weekly with `pg_stat_statements`

### 23.3 10k–100k orders / month
- Horizontal app servers (2–4) behind LB
- Dedicated Redis (managed)
- Materialised view for the catalog read model, refreshed every minute
- Move search to Meilisearch if FTS p95 creeps over 200 ms
- Partition `stock_movements` and `admin_audit_log` by month
- ETL nightly to a warehouse (BigQuery / ClickHouse) for reporting; stop running heavy reports on the OLTP DB

### 23.4 Multi-branch (the planned expansion)
- Schema already supports it — toggle the branch selector in admin and storefront
- Add inter-branch transfers (`transferred_in/out` movements, simple form)
- "Find nearest pharmacy" using `latitude`/`longitude` + PostGIS or simple haversine
- Per-branch reporting was already keyed correctly

### 23.5 100k+ orders / month
- Split admin and customer APIs to separate deploys with separate scaling
- Consider extracting the search service
- Consider sharding `stock_movements` by branch_id when partitioning is no longer enough
- Read replicas per region if expanding beyond Bishkek/Osh latency

---

## 24. Backups & Disaster Recovery

### 24.1 Postgres
- **Logical backup:** `pg_dump --format=custom` nightly to R2, encrypted, retained 30 days
- **Physical / WAL:** PITR via continuous WAL archiving — once on managed Postgres
- **Test restore:** monthly automated restore to staging — *backups are only real when proven to restore*

### 24.2 R2 (object storage)
- Bucket versioning enabled
- Lifecycle: keep latest + 30 days of versions, then expire

### 24.3 RTO / RPO targets

| Failure | RTO (recovery time) | RPO (data loss) |
|---|---|---|
| App container crash | < 1 min (auto-restart) | 0 |
| App server lost | < 10 min (redeploy) | 0 |
| DB corruption (non-managed) | < 2 hours (restore last nightly) | up to 24h |
| DB corruption (managed + PITR) | < 30 min | < 5 min |
| Region outage | < 4 hours (rebuild in another region from off-region backups) | < 24h |

### 24.4 Runbooks (live in the repo)
- DB restore (logical and PITR)
- Rotate JWT signing keys
- Revoke all admin sessions
- Kill stuck background jobs
- Roll back a bad deploy
- Replay failed payment webhooks
- Manually expire a poisoned product (recall)

---

## 25. Open Questions & Future Work

### 25.1 Decisions to lock before coding starts

1. **Backend language** — Django or NestJS? (Django recommended above; NestJS fine if team is TS-strong.)
2. **Admin UI** — Reuse Django admin (fast) or build custom? (Recommended: Django admin for MVP; custom in Phase 2.)
3. **Payment provider** — Freedom Pay vs Kassa24 vs MBank API. Pricing and integration effort comparison needed.
4. **SMS provider** — choose one local provider; have a fallback configured.
5. **Currency-only KGS at launch?** Schema supports multi-currency; decide if storefront ever shows USD.
6. **Customer reviews on medicines** — likely skip permanently; confirm.
7. **Loyalty program** — out of MVP; design hook (`user_id`, `order_id`, `points_delta`) so it can land later without schema churn.

### 25.2 Future schema additions (designed-for, not built)

- `subscriptions` for repeat orders
- `wishlists` (`user_id`, `product_id`, `created_at`)
- `promotions` and `promotion_rules` with applicability matrix
- `loyalty_points` and `point_transactions`
- `recall_notices` (when a batch must be pulled — schema already supports tracing via `inventory_batch_id` on `order_items`)
- `branch_inventory_transfers` with line items
- `prescriptions` — if regulation tightens or you choose to handle Rx

### 25.3 Things deliberately not built in MVP

- Live pharmacist chat
- Multi-currency
- Subscriptions / auto-refill
- Loyalty / referrals
- Promotions and coupons (beyond simple `discount_amount` on order)
- Click-and-collect with appointment slots
- Multi-pharmacy chain support beyond simple branches
- Reviews and Q&A
- A/B testing framework

These are real features for a world-class platform, but each one is a project. The schema above has clean seams to add them when they earn priority.

---

## Appendix A — DDL Application Order Summary

```sql
-- 1. Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "unaccent";
CREATE EXTENSION IF NOT EXISTS "btree_gin";
CREATE EXTENSION IF NOT EXISTS "citext";

-- 2. Enums
CREATE TYPE admin_role AS ENUM (...);
CREATE TYPE product_form AS ENUM (...);
CREATE TYPE order_status AS ENUM (...);
CREATE TYPE payment_status AS ENUM (...);
CREATE TYPE payment_method AS ENUM (...);
CREATE TYPE delivery_method AS ENUM (...);
CREATE TYPE stock_movement_type AS ENUM (...);

-- 3. Tables in dependency order (see §13.2)

-- 4. Indexes (see §9)

-- 5. Seed (see §13.3)
```

## Appendix B — Quick Sanity Checklist

Use this when reviewing PRs that touch the schema:

- [ ] New table has `created_at` and `updated_at`
- [ ] FK has an index (Postgres does NOT auto-index FKs)
- [ ] Money column is `NUMERIC(12,2)` and non-negative
- [ ] Timestamp is `TIMESTAMPTZ`
- [ ] Soft-deletable entity has `deleted_at`
- [ ] Translation table has `UNIQUE (entity_id, language_code)`
- [ ] Multi-branch awareness: query/data scoped by `branch_id` where applicable
- [ ] If table writes affect stock, a `stock_movements` row is written in the same transaction
- [ ] If admin can mutate it, an `admin_audit_log` row is written
- [ ] If user-facing, has matching translations seeded for `ru`, `ky`, `en`
- [ ] If hot path, a covering index exists; verified with `EXPLAIN ANALYZE`

---

*Document version 1.0 — Pharmacy Platform initial blueprint.*
