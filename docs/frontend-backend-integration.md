# 前后端对接方案（草案）

> 状态：方案阶段，尚未改代码。基于 2026-05 读到的 `task-recommender/app/main.py` 与 `frontend/js/**`。

## 1. 现状

**后端** `task-recommender/`：FastAPI 单进程，`create_app()` 启动时用 seed=42 合成 100 worker / 50 customer / 500 task / 3000 历史分配，全部放内存 `Store`。重启即重置。落盘的只有权重版本（`data/weights/`）、事件审计日志（`data/events/*.jsonl`，不回放）和报告。无 CORS、无鉴权、无用户体系。

**前端** `frontend/`：纯静态，普通 `<script>`（为支持 file://），数据全在 `js/data/mock.js`，状态存 `localStorage`。没有任何网络请求。

两边的业务模型对不上：前端是“接单者刷任务 → 认领 → 发包方选定 → 执行子任务 → 提交 → 验收结算”的完整市场流程；后端是“推荐引擎 + 反馈学习 + 任务链规划 + 验收评分”的算法服务，缺少市场流程需要的几个写接口。

## 2. 基础设施决策

| 问题 | 建议 | 理由 |
|---|---|---|
| 怎么跑 | 让 FastAPI 把 `frontend/` 挂到 `/app`（保留旧 `/ui`） | 同源，不用配 CORS；前端仍可 file:// 打开走 mock |
| 前端代码组织 | 新增 `js/core/api.js`（fetch 封装）+ `js/data/adapters.js`（后端 → 前端字段映射），按顺序插在 core 与 pages 之间 | 不改“普通 script”约定 |
| mock 还要不要 | 保留，`api.js` 探测 `/health` 失败就回退 mock | file:// 演示不坏 |
| 当前用户 | 固定演示身份：接单者 = 某个 `worker_id`，发包方 = 某个 `customer_id`，写在一个配置里 | 后端无登录，先不做 |
| 数据真相源 | 任务、分配、验收以后端为准；收藏、最近浏览、筛选条件继续留 localStorage | 后端没有收藏概念，也不必加 |
| 重启丢数据 | 演示阶段接受；前端不要把后端 ID 长期缓存进 localStorage，否则重启后悬空 | 持久化是另一件事 |

## 3. 字段映射：后端 Task → 前端卡片

| 前端字段 | 后端来源 | 处理 |
|---|---|---|
| `id` `title` `desc` | `task_id` `title` `description` | 直接用 |
| `cat` | `category`（12 个英文 key） | 用 `app/nlp/lexicon.py` 里已有的中文名；`CATS` 筛选项改成这 12 类 |
| `budget` `budgetNum` | `budget_min` / `budget_max` / `budget` | 显示区间“¥3,000–19,900” |
| `deadline` `hours` | `deadline` `estimated_hours` | 前端格式化 |
| `level` `levelText` | `required_level`(1–5?) / `difficulty` | 需约定映射到 L1–L4 |
| `poster` `avatar` | `customer_id` → Customer.name | 合成名是 “Customer 1”，**后端需给中文公司名** |
| `match` | 推荐返回的 `score` | `score*100` 取整；只有推荐流里有 |
| `why` | 推荐返回的 `reasons` | 现在是 `skill=0.82` 这种英文，**后端需改成中文理由**，或前端按 `breakdown` 七维自己写文案 |
| `outputs` `checks` | `requirements` / 任务链节点 | 有链时用 `/chains/{id}` 节点标题当 checks |
| `accept` `verify` | `/tasks/{id}/acceptance-spec` | **只有 `consulting_research` 有规格**，其他类别前端给默认文案 |
| `applicants` `rate` | 无 | 后端加统计（apply 事件数、历史按时率），或前端先去掉 |
| `contract` | 无 | 前端从上面字段拼出来 |
| `cover` | 无 | 前端已改为分类色块，不需要 |

## 4. 逐页对接

| 页面 | 可直接用的接口 | 缺口 | 前端要改什么 |
|---|---|---|---|
| **推荐 feed** | `POST /recommend/tasks {worker_id, top_n}` | 返回只有 `candidate_id`，要再逐个 `GET /tasks/{id}`（N+1） | 卡片数据异步加载；翻到底时再拉一批；**上报事件**：进详情=`click`，接单=`apply`，划走未操作=`ignore`，都带 `request_id` |
| **搜索** | `GET /tasks`（500 条全量） | 无服务端筛选/搜索 | 500 条量级可继续前端过滤；筛选项按后端类别和预算区间改 |
| **任务详情** | `GET /tasks/{id}`、`/tasks/{id}/acceptance-spec` | 见字段表 | “为什么推荐给你”只在从推荐流进入时有数据，否则隐藏 |
| **认领 / 工作台** | `POST /assignments`（发包方指派） | **没有“接单者申请”实体**，申请只是一条 `apply` 事件；**没有按 worker 查分配的接口** | 状态机对齐：已接受=已发 apply，进行中=存在 assignment，已完成=assignment 有 feedback/验收通过；取消认领后端无对应操作 |
| **子任务勾选** | `POST /chains/decompose`、`/chains/{id}/nodes/{n}/status` | 链只存在内存，**没有 task → chain 的查找** | checks 改为链节点；勾选写节点状态 |
| **发布** | `POST /classify`（文本 → 类别/字段）、`POST /upload/task`（文档 → 草稿 + 推荐执行者） | **没有 `POST /tasks` 创建任务**，草稿不入库，后续 decompose/plan/推荐都要 task_id | 发布第一步调 classify 自动填类别；第二步节点用 decompose 结果替换 `defaultPublishNodes`；发布后展示“推荐执行者”（`/recommend/workers`） |
| **已发布管理** | `/recommend/workers`、`/chains/{id}/plan`、`/replan` | 无“我发布的任务”列表、无修改任务接口 | 发包方在这里看候选人并点“选定”→ `POST /assignments` |
| **AI 拆解** | `/classify` + `/chains/decompose` + `/chains/{id}/plan` | 同上，需要先有 task_id | 去掉假动画里的固定节点，用真实节点、工时、依赖、关键路径、分配的 worker |
| **成果提交** | `POST /tasks/{id}/submissions {worker_id, artifacts}` | 只有调研类有机器校验；`artifacts` 要按验收规格的结构填（章节、来源、数据表） | 提交页从“随机加假文件”改为按规格逐项填写/上传；自检直接展示 `machine_record` |
| **验收结算** | `/submissions/{id}/review`、`/decision`、`POST /feedback` | 结算金额/平台费后端没有 | 发包方评分 → 决定接受/返工/驳回；接受后调 `/feedback` 触发学习；费用计算留在前端 |
| **我的** | `/workers/{id}/capability`、`/reputation`、`/resume`、`/learning-curve` | 收入序列无 | 能力图谱、信誉、学习曲线用真数据；收入图先保留 mock |
| **人机协作** | 无 | 后端明确不接 LLM | 保持演示 |

## 5. 后端需要补的接口（按优先级）

1. `POST /tasks`：创建任务入 Store（接受 classify / upload 产出的草稿），返回 task_id。发布、拆解、推荐执行者都依赖它。
2. `GET /workers/{id}/assignments`、`GET /customers/{id}/tasks`：工作台和已发布管理的列表。
3. 推荐返回里直接带任务/worker 摘要（或加 `GET /tasks?ids=...` 批量），去掉 N+1。
4. `reasons` 中文化；Customer 生成中文名。
5. `GET /tasks/{id}/chain`：按任务找最近一次拆解的链。
6. 任务列表统计：申请人数（apply 事件计数）。
7. （可选）`GET /tasks` 加 `category` / `q` / 分页参数。

## 6. 数据存储现状

后端没有业务数据库。

| 存储 | 内容 | 读写方 | 持久性 |
|---|---|---|---|
| 内存 `Store`（`app/data/store.py`） | 主服务全部业务数据：100 worker、50 customer、500 task、3000 分配及反馈/事件/曝光，另有任务链、计划版本、验收提交 | 所有业务接口 | 每次启动用 seed=42 重新生成，重启丢失一切写入 |
| `data/benchmark/task_benchmark.sqlite`（6.8 MB） | 1000 任务基准：50 customer / 100 worker / 1000 task / 1000 label / 20 rounds / 100000 recommendations | 只有 `/benchmark/*` | 离线评测库，与主服务数据无关 |
| `data/benchmark/task_benchmark_large.sqlite`（25 MB）+ `.jsonl`（35 MB） | 10000 任务大基准：500 / 1000 / 10000 / 100000 assignments | 只有离线脚本 | 同上 |
| `data/weights/*.json` | 权重版本 v0000–v0011、`active.json`、changelog | `/weights*` | 真持久，启动时读 active |
| `data/events/*.jsonl` | 事件与曝光审计日志（当前 12 条曝光） | `/events`、推荐接口追加写 | 只写不读，启动不回放 |
| `reports/*.json` | 评估报告、权重绑定 | `/metrics/*` 只读 | 脚本生成 |

上面这些文件都提交进了 git，包括 60 MB 的基准库。

对前端的影响：
- 前端发布的任务、认领、验收，在后端重启后都会消失。
- 前端不能把后端 ID 长期存进 localStorage，否则重启后会指向不存在的数据。

更新（2026-11-15）：已接入 SQLite 业务库（`app/db/`，默认 `data/tasktok.sqlite`），写入在重启后保留。前端实际对接的是 `/market/*` 业务接口，而不是下面计划里逐个调用的底层接口，接口清单和现状见 [db-integration-progress.md](db-integration-progress.md)。上表中“重启丢失一切写入”和下面两条影响已不再成立。

## 7. 实施计划

按顺序做，每一步做完就能演示，不依赖后面的步骤。“后端”“前端”指这一步要动哪一边。

**1. 环境与基线**
- 装 `requirements.txt`，`pytest tests/ -q` 跑通，记下基线结果。
- 后端：`create_app` 把 `frontend/` 挂到 `/app`；加启动脚本。
- 验收：`/app/` 打开新前端，`/ui/` 旧页面不受影响，测试不比基线差。

**2. 前端接入层**
- 前端：新增 `js/core/api.js`（fetch 封装、`/health` 探测、失败回退 mock）和 `js/data/adapters.js`（后端 Task → 前端字段，见第 3 节）。
- 前端：`config` 里固定演示身份 `worker_id` / `customer_id`；类别筛选 `CATS` 换成后端 12 类中文名。
- 验收：file:// 打开仍走 mock；`/app/` 打开时控制台能看到后端数据加载。

**3. 后端展示数据整理**
- 后端：Customer 生成中文公司名；推荐 `reasons` 改中文（按 `breakdown` 七维生成）；推荐返回带任务/worker 摘要，去掉 N+1；`GET /tasks` 加 `category` / `q` / `limit` / `offset`；任务带申请人数（apply 事件计数）。
- 补对应测试。
- 验收：`/recommend/tasks` 一次请求就能渲染卡片，理由是中文。

**4. 推荐、搜索、详情、我的改读后端**
- 前端：feed 用 `/recommend/tasks`，翻到底再拉一批；搜索用 `/tasks` 查询参数；详情用 `/tasks/{id}` + `acceptance-spec`（非调研类用默认文案）；我的用 `capability` / `reputation` / `learning-curve`，收入图保留 mock。
- 前端：feed 上报事件：进详情 `click`，接单 `apply`，划走 `ignore`，都带 `request_id`。
- 验收：`/events/metrics` 计数随操作增长；收藏和最近浏览仍在 localStorage。

**5. 接单与工作台**
- 后端：`GET /workers/{id}/assignments`（含状态和是否已反馈）；`GET /workers/{id}/applications`（来自 apply 事件）；取消申请接口。
- 前端：工作台三组改为后端状态：已接受=申请，进行中=分配，已完成=有反馈/验收通过；认领调 `apply`，取消调取消接口。
- 验收：认领后刷新页面，工作台状态不丢（后端不重启的前提下）。

**6. 发布与发包方管理**
- 后端：`POST /tasks`（接收 classify/upload 草稿，写入 Store 并刷新推荐缓存）；`GET /customers/{id}/tasks`；`PATCH /tasks/{id}`（接取截止前可改）；`GET /tasks/{id}/chain`。
- 前端：发布第一步调 `/classify` 自动填类别和字段，也支持 `/upload/task` 上传文档；第二步节点用 `/chains/decompose` 结果替换 `defaultPublishNodes`；发布调 `POST /tasks`。
- 前端：已发布页用 `/recommend/workers` 列出候选人和申请人，点“选定”调 `POST /assignments`，接单者那边任务进入“进行中”。
- 验收：发布一个任务 → 接单者推荐流能刷到 → 发包方选定 → 接单者工作台出现。

**7. AI 拆解与子任务**
- 前端：拆解页去掉固定节点和假动画，用 `/classify` → `POST /tasks` → `/chains/decompose` → `/chains/{id}/plan` 展示真实节点、工时、依赖、关键路径、规划出的执行者。
- 前端：工作台子任务清单改成链节点，勾选调 `/chains/{id}/nodes/{n}/status`；没有链的任务退回用 `requirements`。
- 验收：节点状态勾选后刷新不丢，重规划能锁住已完成节点。

**8. 提交、验收与反馈学习**
- 前端：提交页按 acceptance spec 逐项填写 `artifacts`（章节、来源、数据表），调 `/tasks/{id}/submissions`，自检展示 `machine_record`；非调研类只走人工验收。
- 前端：发包方在验收页评分 `/review` → 决定 `/decision`（接受/返工/驳回）→ 接受后调 `/feedback`；平台费和到手金额继续前端计算。
- 验收：完成一轮验收后 `/workers/{id}/reputation` 变化，推荐排序随之变化。

**9. 收尾**
- 更新 `frontend/README.md` 和 `task-recommender/README.md` 的运行方式与接口说明；全量测试；桌面端和移动端各走一遍主流程并截图检查。

## 8. 待确认

- 演示时是否需要在接单者/发包方两个身份之间切换（前端现在是“一端两用”同一个人）。
- L1–L4 与后端的映射口径：后端 `required_level` 只有 1–2，`difficulty` 是 1–5，建议按 `difficulty` 映射。
- 验收规格只覆盖调研类，其他 11 类是否先只走人工验收。
- ~~是否要在这次就接数据库（见第 6 节）。~~ 已接入。
