"""配置加载的测试。

配置是「静默出错」的高发区：密钥没换、环境变量没生效、.env 读不到，
这些都不会报错，只会安静地做出错误行为。所以值得专门测。
"""

import pytest
from pydantic import ValidationError

from paper_manage.core.config import PLACEHOLDER_API_KEY, Settings


class TestApiKeyGuard:
    def test_rejects_placeholder_value(self) -> None:
        """照抄 .env.example 就部署是最常见的低级事故，必须被拦住。

        这个项目真的踩过一次：把真实 API Key 写在 .env.example 里提交到了
        公开仓库，任何人一条 curl 就能拿到。护栏至少要挡住"抄占位值"这一种。
        """
        with pytest.raises(ValidationError) as exc_info:
            Settings(api_key=PLACEHOLDER_API_KEY, database_url="postgresql+psycopg://x")

        assert "占位值" in str(exc_info.value)

    def test_accepts_a_real_key(self) -> None:
        settings = Settings(api_key="a-real-random-key", database_url="postgresql+psycopg://x")
        assert settings.api_key == "a-real-random-key"


class TestEnvPrecedence:
    def test_environment_variable_beats_env_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """同一份代码能在本地 / 容器 / CI 三处通用，靠的就是这条优先级。

        本地有 .env 文件，容器和 CI 里没有（配置全靠环境变量注入）。
        如果环境变量的优先级不是最高的，容器里就会读到过期配置。
        """
        monkeypatch.setenv("API_KEY", "from-environment")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://env-host:5432/db")

        settings = Settings()

        assert settings.api_key == "from-environment"
        assert settings.database_url == "postgresql+psycopg://env-host:5432/db"
