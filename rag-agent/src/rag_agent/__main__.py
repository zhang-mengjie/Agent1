"""允许 `python -m rag_agent` 启动 HTTP；MCP 用 `python -m rag_agent.mcp_server`。"""

from rag_agent.main import run

if __name__ == "__main__":
    run()
