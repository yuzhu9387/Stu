from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from recipe_agent.domain.feedback.models import FeedbackEventRecord, RatingRecord
from recipe_agent.domain.identity.models import (
    Account,
    AgentRun,
    Conversation,
    FamilyMembership,
    Household,
    SuggestedActionRecord,
)
from recipe_agent.domain.identity.preferences import DietaryPreference
from recipe_agent.domain.identity.repository import IdentityRepository
from recipe_agent.domain.identity.service import (
    HouseholdScope,
    IdentityConflictError,
    IdentityService,
    InvalidTokenError,
)
from recipe_agent.domain.planning.models import MealPlanRecord
from recipe_agent.domain.recipes.models import MediaObject, RawInput, Recipe
from recipe_agent.domain.sharing.models import ShareSnapshotRecord


@pytest.mark.asyncio
async def test_two_accounts_join_one_family_without_merging_identity(
    identity_service, session_factory
) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    member_delivery = await identity_service.request_magic_link("member@example.com")
    member = await identity_service.consume_magic_link(member_delivery.token)
    member_source_household_id = member.household.id

    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )
    joined = await identity_service.accept_family_invite(
        HouseholdScope(member.account.id, member.household.id), invite.code
    )

    assert joined.household_id == owner.household.id
    assert joined.account_id == member.account.id
    assert joined.account_id != owner.account.id
    assert joined.role == "member"
    assert await identity_service.resolve_web_session(member.session_token) == HouseholdScope(
        member.account.id, owner.household.id
    )

    reauth_delivery = await identity_service.request_magic_link("member@example.com")
    reauthenticated = await identity_service.consume_magic_link(reauth_delivery.token)
    assert reauthenticated.household.id == owner.household.id

    async with session_factory() as session:
        assert await session.get(Household, member_source_household_id) is None
        visible_member = await IdentityRepository(session).get_household_account(
            HouseholdScope(owner.account.id, owner.household.id), member.account.id
        )
    assert visible_member.id == member.account.id


@pytest.mark.asyncio
async def test_only_family_owner_can_create_invite(identity_service, session_factory) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    member_delivery = await identity_service.request_magic_link("member@example.com")
    member = await identity_service.consume_magic_link(member_delivery.token)
    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )
    membership = await identity_service.accept_family_invite(
        HouseholdScope(member.account.id, member.household.id), invite.code
    )

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
    first_delivery = await identity_service.request_magic_link("first@example.com")
    first = await identity_service.consume_magic_link(first_delivery.token)
    second_delivery = await identity_service.request_magic_link("second@example.com")
    second = await identity_service.consume_magic_link(second_delivery.token)
    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )

    async with session_factory() as session:
        session.add(
            RawInput(
                household_id=second.household.id,
                owner_account_id=second.account.id,
                kind="text",
                raw_text="do not discard",
            )
        )
        await session.commit()

    with pytest.raises(IdentityConflictError, match="Personal family is not empty"):
        await identity_service.accept_family_invite(
            HouseholdScope(second.account.id, second.household.id), invite.code
        )
    joined = await identity_service.accept_family_invite(
        HouseholdScope(first.account.id, first.household.id), invite.code
    )
    third_delivery = await identity_service.request_magic_link("third@example.com")
    third = await identity_service.consume_magic_link(third_delivery.token)
    with pytest.raises(InvalidTokenError):
        await identity_service.accept_family_invite(
            HouseholdScope(third.account.id, third.household.id), invite.code
        )

    async with session_factory() as session:
        result = await session.execute(
            select(FamilyMembership).where(FamilyMembership.account_id == second.account.id)
        )
        preserved = result.scalar_one()
    assert joined.account_id == first.account.id
    assert preserved.household_id == second.household.id


@pytest.mark.asyncio
async def test_family_invite_expires_after_ten_minutes(session_factory) -> None:
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    clock = {"now": now}
    service = IdentityService(session_factory=session_factory, now=lambda: clock["now"])
    owner_delivery = await service.request_magic_link("owner@example.com")
    owner = await service.consume_magic_link(owner_delivery.token)
    member_delivery = await service.request_magic_link("member@example.com")
    member = await service.consume_magic_link(member_delivery.token)
    invite = await service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )

    assert invite.expires_at == now + timedelta(minutes=10)
    clock["now"] = now + timedelta(minutes=10)
    with pytest.raises(InvalidTokenError):
        await service.accept_family_invite(
            HouseholdScope(member.account.id, member.household.id), invite.code
        )


@pytest.mark.asyncio
async def test_family_with_another_member_cannot_be_replaced(
    identity_service, session_factory
) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    actor_delivery = await identity_service.request_magic_link("actor@example.com")
    actor = await identity_service.consume_magic_link(actor_delivery.token)
    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )
    async with session_factory() as session:
        other = Account(email="other@example.com")
        session.add(other)
        await session.flush()
        session.add(
            FamilyMembership(
                account_id=other.id,
                household_id=actor.household.id,
                role="member",
            )
        )
        await session.commit()

    with pytest.raises(IdentityConflictError, match="Personal family is not empty"):
        await identity_service.accept_family_invite(
            HouseholdScope(actor.account.id, actor.household.id), invite.code
        )


@pytest.mark.parametrize(
    "record_kind",
    (
        "recipe",
        "raw_input",
        "media",
        "plan",
        "feedback",
        "rating",
        "conversation",
        "run",
        "suggested_action",
        "preference",
        "share",
    ),
)
@pytest.mark.asyncio
async def test_every_business_record_kind_makes_family_nonempty(
    identity_service, session_factory, record_kind
) -> None:
    delivery = await identity_service.request_magic_link(f"{record_kind}@example.com")
    authenticated = await identity_service.consume_magic_link(delivery.token)
    household_id = authenticated.household.id
    account_id = authenticated.account.id
    record_id = uuid4()
    records = {
        "recipe": Recipe(id=record_id, household_id=household_id, owner_account_id=account_id),
        "raw_input": RawInput(
            id=record_id,
            household_id=household_id,
            owner_account_id=account_id,
            kind="text",
        ),
        "media": MediaObject(
            id=record_id,
            household_id=household_id,
            owner_account_id=account_id,
            object_key=f"media/{record_id}",
            content_type="image/jpeg",
        ),
        "plan": MealPlanRecord(
            id=record_id,
            household_id=household_id,
            owner_account_id=account_id,
            week_start=date(2026, 7, 13),
        ),
        "feedback": FeedbackEventRecord(
            id=record_id,
            household_id=household_id,
            owner_account_id=account_id,
            recipe_id=uuid4(),
            raw_text="feedback",
        ),
        "rating": RatingRecord(
            id=record_id,
            household_id=household_id,
            owner_account_id=account_id,
            recipe_id=uuid4(),
            value=5,
        ),
        "conversation": Conversation(
            id=record_id,
            household_id=household_id,
            owner_account_id=account_id,
            transport="web",
        ),
        "run": AgentRun(
            id=record_id,
            conversation_id=uuid4(),
            account_id=account_id,
            household_id=household_id,
            transport="web",
            idempotency_key=f"test:{record_id}",
            status="queued",
            request_json="{}",
        ),
        "suggested_action": SuggestedActionRecord(
            id=record_id,
            token_hash=record_id.hex * 2,
            run_id=uuid4(),
            account_id=account_id,
            household_id=household_id,
            action_type="test",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        ),
        "preference": DietaryPreference(
            id=record_id,
            household_id=household_id,
            owner_account_id=account_id,
            label="vegetarian",
        ),
        "share": ShareSnapshotRecord(
            id=record_id,
            household_id=household_id,
            owner_account_id=account_id,
            token_hash=record_id.hex * 2,
            snapshot_json="{}",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    }
    async with session_factory() as session:
        session.add(records[record_kind])
        await session.commit()
        assert await IdentityRepository(session).household_has_business_records(household_id)


@pytest.mark.asyncio
async def test_invite_membership_race_maps_integrity_error_to_domain_conflict(
    identity_service, monkeypatch
) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    actor_delivery = await identity_service.request_magic_link("actor@example.com")
    actor = await identity_service.consume_magic_link(actor_delivery.token)
    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )
    original_move = IdentityRepository.move_membership_to_family

    async def raise_integrity_error(*args, **kwargs):
        raise IntegrityError("UPDATE membership", {}, Exception("unique race"))

    monkeypatch.setattr(
        IdentityRepository,
        "move_membership_to_family",
        raise_integrity_error,
        raising=False,
    )

    with pytest.raises(IdentityConflictError, match="Family invite could not be accepted"):
        await identity_service.accept_family_invite(
            HouseholdScope(actor.account.id, actor.household.id), invite.code
        )
    monkeypatch.setattr(IdentityRepository, "move_membership_to_family", original_move)
    retried = await identity_service.accept_family_invite(
        HouseholdScope(actor.account.id, actor.household.id), invite.code
    )
    assert retried.household_id == owner.household.id


@pytest.mark.asyncio
async def test_invite_acceptance_requests_both_household_locks(
    identity_service, monkeypatch
) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    actor_delivery = await identity_service.request_magic_link("actor@example.com")
    actor = await identity_service.consume_magic_link(actor_delivery.token)
    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )
    lock_requests = []

    async def record_lock_request(repository, household_ids):
        lock_requests.append(tuple(household_ids))
        households = []
        for household_id in sorted(set(household_ids), key=str):
            household = await repository.lock_household(household_id)
            if household is not None:
                households.append(household)
        return tuple(households)

    monkeypatch.setattr(IdentityRepository, "lock_households", record_lock_request, raising=False)

    await identity_service.accept_family_invite(
        HouseholdScope(actor.account.id, actor.household.id), invite.code
    )

    assert len(lock_requests) == 1
    assert set(lock_requests[0]) == {actor.household.id, owner.household.id}


class _SqlStateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


@pytest.mark.parametrize("sqlstate", ("40P01", "40001"))
@pytest.mark.asyncio
async def test_retryable_postgres_transaction_error_maps_to_domain_conflict(
    identity_service, monkeypatch, sqlstate
) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    actor_delivery = await identity_service.request_magic_link("actor@example.com")
    actor = await identity_service.consume_magic_link(actor_delivery.token)
    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )

    async def raise_retryable_error(*args, **kwargs):
        raise OperationalError("lock households", {}, _SqlStateError(sqlstate))

    monkeypatch.setattr(IdentityRepository, "lock_households", raise_retryable_error, raising=False)

    with pytest.raises(IdentityConflictError, match="Family invite could not be accepted"):
        await identity_service.accept_family_invite(
            HouseholdScope(actor.account.id, actor.household.id), invite.code
        )


@pytest.mark.asyncio
async def test_unrelated_database_error_is_not_swallowed(identity_service, monkeypatch) -> None:
    owner_delivery = await identity_service.request_magic_link("owner@example.com")
    owner = await identity_service.consume_magic_link(owner_delivery.token)
    actor_delivery = await identity_service.request_magic_link("actor@example.com")
    actor = await identity_service.consume_magic_link(actor_delivery.token)
    invite = await identity_service.create_family_invite(
        HouseholdScope(owner.account.id, owner.household.id)
    )

    async def raise_unrelated_error(*args, **kwargs):
        raise OperationalError("lock households", {}, _SqlStateError("08006"))

    monkeypatch.setattr(IdentityRepository, "lock_households", raise_unrelated_error, raising=False)

    with pytest.raises(OperationalError):
        await identity_service.accept_family_invite(
            HouseholdScope(actor.account.id, actor.household.id), invite.code
        )


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


@pytest.mark.asyncio
async def test_lark_uniqueness_race_maps_integrity_error_to_domain_conflict(
    identity_service, monkeypatch
) -> None:
    delivery = await identity_service.request_magic_link("cook@example.com")
    authenticated = await identity_service.consume_magic_link(delivery.token)
    link = await identity_service.create_lark_link_code(authenticated.account.id)

    async def raise_integrity_error(*args, **kwargs):
        raise IntegrityError("INSERT lark identity", {}, Exception("unique race"))

    monkeypatch.setattr(IdentityRepository, "create_lark_identity", raise_integrity_error)

    with pytest.raises(IdentityConflictError, match="Lark identity is already linked"):
        await identity_service.link_lark_identity(link.code, "ou_race")
    with pytest.raises(InvalidTokenError):
        await identity_service.link_lark_identity(link.code, "ou_retry")
