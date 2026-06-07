from faststream.rabbit.fastapi import RabbitRouter
from main_app.key_logic.hash import get_current_user
from main_app.database.models import User
from fastapi import Depends, HTTPException
import os

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")

router = RabbitRouter(RABBITMQ_URL, tags=['help'])

@router.post("/help")
async def help_command(name: str, message: str, user: User = Depends(get_current_user)):
    await router.broker.publish(
        f"к вам обратился {name}\n с вопросом:\n {message}",
        queue="help"
    )
    return {"data": "ok"}