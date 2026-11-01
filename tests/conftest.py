import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/messenger_db",
)
os.environ.setdefault("SECRET_KEY", "test-secret")