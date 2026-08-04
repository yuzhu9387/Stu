from uuid import uuid4

import pytest

from recipe_agent.infrastructure.lark.crypto import (
    ActionContextSigner,
    LarkCipher,
    LarkDecryptionError,
)


def test_lark_cipher_decrypts_aes_cbc_payload() -> None:
    encrypted = (
        "rbuYtJW6Y+aDvBzzeEs0vOZcCBKHSkc4tGgJBSMErvBbfzNfqtazfvUmi0N46nxu"
        "vJf+xHbeXR37NAW2R236ODDbRsYdE5Ef+5s+ydUKgNWKPWYJ2YZH07Q7IUIjCJjb"
    )

    payload = LarkCipher("test-encrypt-key").decrypt(encrypted)

    assert payload["header"]["event_id"] == "evt_encrypted"


def test_action_context_is_signed_and_does_not_expose_household_id() -> None:
    household_id = uuid4()
    signer = ActionContextSigner("test-signing-key")

    token = signer.dumps({"action": "save_recipe", "household_id": str(household_id)})

    assert str(household_id) not in token
    assert signer.loads(token) == {
        "action": "save_recipe",
        "household_id": str(household_id),
    }


def test_action_context_token_is_deterministic_for_persisted_claim_reconstruction() -> None:
    signer = ActionContextSigner("test-signing-key")
    values = {
        "action_id": "00000000-0000-0000-0000-000000000001",
        "account_id": "00000000-0000-0000-0000-000000000002",
        "household_id": "00000000-0000-0000-0000-000000000003",
        "source_run_id": "00000000-0000-0000-0000-000000000004",
        "action_type": "save_recipe",
        "expires_at": "2026-07-16T12:00:00Z",
    }

    assert signer.dumps(values) == signer.dumps(dict(reversed(tuple(values.items()))))


def test_invalid_action_context_has_no_sensitive_exception_chain() -> None:
    private_token = "private-consent-token"

    with pytest.raises(LarkDecryptionError) as caught:
        ActionContextSigner("test-signing-key").loads(private_token)

    assert caught.value.__cause__ is None
    assert private_token not in repr(caught.value)
