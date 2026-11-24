"""登录与当前用户。

【初学者 · 目的】LoginRequest/UserInfo/ExpenseDecideRequest 的类型边界。
【易错点】role 只有 user|admin（约定）；action 只有 approve|reject。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserInfo(BaseModel):
    username: str
    role: str = Field(description="user | admin")
    display_name: str
    employee_id: str
    department: str


class LoginResponse(BaseModel):
    token: str
    user: UserInfo


class ExpenseDecideRequest(BaseModel):
    action: str = Field(..., description="approve | reject")
    note: str | None = Field(default=None, max_length=1000)
    submit_to_erp: bool = True


class ExpensePaidRequest(BaseModel):
    paid: bool = Field(..., description="是否已打款")
