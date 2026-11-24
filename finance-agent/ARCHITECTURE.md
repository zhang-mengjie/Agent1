# finance-agent 架构说明

企业财务审批 Agent：从费用申请到 ERP 报销单落单的智能审批链路。

完整方案见 **[技术方案.md](./技术方案.md)**（目标、架构、选型、数据、接口、演进）。

## 业务链路

```text
员工提交报销
   │
   ├─1. 票据结构化（receipt_parser）
   ├─2. 重复报销检测（duplicate）
   ├─3. 财务制度检索（rag / policy）
   ├─4. 报销标准校验（standards）
   ├─5. 部门预算检查（budget）
   ├─6. 风险分级（risk）
   ├─7. 动态审批路径（approval）
   └─8. ERP 报销单提交（erp，可 mock）
```

## 与现有 Agent 对齐

| 能力 | rag-agent | cs-agent | finance-agent |
| --- | --- | --- | --- |
| RAG 制度/知识 | 通用 | FAQ | 财务制度 |
| 领域流水线 | 无 | 意图+转人工 | 报销 8 步审批链 |
| API 端口 | 8001 | 8002 | 8003 |
| PG / Redis | 5432/6379 | 5433/6380 | 5434/6381 |

## 模块入口

- `agent/finance_agent.py`：审批编排 + 制度问答
- `services/*`：各审批步骤
- `api/routes.py`：HTTP
- `mcp_server.py`：Cursor MCP
