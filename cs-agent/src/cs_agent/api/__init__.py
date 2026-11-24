"""HTTP API 层：聚合 routes 中的路由并对外暴露统一的 ``router``。"""

from fastapi import APIRouter  # FastAPI：路由分组器，用于聚合子路由后挂到应用

from .routes import router as api_router

router = APIRouter()
router.include_router(api_router)
