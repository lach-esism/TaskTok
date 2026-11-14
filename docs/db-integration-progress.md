# 三端融合（前端 + 后端 + 数据库）进度交接

更新时间：2026-11-15。所有改动都未提交。

## 目标

用户原话：“设计数据库，把业务跑通。我们要开始把三端融起来了。”
三端指前端（frontend/）、后端（task-recommender/）、数据库（SQLite）。前端设计已定稿，后端按现有前端适配，前端只改数据层。

## 运行

```bash
cd task-recommender
.venv/Scripts/python.exe scripts/run_demo.py
```

打开 `http://127.0.0.1:8000/app/`。数据库默认 `task-recommender/data/tasktok.sqlite`（已加入 .gitignore），首次启动自动播种并预置演示工作台；删掉这个文件即可重置。`TASKTOK_DB=其他路径` 换库，`TASKTOK_DB=`（空）走纯内存。

测试：`cd task-recommender && .venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider`，当前 422 passed, 9 skipped。

## 已完成（已验证）

- 数据库层 `app/db/`：schema.sql、codec.py、repository.py（增量 sync、load 重建 Store/链/计划/验收状态）、bootstrap.py（空库播种，中文名，时间线对齐到今天）。写请求成功后由中间件自动 sync。
- 市场业务层 `app/market/`（service.py + cards.py），接口都在 `/market` 下，演示身份：执行者 w0033，发包方 c_demo（显示为李洋）：
  - `GET /market/feed`：推荐流（记录曝光），未进入排序的在招任务排在后面。
  - `GET/PATCH /market/tasks/{id}`，`POST /market/tasks`（前端生成 `pub_` id；发布时按推荐结果邀请前 3 名执行者）。
  - `POST/DELETE /market/tasks/{id}/applications`：认领 / 撤回（有 request_id 时记 apply 事件）。
  - `GET /market/tasks/{id}/applicants`，`GET /market/workers/{id}/applicant`。
  - `POST /market/tasks/{id}/select`、`/decline`：选定执行者（建 Assignment，其他认领转 rejected）/ 拒绝认领。
  - `POST /market/tasks/{id}/submission`、`/simulate-delivery`：提交成果（走 AcceptanceService）。
  - `POST /market/tasks/{id}/review`：`{passed:[...]}` 验收通过（写反馈、更新信誉）或 `{decision:"rework", reason}` 返工。
  - `GET /market/work-items`、`/market/published`、`/market/me`：工作台、我发布的任务、我的/能力图谱/收入。
- 推荐理由已中文化。
- 前端数据层：`js/core/api.js`（fetch 封装、/health 探测）、`js/data/remote.js`（后端在线时替换 mock 数据，包装 flow.js 的流程函数同步到后端；离线时什么都不改）。`/app/` 挂载 frontend/。
- 浏览器走查（2026-11-15）：执行者侧 认领 → 演示选定 → 提交 → 返工 → 再提交 → 通过；发包方侧 发布 → 3 名邀请认领者 → 选定 → 模拟交付 → 返工 → 通过，前后端状态一致，控制台无报错。我的、能力图谱、收入页显示后端数据，布局正常。

## 已知问题 / 待办

- “我的”页显示的名字是发包方李洋（前端是“一端两用”同一个人），但数据来自执行者 w0033 的履历。要不要拆成两个身份待定。
- 远端 PR lach-esism/TaskTok#1（细化评价体系）合入后同步：预计 .gitignore、domain.py、main.py 的 create_app 参数有 3 处叠加式冲突；materializations 需要接入数据库持久化。
