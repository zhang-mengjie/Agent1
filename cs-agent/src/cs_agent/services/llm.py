"""LLM / Embedding 工厂。

【初学者 · 目的】与 rag-agent 同构：Chat 走网关，Embedding 默认可 local。
【易错点】网关 403 model group → EMBEDDING_PROVIDER=local；模型名写错看别名表。
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings  # LangChain Core：Embedding 抽象基类，统一 embed_documents/embed_query 接口
from langchain_openai import (  # LangChain-OpenAI：走 OpenAI 兼容网关的实现
    ChatOpenAI,  # 聊天模型：调用 Chat Completions API
    OpenAIEmbeddings,  # 远程 Embedding：调用 Embeddings API
)

from cs_agent.config import Settings, get_settings
from cs_agent.schemas.chat import ModelParams

_LOCAL_MODEL_ALIASES = {
    "BAAI/base-zh-v1.5": "BAAI/bge-small-zh-v1.5",
    "BAAI/bge-base-zh-v1.5": "BAAI/bge-small-zh-v1.5",
}


def build_chat_model(
    params: ModelParams | None = None,
    settings: Settings | None = None,
) -> ChatOpenAI:
    """构造 Chat 模型实例（走 OpenAI 兼容网关）。

    单次请求参数优先于全局配置：params 中未指定的字段回退到 settings。

    Args:
        params: 单次请求覆盖的模型参数，None 表示全部用全局配置。
        settings: 显式配置对象，None 时从 ``get_settings()`` 获取。

    Returns:
        ChatOpenAI: 配置好的 Chat 模型，可直接 ``ainvoke``。
    """
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
    """按配置构造 Embedding 实例：local 用 FastEmbed，否则走 OpenAI 兼容网关。

    local 模式下会用 ``_LOCAL_MODEL_ALIASES`` 把别名模型名映射到实际支持的小模型。

    Args:
        settings: 显式配置对象，None 时从 ``get_settings()`` 获取。

    Returns:
        Embeddings: langchain 的 Embeddings 实现，提供 embed_documents / embed_query。
    """
    cfg = settings or get_settings()
    provider = (cfg.embedding_provider or "openai").strip().lower()
    if provider == "local":
        from langchain_community.embeddings.fastembed import FastEmbedEmbeddings  # 本地 Embedding：进程内运行，无需 API Key

        model_name = _LOCAL_MODEL_ALIASES.get(cfg.embedding_model, cfg.embedding_model)
        return FastEmbedEmbeddings(model_name=model_name)
    return OpenAIEmbeddings(
        model=cfg.embedding_model,
        api_key=cfg.effective_embedding_api_key,
        base_url=cfg.effective_embedding_base_url,
    )


def resolve_model_name(params: ModelParams | None = None) -> str:
    """解析实际使用的模型名：单次请求指定优先，否则用全局配置。

    Args:
        params: 单次请求覆盖参数，None 表示用全局配置。

    Returns:
        str: 模型名字符串，用于写入对话轮次的 model 字段与响应。
    """
    cfg = get_settings()
    p = params or ModelParams()
    return p.model or cfg.llm_model
