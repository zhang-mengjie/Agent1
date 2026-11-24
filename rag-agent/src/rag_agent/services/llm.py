"""LLM / Embedding 工厂。

【初学者 · 目的】
- 业务代码不直接 new ChatOpenAI，统一走这里，便于换模型、换本地向量。
- Chat 与 Embedding 分离：很多网关「有 chat 无 embedding」。

【易错点】
1. base_url 漏写 /v1 → 404。
2. EMBEDDING_MODEL 写成网上随便一个名字 → FastEmbed 下载失败。
3. provider=openai 但网关返回 model group 403 → 改 local。
4. 请求里的 ModelParams 可覆盖全局；前端乱传 api_key 会打到错误账号（演示可关）。
"""

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from rag_agent.config import Settings, get_settings
from rag_agent.schemas.chat import ModelParams

# 把常见「抄错的模型名」映射到 FastEmbed 真实支持的 id
_LOCAL_MODEL_ALIASES = {
    "BAAI/base-zh-v1.5": "BAAI/bge-small-zh-v1.5",
    "BAAI/bge-base-zh-v1.5": "BAAI/bge-small-zh-v1.5",
    "bge-small-zh": "BAAI/bge-small-zh-v1.5",
    "bge-small-zh-v1.5": "BAAI/bge-small-zh-v1.5",
}


def build_chat_model(
    params: ModelParams | None = None,
    settings: Settings | None = None,
) -> ChatOpenAI:
    """按全局配置 + 单次请求覆盖构建 Chat 模型。"""
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


def _resolve_local_model_name(model_name: str) -> str:
    name = (model_name or "").strip()
    return _LOCAL_MODEL_ALIASES.get(name, name)


def build_embeddings(settings: Settings | None = None) -> Embeddings:
    cfg = settings or get_settings()
    provider = (cfg.embedding_provider or "openai").strip().lower()

    if provider == "local":
        # 延迟 import：只有 local 才需要 onnxruntime，加快纯 chat 场景启动
        from langchain_community.embeddings.fastembed import FastEmbedEmbeddings

        model_name = _resolve_local_model_name(cfg.embedding_model)
        try:
            return FastEmbedEmbeddings(model_name=model_name)
        except Exception as exc:
            raise ValueError(
                f"本地 embedding 模型不可用: {model_name}。"
                "请将 EMBEDDING_MODEL 改为 FastEmbed 支持的名称，"
                "例如 BAAI/bge-small-zh-v1.5。"
                f" 原始错误: {exc}"
            ) from exc

    return OpenAIEmbeddings(
        model=cfg.embedding_model,
        api_key=cfg.effective_embedding_api_key,
        base_url=cfg.effective_embedding_base_url,
    )


def resolve_model_name(params: ModelParams | None = None) -> str:
    """只解析展示用模型名，不发起网络请求。"""
    cfg = get_settings()
    p = params or ModelParams()
    return p.model or cfg.llm_model
