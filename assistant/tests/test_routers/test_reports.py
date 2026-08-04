async def test_gen_daily(client):
    u = await client.post("/api/users", json={"name": "T", "lark_user_id": "lark_rr1"})
    uid = u.json()["id"]
    await client.post(f"/api/users/{uid}/tasks", json={"title": "A"})
    r = await client.post(f"/api/reports/{uid}/daily", json={"date": "2026-05-12"})
    assert r.status_code == 201 and r.json()["report_type"] == "daily"

async def test_gen_weekly(client):
    u = await client.post("/api/users", json={"name": "T", "lark_user_id": "lark_rr2"})
    r = await client.post(f"/api/reports/{u.json()['id']}/weekly", json={"week_end": "2026-05-12"})
    assert r.status_code == 201 and r.json()["report_type"] == "weekly"

async def test_list_reports(client):
    u = await client.post("/api/users", json={"name": "T", "lark_user_id": "lark_rr3"})
    uid = u.json()["id"]
    await client.post(f"/api/reports/{uid}/daily", json={"date": "2026-05-12"})
    await client.post(f"/api/reports/{uid}/daily", json={"date": "2026-05-13"})
    r = await client.get(f"/api/reports/{uid}?report_type=daily")
    assert r.status_code == 200 and len(r.json()) == 2
