async def test_create_user(client):
    resp = await client.post("/api/users", json={"name": "Alice", "lark_user_id": "lark_u1"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Alice"
    assert data["id"] is not None


async def test_get_user(client):
    resp = await client.post("/api/users", json={"name": "Bob", "lark_user_id": "lark_u2"})
    user_id = resp.json()["id"]
    resp = await client.get(f"/api/users/{user_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Bob"


async def test_get_user_not_found(client):
    resp = await client.get("/api/users/9999")
    assert resp.status_code == 404


async def test_update_user(client):
    resp = await client.post("/api/users", json={"name": "Charlie", "lark_user_id": "lark_u3"})
    user_id = resp.json()["id"]
    resp = await client.patch(f"/api/users/{user_id}", json={"name": "Charles"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Charles"
