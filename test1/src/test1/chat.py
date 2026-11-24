from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    model: str = Field(default="deepseek-chat", description="模型名称")
    temperature: float = Field(default=0.7, ge=0, le=2, description="温度")
    stream: bool = Field(default=False, description="是否流式输出")


class ChatResponse(BaseModel):
    answer: str = Field(..., description="AI 回答")
    model: str = Field(..., description="模型名称")