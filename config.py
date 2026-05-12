import os
from dotenv import load_dotenv

load_dotenv()  

class Settings:
    url_connection: str = os.getenv("DATABASE_URL", "postgresql://default")

    class Config():
        env_file = '.env'


settings = Settings()