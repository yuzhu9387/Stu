from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from recipe_agent.domain.identity.models import Account, FamilyMembership
from recipe_agent.domain.identity.repository import IdentityRepository
from recipe_agent.domain.identity.service import (
    HouseholdScope,
    IdentityConflictError,
    IdentityService,
    InvalidTokenError,
)


async def _create_account_without_family(session_factory, email: str) -> Account:
    async with session_factory() as session:
        account = Account(email=email)
        session.add(account)
        await session.commit()
        return account


@pytest.mark.asyncio
async def test_two_accounts_join_one_family_without_merging_identity(
    identity_service, session_factory
) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    member = await _create_account_without_family(session_factory, "member@example.com")

    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )
    joined = await identity_service.accept_family_invite(member.id, invite.code)

    assert joined.household_id == owner.household.id
    assert joined.account_id == member.id
    assert joined.account_id != owner.account.id
    assert joined.role == "member"

    member_delivery = await identity_service.request_magic_link("member@example.com")
    reauthenticated = await identity_service.consume_magic_link(member_delivery.token)
    assert reauthenticated.household.id == owner.household.id

    async with session_factory() as session:
        visible_member = await IdentityRepository(session).get_household_account(
            HouseholdScope(owner.account.id, owner.household.id), member.id
        )
    assert visible_member.id == member.id


@pytest.mark.asyncio
async def test_only_family_owner_can_create_invite(identity_service, session_factory) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    member = await _create_account_without_family(session_factory, "member@example.com")
    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )
    membership = await identity_service.accept_family_invite(member.id, invite.code)

    with pytest.raises(PermissionError):
        await identity_service.create_family_invite(
            HouseholdScope(membership.account_id, membership.household_id)
        )


@pytest.mark.asyncio
async def test_family_invite_is_single_use_and_existing_membership_is_preserved(
    identity_service, session_factory
) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    first = await _create_account_without_family(session_factory, "first@example.com")
    second_delivery = await identity_service.request_magic_link("second@example.com")
    second = await identity_service.consume_magic_link(second_delivery.token)
    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )

    with pytest.raises(ValueError, match="already belongs"):
        await identity_service.accept_family_invite(second.account.id, invite.code)
    joined = await identity_service.accept_family_invite(first.id, invite.code)
    third = await _create_account_without_family(session_factory, "third@example.com")
    with pytest.raises(InvalidTokenError):
        await identity_service.accept_family_invite(third.id, invite.code)

    async with session_factory() as session:
        result = await session.execute(
            select(FamilyMembership).where(
                FamilyMembership.account_id == second.account.id
            )
        )
        preserved = result.scalar_one()
    assert joined.account_id == first.id
    assert preserved.household_id == second.household.id


@pytest.mark.asyncio
async def test_family_invite_expires_after_ten_minutes(session_factory) -> None:
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    clock = {"now": now}
    service = IdentityService(session_factory=session_factory, now=lambda: clock["now"])
    owner_delivery = await service.request_magic_link("owner@example.com")
    owner = await service.consume_magic_link(owner_delivery.token)
    member = await _create_account_without_family(session_factory, "member@example.com")
    invite = await service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )

    assert invite.expires_at == now + timedelta(minutes=10)
    clock["now"] = now + timedelta(minutes=10)
    with pytest.raises(InvalidTokenError):
        await service.accept_family_invite(member.id, invite.code)


@pytest.mark.asyncio
async def test_lark_identity_resolves_existing_account_scope(identity_service) -> None:
    delivery = await identity_service.request_magic_link("cook@example.com")
    authenticated = await identity_service.consume_magic_link(delivery.token)
    link = await identity_service.create_lark_link_code(authenticated.account.id)

    await identity_service.link_lark_identity(link.code, "ou_family_cook")
    scope = await identity_service.resolve_lark_identity("ou_family_cook")

    assert scope == HouseholdScope(authenticated.account.id, authenticated.household.id)
    assert await identity_service.resolve_lark_identity("ou_unknown") is None


@pytest.mark.asyncio
async def test_lark_link_code_expires_after_ten_minutes(session_factory) -> None:
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    clock = {"now": now}
    service = IdentityService(session_factory=session_factory, now=lambda: clock["now"])
    delivery = await service.request_magic_link("cook@example.com")
    authenticated = await service.consume_magic_link(delivery.token)
    link = await service.create_lark_link_code(authenticated.account.id)

    clock["now"] = now + timedelta(minutes=10)
    with pytest.raises(InvalidTokenError):
        await service.link_lark_identity(link.code, "ou_expired")


@pytest.mark.asyncio
async def test_lark_open_id_and_account_each_link_only_once(identity_service) -> None:
    first_delivery = await identity_service.request_magic_link("first@example.com")
    first = await identity_service.consume_magic_link(first_delivery.token)
    second_delivery = await identity_service.request_magic_link("second@example.com")
    second = await identity_service.consume_magic_link(second_delivery.token)
    first_code = await identity_service.create_lark_link_code(first.account.id)
    second_code = await identity_service.create_lark_link_code(second.account.id)

    await identity_service.link_lark_identity(first_code.code, "ou_cook")

    with pytest.raises(IdentityConflictError):
        await identity_service.create_lark_link_code(first.account.id)
    with pytest.raises(IdentityConflictError):
        await identity_service.link_lark_identity(second_code.code, "ou_cook")
    with pytest.raises(InvalidTokenError):
        await identity_service.link_lark_identity(second_code.code, "ou_other")
