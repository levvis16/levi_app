from contextlib import asynccontextmanager
from fastapi import FastAPI
from database.database import engine
from database.models import Base
from routers import dialogs, group, uploads, user, broker
from fastapi.staticfiles import StaticFiles
import asyncio

async def wait_for_rabbitmq():
    import aio_pika
    import os
    url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
    for i in range(30):
        try:
            conn = await aio_pika.connect_robust(url)
            await conn.close()
            print("RabbitMQ ready!")
            return
        except Exception:
            print(f"Waiting for RabbitMQ... attempt {i+1}/30")
            await asyncio.sleep(3)
    raise RuntimeError("RabbitMQ not available")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await wait_for_rabbitmq()
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
app.include_router(broker.router)