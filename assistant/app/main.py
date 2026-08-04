from fastapi import FastAPI
from app.routers import users, tasks, goals, habits, lark_webhook, ingestion, reports, conversation
from app.config import settings
from app.scheduler import scheduler, start_scheduler, shutdown_scheduler

app = FastAPI(title="Personal Assistant", version="0.1.0")
app.include_router(users.router)
app.include_router(tasks.router)
app.include_router(goals.router)
app.include_router(habits.router)
app.include_router(lark_webhook.router)
app.include_router(ingestion.router)
app.include_router(reports.router)
app.include_router(conversation.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def _startup_scheduler():
    if settings.enable_scheduler:
        start_scheduler()


@app.on_event("shutdown")
async def _shutdown_scheduler():
    shutdown_scheduler()
