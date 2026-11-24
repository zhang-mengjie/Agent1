"""RAG 对话编排。

【初学者 · 目的】
把「检索 → 拼提示词 → 调模型 → 记会话」串成一次 /chat。
核心策略「严格知识库」：宁可说不知道，也不让模型用常识冒充公司制度。

【易错点】
1. 只改 SystemMessage 不够：用户消息里仍要塞摘录，并再次强调「只根据摘录」。
2. 检索为空时若仍让模型自由答 → 必现「天气/百科」幻觉（本文件专门分支禁止）。
3. session_id 为空会新建；前端要回传，否则每轮都像新会话，Redis 历史用不上。
4. 历史写入 Redis（快）+ Postgres（持久）；只写一边排障时会对不上。
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from rag_agent.schemas.chat import AgentChatRequest, AgentChatResponse
from rag_agent.services.db import save_turn
from rag_agent.services.llm import build_chat_model, resolve_model_name
from rag_agent.services.rag import format_context, retrieve
from rag_agent.services.redis_memory import memory

SYSTEM_PROMPT = """你是严格绑定本地业务知识库的中文助手。

硬性规则：
1. 只能依据本轮消息中的「知识库摘录」回答事实性问题。
2. 摘录里没有的信息，必须明确说「知识库中没有相关信息」，可以简短建议用户去哪里查，但禁止用模型自带常识补全答案（例如天气、新闻、百科）。
3. 用户问知识库有什么时，只总结摘录内容。
4. 不要声称可以联网或访问其他外部知识库。
"""


async def run_agent(
    request: AgentChatRequest,
    db: AsyncSession,
) -> AgentChatResponse:
    session_id = request.session_id or memory.new_session_id()
    model_name = resolve_model_name(request.model_params)
    llm = build_chat_model(request.model_params)

    sources: list[str] = []
    context = ""
    used_rag = False
    retrieve_error: str | None = None
    if request.use_rag:
        try:
            docs = retrieve(request.message, top_k=request.top_k)
            if docs:
                used_rag = True
                context = format_context(docs)
                sources = [
                    (d.page_content[:120] + "…") if len(d.page_content) > 120 else d.page_content
                    for d in docs
                ]
        except Exception as exc:
            used_rag = False
            retrieve_error = str(exc)

    history = await memory.get_history(session_id)
    messages: list = [SystemMessage(content=SYSTEM_PROMPT)]
    for turn in history:
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=turn["content"]))

    if context:
        user_content = (
            f"知识库摘录：\n{context}\n\n"
            f"用户问题：{request.message}\n\n"
            "只根据摘录回答。"
            "若摘录与问题无关或不含所需事实，回复：知识库中没有相关信息。"
            "禁止使用摘录之外的通用知识作答。"
        )
    elif request.use_rag and retrieve_error:
        user_content = (
            f"用户问题：{request.message}\n\n"
            f"知识库检索失败：{retrieve_error}。"
            "请如实告知无法从知识库作答，不要编造内容。"
        )
    elif request.use_rag:
        user_content = (
            f"用户问题：{request.message}\n\n"
            "知识库未检索到相关切片。"
            "请明确告知：知识库中没有相关信息。禁止用通用知识补充事实。"
        )
    else:
        user_content = (
            f"用户问题：{request.message}\n\n"
            "当前未启用知识库检索。请说明需要启用 RAG 才能基于知识库回答，不要用通用知识编造业务事实。"
        )
    messages.append(HumanMessage(content=user_content))

    result = await llm.ainvoke(messages)
    answer = result.content if isinstance(result.content, str) else str(result.content)

    await memory.append_turn(session_id, "user", request.message)
    await memory.append_turn(session_id, "assistant", answer)
    await save_turn(
        db,
        session_id=session_id,
        role="user",
        content=request.message,
        model=model_name,
        used_rag=used_rag,
    )
    await save_turn(
        db,
        session_id=session_id,
        role="assistant",
        content=answer,
        model=model_name,
        used_rag=used_rag,
    )

    return AgentChatResponse(
        session_id=session_id,
        answer=answer,
        model=model_name,
        used_rag=used_rag,
        sources=sources,
    )
