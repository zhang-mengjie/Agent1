"""健康检查接口的响应模型。"""

from pydantic import (  # Pydantic v2：数据校验与序列化库
    BaseModel,  # 模型基类：子类自动获得字段校验与 JSON 序列化能力
    Field,  # 字段声明：配置默认值与 OpenAPI 描述
)


class HealthResponse(BaseModel):
    """GET /health 的响应体。

    Note:
        接口采用 soft-fail 策略：即使 postgres / redis 为 False，HTTP 仍返回 200。
        调用方必须检查这两个布尔字段判断依赖真实可用性。

    Attributes:
        status: 应用自身状态，固定为 "ok"。
        app: 应用名（配置 app_name）。
        postgres: PostgreSQL 当前是否可连通。
        redis: Redis 当前是否可连通。
        llm_model: 当前默认 Chat 模型名。
    """

    status: str = Field(default="ok", description="应用自身状态，固定为 ok")
    app: str = Field(description="应用名")
    postgres: bool = Field(default=False, description="PostgreSQL 是否可连通")
    redis: bool = Field(default=False, description="Redis 是否可连通")
    llm_model: str = Field(description="当前默认 Chat 模型")
