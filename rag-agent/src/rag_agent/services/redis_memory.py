"""短期会话记忆（Redis）。

【初学者 · 目的】
多轮对话需要「上一句说了啥」。Redis 快、带 TTL，适合会话；Postgres 另存长期审计。

【易错点】
1. 忘记 connect() 就读写 → RuntimeError。
2. key 前缀含项目名（rag-agent:session:），三项目共用一台 Redis 时靠前缀隔离；
   本仓库则用不同端口更干净。
3. TTL 到期历史清空，看起来像「机器人失忆」——属预期。
"""

import json
from typing import Any
from uuid import uuid4

import redis.asyncio as redis

from rag_agent.config import get_settings


class RedisMemory:
    """短期会话记忆：最近若干轮对话缓存在 Redis。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = redis.from_url(
                self._settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("Redis 未连接，请先调用 connect()")
        return self._client

    def new_session_id(self) -> str:
        return uuid4().hex

    def _key(self, session_id: str) -> str:
        return f"rag-agent:session:{session_id}"

    async def ping(self) -> bool:
        try:
            await self.connect()
            return bool(await self.client.ping())
        except Exception:
            return False

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        await self.connect()
        raw = await self.client.get(self._key(session_id))
        if not raw:
            return []
        data = json.loads(raw)
        return data if isinstance(data, list) else []

    async def append_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        max_turns: int = 20,
    ) -> None:
        await self.connect()
        history = await self.get_history(session_id)
        history.append({"role": role, "content": content})
        history = history[-max_turns:]
        await self.client.set(
            self._key(session_id),
            json.dumps(history, ensure_ascii=False),
            ex=self._settings.session_ttl_seconds,
        )


memory = RedisMemory()
