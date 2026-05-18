from contextlib import asynccontextmanager
from fastapi import FastAPI
from database.database import engine
from database.models import Base
from routers import user, group, dialogs, uploads
from fastapi.staticfiles import StaticFiles
import subprocess
import sys


def run_migrations():
    """Применяет миграции Alembic при запуске"""
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True
        )
        print("Миграции применены успешно")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка миграций: {e.stderr}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/files", StaticFiles(directory="uploads"), name="files")

app.include_router(uploads.router)
app.include_router(user.router)
app.include_router(group.router)
app.include_router(dialogs.router)