"""演示账号与会话鉴权（Bearer token → Redis）。

【初学者 · 目的】
教学用「内存字典账号 + Redis 会话」，避免一上来就上 OAuth/JWT 复杂度。
普通用户：提交报销、查看本人申请。
管理员：全部单据、人工审批、制度入库。

【账号保存在哪】
就在本文件 DEMO_ACCOUNTS（不是数据库、不是 .env）。

【易错点】
1. 前端必须带 Authorization: Bearer <token>；漏了会 401。
2. Redis 挂了会落到 _LOCAL_TOKENS；进程重启本地 token 全失效。
3. 改密码/加用户只改 DEMO_ACCOUNTS 后重启即可；勿以为在 Postgres 里。
4. 普通用户提交时路由会强制覆盖工号——前端改工号无效（防冒名）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Header, HTTPException

from finance_agent.config import get_settings
from finance_agent.schemas.auth import UserInfo
from finance_agent.services.redis_memory import memory

# 进程内兜底（Redis 不可用时仍可演示登录）
_LOCAL_TOKENS: dict[str, dict] = {}


@dataclass(frozen=True)
class DemoAccount:
    username: str
    password: str
    role: str
    display_name: str
    employee_id: str
    department: str


DEMO_ACCOUNTS: dict[str, DemoAccount] = {
    "zhangsan": DemoAccount(
        username="zhangsan",
        password="123456",
        role="user",
        display_name="张三",
        employee_id="E1001",
        department="研发中心",
    ),
    "lisi": DemoAccount(
        username="lisi",
        password="123456",
        role="user",
        display_name="李四",
        employee_id="E1002",
        department="销售部",
    ),
    "admin": DemoAccount(
        username="admin",
        password="admin123",
        role="admin",
        display_name="财务管理员",
        employee_id="ADMIN",
        department="财务部",
    ),
}


def account_to_user(acc: DemoAccount) -> UserInfo:
    return UserInfo(
        username=acc.username,
        role=acc.role,
        display_name=acc.display_name,
        employee_id=acc.employee_id,
        department=acc.department,
    )


def list_demo_accounts() -> list[dict]:
    return [
        {
            "username": a.username,
            "role": a.role,
            "display_name": a.display_name,
            "employee_id": a.employee_id,
            "department": a.department,
            "password_hint": a.password,
        }
        for a in DEMO_ACCOUNTS.values()
    ]


def authenticate(username: str, password: str) -> UserInfo:
    acc = DEMO_ACCOUNTS.get((username or "").strip().lower())
    if not acc or acc.password != password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return account_to_user(acc)


async def create_session(user: UserInfo) -> str:
    token = uuid4().hex
    payload = user.model_dump()
    ttl = get_settings().session_ttl_seconds
    try:
        await memory.connect()
        await memory.client.set(
            f"finance-agent:auth:{token}",
            json.dumps(payload, ensure_ascii=False),
            ex=ttl,
        )
    except Exception:
        _LOCAL_TOKENS[token] = payload
    return token


async def destroy_session(token: str) -> None:
    if not token:
        return
    _LOCAL_TOKENS.pop(token, None)
    try:
        await memory.connect()
        await memory.client.delete(f"finance-agent:auth:{token}")
    except Exception:
        pass


async def resolve_user(token: str | None) -> UserInfo | None:
    if not token:
        return None
    raw = None
    try:
        await memory.connect()
        raw = await memory.client.get(f"finance-agent:auth:{token}")
    except Exception:
        raw = None
    if raw:
        return UserInfo.model_validate(json.loads(raw))
    local = _LOCAL_TOKENS.get(token)
    if local:
        return UserInfo.model_validate(local)
    return None


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> UserInfo:
    token = _extract_bearer(authorization) or (x_auth_token or "").strip() or None
    user = await resolve_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return user


async def get_optional_user(
    authorization: Annotated[str | None, Header()] = None,
    x_auth_token: Annotated[str | None, Header(alias="X-Auth-Token")] = None,
) -> UserInfo | None:
    token = _extract_bearer(authorization) or (x_auth_token or "").strip() or None
    return await resolve_user(token)


async def require_admin(user: Annotated[UserInfo, Depends(get_current_user)]) -> UserInfo:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


CurrentUser = Annotated[UserInfo, Depends(get_current_user)]
AdminUser = Annotated[UserInfo, Depends(require_admin)]
