# finance-agent

企业财务审批 Agent（架构对齐 `rag-agent` / `cs-agent`）。

覆盖完整智能审批链路：

1. 票据结构化  
2. 重复报销检测  
3. 财务制度检索（RAG）  
4. 报销标准校验  
5. 部门预算检查  
6. 风险分级  
7. 动态审批  
8. ERP 报销单提交（默认 mock）

详见 [ARCHITECTURE.md](./ARCHITECTURE.md)、**[技术方案.md](./技术方案.md)**。  
启动服务 / 查看数据库 / Docker 部署见仓库根目录 [运维指南.md](../运维指南.md)。

## 快速开始

```powershell
cd finance-agent
# 确认 .env 中 LLM_API_KEY
docker compose up -d
uv sync
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m uvicorn finance_agent.main:app --host 0.0.0.0 --port 8003 --reload --reload-dir src
```

- 前端：http://127.0.0.1:8003/
- API：http://127.0.0.1:8003/docs

建议先把 `fixtures/finance_policy.txt` 粘贴到「财务制度」页入库。

## 端口

| API | Postgres | Redis |
| --- | --- | --- |
| 8003 | 5434 | 6381 |

## 角色与界面

| 角色 | 演示账号 | 界面能力 |
| --- | --- | --- |
| 普通用户 | `zhangsan` / `123456`，`lisi` / `123456` | 提交报销、查看本人申请、制度问答 |
| 管理员 | `admin` / `admin123` | 待审批、全部单据、代提申请、制度入库、审批通过/驳回 |

登录后前端按角色切换 Tab；接口需 `Authorization: Bearer <token>`。

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/login` | 登录 |
| GET | `/auth/me` | 当前用户 |
| POST | `/expenses/submit` | 提交报销（JSON） |
| POST | `/expenses/submit-file` | 提交报销并上传发票 PDF/图片 |
| POST | `/expenses/parse-receipt` | 仅解析发票 PDF/图片 |
| POST | `/expenses/{id}/decide` | 管理员批准/驳回 |
| GET | `/expenses` | 单据列表（用户仅本人；管理员可全量/按状态） |
| GET | `/expenses/{id}` | 单据详情 |
| POST | `/chat` | 财务制度问答 |
| POST | `/documents` | 制度入库（管理员） |
| POST | `/documents/pdf` | 制度 PDF 入库（管理员） |

发票附件：PDF（优先抽文本层，无文本则 OCR）、图片（png/jpg/jpeg/webp/bmp/tif）。

### 票据一次提交与原件

- 提交必须上传原件；按文件 SHA256 + 发票号去重，同一张票不能再报。
- 原件保存在 `data/receipts/<expense_id>/`（已 gitignore）。
- `GET /expenses/{id}/receipt` 查看单张原件。
- 管理员 `GET /admin/expenses/export` 批量下载 ZIP（**forms.xlsx** + UTF-8 BOM CSV + json + receipts/）。
- 全部单据页：上报日期、已打款手动标记、删除、按状态/打款/日期/关键词筛选。

## MCP

`.cursor/mcp.json` 已加入 `finance-agent`（venv python，避免 uv 锁文件问题）。
