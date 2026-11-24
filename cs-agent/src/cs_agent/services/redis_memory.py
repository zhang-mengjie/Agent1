"""Redis 短期会话记忆 + 客服未命中计数。

【初学者 · 目的】
会话历史与「连续未命中」分两个 key，转人工阈值不污染对话 JSON。

键设计：
- cs-agent:session:{id} → 最近对话
- cs-agent:miss:{id}    → FAQ 连续未命中次数

【易错点】
1. 命中后必须 reset_miss，否则计数只增不减。
2. miss key 也要设 TTL，避免僵尸 session 永久占键。
3. 端口必须是 6380；连到 6379 会和 rag 的会话搅在一起（若同机多项目）。
"""

from __future__ import annotations

import json  # Python 标准库：JSON 序列化/反序列化，用于存储与读取会话历史
from typing import Any  # Python 标准库：任意类型标注，用于会话历史字典的值类型
from uuid import uuid4  # Python 标准库：生成 UUID，此处生成会话 ID（十六进制串）

import redis.asyncio as redis  # redis-py 异步客户端：异步连接 Redis 执行 GET/SET/INCR 等命令

from cs_agent.config import get_settings


class RedisMemory:
    """Redis 短期会话记忆：保存最近对话轮次与 FAQ 连续未命中计数。

    使用两个 key 分离存储，避免计数污染对话 JSON：
    - ``cs-agent:session:{id}``：最近若干轮对话（JSON 数组）。
    - ``cs-agent:miss:{id}``：连续未命中次数。
    两者均设置 TTL（session_ttl_seconds）避免僵尸键永久占用。

    采用懒连接：首次使用时才建立客户端连接；模块底部导出单例 ``memory``。
    """

    def __init__(self) -> None:
        """初始化实例，读取配置并置空客户端（延迟到 connect 建连）。"""
        self._settings = get_settings()
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """建立 Redis 连接（幂等）；已连接时不做任何事。"""
        if self._client is None:
            self._client = redis.from_url(
                self._settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

    async def close(self) -> None:
        """关闭 Redis 连接并置空客户端（供 lifespan 退出时调用）。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        """返回已建立的 Redis 客户端。

        Returns:
            redis.Redis: 客户端实例。

        Raises:
            RuntimeError: 尚未调用 ``connect`` 建立连接时抛出。
        """
        if self._client is None:
            raise RuntimeError("Redis 未连接")
        return self._client

    def new_session_id(self) -> str:
        """生成新的会话 ID（无连字符的 UUID 十六进制串）。"""
        return uuid4().hex

    def _session_key(self, session_id: str) -> str:
        """构造会话历史在 Redis 中的 key。"""
        return f"cs-agent:session:{session_id}"

    def _miss_key(self, session_id: str) -> str:
        """构造连续未命中计数在 Redis 中的 key。"""
        return f"cs-agent:miss:{session_id}"

    async def ping(self) -> bool:
        """探活：尝试连接并执行 PING。

        Returns:
            bool: 正常返回 True，任何异常返回 False（供 /health 使用）。
        """
        try:
            await self.connect()
            return bool(await self.client.ping())
        except Exception:
            return False

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        """读取会话的最近对话历史。

        Args:
            session_id: 会话 ID。

        Returns:
            list[dict]: 每项形如 {"role", "content"}；键不存在或数据非法时返回空列表。
        """
        await self.connect()
        raw = await self.client.get(self._session_key(session_id))
        if not raw:
            return []
        data = json.loads(raw)
        return data if isinstance(data, list) else []

    async def append_turn(
        self, session_id: str, role: str, content: str, *, max_turns: int = 20
    ) -> None:
        """向会话历史追加一轮消息，并只保留最近 max_turns 条。

        写入后重设 TTL，使活跃会话不过期。

        Args:
            session_id: 会话 ID。
            role: 角色，user 或 assistant。
            content: 消息正文。
            max_turns: 最多保留的轮次数，默认 20。
        """
        await self.connect()
        history = await self.get_history(session_id)
        history.append({"role": role, "content": content})
        history = history[-max_turns:]
        await self.client.set(
            self._session_key(session_id),
            json.dumps(history, ensure_ascii=False),
            ex=self._settings.session_ttl_seconds,
        )

    async def incr_miss(self, session_id: str) -> int:
        """把会话的连续未命中计数加一并重设 TTL。

        Args:
            session_id: 会话 ID。

        Returns:
            int: 自增后的计数值，供调用方与转人工阈值比较。
        """
        await self.connect()
        key = self._miss_key(session_id)
        val = await self.client.incr(key)
        await self.client.expire(key, self._settings.session_ttl_seconds)
        return int(val)

    async def reset_miss(self, session_id: str) -> None:
        """删除会话的连续未命中计数（FAQ 命中后必须调用，否则计数只增不减）。

        Args:
            session_id: 会话 ID。
        """
        await self.connect()
        await self.client.delete(self._miss_key(session_id))


# 全局单例：整个进程共享一个 RedisMemory 实例（懒连接）
memory = RedisMemory()
