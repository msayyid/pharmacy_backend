"""E2E-specific test helpers.

These fixtures and helpers wrap the persistent-DB seeding patterns the
identity E2E tests need (admin users, branches). Per-test unique values
(email/phone with random suffix) avoid cross-test pollution.

The autouse :data:`_e2e_db_at_head` fixture forces every E2E test to depend
on ``_migrated_db`` from the root conftest — E2E tests don't usually
request ``session``, so we wire the dep here.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from app.integrations.sms.base import set_sms_queue
from app.integrations.sms.fake import FakeSmsQueue


@pytest.fixture(autouse=True)
def _e2e_db_at_head(_migrated_db: None) -> None:
    """Ensure the DB is migrated to head for every E2E test."""
    return


def install_fresh_sms_queue() -> FakeSmsQueue:
    """Replace the module-level SMS queue with a fresh fake; return it."""
    fake = FakeSmsQueue()
    set_sms_queue(fake)
    return fake


def extract_otp_from_messages(messages: list[Any]) -> str | None:
    """Pull the first all-digits run out of the most recent OTP message body."""
    for msg in reversed(messages):
        if msg.purpose != "otp":
            continue
        m = re.search(r"(\d{4,})", msg.body)
        if m:
            return m.group(1)
    return None


async def seed_admin_committed(
    *,
    email: str,
    password: str,
    role: str = "super_admin",
    branch_id: int | None = None,
) -> int:
    """Create an admin in a one-off committed session. Returns admin_id."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings
    from app.core.security import hash_password
    from app.domain.identity.models import AdminUser

    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    pepper = settings.password_pepper.get_secret_value()
    try:
        async with factory() as s:
            admin = AdminUser(
                email=email,
                password_hash=hash_password(password, pepper),
                first_name="Test",
                last_name="Admin",
                role=role,
                branch_id=branch_id,
                is_active=True,
            )
            s.add(admin)
            await s.commit()
            assert admin.id is not None
            return admin.id
    finally:
        await engine.dispose()


async def seed_branch_committed(*, code: str, name: str = "Test Branch") -> int:
    """Create a branch in a one-off committed session. Returns branch_id."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings
    from app.domain.inventory.models import Branch

    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            branch = Branch(
                code=code,
                name=name,
                address="Test address",
            )
            s.add(branch)
            await s.commit()
            assert branch.id is not None
            return branch.id
    finally:
        await engine.dispose()
