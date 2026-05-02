"""Customer account endpoints — ``/api/v1/me`` + ``/api/v1/me/addresses``.

All endpoints require :data:`CurrentUser` (Bearer JWT).

Reference: BACKEND_BLUEPRINT.md §13; PRODUCT_BLUEPRINT.md §8.1
(F-ACC-001..004), §16.3 (address shape).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_account_service
from app.domain.identity.dependencies import CurrentUser
from app.domain.identity.schemas import (
    AddressCreate,
    AddressRead,
    AddressUpdate,
    UserMeRead,
    UserMeUpdate,
)
from app.domain.identity.services import AccountService

router = APIRouter(tags=["account"])


# ─── /me ──────────────────────────────────────────────────────────────────────


@router.get("/me", response_model=UserMeRead)
async def get_me(user: CurrentUser) -> UserMeRead:
    return UserMeRead.model_validate(user)


@router.patch("/me", response_model=UserMeRead)
async def update_me(
    payload: UserMeUpdate,
    user: CurrentUser,
    service: Annotated[AccountService, Depends(get_account_service)],
) -> UserMeRead:
    updated = await service.update_me(
        user,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email) if payload.email else None,
        preferred_language=payload.preferred_language,
    )
    return UserMeRead.model_validate(updated)


# ─── /me/addresses ────────────────────────────────────────────────────────────


@router.get("/me/addresses", response_model=list[AddressRead])
async def list_addresses(
    user: CurrentUser,
    service: Annotated[AccountService, Depends(get_account_service)],
) -> list[AddressRead]:
    addresses = await service.list_addresses(user)
    return [AddressRead.model_validate(a) for a in addresses]


@router.post(
    "/me/addresses",
    response_model=AddressRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_address(
    payload: AddressCreate,
    user: CurrentUser,
    service: Annotated[AccountService, Depends(get_account_service)],
) -> AddressRead:
    addr = await service.create_address(user, payload.model_dump())
    return AddressRead.model_validate(addr)


@router.patch("/me/addresses/{address_id}", response_model=AddressRead)
async def update_address(
    address_id: int,
    payload: AddressUpdate,
    user: CurrentUser,
    service: Annotated[AccountService, Depends(get_account_service)],
) -> AddressRead:
    updates = payload.model_dump(exclude_unset=True)
    addr = await service.update_address(user, address_id, updates)
    return AddressRead.model_validate(addr)


@router.delete(
    "/me/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_address(
    address_id: int,
    user: CurrentUser,
    service: Annotated[AccountService, Depends(get_account_service)],
) -> None:
    await service.delete_address(user, address_id)
