from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"

load_dotenv(env_path)


class Settings(BaseSettings):
    DEBUG_MODE: bool = Field(default=True)
    BIZ_DB_CONNECTION: str = Field(...)
    VEC_DB_CONNECTION: str = Field(...)
    # REDIS_CONNECTION: str = Field(...)
    LOGURU_LEVEL: str = Field(default="DEBUG")
    ARK_API_KEY: str = Field(...)
    DASHSCOPE_API_KEY: str = Field(...)
    # OSS_ACCESS_KEY_ID: str = Field()
    # OSS_ACCESS_KEY_SECRET: str = Field()


settings = Settings()  # type: ignore

if __name__ == "__main__":
    print(settings.model_dump_json(indent=2, exclude_none=True))
