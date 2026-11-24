"""包级启动入口：支持 ``python -m cs_agent`` 启动 HTTP 服务。

    仅当以模块方式执行时调用 ``cs_agent.main.run()``（内部启动 uvicorn）；
    被 import 时不触发。用 uvicorn / ``cs-agent`` 命令启动时不会走到本文件。
"""

from cs_agent.main import run

if __name__ == "__main__":
    run()
