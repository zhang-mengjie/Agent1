# spine-agent

把一句角色描述做成可播放的 Spine 角色。分三步：

1. **整图**：按内容描述生成一张全身图。不满意就再生成一次。
2. **拆件**：对话模型看着这张整图，标出部件矩形和骨骼父子，再从原图裁开。
3. **动画**：按动作描述生成 Spine 4.1 的 `character.json` / `character.atlas`，并在页面里播放。

第 1 步走阿里云文生图（`IMAGE_BASE_URL` / `IMAGE_API_KEY` / `IMAGE_MODEL`）。第 2、3 步走对话模型（`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`）。两套密钥分开。没有图像密钥时，只有内置橙猫示例可以走完三步。

本服务不使用 Postgres / Redis。工程在 `data/projects/`。

## 快速开始

```powershell
cd spine-agent
copy .env.example .env
# 编辑 LLM_API_KEY（拆件和动画）和 IMAGE_API_KEY（整图）。橙猫示例不需要密钥。
uv sync
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m uvicorn spine_agent.main:app --host 0.0.0.0 --port 8004 --reload --reload-dir src
```

- 前端：http://127.0.0.1:8004/
- API 文档：http://127.0.0.1:8004/docs

Windows 不要长期用 `uv run`，它会锁住 `.venv` 里的 exe。

## 复制项目

不要把 `.venv` 打进压缩包。里面的解释器路径指向当前机器，拷走之后经常无法运行。仓库脚本会把项目写进 zip，并跳过所有名为 `.venv` 的目录。`.env` 会一起放进去：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\PJ\AI\Agent1\scripts\copy-project.ps1 -Destination D:\backup\Agent1.zip
```

也可以在任务里运行「打包项目到 zip（不含 .venv）」。解压后在各 Agent 目录执行 `uv sync`。

在新目录重建环境后再启动：

```powershell
cd spine-agent
uv sync
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m uvicorn spine_agent.main:app --host 0.0.0.0 --port 8004 --reload --reload-dir src
```

改完 `.env` 要重启进程。`get_settings` 有缓存，只保存文件不会生效。

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 探活，含模型是否已配置 |
| POST | `/api/projects` | 新建工程 |
| POST | `/api/projects/{id}/texture` | 第 1 步。`{"prompt":"...","offline":false}` |
| POST | `/api/projects/{id}/split` | 第 2 步 |
| POST | `/api/projects/{id}/animate` | 第 3 步 |
| GET | `/api/projects/{id}/export/character.json` | Spine 骨架 |
| GET | `/api/projects/{id}/export/character.atlas` | 图集 |
| GET | `/api/projects/{id}/export.zip` | json + atlas + 贴图 + 碎图 |

`offline: true` 使用内置橙猫，不调用模型。

## 自检

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\self_check.py
```

## MCP

`.cursor/mcp.json` 中的 `spine-agent` 提供 `spine_texture` / `spine_split` / `spine_animate`。

## 端口

| 服务 | API |
| --- | --- |
| rag-agent | 8001 |
| cs-agent | 8002 |
| finance-agent | 8003 |
| spine-agent | 8004 |
