async def test_upload_screen_time(client):
    u = await client.post("/api/users", json={"name": "T", "lark_user_id": "lark_st1"})
    r = await client.post(f"/api/ingestion/screen-time/{u.json()['id']}", json={"date": "2026-05-12", "entries": [{"app": "WeChat", "minutes": 90, "category": "social"}]})
    assert r.status_code == 200 and r.json()["items_synced"] == 1

async def test_get_screen_time(client):
    u = await client.post("/api/users", json={"name": "T", "lark_user_id": "lark_st2"})
    uid = u.json()["id"]
    await client.post(f"/api/ingestion/screen-time/{uid}", json={"date": "2026-05-12", "entries": [{"app": "X", "minutes": 60, "category": "social"}]})
    r = await client.get(f"/api/ingestion/screen-time/{uid}/2026-05-12")
    assert r.status_code == 200 and r.json()["total_minutes"] == 60
