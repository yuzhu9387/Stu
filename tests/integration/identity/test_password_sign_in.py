"""Anyone can sign up with an email and a password; wrong passwords lock the account a while."""

from datetime import UTC, datetime, timedelta

import pytest

from recipe_agent.domain.identity.passwords import WeakPasswordError, verify_password
from recipe_agent.domain.identity.service import (
    MAX_FAILED_SIGN_INS,
    AccountExistsError,
    AccountLockedError,
    IdentityService,
    InvalidCredentialsError,
)


@pytest.mark.asyncio
async def test_signing_up_makes_an_account_with_its_own_household(identity_service) -> None:
    joined = await identity_service.register(" Cook@Example.COM ", "correct horse")
    assert joined.account.email == "cook@example.com"
    assert joined.household.owner_account_id == joined.account.id
    assert joined.session_token
    # The password itself is never stored.
    assert joined.account.password_hash != "correct horse"
    assert verify_password("correct horse", joined.account.password_hash)

    again = await identity_service.sign_in("cook@example.com", "correct horse")
    assert again.account.id == joined.account.id
    assert again.household.id == joined.household.id
    assert again.session_token != joined.session_token


@pytest.mark.asyncio
async def test_one_account_per_email_and_a_minimum_length(identity_service) -> None:
    await identity_service.register("cook@example.com", "correct horse")
    with pytest.raises(AccountExistsError):
        await identity_service.register("COOK@example.com", "another password")
    with pytest.raises(WeakPasswordError):
        await identity_service.register("new@example.com", "short")


@pytest.mark.asyncio
async def test_wrong_password_or_unknown_email_is_refused_alike(identity_service) -> None:
    await identity_service.register("cook@example.com", "correct horse")
    with pytest.raises(InvalidCredentialsError):
        await identity_service.sign_in("cook@example.com", "wrong horse")
    with pytest.raises(InvalidCredentialsError):
        await identity_service.sign_in("nobody@example.com", "correct horse")


@pytest.mark.asyncio
async def test_an_account_without_a_password_cannot_sign_in_with_one(identity_service) -> None:
    delivery = await identity_service.request_magic_link("old@example.com")
    await identity_service.consume_magic_link(delivery.token)
    with pytest.raises(InvalidCredentialsError):
        await identity_service.sign_in("old@example.com", "anything at all")


@pytest.mark.asyncio
async def test_repeated_wrong_passwords_lock_the_account_for_a_while(session_factory) -> None:
    clock = [datetime(2026, 9, 25, 12, tzinfo=UTC)]
    service = IdentityService(session_factory=session_factory, now=lambda: clock[0])
    await service.register("cook@example.com", "correct horse")
    for _ in range(MAX_FAILED_SIGN_INS):
        with pytest.raises(InvalidCredentialsError):
            await service.sign_in("cook@example.com", "wrong horse")
    # Locked: even the right password waits.
    with pytest.raises(AccountLockedError):
        await service.sign_in("cook@example.com", "correct horse")
    clock[0] += timedelta(minutes=16)
    assert (await service.sign_in("cook@example.com", "correct horse")).session_token
