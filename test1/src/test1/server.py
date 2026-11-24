from fastapi import FastAPI
import time

app = FastAPI(
    title="AI Agent Course API",
    description="Python + FastAPI + LLM + Agent 开发实战",
    version="0.1.0",
)

@app.get("/test")
async def test_api(msg: str) -> dict:
    return {
        "message": f"{msg}: Hello, World!"
    }

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    return {
        "user_id": user_id,
        "name": f"用户 {user_id}"
    }