"""全局配置：项目根 `.env` + 环境变量。

【初学者 · 目的】
财务 Agent 在 RAG 同构配置上，增加报销标准、自动审批阈值、ERP 开关。

【易错点】
1. 端口 8003 / 5434 / 6381，勿与 rag/cs 混用。
2. AUTO_APPROVE_LIMIT 过小 → 几乎单子都进待审批；过大 → 风控形同虚设。
3. ERP_MOCK=false 却未实现真实适配器 → 提交到 ERP 步骤会失败。
4. 演示账号不在本文件，在 services/auth.py。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "finance-agent"
    app_env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8003

    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048
    llm_top_p: float = 1.0

    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dims: int = 512
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    hf_endpoint: str = "https://hf-mirror.com"

    database_url: str = "postgresql+asyncpg://fin:fin@127.0.0.1:5434/finance_agent"
    database_url_sync: str = "postgresql+psycopg://fin:fin@127.0.0.1:5434/finance_agent"
    redis_url: str = "redis://127.0.0.1:6381/0"
    session_ttl_seconds: int = 3600

    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 80
    rag_top_k: int = 4
    rag_max_distance: float = 0.55
    collection_name: str = "finance_policy"
    max_pdf_bytes: int = 10 * 1024 * 1024
    max_receipt_bytes: int = 12 * 1024 * 1024
    # 票据原件目录（相对项目根或绝对路径）
    receipt_storage_dir: str = "data/receipts"

    # --- 业务阈值（演示用，生产应来自主数据/制度系统）---
    meal_limit_per_day: float = 80
    travel_hotel_limit: float = 450
    transport_taxi_limit: float = 200
    auto_approve_limit: float = 500
    default_dept_budget: float = 20000
    company_name: str = "示例科技"
    erp_mock: bool = True

    @property
    def effective_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.llm_api_key

    @property
    def effective_embedding_base_url(self) -> str:
        return self.embedding_base_url or self.llm_base_url


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.hf_endpoint and not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = s.hf_endpoint
    return s


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
