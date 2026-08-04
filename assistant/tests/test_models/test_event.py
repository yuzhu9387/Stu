from app.models.event import Event
from app.models.user import User


async def test_event_persists_with_payload(session):
    user = User(name="A", lark_user_id="evt_u1")
    session.add(user)
    await session.commit()
    ev = Event(
        user_id=user.id,
        type="task_created",
        entity_type="task",
        entity_id=42,
        payload={"title": "test"},
    )
    session.add(ev)
    await session.commit()
    await session.refresh(ev)
    assert ev.id is not None
    assert ev.payload["title"] == "test"
    assert ev.created_at is not None
