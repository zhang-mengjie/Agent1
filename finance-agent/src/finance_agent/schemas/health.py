from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    postgres: bool = False
    redis: bool = False
    llm_model: str = Field(description="默认 Chat 模型")
