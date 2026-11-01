import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from faststream.rabbit import RabbitBroker

if __package__:
    from telegram_app.help_text import (
        HELP_QUEUE,
        HELP_REPLY_QUEUE,
        build_help_reply,
        format_help_message,
        parse_help_meta,
    )
else:
    from help_text import (
        HELP_QUEUE,
        HELP_REPLY_QUEUE,
        build_help_reply,
        format_help_message,
        parse_help_meta,
    )

load_dotenv()

ADMIN_ID = os.getenv("ADMIN_ID")
BOT_TOKEN = os.getenv("BOT_TOKEN")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
broker = RabbitBroker(RABBITMQ_URL)


@broker.subscriber(HELP_QUEUE)
async def handle_help(data: dict | str):
    text = data if isinstance(data, str) else format_help_message(data)
    await bot.send_message(
        chat_id=int(ADMIN_ID),
        text=text,
    )


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("привет lev")


@dp.message()
async def operator_reply(message: types.Message):
    if message.reply_to_message is None or not ADMIN_ID or message.chat.id != int(ADMIN_ID):
        return

    source = message.reply_to_message.text or message.reply_to_message.caption or ""
    if parse_help_meta(source) is None:
        return

    payload = build_help_reply(source, message.text)
    if payload is None:
        await message.answer("Нужен текст ответа")
        return

    await broker.publish(payload, queue=HELP_REPLY_QUEUE)
    await message.answer(f"Ответ по обращению #{payload['ticket_id']} отправлен")


async def main() -> None:
    await broker.start()
    logging.info("брокер стартовал")
    try:
        await dp.start_polling(bot)
    finally:
        await broker.close()
        logging.info("брокер остановлен")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info("запуск приложения")
    asyncio.run(main())
