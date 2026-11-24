import asyncio

from app.schemas.chat import ChatRequest, ChatResponse


async def chat_with_ai(request: ChatRequest) -> ChatResponse:
    await asyncio.sleep(0.5)

    if "AI Agent" in request.message:
        answer = (
            "AI Agent 可以理解为具备目标理解、任务规划、工具调用和结果反馈能力的智能体。"
        )
    elif "RAG" in request.message:
        answer = (
            "RAG 是 Retrieval Augmented Generation，也就是检索增强生成，"
            "通常用于让大模型结合企业私有知识库回答问题。"
        )
    else:
        answer = f"这是一个模拟回答：你刚才问的是「{request.message}」。"

    return ChatResponse(
        answer=answer,
        model=request.model
    )