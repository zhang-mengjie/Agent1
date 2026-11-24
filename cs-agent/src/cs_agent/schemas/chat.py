"""对话相关的请求/响应模型（Pydantic）。"""

from pydantic import (  # Pydantic v2：数据校验与序列化库
    BaseModel,  # 模型基类：子类自动获得字段校验、JSON 序列化能力
    Field,  # 字段声明：配置默认值、约束（ge/le/min_length）与 OpenAPI 描述
)


class ModelParams(BaseModel):
    """单次请求可覆盖的模型参数；不传的字段回退到 `.env` 全局配置。

    Attributes:
        model: 模型组名/模型名，如 deepseek-chat。
        temperature: 采样温度，范围 0~2，越高回答越发散。
        max_tokens: 单次回复的最大 token 数，范围 1~128000。
        top_p: 核采样概率阈值，范围 0~1。
        base_url: 自定义 OpenAI 兼容 API 地址。
        api_key: 自定义 API Key；传入后本次请求优先于全局配置。
    """

    model: str | None = Field(default=None, description="模型组名/模型名，如 deepseek-chat")
    temperature: float | None = Field(default=None, ge=0, le=2, description="采样温度，0~2，越高越发散")
    max_tokens: int | None = Field(default=None, ge=1, le=128000, description="单次回复最大 token 数，1~128000")
    top_p: float | None = Field(default=None, ge=0, le=1, description="核采样概率阈值，0~1")
    base_url: str | None = Field(default=None, description="自定义 OpenAI 兼容 API 地址")
    api_key: str | None = Field(default=None, description="自定义 API Key，优先于全局配置")


class AgentChatRequest(BaseModel):
    """POST /chat 的请求体。

    Attributes:
        message: 用户问题，必填，长度 1~8000 字符。
        session_id: 会话 ID；传空则服务端新建，前端应保存并复用返回值以延续多轮对话。
        customer_id: 可选客户标识，仅随对话轮次落库记录，不参与检索。
        use_rag: 是否检索 FAQ 知识库；关闭后仅靠模型自身回答。
        top_k: 本次检索返回的 FAQ 条数，范围 1~20；不传则用配置默认值。
        model_params: 单次请求覆盖的模型参数，未指定字段走全局配置。
    """

    message: str = Field(..., min_length=1, max_length=8000, description="用户问题，必填，1~8000 字符")
    session_id: str | None = Field(default=None, description="会话 ID；空则新建，前端应复用返回值")
    customer_id: str | None = Field(default=None, description="客户标识（可选，仅记录，不参与检索）")
    use_rag: bool = Field(default=True, description="是否检索 FAQ 知识库")
    top_k: int | None = Field(default=None, ge=1, le=20, description="本次检索条数，1~20；空则用配置默认值")
    model_params: ModelParams = Field(default_factory=ModelParams, description="单次模型参数覆盖，未指定则用全局配置")


class AgentChatResponse(BaseModel):
    """POST /chat 的响应体。

    Attributes:
        session_id: 本次对话的会话 ID；请求未传时由服务端新建，前端应保存复用。
        answer: 助手回复文本。
        model: 实际使用的 Chat 模型名。
        used_rag: 本次是否检索了 FAQ 知识库。
        intent: 识别到的意图，如 refund / shipping / account / other。
        need_human: 是否建议转人工；前端应据此展示转人工提示，而非解析答句。
        sources: 命中的 FAQ 摘要列表，未命中时为空。
    """

    session_id: str = Field(description="会话 ID；请求未传时由服务端新建")
    answer: str = Field(description="助手回复文本")
    model: str = Field(description="实际使用的 Chat 模型名")
    used_rag: bool = Field(description="本次是否检索了 FAQ 知识库")
    # 客服特有字段
    intent: str = Field(description="识别到的意图，如 refund/shipping/account/other")
    need_human: bool = Field(description="是否建议转人工")
    sources: list[str] = Field(default_factory=list, description="命中 FAQ 摘要，未命中为空")
