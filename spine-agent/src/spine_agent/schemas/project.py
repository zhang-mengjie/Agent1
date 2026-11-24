from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    title: str = ""


class PromptRequest(BaseModel):
    prompt: str = ""
    offline: bool = False
    project_id: str | None = Field(default=None, description="第 1 步可省略，省略时新建工程")
