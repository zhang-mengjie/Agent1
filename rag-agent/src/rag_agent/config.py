"""全局配置加载。

【初学者 · 目的】
- 把「可变运维参数」集中在一处，业务代码只调用 get_settings()。
- 用 pydantic-settings：字段名自动映射环境变量（llm_api_key → LLM_API_KEY）。

【易错点】
1. `.env` 路径用 PROJECT_ROOT 绝对值：若用相对路径，从别的 cwd 启动会读错/读不到。
2. get_settings() 有 @lru_cache：改 .env 后不重启仍是旧值 → 调用 reload_settings() 或重启。
3. embedding_dims 必须与真实模型维度一致；改维度后要重建向量表（见 services/rag.py）。
4. extra="ignore"：.env 多写未知键不会报错，但拼错变量名也会被静默忽略——改完要核对。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/rag_agent/config.py → parents[0]=rag_agent, [1]=src, [2]=项目根 rag-agent/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """全局可配置参数（.env / 环境变量）。环境变量优先于文件。"""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "rag-agent"
    app_env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    llm_api_key: str = Field(default="", description="LLM API Key")
    llm_base_url: str = Field(
        default="https://api.deepseek.com/v1",
        description="OpenAI 兼容 Base URL，通常以 /v1 结尾",
    )
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048
    llm_top_p: float = 1.0

    # openai: 走远程；local: FastEmbed。网关无 embedding 模型组时务必 local
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dims: int = 512
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    # FastEmbed 首次会从 HuggingFace 拉模型；国内建议镜像
    hf_endpoint: str = "https://hf-mirror.com"

    # 注意：asyncpg 与 psycopg 是两套驱动，URL 前缀不同，端口必须指向本项目 compose
    database_url: str = "postgresql+asyncpg://rag:rag@127.0.0.1:5432/rag_agent"
    database_url_sync: str = "postgresql+psycopg://rag:rag@127.0.0.1:5432/rag_agent"

    redis_url: str = "redis://127.0.0.1:6379/0"
    session_ttl_seconds: int = 3600

    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 80
    rag_top_k: int = 4
    # cosine distance：0=相同；超过此值的命中会被丢掉（防答非所问）
    rag_max_distance: float = 0.55
    collection_name: str = "rag_docs"
    max_pdf_bytes: int = 10 * 1024 * 1024

    @property
    def effective_embedding_api_key(self) -> str:
        # 目的：少配一项；易错：以为填了 EMBEDDING_API_KEY 其实空，实际用的是 LLM key
        return self.embedding_api_key or self.llm_api_key

    @property
    def effective_embedding_base_url(self) -> str:
        return self.embedding_base_url or self.llm_base_url


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # 让 FastEmbed/huggingface_hub 进程级读到镜像；已有环境变量则不覆盖
    if settings.hf_endpoint and not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = settings.hf_endpoint
    return settings


def reload_settings() -> Settings:
    """清缓存后重读——运维改配置后可调；日常开发直接重启更省事。"""
    get_settings.cache_clear()
    return get_settings()
