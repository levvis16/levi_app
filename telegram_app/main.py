import asyncio                           
import logging
import os               
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types     
from aiogram.filters import Command        
from faststream.rabbit import RabbitBroker

load_dotenv()

ADMIN_ID = os.getenv("ADMIN_ID")
BOT_TOKEN = os.getenv("BOT_TOKEN")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
broker = RabbitBroker(RABBITMQ_URL)

@broker.subscriber("help")
async def handle_help(data: str):
    await bot.send_message(
        chat_id=int(ADMIN_ID),
        text=data
    )

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("привет lev")

async def main() -> None:
    await broker.start()
    logging.info('брокер стартовал')
    try:
        await dp.start_polling(bot)
    finally:
        await broker.close()
        logging.info('брокер остановлен')

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info("запуск приложения")
    asyncio.run(main())