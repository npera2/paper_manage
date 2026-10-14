from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]

# .env.example 里的占位值。若 API_KEY 还是它，应用会拒绝启动。
PLACEHOLDER_API_KEY = "replace-with-your-own-random-string"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    database_url: str
    api_key: str

    @field_validator("api_key")
    @classmethod
    def reject_placeholder_api_key(cls, value: str) -> str:
        """拦住「照抄 .env.example 就部署」这种最常见的低级事故。

        静默的不安全比响亮的失败危险得多：这里不拦的话，服务会正常启动、
        接口也工作正常，只有等到别人拿着公开的占位值调通了你的写接口，
        你才会发现。宁可起不来。
        """
        if value == PLACEHOLDER_API_KEY:
            raise ValueError(
                f"API_KEY 还是 .env.example 里的占位值（{PLACEHOLDER_API_KEY}）。"
                "请换成自己生成的随机字符串："
                'python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return value


settings = Settings()
