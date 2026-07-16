from uuid import uuid4

from recipe_agent.infrastructure.lark.crypto import ActionContextSigner, LarkCipher


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
