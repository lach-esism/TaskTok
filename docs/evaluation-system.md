# TaskTok 整体评价体系

> 版本：2026-11-14  
> 范围：推荐质量、任务完成度、履约能力、验收闭环，以及它们共用的属性结构。

---

## 1. 总览

整体评价体系分为四层，加一组通用元数据：

```text
L1 推荐质量（一次推荐/一批候选）
L2 任务完成度（单个已接任务）
L3 履约能力（worker 长期表现）
L4 验收（单次交付物是否达标）
```

| 层 | 评价对象 | 回答的问题 | 当前落地位置 |
|---|---|---|---|
| L1 推荐质量 | 一次推荐 / 一批候选 | 推得准不准、是否有曝光偏差 | 主应用离线评估 + 简历推送页 propensity/漏斗 |
| L2 任务完成度 | 单个已接任务 | 这单交付得怎么样 | 简历推送页「提交与评价」 |
| L3 履约能力 | worker 长期表现 | 这个人整体靠不靠谱 | 简历推送页「能力评价」 |
| L4 验收 | 单次交付物 | 是否达到验收标准 | 主应用 acceptance 闭环 |

---

## 2. L1 推荐质量

### 2.1 离线指标

| 属性 | 含义 |
|---|---|
| HR@k | Top-k 中是否命中真实答案 |
| NDCG@k | 排序质量（位置折损） |
| MRR@k | 第一个正确结果的排名倒数 |
| propensity | 该候选被展示的概率（探索策略决定） |
| IPS / SNIPS | 用 propensity 纠正曝光偏差的评估 |
| 约束违规数 | 是否破坏技能/等级/容量/违约等硬约束 |
| 校准 Brier | 预测分数与真实反馈的校准 |
| 冷启动可用性 | 是否有零历史用户可评估 |
| 延迟 | 进程内打分 p50/p95；HTTP 端点延迟单独标注 |

评估协议要求：

- train-only 特征，test 只用于评分
- 标签与特征隔离
- serving parity：评估使用与线上相同的语义模型/接受模型
- paired bootstrap 95% CI
- 未测项明确标记 `N/A`，未实现项标记 `null`

### 2.2 在线漏斗

| 事件 | 含义 |
|---|---|
| impression | 候选被曝光 |
| click / apply | 点击 / 申请 |
| accept | 接单 |
| reject / ignore | 拒绝 / 忽略 |

简历推送页使用 ε-greedy：

- 每个候选返回精确 `propensity`
- 每次预取记录 Impression
- 接单/跳过写入 accept/reject 事件
- 顶部/调试栏展示曝光、接单、跳过、池大小、召回大小

---

## 3. L2 任务完成度

### 3.1 维度与权重

| 维度 | 权重 | 自动初评 |
|---|---|---|
| 需求覆盖 | 30% | `0.7 × skill + 0.3 × customer_preference` |
| 交付质量 | 25% | `0.55 + 0.45 × 匹配分` |
| 时效 | 20% | `load` |
| 完整度 | 15% | `0.6 × expertise + 0.4 × preference` |
| 沟通 | 10% | `0.5 + 0.5 × customer_preference` |

总分 = 五维加权和（0–100）。

### 3.2 评价流程

```text
接单 → 任务进入「我的任务」（待提交，保存到 localStorage）
     → 打开「提交与评价」弹窗
     → 填写交付说明/链接
     → 查看自动初评，可拖动滑块手动调整
     → 提交并评价
     → 状态变为「已评价」
```

### 3.3 完成度属性

| 属性 | 说明 |
|---|---|
| dimensions | 五个维度分数 |
| total | 加权总分 |
| adjusted | 是否手动调整过 |
| deliverable | 交付说明/链接（必填） |
| status | accepted（待提交）/ evaluated（已评价） |
| evaluated_at | 评价时间 |
| auto | 自动初评分 |
| final | 最终提交分 |

规则：

- 只有 **已评价** 任务进入 L3 动态履约
- 待提交任务不产生履约分
- 手动调整后标记「手动」；未调整标记「自动」

---

## 4. L3 履约能力

### 4.1 静态能力（简历）

| 维度 | 权重 | 计算 |
|---|---|---|
| 技能广度 | 20% | `min(1, 识别技能数 / 8)` |
| 领域专业度 | 30% | 按类别置信度加权的 specialty |
| 经验等级 | 20% | `level / 5` |
| 领域聚焦度 | 15% | 最高领域置信度 / 全部置信度之和 |
| 简历完整度 | 15% | 技能、领域、经验、地区、远程、报酬命中比例 |

### 4.2 动态履约（模拟）

| 维度 | 权重 | 由完成度决定 |
|---|---|---|
| 一次通过率 | 30% | 总分 ≥60 且最低分项 ≥40 |
| 平均验收分 | 30% | 总分映射到 1–5 |
| 按时率 | 20% | 时效 ≥60 |
| 返工率（反向） | 10% | 总分 <55 或质量 <50 记为返工 |
| 争议率（反向） | 10% | 总分 <40 或沟通 <30 记为争议 |

没有完成度记录时，回退到按匹配分/负载的确定性模拟。

### 4.3 总分与等级

| 属性 | 规则 |
|---|---|
| 无履约样本 | 总分 = 静态分 |
| 有履约样本 | 总分 = 静态 60% + 动态 40% |
| 等级 | A ≥85 / B ≥70 / C ≥55 / D <55 |
| 优势/短板 | 全部维度排序后的 Top 2 / Bottom 2 |
| 样本数 | 已评价任务数 |
| 模拟标识 | 动态部分为模拟履约，不是真实验收 |

---

## 5. L4 验收

第一版面向 B2B 市场调研任务，10 条可执行标准：

| 标准 | 层 | 硬门槛 | 权重 |
|---|---|---|---|
| 市场规模 / 客户细分 / 竞争格局 / 进入建议章节 | 机器 | 是 | 各 0.08 |
| 至少 8 个来源，含 URL 与日期 | 机器 | 是 | 0.15 |
| 数据表含市场/规模/CAGR/来源 | 机器 | 是 | 0.10 |
| TAM ≥ SAM ≥ SOM | 机器 | 是 | 0.08 |
| 洞察与决策价值 | 客户 | 否 | 0.20 |
| 引用与结论一致 | 同行 | 否 | 0.10 |
| 截止时间前提交 | 机器 | 是 | 0.05 |

判定规则：

- accepted：无硬门槛失败且总分 ≥ 0.80
- rejected 但没有指出失败标准且总分 ≥ 0.50 → 自动转为 disputed
- 其他：rework / rejected

执行者能力指标：

- 一次通过率
- 返工率
- 争议率
- 按时率
- 平均验收分
- 标准通过率

---

## 6. 通用属性（统一 schema）

任何一层评价记录都建议带以下字段：

```json
{
  "evaluation_id": "eval_...",
  "target_type": "task_completion | ranking | worker_capability | acceptance",
  "target_id": "t0158",
  "layer": "L2",
  "dimensions": {
    "requirement_coverage": 91,
    "quality": 87,
    "timeliness": 80,
    "completeness": 75,
    "communication": 85
  },
  "weights": {
    "requirement_coverage": 0.30,
    "quality": 0.25,
    "timeliness": 0.20,
    "completeness": 0.15,
    "communication": 0.10
  },
  "total_score": 84.7,
  "grade": null,
  "status": "evaluated",
  "data_sources": ["resume", "match_features", "manual_adjustment"],
  "sample_count": 1,
  "confidence": 0.0476,
  "version": "v1",
  "simulated": false,
  "evidence": {
    "deliverable": "交付说明/链接",
    "raw_item": {}
  },
  "created_at": "2026-11-14T10:00:00Z"
}
```

| 属性 | 说明 |
|---|---|
| target_type / target_id | 评价对象 |
| layer | L1/L2/L3/L4 |
| dimensions / weights | 分项分与权重 |
| total_score | 加权总分 |
| grade | 能力层 A–D；验收层可空 |
| status | 待提交/已评价/通过/拒绝等 |
| data_sources | 简历、特征、事件、完成度、验收记录 |
| sample_count | 样本量 |
| confidence | 置信度 |
| version | 评价规则/权重版本 |
| simulated | 是否为模拟数据 |
| evidence | 交付说明、标准结果、原始 JSON |
| created_at | 评价时间 |

---

## 7. 数据流

```text
简历解析
  → 静态能力画像（L3-static）
  → 推荐曝光/接单/跳过（L1 漏斗 + 个人权重学习）
  → 接单保存「我的任务」（L2 待提交）
  → 提交交付说明 + 完成度评分（L2）
  → 已评价任务汇总（L3-dynamic）
  → 主应用验收闭环（L4）
```

---

## 8. 当前边界

- 简历推送页实现了 **L2 + L3**，并有轻量 **L1**（propensity、漏斗、个人权重）。
- **L4** 在主应用 acceptance 模块，简历页未接入。
- 简历页的动态履约、完成度是**模拟/手动**，没有真实客户验收；页面已标注。
- 简历页的漏斗计数是**服务端按该简历 worker 累计的**，同一份简历多次会话会累加。
- 离线严格评估、校准、bootstrap CI 在主应用 `evaluation_strict` 与报告中。

---

## 9. 代码位置

| 内容 | 位置 |
|---|---|
| L2/L3 评分规则 | `app/learning/capability.py` |
| 简历推送、探索、曝光/事件、个人权重 | `app/learning/resume_feed.py` |
| L1 离线严格评估 | `app/evaluation_strict.py`、`scripts/evaluate_strict.py` |
| L4 验收 | `app/acceptance/specs.py`、`checks.py`、`service.py` |
| 事件与漏斗 | `app/events.py` |
| 探索策略 | `app/learning/exploration.py` |
| 简历推送页面 | `frontend/resume-feed.html` |
| 学习过程演示 | `frontend/learning-demo.html` |

---

## 10. 查看入口

- 简历推送 / 能力评价 / 学习过程：`http://127.0.0.1:8010/ui/resume-feed.html`
- 学习过程演示：`http://127.0.0.1:8010/ui/learning-demo.html`
- 验收演示：`GET /acceptance/demo`、`POST /acceptance/demo/learning`
- 离线评估报告：`reports/strict_eval_tuned.md`、`reports/final_summary.md`
