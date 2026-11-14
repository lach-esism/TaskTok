"""Render the self-contained learning-process demo page."""

from __future__ import annotations

import json

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TaskTok · 学习过程演示</title>
<style>
  :root{
    --bg:#08111f; --panel:#101b2e; --panel-2:#142239; --line:#233552;
    --text:#e8eefc; --muted:#8ea3c4; --cyan:#4cc9f0; --green:#3ddc97;
    --violet:#a78bfa; --amber:#ffc857; --red:#ff7b7b;
  }
  *{box-sizing:border-box}
  [hidden]{display:none !important}
  html,body{margin:0;padding:0}
  body{
    background:radial-gradient(1200px 600px at 15% -10%, #14314d 0%, var(--bg) 55%) fixed;
    color:var(--text);
    font:14px/1.5 "Inter","Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;
    padding:28px clamp(14px,3vw,40px) 48px;
  }
  h1{font-size:clamp(22px,2.6vw,32px);margin:10px 0 6px;letter-spacing:.2px}
  h2{font-size:18px;margin:0 0 12px}
  h3{font-size:13px;color:var(--muted);font-weight:600;margin:0 0 8px}
  .brand{display:flex;align-items:center;gap:10px;font-weight:700;letter-spacing:.12em;font-size:13px;color:var(--muted)}
  .brand .dot{width:9px;height:9px;border-radius:50%;background:var(--cyan);box-shadow:0 0 16px var(--cyan)}
  .tag{font-size:11px;letter-spacing:.08em;padding:2px 8px;border:1px solid var(--line);border-radius:999px;color:var(--cyan)}
  .lede{color:var(--muted);max-width:920px;margin:0 0 18px}
  .scene-bar{display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;align-items:center;margin-bottom:12px}
  .scene-task{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline}
  .scene-task b{font-size:16px}
  .pill{border:1px solid var(--line);background:var(--panel);padding:3px 9px;border-radius:999px;color:var(--muted);font-size:12px}
  .round{font-variant-numeric:tabular-nums;color:var(--muted)}
  .round b{color:var(--text);font-size:18px}
  .controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:18px}
  button{
    background:var(--panel);color:var(--text);border:1px solid var(--line);
    padding:7px 13px;border-radius:9px;font:inherit;cursor:pointer;transition:.2s;
  }
  button:hover{border-color:var(--cyan);transform:translateY(-1px)}
  button.primary{background:linear-gradient(120deg,#1e6f92,#2a9d8f);border-color:transparent;font-weight:600}
  select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:6px 8px;font:inherit}
  input[type=range]{flex:1;min-width:160px;accent-color:var(--cyan)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .side{background:linear-gradient(180deg,var(--panel),#0d1728);border:1px solid var(--line);border-radius:16px;padding:16px}
  .side.worker{border-top:3px solid var(--cyan)}
  .side.customer{border-top:3px solid var(--violet)}
  .side-head{display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
  .side-title{font-weight:700;font-size:15px}
  .side-title span{font-weight:400;font-size:12px;color:var(--muted);margin-left:6px}
  .profile{display:flex;flex-wrap:wrap;gap:6px}
  .stat{display:flex;gap:5px;align-items:baseline;background:var(--panel-2);border:1px solid var(--line);border-radius:8px;padding:3px 8px;font-size:11px}
  .stat-k{color:var(--muted)}
  .stat-v{font-weight:700;font-variant-numeric:tabular-nums}
  .weights{display:grid;gap:5px;margin:0 0 14px}
  .weight-row{display:grid;grid-template-columns:72px 1fr 48px 52px;gap:8px;align-items:center;font-size:11px}
  .weight-name{color:var(--muted);white-space:nowrap}
  .weight-track{height:8px;background:#0a1424;border-radius:99px;overflow:hidden;border:1px solid #1b2b46}
  .weight-track i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,#2c7be5,#4cc9f0);transition:width .5s cubic-bezier(.2,.8,.2,1)}
  .customer .weight-track i{background:linear-gradient(90deg,#6d5bd0,#a78bfa)}
  .weight-val{text-align:right;font-variant-numeric:tabular-nums}
  .delta{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
  .delta.pos{color:var(--green)} .delta.neg{color:var(--red)}
  .feed{display:grid;gap:7px}
  .card{
    display:grid;grid-template-columns:28px 1fr 92px;gap:9px;align-items:center;
    background:var(--panel-2);border:1px solid var(--line);border-radius:11px;padding:9px 10px;
    animation:in .35s ease both;
  }
  @keyframes in{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
  .card.gold{border-color:rgba(255,200,87,.55)}
  .card.chosen{background:linear-gradient(90deg,rgba(76,201,240,.16),rgba(76,201,240,.04));border-color:rgba(76,201,240,.5)}
  .customer .card.chosen{background:linear-gradient(90deg,rgba(167,139,250,.18),rgba(167,139,250,.04));border-color:rgba(167,139,250,.5)}
  .rank{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;background:#0b1628;border:1px solid var(--line);font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}
  .card.chosen .rank{color:var(--text);border-color:var(--cyan)}
  .card-title{font-weight:600;font-size:13px;line-height:1.35}
  .card-sub{color:var(--muted);font-size:11px}
  .card-meta{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
  .badge{font-size:10px;padding:1px 6px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
  .badge.gold{color:var(--amber);border-color:rgba(255,200,87,.45)}
  .badge.chosen{color:var(--cyan);border-color:rgba(76,201,240,.45)}
  .customer .badge.chosen{color:var(--violet);border-color:rgba(167,139,250,.45)}
  .badge.up{color:var(--green)} .badge.down{color:var(--red)}
  .card-right{text-align:right}
  .score{font-variant-numeric:tabular-nums;font-size:12px;font-weight:700}
  .bar{height:5px;background:#0a1424;border-radius:99px;overflow:hidden;margin-top:5px}
  .bar i{display:block;height:100%;width:0;background:var(--cyan);border-radius:99px;transition:width .5s ease}
  .customer .bar i{background:var(--violet)}
  .chart-wrap{margin-top:14px;border-top:1px dashed var(--line);padding-top:10px}
  .chart-legend{display:flex;gap:14px;font-size:11px;color:var(--muted);margin-top:4px}
  .legend-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}
  svg.chart{width:100%;height:170px;display:block}
  .grid line{stroke:#1b2c48;stroke-width:1}
  .axis{fill:#6f86a8;font-size:10px}
  .feedback{margin:16px 0;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
  .event{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:5px 0;font-size:12px}
  .event + .event{border-top:1px dashed var(--line)}
  .event .who{color:var(--muted);min-width:64px}
  .event b{font-size:13px}
  .hit{color:var(--green);font-weight:700}
  .miss{color:var(--red);font-weight:700}
  .chip{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:7px;padding:1px 6px}
  .chip em{font-style:normal;color:var(--text)}
  .global{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;margin-top:16px}
  .charts{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .note{color:var(--muted);font-size:12px;margin:10px 0 0}
  footer{margin-top:18px;color:var(--muted);font-size:12px;line-height:1.7}
  footer code{color:#bcd2f0;background:#0b1628;border:1px solid var(--line);border-radius:5px;padding:1px 5px}
  .variables{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-bottom:14px}
  .variables .var-head{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-bottom:10px}
  .variables .var-title{font-weight:700}
  .variables .var-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
  .variables label{display:grid;gap:4px;font-size:11px;color:var(--muted)}
  .variables select{width:100%}
  .tag-effect{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;font-size:11px}
  .tag-effect .effect{background:var(--panel-2);border:1px solid var(--line);border-radius:8px;padding:3px 8px;color:var(--muted)}
  .tag-effect .effect b{color:var(--text)}
  .case-wall{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;margin-top:16px}
  .case-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
  .case-card{background:var(--panel-2);border:1px solid var(--line);border-radius:11px;padding:10px}
  .case-card .case-cat{font-size:10px;color:var(--cyan);letter-spacing:.06em}
  .case-card .case-title{font-weight:600;font-size:12px;margin:3px 0 2px;line-height:1.35}
  .case-card .case-sub{color:var(--muted);font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .case-ranks{display:flex;gap:6px;margin-top:6px;font-size:10px;color:var(--muted)}
  .case-ranks span{background:#0b1628;border:1px solid var(--line);border-radius:6px;padding:1px 5px;font-variant-numeric:tabular-nums}
  .case-ranks b{color:var(--text)}
  .spark{width:100%;height:34px;display:block;margin-top:6px}
  .custom{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;margin-top:16px}
  .custom-head{display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;margin-bottom:12px}
  .mode-tabs{display:flex;gap:6px}
  .mode-tabs button{padding:5px 11px;font-size:12px}
  .mode-tabs button.active{border-color:var(--cyan);color:var(--cyan)}
  .custom-form{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .custom-form .field{display:grid;gap:4px;font-size:11px;color:var(--muted)}
  .custom-form .field input,.custom-form .field select{background:var(--panel-2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:6px 8px;font:inherit;font-size:12px;width:100%}
  .custom-form .wide{grid-column:1/-1}
  .chips{display:flex;flex-wrap:wrap;gap:5px}
  .chip-toggle{cursor:pointer;font-size:11px;border:1px solid var(--line);border-radius:99px;padding:2px 8px;color:var(--muted);background:var(--panel-2);transition:.15s}
  .chip-toggle.active{border-color:var(--cyan);color:var(--cyan);background:rgba(76,201,240,.12)}
  .custom-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center}
  .custom-error{color:var(--red);font-size:12px;margin-top:8px}
  .custom-note{color:var(--muted);font-size:11px;margin-top:8px}
  .custom-result{margin-top:14px;border-top:1px dashed var(--line);padding-top:12px}
  .custom-feed{display:grid;gap:7px;margin-top:8px}
  .custom-card{display:grid;grid-template-columns:28px 1fr 92px auto;gap:9px;align-items:center;background:var(--panel-2);border:1px solid var(--line);border-radius:11px;padding:9px 10px}
  .custom-card .pick{background:linear-gradient(120deg,#1e6f92,#2a9d8f);border-color:transparent;font-size:11px;padding:4px 9px}
  .custom-weights{display:grid;gap:5px;margin-top:10px}
  .spark path{stroke-linecap:round;stroke-linejoin:round;fill:none}
  @media (max-width:1100px){
    .case-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  }
  @media (max-width:900px){
    .grid,.charts,.variables .var-grid,.custom-form{grid-template-columns:1fr}
    .weight-row{grid-template-columns:64px 1fr 44px 48px}
    .case-grid{grid-template-columns:1fr}
  }
</style>
</head>
<body>
<header>
  <div class="brand"><span class="dot"></span> TASKTOK <span class="tag">LEARNING DEMO</span> <a class="tag" style="text-decoration:none" href="/ui/resume-feed.html">简历推送演示 →</a></div>
  <h1>同一场景，两端是怎么学会的</h1>
  <p class="lede">左边是 <b>接单端</b> 刷到的任务，右边是 <b>任务端</b> 收到的工人推荐。每一轮，双方各自做出选择、评分；系统用真实学习器更新七维权重，下一次推荐随之变化。</p>
</header>

<section class="stage">
  <div class="scene-bar">
    <div class="scene-task">
      <b id="scene-title"></b>
      <span class="pill" id="scene-task-meta"></span>
    </div>
    <div class="round">第 <b id="round-no">1</b> / <span id="round-total"></span> 轮</div>
  </div>
  <div class="variables">
    <div class="var-head">
      <div class="var-title">初始标签 <span class="pill">只改变起点，学习后回到真实偏好</span></div>
      <div class="pill" id="scenario-label"></div>
    </div>
    <div class="var-grid">
      <label>接单领域
        <select id="domain-select"></select>
      </label>
      <label>worker 偏好
        <select id="worker-pref-select"></select>
      </label>
      <label>customer 偏好
        <select id="customer-pref-select"></select>
      </label>
    </div>
    <div class="tag-effect" id="tag-effect"></div>
  </div>
  <div class="controls">
    <button id="prev" title="上一轮">上一轮</button>
    <button id="play" class="primary">播放</button>
    <button id="next" title="下一轮">下一轮</button>
    <button id="reset">重置</button>
    <label class="pill">速度
      <select id="speed">
        <option value="0.75">0.75×</option>
        <option value="1" selected>1×</option>
        <option value="1.5">1.5×</option>
        <option value="2">2×</option>
      </select>
    </label>
    <input type="range" id="scrub" min="0" value="0">
  </div>
</section>

<main class="grid">
  <section class="side worker">
    <div class="side-head">
      <div>
        <div class="side-title">接单端 <span>worker 刷到的单子</span></div>
        <div class="pill" id="worker-name"></div>
      </div>
      <div class="profile" id="worker-profile"></div>
    </div>
    <div class="weights" id="worker-weights"></div>
    <div class="feed" id="worker-feed"></div>
    <div class="chart-wrap">
      <h3>学习曲线（累计）</h3>
      <svg class="chart" id="worker-chart"></svg>
      <div class="chart-legend">
        <span><i class="legend-dot" style="background:#4cc9f0"></i>累计命中率</span>
        <span><i class="legend-dot" style="background:#3ddc97"></i>与真实偏好 cosine</span>
        <span><i class="legend-dot" style="background:#6f86a8"></i>虚线：无标签基线</span>
      </div>
    </div>
  </section>

  <section class="side customer">
    <div class="side-head">
      <div>
        <div class="side-title">任务端 <span>客户收到的工人推荐</span></div>
        <div class="pill" id="customer-name"></div>
      </div>
      <div class="profile" id="customer-profile"></div>
    </div>
    <div class="weights" id="customer-weights"></div>
    <div class="feed" id="customer-feed"></div>
    <div class="chart-wrap">
      <h3>学习曲线（累计）</h3>
      <svg class="chart" id="customer-chart"></svg>
      <div class="chart-legend">
        <span><i class="legend-dot" style="background:#a78bfa"></i>累计命中率</span>
        <span><i class="legend-dot" style="background:#3ddc97"></i>与真实偏好 cosine</span>
        <span><i class="legend-dot" style="background:#6f86a8"></i>虚线：无标签基线</span>
      </div>
    </div>
  </section>
</main>

<section class="feedback" id="feedback"></section>

<section class="case-wall">
  <div class="side-head">
    <div>
      <div class="side-title">案例墙 <span>8 个跨领域案例，证明不是个例</span></div>
    </div>
    <div class="pill">首轮 → 末轮真实答案排名</div>
  </div>
  <div class="case-grid" id="case-wall"></div>
</section>

<section class="custom">
  <div class="custom-head">
    <div>
      <div class="side-title">自定义案例 <span>输入任务或 worker 画像，逐轮点选，服务器更新权重</span></div>
    </div>
    <div class="mode-tabs">
      <button class="active" data-mode="task">发布任务</button>
      <button data-mode="worker">接单画像</button>
    </div>
  </div>
  <div class="custom-form">
    <div class="field" data-modes="task">任务标题
      <input id="custom-title" value="品牌短视频投放">
    </div>
    <div class="field" data-modes="task">领域
      <select id="custom-category"></select>
    </div>
    <div class="field" data-modes="task">预算（元）
      <input id="custom-budget" type="number" value="8000">
    </div>
    <div class="field" data-modes="task">截止天数
      <input id="custom-deadline" type="number" value="14">
    </div>
    <div class="field" data-modes="task">难度
      <select id="custom-difficulty"></select>
    </div>
    <div class="field" data-modes="task">技能等级
      <select id="custom-skill-level"></select>
    </div>
    <div class="field" data-modes="worker">名称
      <input id="custom-worker-name" value="自建画像">
    </div>
    <div class="field" data-modes="worker">期望报酬（元）
      <input id="custom-pay" type="number" value="7000">
    </div>
    <div class="field" data-modes="worker">当前负载（小时）
      <input id="custom-load" type="number" value="4">
    </div>
    <div class="field" data-modes="worker">地区
      <select id="custom-region"></select>
    </div>
    <div class="field wide">技能标签 <span class="muted">（点选，最多 3 个）</span>
      <div class="chips" id="custom-skills"></div>
    </div>
    <div class="field wide" data-modes="worker">偏好领域
      <div class="chips" id="custom-preferred-categories"></div>
    </div>
    <div class="field wide">偏好标签
      <div class="chips" id="custom-preferences"></div>
    </div>
  </div>
  <div class="custom-actions">
    <button class="primary" id="custom-start">开始模拟</button>
    <button id="custom-reset">重新开始</button>
    <span class="pill" id="custom-status">等待输入</span>
  </div>
  <div class="custom-error" id="custom-error"></div>
  <p class="custom-note">输入只发送到本机接口，不落库；自定义案例没有 ground truth，因此不显示命中率。</p>
  <div class="custom-result" id="custom-result" hidden>
    <div class="side-head">
      <div class="side-title">第 <span id="custom-round">1</span> 轮</div>
      <div class="profile" id="custom-profile"></div>
    </div>
    <div class="custom-feed" id="custom-feed"></div>
    <div class="custom-weights" id="custom-weights"></div>
    <div class="tag-effect" id="custom-effect"></div>
  </div>
</section>

<section class="global">
  <h2>全局 20 轮：学习组 vs 对照组</h2>
  <div class="charts">
    <div>
      <h3>Top-1 准确率</h3>
      <svg class="chart" id="global-top1"></svg>
    </div>
    <div>
      <h3>Top-5 准确率</h3>
      <svg class="chart" id="global-top5"></svg>
    </div>
  </div>
  <div class="chart-legend" style="margin-top:8px">
    <span><i class="legend-dot" style="background:#3ddc97"></i>学习组</span>
    <span><i class="legend-dot" style="background:#8ea3c4"></i>对照组（不学习）</span>
  </div>
  <p class="note" id="global-note"></p>
</section>

<footer>
  <div><b>口径</b>：排分与权重更新走真实代码路径（<code>RecommendationService.features_for</code> → <code>fuse_scores</code> → <code>OnlineWeightLearner.update_pair</code> → <code>project_weights</code>）。人类的点选/验收由隐藏偏好模拟生成，用于展示学习方向，不代表线上效果。</div>
  <div id="meta-note"></div>
</footer>

<script>
window.__DEMO_DATA__ = __DEMO_DATA_JSON__;

(function () {
  "use strict";
  const DATA = window.__DEMO_DATA__;
  const scenarios = DATA.scenarios;
  let activeKey = DATA.baseline_key;
  let workerRounds = scenarios[activeKey].worker.rounds;
  let customerRounds = scenarios[activeKey].customer.rounds;
  const total = workerRounds.length;
  const WEIGHT_LABELS = {
    reputation: "信誉",
    skill: "技能",
    expertise: "专业度",
    collaborative: "协同",
    preference: "历史偏好",
    load: "负载",
    customer_preference: "客户偏好"
  };
  const state = { index: 0, playing: false, timer: null, speed: 1 };

  const $ = (selector) => document.querySelector(selector);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const fmt = (value, digits) => (value === null || value === undefined)
    ? "—" : Number(value).toFixed(digits === undefined ? 3 : digits);
  const pct = (value) => (value === null || value === undefined)
    ? "—" : (Number(value) * 100).toFixed(1) + "%";

  function previousRank(rounds, id) {
    if (state.index <= 0) return null;
    const item = rounds[state.index - 1].feed.find((entry) => entry.id === id);
    return item ? item.rank : null;
  }

  function renderFeed(container, round, rounds) {
    container.textContent = "";
    const maxScore = Math.max.apply(null, round.feed.map((item) => item.score).concat([1e-9]));
    round.feed.forEach((item, index) => {
      const card = el("article", "card");
      if (item.is_gold) card.classList.add("gold");
      if (item.is_chosen) card.classList.add("chosen");
      card.style.animationDelay = index * 25 + "ms";

      card.appendChild(el("div", "rank", item.rank));
      const body = el("div", "card-body");
      body.appendChild(el("div", "card-title", item.title));
      body.appendChild(el("div", "card-sub", item.subtitle || ""));
      const meta = el("div", "card-meta");
      if (item.is_gold) meta.appendChild(el("span", "badge gold", "真实最合适"));
      if (item.is_chosen) {
        const label = round.hit && item.is_gold ? "选中 · 命中" : "选中";
        meta.appendChild(el("span", "badge chosen", label));
      }
      const before = previousRank(rounds, item.id);
      if (before !== null && before !== item.rank) {
        const movedUp = item.rank < before;
        meta.appendChild(el(
          "span",
          "badge " + (movedUp ? "up" : "down"),
          (movedUp ? "↑ 从 #" : "↓ 从 #") + before
        ));
      }
      if (meta.childNodes.length) body.appendChild(meta);
      card.appendChild(body);

      const right = el("div", "card-right");
      right.appendChild(el("div", "score", fmt(item.score)));
      const bar = el("div", "bar");
      const fill = el("i");
      fill.style.width = "0%";
      bar.appendChild(fill);
      right.appendChild(bar);
      card.appendChild(right);
      container.appendChild(card);

      fill.style.width = Math.max(4, (item.score / maxScore) * 100) + "%";
    });
  }

  function renderWeights(container, round) {
    container.textContent = "";
    Object.keys(WEIGHT_LABELS).forEach(function (key) {
      const value = round.weights_after[key];
      const delta = round.delta[key] || 0;
      const row = el("div", "weight-row");
      row.appendChild(el("div", "weight-name", WEIGHT_LABELS[key]));
      const track = el("div", "weight-track");
      const fill = el("i");
      fill.style.width = "0%";
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("div", "weight-val", fmt(value, 3)));
      const deltaClass = delta > 0.0005 ? "delta pos" : (delta < -0.0005 ? "delta neg" : "delta");
      row.appendChild(el("div", deltaClass, (delta > 0 ? "+" : "") + fmt(delta, 3)));
      container.appendChild(row);
      fill.style.width = Math.max(2, (value / 0.45) * 100) + "%";
    });
  }

  function renderProfile(container, profile, side) {
    container.textContent = "";
    const entries = side === "worker" ? [
      ["评分", profile.rating === null ? "—" : fmt(profile.rating, 2)],
      ["已完成", profile.completed],
      ["模拟接单", profile.accepted],
      ["模拟收入", "¥" + Math.round(profile.simulated_earnings)]
    ] : [
      ["已选人", profile.selections],
      ["最近验收", fmt(profile.last_acceptance, 1)],
      ["平均验收", fmt(profile.avg_acceptance, 2)],
      ["样本", profile.samples]
    ];
    entries.forEach(function (entry) {
      const chip = el("div", "stat");
      chip.appendChild(el("span", "stat-k", entry[0]));
      chip.appendChild(el("span", "stat-v", entry[1]));
      container.appendChild(chip);
    });
  }

  function topDeltas(round) {
    return Object.keys(round.delta)
      .map(function (key) { return [key, round.delta[key]]; })
      .sort(function (a, b) { return Math.abs(b[1]) - Math.abs(a[1]); })
      .slice(0, 2);
  }

  function renderFeedback(workerRound, customerRound) {
    const box = $("#feedback");
    box.textContent = "";
    box.appendChild(el("h2", null, "本轮反馈 → 权重更新"));
    const events = [
      ["接单端", "worker 选择", workerRound],
      ["任务端", "customer 选择", customerRound]
    ];
    events.forEach(function (entry) {
      const who = entry[0];
      const action = entry[1];
      const round = entry[2];
      const chosenItem = round.feed.find(function (item) {
        return item.id === round.chosen;
      });
      const line = el("div", "event");
      line.appendChild(el("span", "who", who));
      line.appendChild(el("span", null, action + "："));
      line.appendChild(el("b", null, chosenItem ? chosenItem.title : round.chosen));
      line.appendChild(el(
        "span",
        round.hit ? "hit" : "miss",
        round.hit ? "命中真实最合适" : (round.gold_shown ? "未命中（真实答案排 #" + round.gold_rank + "）" : "未命中（真实答案还没进 Top-5）")
      ));
      topDeltas(round).forEach(function (pair) {
        const chip = el("span", "chip");
        chip.appendChild(document.createTextNode(WEIGHT_LABELS[pair[0]] + " "));
        const value = el("em", null, (pair[1] > 0 ? "+" : "") + fmt(pair[1], 3));
        chip.appendChild(value);
        line.appendChild(chip);
      });
      box.appendChild(line);
    });
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  function makeSvg(tag, attributes) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.keys(attributes || {}).forEach(function (key) {
      node.setAttribute(key, attributes[key]);
    });
    return node;
  }

  function drawChart(svg, series, maxX) {
    const width = 560, height = 190;
    const pad = { left: 42, right: 14, top: 14, bottom: 24 };
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const xMax = Math.max(1, maxX === undefined ? 1 : maxX);
    const x = function (value) {
      return pad.left + (value / xMax) * (width - pad.left - pad.right);
    };
    const y = function (value) {
      return pad.top + (1 - value) * (height - pad.top - pad.bottom);
    };
    [0, 0.25, 0.5, 0.75, 1].forEach(function (value) {
      svg.appendChild(makeSvg("line", {
        x1: pad.left, x2: width - pad.right, y1: y(value), y2: y(value), class: "grid"
      }));
      const label = makeSvg("text", {
        x: pad.left - 7, y: y(value) + 4, class: "axis", "text-anchor": "end"
      });
      label.textContent = Math.round(value * 100) + "%";
      svg.appendChild(label);
    });
    series.forEach(function (entry) {
      if (!entry.values.length) return;
      const path = entry.values.map(function (value, index) {
        return (index === 0 ? "M" : "L") + x(index).toFixed(1) + "," + y(value).toFixed(1);
      }).join(" ");
      svg.appendChild(makeSvg("path", {
        d: path,
        fill: "none",
        stroke: entry.color,
        "stroke-width": entry.width || 2.5,
        "stroke-dasharray": entry.dash || "",
        "stroke-linecap": "round",
        "stroke-linejoin": "round"
      }));
      const last = entry.values.length - 1;
      if (last >= 0) {
        svg.appendChild(makeSvg("circle", {
          cx: x(last), cy: y(entry.values[last]), r: 4, fill: entry.color
        }));
      }
    });
    const first = makeSvg("text", {
      x: pad.left, y: height - 7, class: "axis", "text-anchor": "start"
    });
    first.textContent = "第 1 轮";
    svg.appendChild(first);
    const lastLabel = makeSvg("text", {
      x: width - pad.right, y: height - 7, class: "axis", "text-anchor": "end"
    });
    lastLabel.textContent = "第 " + total + " 轮";
    svg.appendChild(lastLabel);
  }

  function drawGlobalCharts() {
    const learning = DATA.global.learning_rounds || {};
    const top1 = $("#global-top1");
    const top5 = $("#global-top5");
    const available = Array.isArray(learning.learning_top1) && learning.learning_top1.length > 0;
    $("#global-note").textContent = available
      ? "数据来自 reports/learning_rounds.json（20 个客户 × 每轮 50 次选择 × 20 轮）。"
      : "未找到 reports/learning_rounds.json，图表为空。";
    if (!available) {
      drawChart(top1, [], 0);
      drawChart(top5, [], 0);
      return;
    }
    const n = learning.learning_top1.length;
    drawChart(top1, [
      { color: "#8ea3c4", dash: "5 5", values: learning.baseline_top1 },
      { color: "#3ddc97", values: learning.learning_top1 }
    ], n - 1);
    drawChart(top5, [
      { color: "#8ea3c4", dash: "5 5", values: learning.baseline_top5 },
      { color: "#3ddc97", values: learning.learning_top5 }
    ], n - 1);
  }

  function fillOptions(select, options, selected) {
    select.textContent = "";
    options.forEach(function (option) {
      const node = document.createElement("option");
      node.value = option.key;
      node.textContent = option.label;
      if (option.key === selected) node.selected = true;
      select.appendChild(node);
    });
  }

  function scenarioKey() {
    return [
      $("#domain-select").value,
      $("#worker-pref-select").value,
      $("#customer-pref-select").value
    ].join("|");
  }

  function selectScenario(key) {
    if (!scenarios[key]) return;
    const parts = key.split("|");
    $("#domain-select").value = parts[0];
    $("#worker-pref-select").value = parts[1];
    $("#customer-pref-select").value = parts[2];
    activeKey = key;
    workerRounds = scenarios[key].worker.rounds;
    customerRounds = scenarios[key].customer.rounds;
    state.index = 0;
    stop();
    renderTagEffect();
    render();
  }

  function effectChip(text, delta, lowerIsBetter) {
    const chip = el("span", "effect");
    chip.appendChild(document.createTextNode(text + " "));
    const value = el("b", null, (delta > 0 ? "+" : "") + delta);
    const good = lowerIsBetter ? delta < 0 : delta > 0;
    const bad = lowerIsBetter ? delta > 0 : delta < 0;
    if (good) value.style.color = "#3ddc97";
    if (bad) value.style.color = "#ff7b7b";
    chip.appendChild(value);
    return chip;
  }

  function topEntry(delta) {
    return Object.keys(delta)
      .map(function (key) { return [key, delta[key]]; })
      .sort(function (a, b) { return Math.abs(b[1]) - Math.abs(a[1]); })[0];
  }

  function renderTagEffect() {
    const scenario = scenarios[activeKey];
    const effect = scenario.tag_effect;
    $("#scenario-label").textContent = [
      scenario.labels.domain,
      scenario.labels.worker_preference,
      scenario.labels.customer_preference
    ].join(" · ");
    const box = $("#tag-effect");
    box.textContent = "";
    box.appendChild(effectChip(
      "接单端首轮 #" + effect.worker_initial_rank,
      effect.worker_initial_rank_delta,
      true
    ));
    box.appendChild(effectChip(
      "任务端首轮 #" + effect.customer_initial_rank,
      effect.customer_initial_rank_delta,
      true
    ));
    const workerTop = topEntry(effect.worker_weights_delta);
    const customerTop = topEntry(effect.customer_weights_delta);
    if (workerTop && Math.abs(workerTop[1]) > 1e-6) {
      box.appendChild(effectChip(
        "worker " + WEIGHT_LABELS[workerTop[0]],
        Number(workerTop[1].toFixed(3))
      ));
    }
    if (customerTop && Math.abs(customerTop[1]) > 1e-6) {
      box.appendChild(effectChip(
        "customer " + WEIGHT_LABELS[customerTop[0]],
        Number(customerTop[1].toFixed(3))
      ));
    }
    const note = el("span", "effect");
    note.textContent = "起点不同，学习后两端仍到 #1";
    box.appendChild(note);
  }

  function drawSpark(svg, values, color) {
    svg.setAttribute("viewBox", "0 0 120 34");
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (!values.length) return;
    const maxX = Math.max(1, values.length - 1);
    const points = values.map(function (value, index) {
      return (index === 0 ? "M" : "L") +
        ((index / maxX) * 116 + 2).toFixed(1) + "," +
        (31 - value * 27).toFixed(1);
    }).join(" ");
    svg.appendChild(makeSvg("path", {
      d: points, stroke: color, "stroke-width": 1.8, fill: "none"
    }));
  }

  function renderCaseWall() {
    const grid = $("#case-wall");
    grid.textContent = "";
    DATA.case_wall.forEach(function (item) {
      const card = el("div", "case-card");
      card.appendChild(el("div", "case-cat", item.category_label));
      card.appendChild(el("div", "case-title", item.task_title));
      card.appendChild(el("div", "case-sub", item.worker_name));
      const ranks = el("div", "case-ranks");
      ranks.appendChild(el("span", null, "接单 #" + item.worker.initial_rank + "→#" + item.worker.final_rank));
      ranks.appendChild(el("span", null, "任务 #" + item.customer.initial_rank + "→#" + item.customer.final_rank));
      card.appendChild(ranks);
      const spark = document.createElementNS(SVG_NS, "svg");
      spark.classList.add("spark");
      drawSpark(spark, item.worker.hit_curve, "#4cc9f0");
      card.appendChild(spark);
      const cosine = el("div", "case-sub");
      cosine.textContent = "cosine " + item.worker.cosine_start.toFixed(2) + " → " + item.worker.cosine_end.toFixed(2);
      card.appendChild(cosine);
      grid.appendChild(card);
    });
  }

  /* ---------------------------------------------------------------- */
  /* Custom case — talks to the local FastAPI endpoint                 */
  /* ---------------------------------------------------------------- */
  const customState = { mode: "task", weights: null, round: 1 };
  const PREFERENCE_CHOICES = [
    { key: "quality", label: "质量优先" },
    { key: "speed", label: "速度优先" },
    { key: "specialty", label: "专精领域" },
    { key: "flexibility", label: "灵活接单" }
  ];

  function fillChips(container, options, cap) {
    container.textContent = "";
    options.forEach(function (option) {
      const key = typeof option === "string" ? option : option.key;
      const label = typeof option === "string" ? option : option.label;
      const chip = el("span", "chip-toggle", label);
      chip.dataset.value = key;
      chip.addEventListener("click", function () {
        if (!chip.classList.contains("active") &&
            cap &&
            container.querySelectorAll(".chip-toggle.active").length >= cap) {
          return;
        }
        chip.classList.toggle("active");
      });
      container.appendChild(chip);
    });
  }

  function activeChips(container) {
    return Array.from(container.querySelectorAll(".chip-toggle.active"))
      .map(function (node) { return node.dataset.value; });
  }

  function setCustomMode(mode) {
    customState.mode = mode;
    document.querySelectorAll(".mode-tabs button").forEach(function (button) {
      button.classList.toggle("active", button.dataset.mode === mode);
    });
    document.querySelectorAll("[data-modes]").forEach(function (node) {
      node.hidden = node.dataset.modes.split(" ").indexOf(mode) === -1;
    });
    resetCustom();
  }

  function resetCustom() {
    customState.weights = null;
    customState.round = 1;
    $("#custom-result").hidden = true;
    $("#custom-error").textContent = "";
    $("#custom-status").textContent = "等待输入";
    $("#custom-feed").textContent = "";
    $("#custom-weights").textContent = "";
    $("#custom-effect").textContent = "";
  }

  function customError(message) {
    $("#custom-error").textContent = message;
    $("#custom-status").textContent = "请求失败";
  }

  function buildCustomPayload(choice) {
    const skills = activeChips($("#custom-skills"));
    if (!skills.length) throw new Error("请至少选择一个技能标签");
    const preferenceKeys = activeChips($("#custom-preferences"));
    const preferences = {};
    preferenceKeys.forEach(function (key) { preferences[key] = 0.6; });
    const payload = {
      mode: customState.mode,
      preferences: preferences,
      weights: customState.weights,
      round: customState.round,
      choice: choice || null
    };
    if (customState.mode === "task") {
      const required = {};
      skills.forEach(function (skill) { required[skill] = 3; });
      payload.task = {
        title: $("#custom-title").value,
        category: $("#custom-category").value,
        budget: Number($("#custom-budget").value || 0),
        deadline_days: Number($("#custom-deadline").value || 14),
        difficulty: Number($("#custom-difficulty").value || 3),
        required_skills: required
      };
    } else {
      const workerSkills = {};
      skills.forEach(function (skill) { workerSkills[skill] = 3; });
      const preferred = {};
      activeChips($("#custom-preferred-categories")).forEach(function (key) {
        preferred[key] = 0.8;
      });
      payload.worker = {
        name: $("#custom-worker-name").value,
        skills: workerSkills,
        preferred_categories: preferred,
        expected_pay: Number($("#custom-pay").value || 0),
        current_load_hours: Number($("#custom-load").value || 0),
        region: $("#custom-region").value,
        remote_ok: true
      };
    }
    return payload;
  }

  async function customStep(choice) {
    if (window.location.protocol === "file:") {
      customError("自定义模拟需要后端：请通过 http://127.0.0.1:8010/ui/learning-demo.html 打开。");
      return;
    }
    $("#custom-error").textContent = "";
    let payload;
    try {
      payload = buildCustomPayload(choice);
    } catch (error) {
      customError(error.message);
      return;
    }
    $("#custom-status").textContent = "请求中…";
    try {
      const response = await fetch("/demo/custom/step", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "请求失败");
      }
      customState.weights = data.weights;
      customState.round = data.round;
      renderCustom(data);
    } catch (error) {
      customError(error.message);
    }
  }

  function renderCustom(data) {
    $("#custom-result").hidden = false;
    $("#custom-round").textContent = data.round;
    $("#custom-status").textContent = data.choice
      ? "已更新 · 继续点选或重新开始"
      : "初始推荐 · 点选一个候选";
    const profile = $("#custom-profile");
    profile.textContent = "";
    [["模式", data.mode === "task" ? "发布任务" : "接单画像"],
     ["候选池", data.pool_size + " 个"]].forEach(function (entry) {
      const chip = el("div", "stat");
      chip.appendChild(el("span", "stat-k", entry[0]));
      chip.appendChild(el("span", "stat-v", entry[1]));
      profile.appendChild(chip);
    });

    const feed = $("#custom-feed");
    feed.textContent = "";
    const maxScore = Math.max.apply(null, data.feed.map(function (item) { return item.score; }).concat([1e-9]));
    data.feed.forEach(function (item) {
      const card = el("div", "custom-card");
      card.appendChild(el("div", "rank", item.rank));
      const body = el("div", "card-body");
      body.appendChild(el("div", "card-title", item.title));
      body.appendChild(el("div", "card-sub", item.subtitle));
      card.appendChild(body);
      const right = el("div", "card-right");
      right.appendChild(el("div", "score", fmt(item.score)));
      const bar = el("div", "bar");
      const fill = el("i");
      fill.style.width = Math.max(4, (item.score / maxScore) * 100) + "%";
      bar.appendChild(fill);
      right.appendChild(bar);
      card.appendChild(right);
      const pick = el("button", "pick", "选择");
      pick.addEventListener("click", function () { customStep(item.id); });
      card.appendChild(pick);
      feed.appendChild(card);
    });

    renderWeights($("#custom-weights"), {
      weights_after: data.weights,
      delta: data.delta
    });

    const effect = $("#custom-effect");
    effect.textContent = "";
    topDeltas({ delta: data.delta }).forEach(function (pair) {
      effect.appendChild(effectChip(
        "权重 " + WEIGHT_LABELS[pair[0]],
        Number(pair[1].toFixed(3))
      ));
    });
    const note = el("span", "effect");
    note.textContent = "无 ground truth，因此不计算命中率";
    effect.appendChild(note);
  }

  function initCustom() {
    const defaultCategory = DATA.options.categories.find(function (category) {
      return category.key === "video_production";
    }) || DATA.options.categories[0];
    fillOptions(
      $("#custom-category"),
      DATA.options.categories,
      defaultCategory ? defaultCategory.key : ""
    );
    fillOptions(
      $("#custom-region"),
      DATA.options.regions.map(function (region) {
        return { key: region, label: region };
      }),
      DATA.options.regions[0] || "CN"
    );
    const levels = [1, 2, 3, 4, 5].map(function (level) {
      return { key: String(level), label: String(level) };
    });
    fillOptions($("#custom-difficulty"), levels, "3");
    fillOptions($("#custom-skill-level"), levels, "3");
    fillChips($("#custom-skills"), DATA.options.skills.slice(0, 14), 3);
    fillChips(
      $("#custom-preferred-categories"),
      DATA.options.categories.map(function (category) {
        return { key: category.key, label: category.label };
      }),
      2
    );
    fillChips($("#custom-preferences"), PREFERENCE_CHOICES, 2);

    document.querySelectorAll(".mode-tabs button").forEach(function (button) {
      button.addEventListener("click", function () {
        setCustomMode(button.dataset.mode);
      });
    });
    $("#custom-start").addEventListener("click", function () {
      resetCustom();
      customStep(null);
    });
    $("#custom-reset").addEventListener("click", resetCustom);
    const requestedMode = new URLSearchParams(
      window.location.search
    ).get("customMode");
    setCustomMode(requestedMode === "worker" ? "worker" : "task");
    if (window.location.protocol === "file:") {
      $("#custom-status").textContent =
        "需通过 http://127.0.0.1:8010/ui/learning-demo.html 打开";
    }
    if (
      new URLSearchParams(window.location.search).get("customStart") === "1"
    ) {
      const firstChip = $("#custom-skills .chip-toggle");
      if (firstChip) firstChip.classList.add("active");
      customStep(null);
    }
  }

  function render() {
    const workerRound = workerRounds[state.index];
    const customerRound = customerRounds[state.index];
    $("#round-no").textContent = state.index + 1;
    $("#round-total").textContent = total;
    $("#scrub").value = state.index;
    $("#play").textContent = state.playing ? "暂停" : "播放";

    renderFeed($("#worker-feed"), workerRound, workerRounds);
    renderFeed($("#customer-feed"), customerRound, customerRounds);
    renderWeights($("#worker-weights"), workerRound);
    renderWeights($("#customer-weights"), customerRound);
    renderProfile($("#worker-profile"), workerRound.profile, "worker");
    renderProfile($("#customer-profile"), customerRound.profile, "customer");
    renderFeedback(workerRound, customerRound);

    const upto = state.index + 1;
    const baseline = scenarios[DATA.baseline_key];
    const showBaseline = activeKey !== DATA.baseline_key;
    const workerSeries = [
      {
        color: "#4cc9f0",
        values: workerRounds.slice(0, upto).map(function (round) { return round.hit_rate; })
      },
      {
        color: "#3ddc97",
        values: workerRounds.slice(0, upto).map(function (round) { return round.cosine_after; })
      }
    ];
    const customerSeries = [
      {
        color: "#a78bfa",
        values: customerRounds.slice(0, upto).map(function (round) { return round.hit_rate; })
      },
      {
        color: "#3ddc97",
        values: customerRounds.slice(0, upto).map(function (round) { return round.cosine_after; })
      }
    ];
    if (showBaseline) {
      workerSeries.push({
        color: "#6f86a8",
        dash: "4 4",
        width: 1.6,
        values: baseline.worker.rounds.slice(0, upto).map(function (round) { return round.cosine_after; })
      });
      customerSeries.push({
        color: "#6f86a8",
        dash: "4 4",
        width: 1.6,
        values: baseline.customer.rounds.slice(0, upto).map(function (round) { return round.cosine_after; })
      });
    }
    drawChart($("#worker-chart"), workerSeries, total - 1);
    drawChart($("#customer-chart"), customerSeries, total - 1);
  }

  function stop() {
    if (state.timer) {
      clearInterval(state.timer);
      state.timer = null;
    }
    state.playing = false;
    $("#play").textContent = "播放";
  }

  function play() {
    if (state.playing) return;
    if (state.index >= total - 1) state.index = -1;
    state.playing = true;
    $("#play").textContent = "暂停";
    state.timer = setInterval(function () {
      if (state.index >= total - 1) {
        stop();
        render();
        return;
      }
      state.index += 1;
      render();
    }, 1700 / state.speed);
  }

  function setRound(value) {
    stop();
    state.index = Math.max(0, Math.min(total - 1, Number(value)));
    render();
  }

  function init() {
    const scenario = DATA.scenario;
    const parts = DATA.baseline_key.split("|");
    fillOptions($("#domain-select"), DATA.variables.domains, parts[0]);
    fillOptions($("#worker-pref-select"), DATA.variables.worker_preferences, parts[1]);
    fillOptions($("#customer-pref-select"), DATA.variables.customer_preferences, parts[2]);
    ["#domain-select", "#worker-pref-select", "#customer-pref-select"].forEach(function (selector) {
      $(selector).addEventListener("change", function () {
        selectScenario(scenarioKey());
      });
    });

    const params = new URLSearchParams(window.location.search);
    const requestedScenario = params.get("scenario");
    if (requestedScenario && scenarios[requestedScenario]) {
      const selected = requestedScenario.split("|");
      activeKey = requestedScenario;
      $("#domain-select").value = selected[0];
      $("#worker-pref-select").value = selected[1];
      $("#customer-pref-select").value = selected[2];
      workerRounds = scenarios[activeKey].worker.rounds;
      customerRounds = scenarios[activeKey].customer.rounds;
    }

    const requested = Number(params.get("round"));
    if (Number.isFinite(requested) && requested >= 1) {
      state.index = Math.max(0, Math.min(total - 1, Math.floor(requested) - 1));
    }
    $("#scene-title").textContent = scenario.task.title;
    $("#scene-task-meta").textContent = scenario.task.category_label + " · ¥" + Math.round(scenario.task.budget);
    $("#worker-name").textContent = scenario.worker.name + " · L" + scenario.worker.level + " · " + scenario.worker.region;
    $("#customer-name").textContent = scenario.customer.name + " · " + scenario.customer.region;
    $("#scrub").max = total - 1;

    $("#play").addEventListener("click", function () {
      if (state.playing) { stop(); render(); } else { play(); }
    });
    $("#prev").addEventListener("click", function () { setRound(state.index - 1); });
    $("#next").addEventListener("click", function () { setRound(state.index + 1); });
    $("#reset").addEventListener("click", function () { setRound(0); });
    $("#scrub").addEventListener("input", function (event) { setRound(event.target.value); });
    $("#speed").addEventListener("change", function (event) {
      state.speed = Number(event.target.value);
      if (state.playing) { stop(); play(); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "ArrowLeft") { event.preventDefault(); setRound(state.index - 1); }
      if (event.key === "ArrowRight") { event.preventDefault(); setRound(state.index + 1); }
      if (event.key === " ") {
        event.preventDefault();
        if (state.playing) { stop(); render(); } else { play(); }
      }
    });

    const meta = DATA.meta;
    $("#meta-note").textContent =
      "seed=" + meta.seed +
      " · 轮数=" + meta.rounds +
      " · 学习率 worker=" + meta.worker_learning_rate +
      " / customer=" + meta.customer_learning_rate +
      " · " + meta.note;

    renderTagEffect();
    renderCaseWall();
    initCustom();
    drawGlobalCharts();
    render();
  }

  init();
}());
</script>
</body>
</html>
"""


def render_demo_html(data: dict) -> str:
    """Return a self-contained HTML document with the demo data embedded."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    return TEMPLATE.replace("__DEMO_DATA_JSON__", payload)
