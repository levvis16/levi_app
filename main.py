from contextlib import asynccontextmanager
from fastapi import FastAPI
from database.database import engine
from database.models import Base
from routers import user, group, dialogs
from fastapi.staticfiles import StaticFiles

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(user.router)
app.include_router(group.router)
app.include_router(dialogs.router)