# TaskTok — 任务分配推荐系统

本目录集中存放本次新增/生成的全部内容，已从 `AI-Research-SKILLs` skill 仓库中分离出来，独立于原有的 `01-*` ~ `22-*` 与 `0-autoresearch-skill/` skill 内容。

## 目录

```text
TaskTok/
├── task-recommender/                      # 可运行的 Task Assignment Recommender（FastAPI + 前端）
├── specs/                                 # 设计文档与任务链模板库
├── plans/                                 # Phase 1/2/3 实施计划
├── sdd/                                   # 各 Phase 的执行 ledger / 评审记录
├── 常见岗位任务链_200岗.md                 # 任务链原始资料
└── 常见岗位任务链_200岗.xlsx               # 任务链原始资料（表格）
```

## 运行

```bash
cd task-recommender
python -m pip install -r requirements.txt
python -m pytest tests/ -q
python scripts/run_demo.py
```

浏览器打开：

```text
http://127.0.0.1:8000/ui/
```

## 内容说明

- `task-recommender/`：反馈闭环、动态权重、三级个性化、任务链组合/Beam/MILP/重规划/回滚、前端演示。
- `specs/2026-11-13-task-assignment-recommender-design.md`：完整设计文档。
- `specs/task-chain-templates/`：12 类常见任务链模板与高级示例。
- `plans/`：Phase 1/2/3 实施计划。
- `sdd/`：执行过程中形成的 ledger、修复记录与 deferred minors。
- `常见岗位任务链_200岗.*`：任务链拆解机制所用的原始岗位任务链资料。

## 边界

- AI-Research-SKILLs 仓库原有的 98 个 skill 目录保持不动。
- 未引入 LLM 客户端或提示词依赖。
- 本目录内文档路径已从 `generated/...` 更新为相对本目录的路径。
