"""create catalog and audit log

Revision ID: 5b872d07a987
Revises: 07f41f005b0a
Create Date: 2026-05-02 17:24:58.638863+00:00

Hand-edited from autogenerate output:

* Removed spurious ALTER COLUMN ... server_default=utc_timestamp(6) noise
  on existing identity tables (existing default already matches; alembic's
  ``compare_server_default`` flagged a paren-form vs no-paren rendering
  difference that is a no-op at the SQL level).
* The ``dosage_unit`` CHECK was emitted as ``'%%'`` (SQLAlchemy auto-doubles
  ``%`` for paramstyle safety). MySQL would store the literal ``%%`` and
  reject runtime inserts of ``'%'``. We drop the autogen CHECK and emit
  the constraint via ``op.execute`` with a single ``%``.
* The FULLTEXT index needs ``WITH PARSER ngram`` for Cyrillic — autogen
  produces a vanilla FULLTEXT. We drop the autogen index and emit a raw
  SQL ``CREATE FULLTEXT INDEX ... WITH PARSER ngram``.
* The downgrade is simplified to ``drop_table`` per table — MySQL refuses
  to drop indexes that back FKs (same Phase 4 finding).
* Added ``import app.core.types`` (autogen references ``app.core.types.GUID``
  but doesn't import it).

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import app.core.types  # GUID type referenced below

# revision identifiers, used by Alembic.
revision: str = "5b872d07a987"
down_revision: str | Sequence[str] | None = "07f41f005b0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── Standalone tables (no FKs into catalog) ────────────────────────────
    op.create_table(
        "manufacturers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_manufacturers_name"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_manufacturers_active", "manufacturers", ["is_active"])

    op.create_table(
        "active_ingredients",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inn_name", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inn_name", name="uq_active_ingredients_inn"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("icon_url", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True),
        # NOTE: self-parent CHECK omitted — MySQL 8.0+ rejects CHECK on
        # AUTO_INCREMENT columns (error 3818). Enforced in service layer.
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name="fk_categories_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_categories_active_sort", "categories", ["is_active", "sort_order"])
    op.create_index("idx_categories_parent", "categories", ["parent_id"])

    op.create_table(
        "symptoms",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("icon_url", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_symptoms_slug"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_symptoms_active_sort", "symptoms", ["is_active", "sort_order"])

    # ─── Translation tables ─────────────────────────────────────────────────
    op.create_table(
        "active_ingredient_translations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("active_ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("synonyms", sa.JSON(), nullable=False),
        sa.CheckConstraint("language_code IN ('ru','ky','en')", name="chk_ai_trans_lang"),
        sa.ForeignKeyConstraint(
            ["active_ingredient_id"],
            ["active_ingredients.id"],
            name="fk_ai_trans_ingredient",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_ingredient_id", "language_code", name="uq_ai_trans_lang"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )

    op.create_table(
        "category_translations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("meta_title", sa.String(length=160), nullable=True),
        sa.Column("meta_description", sa.String(length=320), nullable=True),
        sa.CheckConstraint("language_code IN ('ru','ky','en')", name="chk_cat_trans_lang"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_cat_trans_category",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id", "language_code", name="uq_cat_trans_lang"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )

    op.create_table(
        "symptom_translations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symptom_id", sa.BigInteger(), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("synonyms", sa.JSON(), nullable=False),
        sa.CheckConstraint("language_code IN ('ru','ky','en')", name="chk_sym_trans_lang"),
        sa.ForeignKeyConstraint(
            ["symptom_id"],
            ["symptoms.id"],
            name="fk_sym_trans_symptom",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symptom_id", "language_code", name="uq_sym_trans_lang"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )

    # ─── Products + product translations + images + M:N ─────────────────────
    op.create_table(
        "products",
        sa.Column("id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("sku", sa.String(length=40), nullable=False),
        sa.Column("barcode", sa.String(length=40), nullable=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("manufacturer_id", sa.BigInteger(), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("form", sa.String(length=32), nullable=False),
        sa.Column("pack_size_label", sa.String(length=60), nullable=True),
        sa.Column("pack_quantity", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("pack_unit", sa.String(length=16), nullable=True),
        sa.Column("requires_prescription", sa.Boolean(), nullable=False),
        sa.Column("min_age", sa.SmallInteger(), nullable=True),
        sa.Column("max_per_order", sa.SmallInteger(), nullable=True),
        sa.Column("storage_temp_min_c", sa.SmallInteger(), nullable=True),
        sa.Column("storage_temp_max_c", sa.SmallInteger(), nullable=True),
        sa.Column("requires_cold_chain", sa.Boolean(), nullable=False),
        sa.Column("weight_grams", sa.Integer(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.CheckConstraint(
            "form IN ('tablet','capsule','syrup','drops','cream','ointment',"
            "'gel','spray','inhaler','injection','suppository','patch','powder',"
            "'solution','suspension','lozenge','other')",
            name="chk_products_form",
        ),
        sa.CheckConstraint(
            "storage_temp_min_c IS NULL OR storage_temp_max_c IS NULL "
            "OR storage_temp_min_c <= storage_temp_max_c",
            name="chk_products_temp_range",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_products_category",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["manufacturer_id"],
            ["manufacturers.id"],
            name="fk_products_manufacturer",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
        sa.UniqueConstraint("slug", name="uq_products_slug"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_products_barcode", "products", ["barcode"])
    op.create_index("idx_products_category_active", "products", ["category_id", "is_active"])
    op.create_index("idx_products_created_at", "products", ["created_at"])
    op.create_index("idx_products_featured", "products", ["is_featured", "created_at"])
    op.create_index("idx_products_manufacturer", "products", ["manufacturer_id"])

    op.create_table(
        "product_translations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("language_code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("short_description", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("usage_instructions", sa.Text(), nullable=True),
        sa.Column("side_effects", sa.Text(), nullable=True),
        sa.Column("contraindications", sa.Text(), nullable=True),
        sa.Column("composition", sa.Text(), nullable=True),
        sa.CheckConstraint("language_code IN ('ru','ky','en')", name="chk_pt_lang"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_pt_product",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "language_code", name="uq_pt_product_lang"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_pt_lang_name", "product_translations", ["language_code", "name"])
    # FULLTEXT WITH PARSER ngram — must be raw SQL since SQLAlchemy doesn't
    # express the parser clause. ngram_token_size is set on the server (2)
    # via docker-compose.
    op.execute(
        "CREATE FULLTEXT INDEX ftx_pt_search "
        "ON product_translations (name, short_description, description) "
        "WITH PARSER ngram"
    )

    op.create_table(
        "product_images",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("medium_url", sa.Text(), nullable=True),
        sa.Column("large_url", sa.Text(), nullable=True),
        sa.Column("alt_text", sa.String(length=255), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column(
            "primary_product_id",
            sa.BINARY(length=16),
            sa.Computed("IF(is_primary, product_id, NULL)", persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_product_images_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("primary_product_id", name="uq_product_images_primary"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_product_images_product_sort",
        "product_images",
        ["product_id", "sort_order"],
    )

    # M:N tables. The dosage_unit CHECK is emitted via op.execute to avoid
    # SQLAlchemy's `%` → `%%` paramstyle escape (which would put the literal
    # ``%%`` in the constraint and reject the runtime value ``%``).
    op.create_table(
        "product_active_ingredients",
        sa.Column("product_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("active_ingredient_id", sa.BigInteger(), nullable=False),
        sa.Column("dosage_amount", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("dosage_unit", sa.String(length=8), nullable=False),
        sa.ForeignKeyConstraint(
            ["active_ingredient_id"],
            ["active_ingredients.id"],
            name="fk_pai_ingredient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_pai_product",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("product_id", "active_ingredient_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_pai_ingredient",
        "product_active_ingredients",
        ["active_ingredient_id"],
    )
    op.execute(
        "ALTER TABLE product_active_ingredients "
        "ADD CONSTRAINT chk_pai_dosage_unit "
        "CHECK (dosage_unit IN ('mg','g','mcg','ml','IU','%'))"
    )

    op.create_table(
        "product_symptoms",
        sa.Column("product_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("symptom_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_psym_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["symptom_id"],
            ["symptoms.id"],
            name="fk_psym_symptom",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("product_id", "symptom_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_psym_symptom", "product_symptoms", ["symptom_id", "product_id"])

    # ─── Admin audit log ────────────────────────────────────────────────────
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=False),
        sa.Column("entity_id", sa.String(length=60), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["admin_users.id"],
            name="fk_audit_admin",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_audit_admin_created",
        "admin_audit_log",
        ["admin_user_id", "created_at"],
    )
    op.create_index("idx_audit_created", "admin_audit_log", ["created_at"])
    op.create_index(
        "idx_audit_entity",
        "admin_audit_log",
        ["entity_type", "entity_id", "created_at"],
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order. DROP TABLE drops indexes
    # automatically; explicit drop_index calls fail on MySQL when they
    # back FKs (Phase 4 finding).
    op.drop_table("admin_audit_log")
    op.drop_table("product_symptoms")
    op.drop_table("product_active_ingredients")
    op.drop_table("product_images")
    op.drop_table("product_translations")
    op.drop_table("products")
    op.drop_table("symptom_translations")
    op.drop_table("category_translations")
    op.drop_table("active_ingredient_translations")
    op.drop_table("symptoms")
    op.drop_table("categories")
    op.drop_table("active_ingredients")
    op.drop_table("manufacturers")
