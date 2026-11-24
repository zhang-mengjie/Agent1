"""全局配置：从项目根目录 `.env` 加载，可用环境变量覆盖。

【初学者 · 目的】
与 rag-agent 同构；多出的 escalate_after_misses / company_name 服务客服策略。

【易错点】
1. 默认端口 8002 / 5433 / 6380 —— 抄成 rag 的 8001/5432 会连错库还「看起来能跑」。
2. get_settings 有缓存；改 .env 要重启。
3. HF_ENDPOINT 写入 os.environ 是为了 FastEmbed 子库能读到镜像。
"""

from __future__ import annotations

import os  # Python 标准库：操作系统接口，此处用于写入 HF_ENDPOINT 环境变量
from functools import lru_cache  # Python 标准库：装饰器，缓存函数返回值（避免重复读取配置）
from pathlib import Path  # Python 标准库：面向对象的文件路径操作

from pydantic import Field  # Pydantic v2：声明字段约束与元数据（默认值、范围、description）
from pydantic_settings import (  # Pydantic Settings：基于环境变量/.env 文件的配置加载
    BaseSettings,  # 配置基类：自动把环境变量/.env 映射为类字段
    SettingsConfigDict,  # 配置元信息类：指定 env_file、编码、extra 等读取规则
)

# src/cs_agent/config.py -> 上两级为项目根 cs-agent/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """客服 Agent 的全部可配置参数。

    来源优先级：环境变量 > 项目根 ``.env`` 文件 > 类内默认值。
    字段分组：应用/服务、LLM、Embedding、数据库/Redis、RAG、客服策略。

    Attributes:
        app_name: 应用名，用于 /health 与 FastAPI 标题。
        app_env: 运行环境；等于 "dev" 时 uvicorn 开启 reload。
        api_host / api_port: HTTP 服务监听地址与端口（默认 0.0.0.0:8002）。
        llm_api_key / llm_base_url / llm_model: Chat 模型网关凭据、地址与模型名。
        llm_temperature / llm_max_tokens / llm_top_p: 模型采样参数。
        embedding_provider: "local" 用本地 FastEmbed，否则走 OpenAI 兼容网关。
        embedding_model / embedding_dims: 向量模型名与维度（须与模型一致）。
        embedding_api_key / embedding_base_url: 远程 embedding 凭据与地址。
        hf_endpoint: HuggingFace 镜像地址，写入环境变量供 FastEmbed 使用。
        database_url / database_url_sync: 异步/同步 PostgreSQL 连接串（端口 5433）。
        redis_url: Redis 连接串（端口 6380）。
        session_ttl_seconds: 会话历史与未命中计数的 TTL（秒）。
        rag_chunk_size / rag_chunk_overlap: 文本切分块大小与重叠。
        rag_top_k: 默认检索条数。
        rag_max_distance: 余弦距离上限，超过则过滤掉。
        collection_name: 逻辑集合名（仅标识，真实表为 rag_chunks）。
        max_pdf_bytes: PDF 上传大小上限（字节）。
        escalate_after_misses: 连续未命中达该次数即建议转人工。
        company_name: 客服提示词中的企业名称。
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",  # 拼错的环境变量名会被忽略——改完请对照字段核对
    )

    app_name: str = "cs-agent"
    app_env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8002

    llm_api_key: str = Field(default="", description="LLM API Key")
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    llm_top_p: float = 1.0

    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dims: int = 512
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    hf_endpoint: str = "https://hf-mirror.com"

    # 默认对接本项目 docker-compose（5433 / 6380）
    database_url: str = "postgresql+asyncpg://cs:cs@127.0.0.1:5433/cs_agent"
    database_url_sync: str = "postgresql+psycopg://cs:cs@127.0.0.1:5433/cs_agent"
    redis_url: str = "redis://127.0.0.1:6380/0"
    session_ttl_seconds: int = 3600

    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 80
    rag_top_k: int = 4
    rag_max_distance: float = 0.55
    collection_name: str = "cs_faq"
    max_pdf_bytes: int = 10 * 1024 * 1024

    # 同一会话连续 FAQ 未命中次数 ≥ 该值 → 建议转人工
    escalate_after_misses: int = 2
    company_name: str = "示例科技"

    @property
    def effective_embedding_api_key(self) -> str:
        """远程 embedding 的实际 API Key：专用 Key 为空时回退到 LLM Key。"""
        return self.embedding_api_key or self.llm_api_key

    @property
    def effective_embedding_base_url(self) -> str:
        """远程 embedding 的实际地址：专用地址为空时回退到 LLM 网关地址。"""
        return self.embedding_base_url or self.llm_base_url


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（带缓存，进程内只读取一次 .env）。

    同时把 hf_endpoint 写入 os.environ，供 FastEmbed 子库读取镜像地址。
    修改 .env 后需调用 ``reload_settings()`` 或重启进程才生效。

    Returns:
        Settings: 缓存的配置对象。
    """
    settings = Settings()
    if settings.hf_endpoint and not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = settings.hf_endpoint
    return settings


def reload_settings() -> Settings:
    """清除 ``get_settings`` 缓存并重新读取配置（供 /config 或运维接口使用）。

    Returns:
        Settings: 最新配置对象。

    Note:
        仅本函数及显式调用它的路径能看到新值；其余任一处 ``get_settings()``
        仍返回旧缓存对象，运行时改 .env 后两者可能短暂不一致。
    """
    get_settings.cache_clear()
    return get_settings()
