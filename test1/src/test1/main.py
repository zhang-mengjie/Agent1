from fastapi import FastAPI, Query
from src.test1.chat import ChatRequest, ChatResponse

app = FastAPI(
    title="AI Agent Course API",
    description="Python + FastAPI + LLM + Agent 开发实战",
    version="0.1.0",
)


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(request: ChatRequest)->ChatRequest:
    return ChatResponse(
        answer=f"你问的是：{request.message}",
        model=request.model
    )
@app.post("/health", response_model=ChatResponse, tags=["health"])
async def health(request: ChatRequest)->ChatRequest:
    return ChatResponse(
        answer=f"你问的是：{request.message}",
        model=request.model
    )