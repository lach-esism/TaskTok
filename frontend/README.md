# TaskTok 前端

纯静态页面，不需要构建。有两种打开方式：

- **离线演示**：双击 `index.html`（file://）。全部数据来自 `js/data/mock.js`，状态存在浏览器本地。
- **接后端**：由 `task-recommender` 后端在 `/app/` 提供页面时，启动时探测 `/health`，在线就改用 `/market` 接口的数据，流程操作同时提交到后端。探测失败会自动回到离线演示。

## 目录

```text
index.html            页面结构（各视图的静态骨架 + 图标 <symbol>）
css/
  tokens.css          设计变量（颜色、圆角、字体），组件只引用语义名
  base.css            重置、排版、布局原语（.row / .wrap / .sec）
  layout.css          应用外壳：侧栏、顶栏、底部栏、视图切换
  components.css      通用组件：按钮、chip、面板、kv、表单、弹窗、toast
  pages/*.css         各页面专属样式
  utilities.css       少量工具类（间距、对齐、颜色），最后加载
js/
  core/dom.js         $ / html`` 安全模板 / ico() / 事件委托 / 格式化
  core/api.js         fetch 封装、/health 探测（file:// 下直接视为离线）
  data/mock.js        离线示例数据
  core/store.js       state、本地持久化、查询函数
  core/router.js      路由注册表、导航、hash 路由、返回栈
  core/flow.js        任务流程：认领、选定、提交、验收（通过 / 返工）的状态变化
  pages/*.js          每个页面一个文件：definePage(route, {enter, render}) + 事件
  data/remote.js      后端在线时替换示例数据，并包装 flow.js 的函数同步到后端；离线时不做任何事
  app.js              启动：先连后端，再渲染首屏
```

## 约定

- **脚本顺序即依赖顺序**。用普通 `<script>` 而不是 ES 模块，因为 file:// 下浏览器会拦截模块加载。现在的顺序是 dom → api → mock → store → router → flow → pages → remote → app，新增文件按依赖插到对应位置。
- **拼 HTML 一律用 `` html`...` ``**。插值会自动转义，避免用户输入（发布表单、搜索词）注入标签；嵌套的 `` html`` `` 和数组原样拼接。
- **事件用委托**：`onClick(selector, handler)`、`onInput(...)`。页面重绘后无需重新绑定。
- **显隐用 `hidden` 属性**，不写 `style.display`。
- **新增页面**：在 `router.js` 的 `ROUTES` 加一项（`nav:true` 才会出现在侧栏和底部栏），在 `index.html` 加 `<section class="view" id="view-xxx">`，再建 `js/pages/xxx.js` 调用 `definePage`。子页面写上 `parent`（决定导航高亮），必要时写 `up(id)`（没有上一页时返回到哪）。
- **返回按钮**用 `data-back`：回到上一页；直接打开链接时按 `up` / `parent` 回到逻辑上一级。带返回按钮的页面自动支持右滑返回。
- **任务状态只通过 `flow.js` 改**，页面不直接改 `status`。
- **演示推进**：原型没有第二个真实用户，`flow.js` 里的 `simulateDelivery`（发包方侧）和 `demoSelect` / `demoReview`（接单方侧）模拟对方的操作，页面上放在虚线框“演示”区里。接后端时 `remote.js` 会把它们转成后端的同名操作（选定、拒绝、验收、模拟交付）。

## 任务流程

| 阶段 | 发包方（发布 → 我发布的任务） | 接单方（工作台） |
|---|---|---|
| 发布 | 填标题、要求、交付物、预算、截止、验收方式和验收标准 | — |
| 认领 | 招募中：查看认领者，选定一位 | 已认领：等待选定，可取消 |
| 执行 | 执行中 | 进行中：自己勾选进度清单 |
| 提交 | 待你验收 | 上传交付物 + 说明，提交后不能改 |
| 验收 | 逐条核对验收标准：全部勾选才能通过结算；不通过必须写返工原因 | 通过 → 已完成（显示到账）；返工 → 需返工（显示原因），改完重新提交 |

- 离线演示的状态存在 `localStorage` 的 `tasktok-market-prototype-v3`，页面异常时清掉它再刷新。接后端时工作台和“我发布的任务”以后端为准，不写进本地。
