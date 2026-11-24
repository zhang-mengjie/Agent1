"""从项目根目录 `.env` 读取配置。

【易错点】
1. 默认端口 8004。抄成 8001–8003 会和另外三个 Agent 抢端口。
2. get_settings 有缓存；改 .env 后要重启进程。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "spine-agent"
    app_env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8004

    llm_api_key: str = Field(default="", description="LLM API Key")
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.4
    llm_max_tokens: int = 4096
    llm_top_p: float = 1.0

    # 文生图与对话模型分开。密钥只用于阿里云兼容接口，不要复用 LLM_API_KEY。
    image_api_key: str = Field(default="", description="阿里云文生图 API Key")
    image_base_url: str = "https://ws-3zvfybfuh8fwmo82.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    image_model: str = "qwen-image-2.1-turbo"

    projects_dir: Path = PROJECT_ROOT / "data" / "projects"
    spine_version: str = "4.1.24"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    return settings


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
