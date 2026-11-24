from pydantic import BaseModel, Field


class ModelParams(BaseModel):
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=128000)
    top_p: float | None = Field(default=None, ge=0, le=1)
    base_url: str | None = None
    api_key: str | None = None


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = None
    use_rag: bool = True
    top_k: int | None = Field(default=None, ge=1, le=20)
    model_params: ModelParams = Field(default_factory=ModelParams)


class AgentChatResponse(BaseModel):
    session_id: str
    answer: str
    model: str
    used_rag: bool
    sources: list[str] = Field(default_factory=list)
