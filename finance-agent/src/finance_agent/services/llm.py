"""Chat / Embedding 工厂（与 rag/cs-agent 同构）。

【初学者 · 目的】换模型只改配置；local embedding 解决网关无向量模型组。
【易错点】模型名别名见 _ALIASES；HF_ENDPOINT 未设时首次下载易失败。
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from finance_agent.config import Settings, get_settings
from finance_agent.schemas.chat import ModelParams

_ALIASES = {
    "BAAI/base-zh-v1.5": "BAAI/bge-small-zh-v1.5",
}


def build_chat_model(params: ModelParams | None = None, settings: Settings | None = None) -> ChatOpenAI:
    cfg = settings or get_settings()
    p = params or ModelParams()
    return ChatOpenAI(
        model=p.model or cfg.llm_model,
        temperature=cfg.llm_temperature if p.temperature is None else p.temperature,
        max_tokens=cfg.llm_max_tokens if p.max_tokens is None else p.max_tokens,
        top_p=cfg.llm_top_p if p.top_p is None else p.top_p,
        api_key=p.api_key or cfg.llm_api_key,
        base_url=p.base_url or cfg.llm_base_url,
    )


def build_embeddings(settings: Settings | None = None) -> Embeddings:
    cfg = settings or get_settings()
    if (cfg.embedding_provider or "").lower() == "local":
        from langchain_community.embeddings.fastembed import FastEmbedEmbeddings

        name = _ALIASES.get(cfg.embedding_model, cfg.embedding_model)
        return FastEmbedEmbeddings(model_name=name)
    return OpenAIEmbeddings(
        model=cfg.embedding_model,
        api_key=cfg.effective_embedding_api_key,
        base_url=cfg.effective_embedding_base_url,
    )


def resolve_model_name(params: ModelParams | None = None) -> str:
    cfg = get_settings()
    p = params or ModelParams()
    return p.model or cfg.llm_model
