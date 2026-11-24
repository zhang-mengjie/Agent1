"""Redis：短期会话 + 部门预算键。"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import redis.asyncio as redis

from finance_agent.config import get_settings


class RedisMemory:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = redis.from_url(
                self._settings.redis_url, encoding="utf-8", decode_responses=True
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("Redis 未连接")
        return self._client

    def new_session_id(self) -> str:
        return uuid4().hex

    async def ping(self) -> bool:
        try:
            await self.connect()
            return bool(await self.client.ping())
        except Exception:
            return False

    def _key(self, session_id: str) -> str:
        return f"finance-agent:session:{session_id}"

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        await self.connect()
        raw = await self.client.get(self._key(session_id))
        if not raw:
            return []
        data = json.loads(raw)
        return data if isinstance(data, list) else []

    async def append_turn(
        self, session_id: str, role: str, content: str, *, max_turns: int = 20
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
