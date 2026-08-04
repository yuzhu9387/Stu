async def test_webhook_url_verification(client):
    resp = await client.post("/api/lark/webhook", json={"type": "url_verification", "challenge": "test-challenge", "token": "test-verify-token"})
    assert resp.status_code == 200
    assert resp.json()["challenge"] == "test-challenge"


async def test_webhook_invalid_token(client):
    resp = await client.post("/api/lark/webhook", json={"type": "url_verification", "challenge": "test", "token": "wrong"})
    assert resp.status_code == 403
