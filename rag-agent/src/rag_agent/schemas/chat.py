"""对话请求/响应模型。

【初学者 · 目的】Pydantic 既做校验又生成 /docs；前端字段名必须与此一致。
【易错点】session_id 不传则每轮新会话；use_rag=false 时严格模式下仍不应瞎编业务事实。
"""

from pydantic import BaseModel, Field


class ModelParams(BaseModel):
    """单次请求可覆盖的模型参数。"""

    model: str | None = Field(default=None, description="模型名，留空用全局配置")
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=128000)
    top_p: float | None = Field(default=None, ge=0, le=1)
    base_url: str | None = Field(default=None, description="OpenAI 兼容 Base URL")
    api_key: str | None = Field(default=None, description="临时覆盖 API Key（不落库）")


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000, description="用户问题")
    session_id: str | None = Field(
        default=None,
        description="会话 ID；不传则新建，用于 Redis 短期记忆",
    )
    use_rag: bool = Field(default=True, description="是否检索知识库")
    top_k: int | None = Field(default=None, ge=1, le=20, description="RAG 检索条数")
    model_params: ModelParams = Field(default_factory=ModelParams)


class AgentChatResponse(BaseModel):
    session_id: str
    answer: str
    model: str
    used_rag: bool
    sources: list[str] = Field(default_factory=list, description="命中的知识片段摘要")
