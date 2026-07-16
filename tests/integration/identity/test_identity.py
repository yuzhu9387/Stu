import pytest

from recipe_agent.domain.identity.service import InvalidTokenError


@pytest.mark.asyncio
async def test_consuming_magic_link_creates_one_account_and_household(identity_service) -> None:
    delivery = await identity_service.request_magic_link(" Cook@Example.COM ")
    authenticated = await identity_service.consume_magic_link(delivery.token)

    assert authenticated.account.email == "cook@example.com"
    assert authenticated.household.owner_account_id == authenticated.account.id
    assert authenticated.session_token


@pytest.mark.asyncio
async def test_magic_link_is_single_use(identity_service) -> None:
    delivery = await identity_service.request_magic_link("cook@example.com")

    await identity_service.consume_magic_link(delivery.token)

    with pytest.raises(InvalidTokenError):
        await identity_service.consume_magic_link(delivery.token)


@pytest.mark.asyncio
async def test_lark_identity_can_be_linked_with_one_time_code(identity_service) -> None:
    delivery = await identity_service.request_magic_link("cook@example.com")
    authenticated = await identity_service.consume_magic_link(delivery.token)
    link = await identity_service.create_lark_link_code(authenticated.account.id)

    identity = await identity_service.link_lark_identity(link.code, "ou_family_cook")

    assert identity.account_id == authenticated.account.id
    assert identity.open_id == "ou_family_cook"
    with pytest.raises(InvalidTokenError):
        await identity_service.link_lark_identity(link.code, "ou_other")
