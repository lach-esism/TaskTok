const DIM_LABELS = {
  reputation: "信誉",
  skill: "技能",
  expertise: "专长",
  collaborative: "协同",
  preference: "偏好",
  load: "负载",
  customer_preference: "客户偏好",
};

const PREF_LABELS = {
  quality: "结果质量优先",
  speed: "交付速度优先",
  specialty: "专长匹配优先",
  flexibility: "灵活低负载优先",
};

const CATEGORIES = [
  ["software_dev", "软件开发"],
  ["ui_ux_design", "UI/UX"],
  ["brand_design", "品牌设计"],
  ["content_writing", "内容写作"],
  ["video_production", "视频制作"],
  ["marketing_campaign", "市场活动"],
  ["data_annotation", "数据标注"],
  ["translation_localization", "翻译本地化"],
  ["ecommerce_ops", "电商运营"],
  ["recruitment", "招聘"],
  ["consulting_research", "咨询调研"],
  ["training_course", "培训课程"],
];

const state = {
  health: null,
  tasks: [],
  workers: [],
  weights: null,
  changelog: [],
  learningCurve: null,
  learningRounds: null,
  chain: null,
  plan: null,
  acceptance: null,
  acceptanceSpec: null,
  acceptanceSubmission: null,
  talentList: [],
  talentResume: null,
  talentRawVisible: false,
  pendingAdopt: null,
  profileUser: null,
  profileType: "worker",
  rating: 0,
  uploadTask: null,
  resumeUpload: null,
  confirmedDraft: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
const fmt = (value, digits = 3) => Number(value || 0).toFixed(digits);
const fmtTime = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
};
const fmtDate = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleDateString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      });
};
const fmtMoney = (value) =>
  `¥${Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
const fmtPct = (value) =>
  value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
const REGION_LABELS = { CN: "中国大陆", US: "美国", EU: "欧洲" };
const openTasks = () => state.tasks.filter((task) => task.status === "open");

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) {
    let detail = data && data.detail ? data.detail : `${response.status} ${response.statusText}`;
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
    }
    throw new Error(detail);
  }
  return data;
}

async function postRecommendationEvent(
  requestId,
  candidateId,
  candidateType,
  action,
  extra = {}
) {
  if (!requestId) return;
  try {
    await api("/events", {
      method: "POST",
      body: JSON.stringify({
        events: [{
          request_id: requestId,
          candidate_id: candidateId,
          candidate_type: candidateType,
          action,
          ...extra,
        }],
      }),
    });
  } catch (error) {
    // Duplicate or stale events must never break the demo flow.
  }
}

async function apiForm(path, form) {
  const response = await fetch(path, { method: "POST", body: form });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) {
    let detail = data && data.detail ? data.detail : `${response.status} ${response.statusText}`;
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
    }
    throw new Error(detail);
  }
  return data;
}

let toastTimer = null;
function toast(message, kind = "ok") {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.className = "toast";
  }, 3600);
}

function setOptions(select, options, placeholder = null) {
  if (!select) return;
  const previous = select.value;
  select.innerHTML = "";
  if (placeholder) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = placeholder;
    select.appendChild(option);
  }
  options.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  });
  if ([...select.options].some((option) => option.value === previous)) {
    select.value = previous;
  }
}

function switchTab(name) {
  $$(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  $$(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function bindTabs() {
  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  $$("[data-goto]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.goto));
  });
}

function bindTheme() {
  const key = "tasktok-theme";
  if (localStorage.getItem(key) === "light") {
    document.body.classList.add("light");
  }
  $("#theme-toggle").addEventListener("click", () => {
    document.body.classList.toggle("light");
    localStorage.setItem(
      key,
      document.body.classList.contains("light") ? "light" : "dark"
    );
  });
}

function renderWeightBars(container, weights) {
  if (!container) return;
  container.innerHTML = "";
  const keys = Object.keys(DIM_LABELS).filter((key) => weights[key] !== undefined);
  if (!keys.length) {
    container.innerHTML = '<div class="empty">暂无权重</div>';
    return;
  }
  keys.forEach((key) => {
    const value = Number(weights[key] || 0);
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <div class="bar-label">${DIM_LABELS[key]}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, value * 100)}%"></div></div>
      <div class="bar-value">${fmt(value)}</div>`;
    container.appendChild(row);
  });
}

function renderRoundsChart(container, data) {
  if (!container) return;
  container.innerHTML = "";
  if (!data || !Array.isArray(data.rounds) || !data.rounds.length) {
    container.innerHTML =
      '<div class="empty">暂无对照曲线；先运行 <span class="mono">python scripts/simulate_learning_rounds.py</span></div>';
    return;
  }
  const width = 760;
  const height = 300;
  const pad = { left: 52, right: 20, top: 28, bottom: 38 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const count = data.rounds.length;
  const x = (index) =>
    pad.left + (count === 1 ? innerW / 2 : (index * innerW) / (count - 1));
  const y = (value) =>
    pad.top + (1 - Math.max(0, Math.min(1, value))) * innerH;
  const svgNS = "http://www.w3.org/2000/svg";
  const make = (tag, attributes = {}, text = null) => {
    const node = document.createElementNS(svgNS, tag);
    Object.entries(attributes).forEach(([key, value]) =>
      node.setAttribute(key, value)
    );
    if (text !== null) node.textContent = text;
    return node;
  };

  const legend = document.createElement("div");
  legend.className = "chart-legend";
  legend.innerHTML =
    '<span><i class="swatch blue"></i>学习 Top-1</span>' +
    '<span><i class="swatch" style="background:var(--faint)"></i>不学习 Top-1</span>' +
    '<span><i class="swatch teal"></i>学习 Top-5</span>' +
    '<span><i class="swatch" style="background:var(--faint)"></i>不学习 Top-5</span>';
  container.appendChild(legend);

  const svg = make("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": "20 轮学习与不学习推荐准确率对比",
  });
  for (let index = 0; index <= 4; index += 1) {
    const ratio = index / 4;
    const lineY = pad.top + ratio * innerH;
    svg.appendChild(
      make("line", {
        class: "chart-grid",
        x1: pad.left,
        y1: lineY,
        x2: width - pad.right,
        y2: lineY,
      })
    );
    svg.appendChild(
      make(
        "text",
        {
          class: "chart-label",
          x: pad.left - 8,
          y: lineY + 3,
          "text-anchor": "end",
        },
        fmt(1 - ratio, 2)
      )
    );
  }
  svg.appendChild(
    make("line", {
      class: "chart-axis",
      x1: pad.left,
      y1: height - pad.bottom,
      x2: width - pad.right,
      y2: height - pad.bottom,
    })
  );
  const labelIndices = [0, 4, 9, 14, count - 1].filter(
    (value, index, array) => value >= 0 && value < count && array.indexOf(value) === index
  );
  labelIndices.forEach((index) => {
    svg.appendChild(
      make(
        "text",
        {
          class: "chart-label",
          x: x(index),
          y: height - pad.bottom + 17,
          "text-anchor": "middle",
        },
        `第 ${Math.round(data.rounds[index])} 轮`
      )
    );
  });
  svg.appendChild(
    make(
      "text",
      {
        class: "chart-title",
        x: (pad.left + width - pad.right) / 2,
        y: height - 5,
        "text-anchor": "middle",
      },
      "模拟轮次"
    )
  );
  svg.appendChild(
    make(
      "text",
      {
        class: "chart-title",
        x: pad.left,
        y: 16,
      },
      "推送准确率"
    )
  );

  const lines = [
    ["learning_top1", "cosine", "chart-point cosine"],
    ["baseline_top1", "baseline", "chart-point baseline"],
    ["learning_top5", "top5", "chart-point top5"],
    ["baseline_top5", "top5-baseline", "chart-point baseline"],
  ];
  lines.forEach(([key, className]) => {
    const values = data[key] || [];
    const points = values.map((value, index) => [x(index), y(value)]);
    if (!points.length) return;
    svg.appendChild(
      make("polyline", {
        class: `chart-line ${className}`,
        points: points.map(([px, py]) => `${px},${py}`).join(" "),
      })
    );
    points.forEach(([px, py], index) => {
      const point = make("circle", {
        class: `chart-point ${className.replace("chart-point ", "")}`,
        cx: px,
        cy: py,
        r: 2.8,
      });
      point.appendChild(
        make(
          "title",
          {},
          `第 ${Math.round(data.rounds[index])} 轮 · ${fmt(values[index], 4)}`
        )
      );
      svg.appendChild(point);
    });
  });
  container.appendChild(svg);

  const finalIndex = count - 1;
  const stats = $("#rounds-stats");
  if (stats) {
    stats.innerHTML = `
      <div class="growth-stat"><span>学习 Top-1（最终）</span><strong>${fmt(data.learning_top1[finalIndex], 3)}</strong></div>
      <div class="growth-stat"><span>不学习 Top-1（最终）</span><strong>${fmt(data.baseline_top1[finalIndex], 3)}</strong></div>
      <div class="growth-stat"><span>学习 Top-5（最终）</span><strong>${fmt(data.learning_top5[finalIndex], 3)}</strong></div>
      <div class="growth-stat"><span>权重 cosine（学习 / 固定）</span><strong>${fmt(data.learning_cosine[finalIndex], 3)} / ${fmt(data.baseline_cosine[finalIndex], 3)}</strong></div>`;
  }
}

function renderProgressChart(container, curve) {
  if (!container) return;
  container.innerHTML = "";
  if (!curve || !Array.isArray(curve.n) || !curve.n.length) {
    container.innerHTML =
      '<div class="empty">暂无进步曲线；先运行 <span class="mono">python scripts/evaluate_phase2.py</span></div>';
    return;
  }

  const n = curve.n;
  const cosine = curve.weight_cosine || [];
  const ndcg = curve.ndcg || [];
  const width = 760;
  const height = 280;
  const pad = { left: 58, right: 58, top: 30, bottom: 40 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const cMin = Math.min(...cosine) - 0.004;
  const cMax = Math.max(...cosine) + 0.004;
  const nMin = Math.min(...ndcg) - 0.002;
  const nMax = Math.max(...ndcg) + 0.002;
  const x = (index) =>
    pad.left + (n.length === 1 ? innerW / 2 : (index * innerW) / (n.length - 1));
  const yCosine = (value) =>
    pad.top + (1 - (value - cMin) / (cMax - cMin || 1)) * innerH;
  const yNdcg = (value) =>
    pad.top + (1 - (value - nMin) / (nMax - nMin || 1)) * innerH;

  const svgNS = "http://www.w3.org/2000/svg";
  const make = (tag, attributes = {}, text = null) => {
    const node = document.createElementNS(svgNS, tag);
    Object.entries(attributes).forEach(([key, value]) =>
      node.setAttribute(key, value)
    );
    if (text !== null) node.textContent = text;
    return node;
  };

  const legend = document.createElement("div");
  legend.className = "chart-legend";
  legend.innerHTML =
    '<span><i class="swatch blue"></i>权重恢复 cosine</span>' +
    '<span><i class="swatch teal"></i>NDCG@10（右轴）</span>';
  container.appendChild(legend);

  const svg = make("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": "新用户学习曲线：权重恢复 cosine 与 NDCG",
  });
  const defs = make("defs");
  const gradient = make("linearGradient", {
    id: "cosineFill",
    x1: "0",
    y1: "0",
    x2: "0",
    y2: "1",
  });
  gradient.appendChild(make("stop", { offset: "0%", "stop-color": "#5b8cff", "stop-opacity": "0.35" }));
  gradient.appendChild(make("stop", { offset: "100%", "stop-color": "#5b8cff", "stop-opacity": "0.01" }));
  defs.appendChild(gradient);
  svg.appendChild(defs);

  for (let index = 0; index <= 4; index += 1) {
    const ratio = index / 4;
    const y = pad.top + ratio * innerH;
    svg.appendChild(
      make("line", {
        class: "chart-grid",
        x1: pad.left,
        y1: y,
        x2: width - pad.right,
        y2: y,
      })
    );
    svg.appendChild(
      make(
        "text",
        {
          class: "chart-label",
          x: pad.left - 10,
          y: y + 3,
          "text-anchor": "end",
        },
        fmt(cMax - ratio * (cMax - cMin), 3)
      )
    );
    svg.appendChild(
      make(
        "text",
        {
          class: "chart-label",
          x: width - pad.right + 10,
          y: y + 3,
        },
        fmt(nMax - ratio * (nMax - nMin), 3)
      )
    );
  }

  svg.appendChild(
    make("line", {
      class: "chart-axis",
      x1: pad.left,
      y1: height - pad.bottom,
      x2: width - pad.right,
      y2: height - pad.bottom,
    })
  );
  svg.appendChild(
    make("line", {
      class: "chart-axis",
      x1: pad.left,
      y1: pad.top,
      x2: pad.left,
      y2: height - pad.bottom,
    })
  );
  svg.appendChild(
    make("line", {
      class: "chart-axis",
      x1: width - pad.right,
      y1: pad.top,
      x2: width - pad.right,
      y2: height - pad.bottom,
    })
  );

  n.forEach((value, index) => {
    svg.appendChild(
      make(
        "text",
        {
          class: "chart-label",
          x: x(index),
          y: height - pad.bottom + 17,
          "text-anchor": "middle",
        },
        `n=${Math.round(value)}`
      )
    );
  });
  svg.appendChild(
    make(
      "text",
      {
        class: "chart-title",
        x: pad.left,
        y: 16,
      },
      "权重恢复 cosine"
    )
  );
  svg.appendChild(
    make(
      "text",
      {
        class: "chart-title",
        x: width - pad.right,
        y: 16,
        "text-anchor": "end",
      },
      "NDCG@10（右轴）"
    )
  );
  svg.appendChild(
    make(
      "text",
      {
        class: "chart-label",
        x: (pad.left + width - pad.right) / 2,
        y: height - 6,
        "text-anchor": "middle",
      },
      "反馈数 n"
    )
  );

  const cosinePoints = cosine.map((value, index) => [x(index), yCosine(value)]);
  const ndcgPoints = ndcg.map((value, index) => [x(index), yNdcg(value)]);
  const areaPath =
    `M ${cosinePoints[0][0]} ${height - pad.bottom} ` +
    cosinePoints.map(([px, py]) => `L ${px} ${py}`).join(" ") +
    ` L ${cosinePoints[cosinePoints.length - 1][0]} ${height - pad.bottom} Z`;
  svg.appendChild(make("path", { class: "chart-area", d: areaPath }));

  const drawLine = (points, className) => {
    svg.appendChild(
      make("polyline", {
        class: `chart-line ${className}`,
        points: points.map(([px, py]) => `${px},${py}`).join(" "),
      })
    );
  };
  drawLine(cosinePoints, "cosine");
  drawLine(ndcgPoints, "ndcg");

  cosinePoints.forEach(([px, py], index) => {
    const point = make("circle", {
      class: "chart-point cosine",
      cx: px,
      cy: py,
      r: 4.5,
    });
    point.appendChild(make("title", {}, `n=${Math.round(n[index])} · cosine ${fmt(cosine[index], 4)}`));
    svg.appendChild(point);
  });
  ndcgPoints.forEach(([px, py], index) => {
    const point = make("circle", {
      class: "chart-point ndcg",
      cx: px,
      cy: py,
      r: 3.4,
    });
    point.appendChild(make("title", {}, `n=${Math.round(n[index])} · NDCG ${fmt(ndcg[index], 4)}`));
    svg.appendChild(point);
  });

  const lastIndex = n.length - 1;
  svg.appendChild(
    make(
      "text",
      {
        class: "chart-value",
        x: cosinePoints[lastIndex][0] - 6,
        y: cosinePoints[lastIndex][1] - 12,
        "text-anchor": "end",
      },
      `cosine ${fmt(cosine[lastIndex], 3)}`
    )
  );
  svg.appendChild(
    make(
      "text",
      {
        class: "chart-value",
        x: ndcgPoints[lastIndex][0] - 6,
        y: ndcgPoints[lastIndex][1] + 18,
        "text-anchor": "end",
      },
      `NDCG ${fmt(ndcg[lastIndex], 3)}`
    )
  );

  container.appendChild(svg);
}

function renderProgressCharts() {
  renderProgressChart($("#progress-chart"), state.learningCurve);
  renderProgressChart($("#progress-chart-feedback"), state.learningCurve);
}

function renderOverview() {
  const open = openTasks();
  $("#stat-workers").textContent = state.workers.length || "—";
  $("#stat-tasks").textContent = open.length || "—";
  $("#stat-weights").textContent = state.weights ? state.weights.version : "—";
  $("#stat-version").textContent = state.health ? state.health.version : "—";
  if (state.weights) {
    renderWeightBars($("#overview-weights"), state.weights.weights);
    $("#overview-weight-meta").textContent =
      `${state.weights.source} · ${state.weights.sample_count} 条反馈`;
  }
}

function fillTaskSelects() {
  const tasks = openTasks();
  const options = tasks.map((task) => [
    task.task_id,
    `${task.title} · ${fmtMoney(task.budget_min)}–${fmtMoney(task.budget_max)} · 截止 ${fmtDate(task.deadline)}`,
  ]);
  ["#t2w-task", "#chain-task", "#growth-task"].forEach((selector) => {
    setOptions($(selector), options, options.length ? null : "暂无开放任务");
  });
  if (!options.length) {
    ["#t2w-task", "#chain-task", "#growth-task"].forEach((selector) => {
      const select = $(selector);
      if (select) select.innerHTML = '<option value="">暂无开放任务</option>';
    });
  }
  if (!state.chainTask && options.length) {
    state.chainTask = options[0][0];
  }
  renderTaskPreview();
}

function renderTaskPreview() {
  const box = $("#t2w-task-preview");
  if (!box) return;
  const task = state.tasks.find((item) => item.task_id === $("#t2w-task").value);
  if (!task) {
    box.innerHTML = '<div class="empty">暂无开放任务</div>';
    return;
  }
  const requirements = (task.requirements || [])
    .map((item) => `<li>${esc(item)}</li>`)
    .join("");
  box.innerHTML = `
    <div class="task-preview-head">
      <div>
        <h3>${esc(task.title)}</h3>
        <div class="task-meta">
          发布于 ${fmtDate(task.created_at)} · 截止 ${fmtDate(task.deadline)} ·
          ${esc(REGION_LABELS[task.region] || task.region)} ·
          ${task.remote_ok ? "支持远程" : "需线下协作"}
        </div>
      </div>
      <div class="task-budget">
        <strong>${fmtMoney(task.budget_min)} – ${fmtMoney(task.budget_max)}</strong>
        <small>服务报酬</small>
      </div>
    </div>
    <p class="task-desc">${esc(task.description)}</p>
    <div class="task-reqs">
      <h4>合作方要求</h4>
      <ul>${requirements || "<li>面议</li>"}</ul>
    </div>`;
}

function fillWorkerSelects() {
  const options = state.workers.slice(0, 200).map((worker) => [
    worker.worker_id,
    `${worker.worker_id} · L${worker.level} · 负载 ${worker.current_load_hours}/${worker.capacity_hours}h`,
  ]);
  setOptions($("#w2t-worker"), options);
}

function fillChainCategories() {
  const container = $("#chain-categories");
  container.innerHTML = "";
  CATEGORIES.forEach(([id, label]) => {
    const chip = document.createElement("label");
    chip.className = "chip";
    chip.innerHTML = `<input type="checkbox" value="${id}" /> ${label}`;
    container.appendChild(chip);
  });
}

function updateChainMode() {
  const mode = $("#chain-mode").value;
  $("#chain-categories-panel").classList.toggle("hidden", mode !== "compose");
}

function selectedCategories() {
  return $$('#chain-categories input[type="checkbox"]:checked').map(
    (input) => input.value
  );
}

async function refreshWeights() {
  state.weights = await api("/weights");
  state.changelog = await api("/learning/changelog");
  renderOverview();
  renderWeightsPanel();
  renderChangelog();
}

function renderWeightsPanel() {
  if (!state.weights) return;
  $("#weights-version").textContent = state.weights.version;
  renderWeightBars($("#weights-bars"), state.weights.weights);
  $("#diff-to").value = state.weights.version;
  if (!$("#diff-from").value) $("#diff-from").value = "v0000";
}

function renderChangelog() {
  const container = $("#changelog");
  if (!state.changelog.length) {
    container.innerHTML = '<div class="empty">暂无学习事件</div>';
    return;
  }
  const rows = state.changelog
    .slice()
    .reverse()
    .map(
      (event) => `
      <tr>
        <td class="mono">${esc(event.event_type)}</td>
        <td class="mono">${esc(event.version)}</td>
        <td>${esc(event.source || event.reason || "—")}</td>
        <td>${esc(event.sample_count ?? "—")}</td>
        <td>${esc(fmtTime(event.updated_at))}</td>
      </tr>`
    )
    .join("");
  container.innerHTML = `
    <table>
      <thead><tr><th>事件</th><th>版本</th><th>来源/原因</th><th>样本</th><th>时间</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

const CLASSIFY_SAMPLE =
  "我们要做一个会员小程序，包含积分、下单支付和后台管理，预算 8000–30000 元，" +
  "期望 30 天内交付，截止 2026-12-20，支持远程。要求熟悉微信小程序和支付接口，" +
  "有同类项目经验优先。";

async function runClassification() {
  const text = $("#classify-text").value.trim();
  if (!text) return toast("请输入任务描述", "error");
  try {
    const data = await api("/classify", {
      method: "POST",
      body: JSON.stringify({ text, top_k: 3 }),
    });
    renderClassification(data);
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderClassification(data) {
  const box = $("#classify-result");
  const fields = data.extracted || {};
  const candidates = (data.candidates || [])
    .map(
      (candidate, index) => `
      <div class="classify-candidate ${index === 0 ? "top" : ""}">
        <span>${esc(candidate.label)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.max(4, candidate.confidence * 100)}%"></div></div>
        <span class="mono">${fmt(candidate.confidence, 2)}</span>
      </div>`
    )
    .join("");
  const budget =
    fields.budget_min != null && fields.budget_max != null
      ? `${fmtMoney(fields.budget_min)} – ${fmtMoney(fields.budget_max)}`
      : "未识别";
  const dates = (fields.dates || []).join("、") || "未识别";
  const skills =
    (fields.skills || [])
      .map((skill) => `<span class="reason">${esc(skill)}</span>`)
      .join("") || '<span class="muted small">未识别</span>';
  const requirements =
    (fields.requirements || []).map((item) => `<li>${esc(item)}</li>`).join("") ||
    "<li>未识别</li>";
  const clarify = data.needs_clarification
    ? '<div class="classify-warn">置信度偏低，建议在 top-3 中确认，或补充预算、交付物和行业信息。</div>'
    : "";
  const confidence = Math.round((data.calibrated_confidence ?? data.confidence ?? 0) * 100);
  const evidence = (data.evidence || [])
    .map((item) => `<span class="reason">${esc(item.phrase)} · ${fmt(item.weight, 1)}</span>`)
    .join("");

  box.innerHTML = `
    <article class="panel classify-card">
      <div class="panel-head"><h3>分类结果</h3><span class="pill">${confidence}%</span></div>
      <div class="classify-verdict">
        <div>
          <span class="eyebrow">推荐类别</span>
          <h2>${esc(data.label)}</h2>
          <p class="muted small">任务链模板 key：${esc(data.suggested_template)}</p>
        </div>
        <div class="classify-score">${fmt(data.calibrated_confidence ?? data.confidence, 2)}</div>
      </div>
      ${clarify}
      <div class="classify-candidates">${candidates}</div>
      ${evidence ? `<div class="reasons">${evidence}</div>` : ""}
      <div class="task-reqs">
        <h4>抽取到的内部技能</h4>
        <div class="reasons">${skills}</div>
      </div>
    </article>
    <article class="panel classify-card">
      <div class="panel-head"><h3>结构化字段</h3></div>
      <div class="classify-fields">
        <div class="classify-field"><span>建议标题</span><strong>${esc(fields.suggested_title || "—")}</strong></div>
        <div class="classify-field"><span>服务报酬</span><strong>${budget}</strong></div>
        <div class="classify-field"><span>交付周期</span><strong>${fields.duration_days ? `${fields.duration_days} 天` : "未识别"}</strong></div>
        <div class="classify-field"><span>日期</span><strong>${esc(dates)}</strong></div>
      </div>
      <div class="task-reqs">
        <h4>合作方要求</h4>
        <ul>${requirements}</ul>
      </div>
    </article>`;
}

async function loadAcceptanceDemo() {
  try {
    const data = await api("/acceptance/demo");
    state.acceptance = data;
    state.acceptanceSpec = data.spec;
    state.acceptanceSubmission = null;
    renderAcceptanceTask(data);
    renderAcceptanceSpec(data.spec);
    $("#acceptance-machine").innerHTML = "";
    $("#acceptance-final").innerHTML = "";
    $("#acceptance-submission-meta").textContent = "尚未提交";
    await refreshAcceptanceMetrics();
    toast("已加载 B2B 调研验收任务");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderAcceptanceTask(data) {
  const box = $("#acceptance-task");
  const task = data.task;
  box.classList.remove("hidden");
  box.innerHTML = `
    <div class="task-preview-head">
      <div>
        <h3>${esc(task.title)}</h3>
        <div class="task-meta">
          执行者 ${esc(data.worker_id)} · 演示时钟 ${fmtDate(data.reference_time)} ·
          截止 ${fmtDate(task.deadline)} · ${esc(REGION_LABELS[task.region] || task.region)}
        </div>
      </div>
      <div class="task-budget">
        <strong>${fmtMoney(task.budget_min)} – ${fmtMoney(task.budget_max)}</strong>
        <small>服务报酬</small>
      </div>
    </div>
    <p class="task-desc">${esc(task.description)}</p>`;
}

function renderAcceptanceSpec(spec) {
  const criteria = spec.criteria || [];
  $("#acceptance-spec-meta").textContent =
    `${criteria.length} 条标准 · 通过线 ${fmt(spec.accept_threshold, 2)}`;
  $("#acceptance-spec").innerHTML = `
    <table>
      <thead><tr><th>标准</th><th>维度</th><th>层</th><th>硬门槛</th><th>权重</th></tr></thead>
      <tbody>${criteria
        .map(
          (item) => `
        <tr>
          <td>${esc(item.label)}</td>
          <td>${esc(item.dimension)}</td>
          <td>${esc(item.layer)}</td>
          <td>${item.required ? "是" : "否"}</td>
          <td class="mono">${fmt(item.weight, 2)}</td>
        </tr>`
        )
        .join("")}</tbody>
    </table>`;
}

async function refreshAcceptanceMetrics() {
  const box = $("#acceptance-metrics-box");
  try {
    const metrics = await api("/acceptance/metrics");
    const fields = [
      ["提交数", metrics.submissions],
      ["已决策", metrics.decided],
      ["一次通过率", fmtPct(metrics.first_pass_rate_raw)],
      ["接受率", fmtPct(metrics.acceptance_rate_raw)],
      ["返工率", fmtPct(metrics.rework_rate_raw)],
      ["争议率", fmtPct(metrics.dispute_rate_raw)],
      ["平均验收分", metrics.avg_acceptance_score ?? "—"],
      ["平均周期", metrics.avg_cycle_hours == null ? "—" : `${metrics.avg_cycle_hours}h`],
    ];
    box.innerHTML = fields
      .map(
        ([label, value]) =>
          `<div class="classify-field"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`
      )
      .join("");
  } catch (error) {
    box.innerHTML = `<div class="empty">${esc(error.message)}</div>`;
  }
}

async function submitAcceptance(valid) {
  if (!state.acceptance) return toast("先加载验收演示", "error");
  const artifacts = JSON.parse(
    JSON.stringify(state.acceptance.example_artifacts || {})
  );
  if (!valid) {
    if (artifacts.sections) delete artifacts.sections.competitive_landscape;
    if (Array.isArray(artifacts.sources)) artifacts.sources = artifacts.sources.slice(0, 4);
  }
  try {
    const data = await api(
      `/tasks/${state.acceptance.task.task_id}/submissions`,
      {
        method: "POST",
        body: JSON.stringify({
          worker_id: state.acceptance.worker_id,
          artifacts,
        }),
      }
    );
    state.acceptanceSubmission = data.submission;
    renderAcceptanceMachine(data);
    $("#acceptance-final").innerHTML = "";
    $("#acceptance-submission-meta").textContent =
      `版本 ${data.submission.version} · ${data.submission.status}`;
    await refreshAcceptanceMetrics();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderAcceptanceMachine(payload) {
  const submission = payload.submission;
  const record = payload.machine_record;
  const criteria = state.acceptanceSpec.criteria || [];
  const rows = (submission.machine_results || [])
    .map((result) => {
      const criterion = criteria.find(
        (item) => item.key === result.criterion_key
      );
      return `
        <tr>
          <td>${esc(criterion ? criterion.label : result.criterion_key)}</td>
          <td class="${result.passed ? "ok-text" : "bad-text"}">${result.passed ? "PASS" : "FAIL"}</td>
          <td>${esc(result.evidence)}</td>
        </tr>`;
    })
    .join("");
  const title = submission.status === "machine_failed"
    ? "机器校验未通过"
    : "机器校验通过";
  $("#acceptance-machine").innerHTML = `
    <div class="panel-head" style="margin-top:12px">
      <h3>${title}</h3>
      <span class="pill">机器层 ${fmt(record.total_score, 2)}</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>标准</th><th>结果</th><th>证据</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function reviewAcceptance() {
  const submission = state.acceptanceSubmission;
  if (!submission) return toast("先提交交付物", "error");
  if (submission.status === "reviewed") return toast("已经评分过");
  try {
    const data = await api(
      `/submissions/${submission.submission_id}/review`,
      {
        method: "POST",
        body: JSON.stringify({
          reviewer_id: state.acceptance.task.customer_id,
          layer: "customer",
          scores: { insight: 0.9, citation_consistency: 0.8 },
          comments: {
            insight: "结论可执行",
            citation_consistency: "引用基本一致",
          },
        }),
      }
    );
    submission.status = "reviewed";
    $("#acceptance-submission-meta").textContent =
      `版本 ${submission.version} · 已评分`;
    toast(`评分已记录，人工层加权 ${fmt(data.total_score, 2)}`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function decideAcceptance(decision) {
  const submission = state.acceptanceSubmission;
  if (!submission) return toast("先提交交付物", "error");
  try {
    if (submission.status !== "reviewed") {
      await api(`/submissions/${submission.submission_id}/review`, {
        method: "POST",
        body: JSON.stringify({
          reviewer_id: state.acceptance.task.customer_id,
          layer: "customer",
          scores: { insight: 0.9, citation_consistency: 0.8 },
          comments: {
            insight: "结论可执行",
            citation_consistency: "引用基本一致",
          },
        }),
      });
      submission.status = "reviewed";
    }
    const data = await api(
      `/submissions/${submission.submission_id}/decision`,
      {
        method: "POST",
        body: JSON.stringify({
          reviewer_id: state.acceptance.task.customer_id,
          decision,
          comment: decision === "accepted" ? "验收通过" : "客户决策",
        }),
      }
    );
    submission.status = data.record.decision;
    const capability = await api(
      `/workers/${data.record.worker_id}/capability`
    );
    renderAcceptanceFinal(data, capability);
    await refreshAcceptanceMetrics();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderAcceptanceFinal(payload, capability) {
  const record = payload.record;
  const learning = payload.learning;
  const labels = {
    accepted: "验收通过",
    rework: "要求返工",
    rejected: "驳回",
    disputed: "转入争议",
  };
  const capabilityFields = [
    ["提交数", capability.submissions],
    ["接受", capability.accepted],
    ["一次通过率", fmtPct(capability.first_pass_rate_raw)],
    ["返工率", fmtPct(capability.rework_rate_raw)],
    ["争议率", fmtPct(capability.dispute_rate_raw)],
    ["平均验收分", capability.avg_acceptance_score ?? "—"],
  ]
    .map(
      ([label, value]) =>
        `<div class="classify-field"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`
    )
    .join("");

  let learningHtml = '<p class="muted small">争议记录不进入学习。</p>';
  if (learning) {
    const rows = Object.keys(learning.before)
      .map((key) => {
        const delta = learning.deltas[key] || 0;
        return `
          <tr>
            <td>${esc(DIM_LABELS[key] || key)}</td>
            <td class="mono">${fmt(learning.before[key], 3)}</td>
            <td class="mono">${fmt(learning.after[key], 3)}</td>
            <td class="mono ${delta >= 0 ? "ok-text" : "bad-text"}">${delta >= 0 ? "+" : ""}${fmt(delta, 3)}</td>
          </tr>`;
      })
      .join("");
    const signals = Object.entries(learning.signals || {})
      .filter(([, value]) => value !== 0)
      .map(
        ([key, value]) =>
          `${DIM_LABELS[key] || key} ${value > 0 ? "+" : ""}${fmt(value, 2)}`
      )
      .join(" · ");
    learningHtml = `
      <div class="classify-fields" style="margin-top:12px">
        <div class="classify-field"><span>学习样本</span><strong>${learning.sample_count}</strong></div>
        <div class="classify-field"><span>置信度</span><strong>${fmtPct(learning.confidence)}</strong></div>
        <div class="classify-field"><span>权重上升</span><strong>${esc(DIM_LABELS[learning.top_up] || learning.top_up || "—")}</strong></div>
        <div class="classify-field"><span>权重下降</span><strong>${esc(DIM_LABELS[learning.top_down] || learning.top_down || "—")}</strong></div>
      </div>
      <p class="muted small">验收信号：${esc(signals || "—")}</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>维度</th><th>之前</th><th>之后</th><th>变化</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  $("#acceptance-final").innerHTML = `
    <article class="panel classify-card">
      <div class="panel-head"><h3>验收结论</h3><span class="pill">${esc(labels[record.decision] || record.decision)}</span></div>
      <div class="classify-verdict">
        <div>
          <span class="eyebrow">加权总分</span>
          <h2>${fmt(record.total_score, 2)}</h2>
          <p class="muted small">${esc(record.layer)} · ${esc(record.reviewer_id)} · ${fmtTime(record.created_at)}</p>
        </div>
        <div class="classify-score">${fmt(record.total_score, 2)}</div>
      </div>
      ${learningHtml}
    </article>
    <article class="panel classify-card">
      <div class="panel-head"><h3>执行者能力</h3><span class="muted small">${esc(capability.worker_id)}</span></div>
      <div class="classify-fields">${capabilityFields}</div>
    </article>`;
}

async function runAcceptanceLearning() {
  try {
    const data = await api("/acceptance/demo/learning?rounds=5", {
      method: "POST",
    });
    renderAcceptanceLearning(data);
    await refreshAcceptanceMetrics();
    toast("连续验收完成，查看权重与排序变化");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderAcceptanceLearning(data) {
  const box = $("#acceptance-learning");
  const deltaRows = Object.keys(data.weights_before)
    .map((key) => {
      const delta = data.deltas[key] || 0;
      return `
        <tr>
          <td>${esc(DIM_LABELS[key] || key)}</td>
          <td class="mono">${fmt(data.weights_before[key], 3)}</td>
          <td class="mono">${fmt(data.weights_after[key], 3)}</td>
          <td class="mono ${delta >= 0 ? "ok-text" : "bad-text"}">${delta >= 0 ? "+" : ""}${fmt(delta, 3)}</td>
        </tr>`;
    })
    .join("");
  const roundRows = data.rounds
    .map(
      (item) => `
      <tr>
        <td>#${item.round}</td>
        <td>${esc(item.decision)}</td>
        <td class="mono">${fmt(item.score, 2)}</td>
        <td class="mono">${item.sample_count}</td>
      </tr>`
    )
    .join("");
  const rankingRows = data.ranking_changes
    .map((item) => {
      let change = "—";
      if (item.before_rank == null) change = "NEW";
      else if (item.before_rank > item.after_rank) change = `↑${item.before_rank - item.after_rank}`;
      else if (item.before_rank < item.after_rank) change = `↓${item.after_rank - item.before_rank}`;
      return `
        <tr>
          <td>#${item.after_rank}</td>
          <td class="mono">${esc(item.worker_id)}</td>
          <td class="mono">${fmt(item.score, 3)}</td>
          <td class="${change === "NEW" || change.startsWith("↑") ? "ok-text" : change.startsWith("↓") ? "bad-text" : "muted"}">${change}</td>
        </tr>`;
    })
    .join("");

  box.innerHTML = `
    <article class="panel classify-card">
      <div class="panel-head"><h3>连续验收后的权重漂移</h3><span class="pill">${data.sample_count} 条验收</span></div>
      <p class="muted small">${esc(data.task_title)} · 客户 ${esc(data.customer_id)} · 执行者 ${esc(data.worker_id)}</p>
      <div class="classify-fields" style="margin-top:12px">
        <div class="classify-field"><span>权重上升</span><strong>${esc(DIM_LABELS[data.top_up] || data.top_up || "—")}</strong></div>
        <div class="classify-field"><span>权重下降</span><strong>${esc(DIM_LABELS[data.top_down] || data.top_down || "—")}</strong></div>
      </div>
      <div class="table-wrap" style="margin-top:12px">
        <table>
          <thead><tr><th>维度</th><th>之前</th><th>之后</th><th>变化</th></tr></thead>
          <tbody>${deltaRows}</tbody>
        </table>
      </div>
    </article>
    <article class="panel classify-card">
      <div class="panel-head"><h3>Top-5 排序变化</h3><span class="muted small">同一任务、同一客户</span></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>排名</th><th>执行者</th><th>分数</th><th>变化</th></tr></thead>
          <tbody>${rankingRows}</tbody>
        </table>
      </div>
      <div class="panel-head" style="margin-top:16px"><h3>验收轮次</h3></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>轮次</th><th>决策</th><th>总分</th><th>学习样本</th></tr></thead>
          <tbody>${roundRows}</tbody>
        </table>
      </div>
    </article>`;
}

async function loadTalentList() {
  try {
    const data = await api("/resumes?limit=30");
    state.talentList = data.items || [];
    const options = state.talentList.map((resume) => [
      resume.worker_id,
      `${resume.name} · ${resume.headline}`,
    ]);
    setOptions(
      $("#talent-select"),
      options,
      options.length ? null : "暂无候选人"
    );
    if (state.talentList.length) {
      $("#talent-select").value = state.talentList[0].worker_id;
      await loadTalentResume();
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

async function loadTalentResume() {
  const workerId = $("#talent-select").value;
  if (!workerId) return;
  try {
    state.talentResume = await api(`/workers/${workerId}/resume`);
    state.talentRawVisible = false;
    renderTalentResume();
  } catch (error) {
    toast(error.message, "error");
  }
}

function toggleTalentRaw() {
  if (!state.talentResume) return;
  state.talentRawVisible = !state.talentRawVisible;
  renderTalentResume();
}

function renderTalentResume() {
  if (!state.talentResume) return;
  const resume = state.talentResume.resume;
  const platform = state.talentResume.platform_data;
  const box = $("#talent-resume");

  const work = (resume.work_experience || [])
    .map(
      (item) => `
      <div class="resume-entry">
        <div class="resume-entry-head">
          <strong>${esc(item.company)}</strong>
          <span>${esc(item.title)}</span>
          <em>${esc(item.period)}</em>
        </div>
        <ul>${(item.bullets || []).map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
      </div>`
    )
    .join("");
  const projects = (resume.projects || [])
    .map(
      (item) => `
      <div class="resume-entry">
        <div class="resume-entry-head">
          <strong>${esc(item.name)}</strong>
          <span>${esc(item.role)}</span>
        </div>
        <ul>${(item.bullets || []).map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
      </div>`
    )
    .join("");
  const skills = (resume.skills || [])
    .map((item) => `<span class="resume-tag">${esc(item)}</span>`)
    .join("");
  const certifications = (resume.certifications || [])
    .map((item) => `<span class="resume-tag subtle">${esc(item)}</span>`)
    .join("");

  const skillRows = Object.entries(platform.skills || {})
    .sort((a, b) => b[1] - a[1])
    .map(
      ([key, value]) => `
      <tr>
        <td>${esc((platform.skill_labels || {})[key] || key)}</td>
        <td class="mono">${esc(key)}</td>
        <td><div class="bar-track"><div class="bar-fill" style="width:${Math.max(4, value * 20)}%"></div></div></td>
        <td class="mono">${value}</td>
      </tr>`
    )
    .join("");
  const specialties = Object.entries(platform.specialties || {})
    .map(([key, value]) => `${esc(CATEGORIES.find(([id]) => id === key)?.[1] || key)} ${value}`)
    .join(" · ");
  const categoryRatings = Object.entries(platform.category_ratings || {})
    .map(
      ([key, value]) =>
        `<tr><td>${esc(CATEGORIES.find(([id]) => id === key)?.[1] || key)}</td><td class="mono">${value}</td></tr>`
    )
    .join("");
  const averageRating = platform.ratings && platform.ratings.length
    ? (platform.ratings.reduce((sum, value) => sum + value, 0) / platform.ratings.length).toFixed(2)
    : "—";

  box.innerHTML = `
    <article class="resume-paper">
      <header class="resume-head">
        <div class="resume-avatar">${esc(resume.name.slice(0, 1))}</div>
        <div class="resume-identity">
          <h2>${esc(resume.name)}</h2>
          <p class="resume-headline">${esc(resume.headline)}</p>
          <div class="resume-meta">
            ${esc(resume.city)} · ${resume.years_experience} 年经验 · ${esc(resume.education)}
          </div>
        </div>
        <div class="resume-rate">
          <strong>${esc(resume.expected_rate)}</strong>
          <small>${esc(resume.availability)}</small>
        </div>
      </header>
      <p class="resume-summary">${esc(resume.summary)}</p>
      <div class="resume-stats">
        <div><span>完成项目</span><strong>${resume.stats.completed}</strong></div>
        <div><span>客户评分</span><strong>${fmt(resume.stats.rating, 1)}</strong></div>
        <div><span>按时交付</span><strong>${fmtPct(resume.stats.on_time_rate)}</strong></div>
        <div><span>返工率</span><strong>${fmtPct(resume.stats.rework_rate)}</strong></div>
      </div>
      <section class="resume-section">
        <h3>工作经历</h3>
        ${work}
      </section>
      <section class="resume-section">
        <h3>项目经历</h3>
        ${projects}
      </section>
      <section class="resume-section">
        <h3>技能标签</h3>
        <div class="resume-tags">${skills}</div>
      </section>
      <section class="resume-section">
        <h3>证书与认证</h3>
        <div class="resume-tags">${certifications || '<span class="muted small">暂无</span>'}</div>
      </section>
    </article>
    <section class="resume-raw ${state.talentRawVisible ? "" : "hidden"}">
      <div class="resume-raw-head">
        <div>
          <span class="eyebrow">PLATFORM VIEW</span>
          <h3>平台原始数据 · 默认隐藏</h3>
        </div>
        <span class="pill">${esc(platform.worker_id)}</span>
      </div>
      <div class="resume-raw-grid">
        <div class="classify-field"><span>内部等级</span><strong>L${platform.level}</strong></div>
        <div class="classify-field"><span>状态</span><strong>${esc(platform.status)}</strong></div>
        <div class="classify-field"><span>负载</span><strong>${platform.current_load_hours}/${platform.capacity_hours}h</strong></div>
        <div class="classify-field"><span>地区 / 协作</span><strong>${esc(platform.region)} · ${platform.remote_ok ? "远程" : "线下"}</strong></div>
        <div class="classify-field"><span>评分均值</span><strong>${averageRating}（${(platform.ratings || []).length} 次）</strong></div>
        <div class="classify-field"><span>完成 / 按时</span><strong>${platform.completed} / ${platform.on_time}</strong></div>
        <div class="classify-field"><span>返工 / 违约</span><strong>${platform.rework_count} / ${(platform.breach_dates || []).length}</strong></div>
        <div class="classify-field"><span>专长</span><strong>${specialties || "—"}</strong></div>
      </div>
      <div class="resume-raw-columns">
        <div>
          <h4>内部技能分</h4>
          <div class="table-wrap">
            <table>
              <thead><tr><th>技能</th><th>Key</th><th>分数</th><th>值</th></tr></thead>
              <tbody>${skillRows}</tbody>
            </table>
          </div>
        </div>
        <div>
          <h4>分类评分</h4>
          <div class="table-wrap">
            <table>
              <thead><tr><th>类别</th><th>评分</th></tr></thead>
              <tbody>${categoryRatings || '<tr><td colspan="2" class="muted">暂无</td></tr>'}</tbody>
            </table>
          </div>
          <h4 style="margin-top:14px">违约日期</h4>
          <p class="muted small">${platform.breach_dates && platform.breach_dates.length ? platform.breach_dates.map(fmtDate).join("、") : "无"}</p>
        </div>
      </div>
    </section>`;

  $("#talent-toggle").textContent = state.talentRawVisible
    ? "隐藏平台原始数据"
    : "查看平台原始数据";
}

async function runBenchmark() {
  const button = $("#benchmark-run");
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "运行中…";
  try {
    const data = await api("/benchmark/run?rounds=20", { method: "POST" });
    const rows = data.results.map((item) => ({
      ...item.metrics,
      round: item.round,
      updates: item.updates,
      forgot: item.forgot_previous_answers,
    }));
    renderBenchmark(rows, data);
    toast("20 轮完成：先对答案，再学习，下一轮清空推荐缓存");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

async function loadBenchmarkSummary() {
  try {
    const data = await api("/benchmark/summary");
    renderBenchmark(data.rounds || [], data);
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderBenchmark(rows, payload) {
  const statsBox = $("#benchmark-stats");
  if (!rows.length) {
    statsBox.innerHTML = "";
    $("#benchmark-meta").textContent = "还没有运行记录";
    $("#benchmark-chart").innerHTML =
      '<div class="empty">先点“跑 20 轮对答案学习”</div>';
    $("#benchmark-table").innerHTML = "";
    return;
  }

  const first = rows[0];
  const last = rows[rows.length - 1];
  const stat = (label, value) =>
    `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
  statsBox.innerHTML = [
    stat("第 1 轮 Top-1", fmt(first.top1, 3)),
    stat("最终 Top-1", fmt(last.top1, 3)),
    stat("最终 Top-5", fmt(last.top5, 3)),
    stat("测试集 Top-1", fmt(last.test_top1, 3)),
  ].join("");
  $("#benchmark-meta").textContent =
    `${payload.tasks || 1000} 任务 · ${payload.workers || 100} worker · ${rows.length} 轮`;

  renderBenchmarkChart($("#benchmark-chart"), rows);

  $("#benchmark-table").innerHTML = `
    <table>
      <thead>
        <tr><th>轮次</th><th>Top-1</th><th>Top-5</th><th>MRR</th><th>NDCG@5</th><th>测试 Top-1</th><th>更新数</th><th>遗忘答案</th></tr>
      </thead>
      <tbody>${rows
        .map(
          (row) => `
        <tr>
          <td>R${row.round}</td>
          <td class="mono">${fmt(row.top1, 3)}</td>
          <td class="mono">${fmt(row.top5, 3)}</td>
          <td class="mono">${fmt(row.mrr, 3)}</td>
          <td class="mono">${fmt(row.ndcg, 3)}</td>
          <td class="mono">${fmt(row.test_top1, 3)}</td>
          <td class="mono">${row.updates ?? "—"}</td>
          <td>${row.forgot === undefined ? "—" : row.forgot ? "是" : "否"}</td>
        </tr>`
        )
        .join("")}</tbody>
    </table>`;
}

function renderBenchmarkChart(container, rows) {
  container.innerHTML = "";
  const width = 760;
  const height = 300;
  const pad = { left: 52, right: 20, top: 28, bottom: 38 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const count = rows.length;
  const x = (index) =>
    pad.left + (count === 1 ? innerW / 2 : (index * innerW) / (count - 1));
  const y = (value) =>
    pad.top + (1 - Math.max(0, Math.min(1, Number(value) || 0))) * innerH;
  const svgNS = "http://www.w3.org/2000/svg";
  const make = (tag, attributes = {}, text = null) => {
    const node = document.createElementNS(svgNS, tag);
    Object.entries(attributes).forEach(([key, value]) =>
      node.setAttribute(key, value)
    );
    if (text !== null) node.textContent = text;
    return node;
  };

  const legend = document.createElement("div");
  legend.className = "chart-legend";
  legend.innerHTML =
    '<span><i class="swatch blue"></i>Top-1</span>' +
    '<span><i class="swatch teal"></i>Top-5</span>' +
    '<span><i class="swatch amber"></i>测试集 Top-1</span>';
  container.appendChild(legend);

  const svg = make("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": "对答案学习命中率曲线",
  });
  for (let index = 0; index <= 4; index += 1) {
    const ratio = index / 4;
    const lineY = pad.top + ratio * innerH;
    svg.appendChild(
      make("line", {
        class: "chart-grid",
        x1: pad.left,
        y1: lineY,
        x2: width - pad.right,
        y2: lineY,
      })
    );
    svg.appendChild(
      make(
        "text",
        {
          class: "chart-label",
          x: pad.left - 8,
          y: lineY + 3,
          "text-anchor": "end",
        },
        fmt(1 - ratio, 2)
      )
    );
  }

  const series = [
    { key: "top1", label: "Top-1", color: "var(--accent)", dash: "" },
    { key: "top5", label: "Top-5", color: "var(--accent-2)", dash: "" },
    {
      key: "test_top1",
      label: "测试集 Top-1",
      color: "var(--amber)",
      dash: "6 4",
    },
  ];
  series.forEach((item) => {
    const points = rows
      .map((row, index) => `${x(index)},${y(row[item.key])}`)
      .join(" ");
    const line = make("polyline", {
      class: "chart-line",
      points,
      fill: "none",
    });
    line.style.stroke = item.color;
    line.style.strokeDasharray = item.dash;
    svg.appendChild(line);
    rows.forEach((row, index) => {
      const point = make("circle", {
        class: "chart-point",
        cx: x(index),
        cy: y(row[item.key]),
        r: 3.4,
      });
      point.style.fill = item.color;
      point.appendChild(
        make(
          "title",
          {},
          `R${row.round} · ${item.label} ${fmt(row[item.key], 3)}`
        )
      );
      svg.appendChild(point);
    });
  });

  rows.forEach((row, index) => {
    if (count > 10 && index % 2 === 1) return;
    svg.appendChild(
      make(
        "text",
        {
          class: "chart-label",
          x: x(index),
          y: height - 14,
          "text-anchor": "middle",
        },
        `R${row.round}`
      )
    );
  });
  container.appendChild(svg);
}

async function runTaskRecommendations() {
  const taskId = $("#t2w-task").value;
  if (!taskId) return toast("请选择任务", "error");
  const topN = Math.max(1, Number($("#t2w-topn").value || 5));
  try {
    const data = await api("/recommend/workers", {
      method: "POST",
      body: JSON.stringify({ task_id: taskId, top_n: topN, user_id: null }),
    });
    renderCandidates($("#t2w-results"), data.candidates, "task", taskId, {
      requestId: data.request_id,
    });
    $("#t2w-adopt").innerHTML = "";
    if (!data.candidates.length) {
      toast("没有符合条件的候选人", "error");
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

async function runWorkerRecommendations() {
  const workerId = $("#w2t-worker").value;
  if (!workerId) return toast("请选择 Worker", "error");
  const topN = Math.max(1, Number($("#w2t-topn").value || 5));
  try {
    const data = await api("/recommend/tasks", {
      method: "POST",
      body: JSON.stringify({ worker_id: workerId, top_n: topN, user_id: null }),
    });
    renderCandidates($("#w2t-results"), data.candidates, "worker", workerId, {
      requestId: data.request_id,
    });
    $("#w2t-adopt").innerHTML = "";
    if (!data.candidates.length) {
      toast("没有符合条件的任务", "error");
    }
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderCandidates(container, candidates, mode, queryId, options = {}) {
  container.innerHTML = "";
  if (!candidates || !candidates.length) {
    container.innerHTML = '<div class="empty">暂无候选</div>';
    return;
  }
  candidates.forEach((candidate, index) => {
    const card = document.createElement("article");
    card.className = "candidate";
    const badges = [];
    if (candidate.cold_start) badges.push('<span class="badge cold">冷启动</span>');
    if (candidate.propensity !== undefined && candidate.propensity < 0.99) {
      badges.push(`<span class="badge explore">探索 p=${fmt(candidate.propensity, 2)}</span>`);
    }
    if (!candidate.cold_start && candidate.breakdown && candidate.breakdown.reputation < 0.5) {
      badges.push('<span class="badge warn">信誉偏低</span>');
    }
    const bars = Object.keys(DIM_LABELS)
      .filter((key) => candidate.breakdown && candidate.breakdown[key] !== undefined)
      .map((key) => {
        const value = Number(candidate.breakdown[key] || 0);
        return `
          <div class="bar-row">
            <div class="bar-label">${DIM_LABELS[key]}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, value * 100)}%"></div></div>
            <div class="bar-value">${fmt(value, 2)}</div>
          </div>`;
      })
      .join("");
    const reasons = (candidate.reasons || [])
      .map((reason) => `<span class="reason">${esc(reason)}</span>`)
      .join("");
    const candidateTask =
      mode === "worker"
        ? state.tasks.find((task) => task.task_id === candidate.candidate_id)
        : null;
    const candidateWorker =
      mode === "task"
        ? state.workers.find((worker) => worker.worker_id === candidate.candidate_id)
        : null;
    const heading = candidateTask
      ? `<strong>${esc(candidateTask.title)}</strong>
         <span class="candidate-sub">${fmtMoney(candidateTask.budget_min)}–${fmtMoney(candidateTask.budget_max)} · 截止 ${fmtDate(candidateTask.deadline)}</span>`
      : candidateWorker
        ? `<strong>${esc(candidateWorker.name || candidateWorker.worker_id)}</strong>
           <span class="candidate-sub">${esc(REGION_LABELS[candidateWorker.region] || candidateWorker.region)} · L${candidateWorker.level}</span>`
        : `<strong>${esc(candidate.candidate_id)}</strong>`;
    const allowAdopt = options.allowAdopt !== false;
    const adoptButton = allowAdopt
      ? '<button class="btn primary adopt-btn">采纳并评分</button>'
      : "";
    const rejectButton = allowAdopt
      ? '<button class="btn danger-ghost reject-btn">不感兴趣</button>'
      : "";
    // ``mode`` is the recommendation query type; the candidate is the other
    // side: task -> workers recommends workers, worker -> tasks recommends tasks.
    const candidateType = mode === "task" ? "worker" : "task";
    const requestId = options.requestId || "";
    card.innerHTML = `
      <div class="candidate-head">
        <span class="rank">#${index + 1}</span>
        ${heading}
        <span class="score">${fmt(candidate.score)}</span>
      </div>
      <div class="badges">${badges.join("") || '<span class="badge">常规候选</span>'}</div>
      <div class="breakdown">${bars}</div>
      <div class="reasons">${reasons}</div>
      <div class="candidate-actions">${adoptButton}${rejectButton}</div>`;
    card.querySelector(".candidate-head").addEventListener("click", () => {
      postRecommendationEvent(
        requestId,
        candidate.candidate_id,
        candidateType,
        "click"
      );
    });
    if (allowAdopt) {
      card.querySelector(".adopt-btn").addEventListener("click", () =>
        adoptCandidate(mode, queryId, candidate, requestId)
      );
      card.querySelector(".reject-btn").addEventListener("click", async () => {
        await postRecommendationEvent(
          requestId,
          candidate.candidate_id,
          candidateType,
          "reject"
        );
        card.classList.add("rejected");
        toast("已记录不感兴趣");
      });
    }
    container.appendChild(card);
  });
}

async function adoptCandidate(mode, queryId, candidate, requestId = "") {
  const taskId = mode === "task" ? queryId : candidate.candidate_id;
  const workerId = mode === "task" ? candidate.candidate_id : queryId;
  const task = state.tasks.find((item) => item.task_id === taskId);
  try {
    const candidateType = mode === "task" ? "worker" : "task";
    await postRecommendationEvent(
      requestId,
      candidate.candidate_id,
      candidateType,
      "apply"
    );
    const assignment = await api("/assignments", {
      method: "POST",
      body: JSON.stringify({
        task_id: taskId,
        worker_id: workerId,
        customer_id: task ? task.customer_id : "c0001",
        recommendation_context: {
          score: candidate.score,
          rank: 1,
          propensity: candidate.propensity ?? 1.0,
          weights_version: state.weights ? state.weights.version : "v0000",
          // Required for the server-side auto-accept event.
          request_id: requestId,
        },
      }),
    });
    state.pendingAdopt = {
      assignmentId: assignment.assignment_id,
      taskId,
      workerId,
    };
    const slot = mode === "task" ? $("#t2w-adopt") : $("#w2t-adopt");
    renderFeedbackBox(slot, assignment.assignment_id, `${taskId} → ${workerId}`);
    toast("已创建分配，请提交客户评分");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderFeedbackBox(slot, assignmentId, label) {
  state.rating = 0;
  slot.innerHTML = `
    <div class="feedback-box">
      <h4>客户评分</h4>
      <div class="muted small">${esc(label)}</div>
      <div class="stars">
        ${[1, 2, 3, 4, 5]
          .map((value) => `<button class="star" data-rating="${value}">${value}</button>`)
          .join("")}
      </div>
      <textarea id="feedback-comment" placeholder="可选评语"></textarea>
      <button id="submit-feedback" class="btn primary" style="margin-top:10px;width:100%">提交评分并学习</button>
    </div>`;
  $$(".star", slot).forEach((button) => {
    button.addEventListener("click", () => {
      state.rating = Number(button.dataset.rating);
      $$(".star", slot).forEach((item) =>
        item.classList.toggle("active", Number(item.dataset.rating) <= state.rating)
      );
    });
  });
  $("#submit-feedback", slot).addEventListener("click", async () => {
    if (!state.rating) return toast("请选择 1–5 分", "error");
    try {
      const response = await api("/feedback", {
        method: "POST",
        body: JSON.stringify({
          assignment_id: assignmentId,
          overall_rating: state.rating,
          quality_rating: state.rating,
          comment: $("#feedback-comment", slot).value || "",
        }),
      });
      const version = response.new_version ? `，个人权重 ${response.new_version}` : "";
      toast(`评分已提交${version}`, "ok");
      slot.innerHTML = `<div class="feedback-box"><h4>已学习</h4><p class="muted small">评分 ${state.rating} 已写回信誉、偏好与个人权重。${response.weights_updated ? " 权重已更新。" : ""}</p></div>`;
      await refreshWeights();
    } catch (error) {
      toast(error.message, "error");
    }
  });
}

async function onboard() {
  const type = $("#onboard-type").value;
  const userId = $("#onboard-id").value.trim();
  if (!userId) return toast("请输入用户 ID", "error");
  try {
    const response = await api(`/${type === "worker" ? "workers" : "customers"}/${encodeURIComponent(userId)}/onboarding`, {
      method: "POST",
      body: JSON.stringify({
        role: $("#onboard-role").value || "unknown",
        industry: $("#onboard-industry").value || "unknown",
        experience_years: Number($("#onboard-years").value || 0),
      }),
    });
    state.profileUser = { id: userId, type };
    renderWeightBars($("#onboard-result"), response.weights);
    $("#curve-meta").textContent = `source: ${response.source} · confidence: ${fmt(response.confidence, 2)}`;
    toast(`初始权重已生成（${response.source}）`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function loadCurve() {
  if (!state.profileUser) return toast("先生成画像权重", "error");
  if (state.profileUser.type !== "worker") {
    $("#learning-curve").innerHTML = '<div class="empty">当前仅 worker 提供学习曲线接口</div>';
    return;
  }
  try {
    const rows = await api(`/workers/${encodeURIComponent(state.profileUser.id)}/learning-curve`);
    if (!rows.length) {
      $("#learning-curve").innerHTML = '<div class="empty">暂无快照；提交一条反馈后再看</div>';
      return;
    }
    $("#learning-curve").innerHTML = `
      <table>
        <thead><tr><th>n</th><th>NDCG@10</th><th>HR@10</th><th>Regret</th></tr></thead>
        <tbody>${rows
          .map(
            (row) => `<tr><td class="mono">${row.n_feedback}</td><td>${fmt(row.ndcg_at_10)}</td><td>${fmt(row.hr_at_10)}</td><td>${fmt(row.regret)}</td></tr>`
          )
          .join("")}</tbody>
      </table>`;
  } catch (error) {
    toast(error.message, "error");
  }
}

async function showDiff() {
  const from = $("#diff-from").value.trim();
  const to = $("#diff-to").value.trim();
  if (!from || !to) return toast("请填写两个版本", "error");
  try {
    const diff = await api(`/weights/diff?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
    const rows = Object.entries(diff)
      .map(([key, value]) => {
        const delta = Number(value.delta || 0);
        const color = delta > 0 ? "var(--accent-2)" : delta < 0 ? "var(--danger)" : "var(--muted)";
        return `<tr><td>${DIM_LABELS[key] || key}</td><td class="mono">${fmt(value.from)}</td><td class="mono">${fmt(value.to)}</td><td class="mono" style="color:${color}">${delta >= 0 ? "+" : ""}${fmt(delta)}</td></tr>`;
      })
      .join("");
    $("#diff-result").innerHTML = `<table><thead><tr><th>维度</th><th>From</th><th>To</th><th>Δ</th></tr></thead><tbody>${rows}</tbody></table>`;
  } catch (error) {
    toast(error.message, "error");
  }
}

async function rollbackWeights() {
  try {
    await api("/weights/rollback", {
      method: "POST",
      body: JSON.stringify({ to_version: "v0000", reason: "前端演示回滚" }),
    });
    await refreshWeights();
    toast("已回滚到 v0000", "ok");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function recomputeWeights() {
  try {
    const version = await api("/weights/recompute", { method: "POST" });
    await refreshWeights();
    toast(`已生成 ${version.version}（${version.sample_count} 条反馈）`, "ok");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderChain() {
  const chain = state.chain;
  if (!chain) return;
  $("#chain-summary").classList.remove("hidden");
  $("#chain-nodes").textContent = chain.nodes.length;
  const quality = chain.quality || {};
  $("#chain-quality").textContent = quality.total !== undefined ? fmt(quality.total) : "—";
  $("#chain-critical").textContent = (chain.critical_path || []).join(" → ") || "—";
  const rows = chain.nodes
    .map((node) => {
      const skills = Object.entries(node.required_skills || {})
        .map(([key, value]) => `${key}:${value}`)
        .join(", ");
      return `<tr>
        <td class="mono">${esc(node.key)}</td>
        <td>${esc(node.title)}</td>
        <td>${esc(node.node_type)}</td>
        <td class="mono">${node.estimated_hours}h</td>
        <td>${esc(skills || "—")}</td>
        <td>${esc((node.depends_on || []).join(", ") || "—")}</td>
        <td>${esc(node.status || "pending")}</td>
      </tr>`;
    })
    .join("");
  $("#chain-node-table").innerHTML = `<table><thead><tr><th>Key</th><th>标题</th><th>类型</th><th>工时</th><th>技能</th><th>依赖</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table>`;
  const nodeOptions = chain.nodes.map((node) => [node.key, `${node.key} · ${node.title}`]);
  setOptions($("#replan-failed"), nodeOptions);
  setOptions($("#replan-locked"), nodeOptions);
  setOptions($("#status-node"), nodeOptions);
  if (!state.plan) {
    $("#plan-table").innerHTML = '<div class="empty">尚未生成计划</div>';
  }
}

function renderPlan() {
  const plan = state.plan;
  if (!plan) {
    $("#plan-table").innerHTML = '<div class="empty">尚未生成计划</div>';
    return;
  }
  $("#chain-plan-version").textContent = plan.version || "—";
  $("#plan-meta").textContent = `${plan.planner || "greedy"} · score ${fmt(plan.score)} · blocked ${plan.blocked ? plan.blocked.length : 0}`;
  const rows = (plan.nodes || [])
    .map(
      (node) => `<tr>
        <td class="mono">${esc(node.subtask_id)}</td>
        <td class="mono">${esc(node.worker_id || "blocked")}</td>
        <td>${esc(node.rank ?? "—")}</td>
        <td>${fmt(node.node_score)}</td>
      </tr>`
    )
    .join("");
  $("#plan-table").innerHTML = `<table><thead><tr><th>Subtask</th><th>Worker</th><th>Rank</th><th>Score</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function decomposeChain() {
  const taskId = $("#chain-task").value;
  if (!taskId) return toast("请选择任务", "error");
  const mode = $("#chain-mode").value;
  const categories = selectedCategories();
  if (mode === "compose" && !categories.length) {
    return toast("组合模式至少选择一个类别", "error");
  }
  try {
    const response = await api("/chains/decompose", {
      method: "POST",
      body: JSON.stringify({
        task_id: taskId,
        mode,
        variant: $("#chain-variant").value,
        categories: mode === "compose" ? categories : null,
      }),
    });
    state.chain = response;
    state.plan = null;
    renderChain();
    renderPlan();
    toast(`已拆解 ${response.nodes.length} 个节点`, "ok");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function planChain() {
  if (!state.chain) return toast("先拆解任务链", "error");
  try {
    const plan = await api(`/chains/${state.chain.chain_id}/plan`, { method: "POST" });
    state.plan = plan;
    renderPlan();
    await loadPlanVersions();
    toast(`计划 ${plan.version} 已生成（${plan.planner || "greedy"}）`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function loadPlanVersions() {
  if (!state.chain) return;
  try {
    const versions = await api(`/chains/${state.chain.chain_id}/plans`);
    if (!versions.length) {
      $("#plan-versions").innerHTML = '<div class="empty">暂无版本</div>';
      return;
    }
    const rows = versions
      .map(
        (item) => `<tr>
          <td class="mono">v${item.version}</td>
          <td class="mono">${esc(item.plan.plan_id.slice(0, 8))}</td>
          <td>${esc(item.plan.planner || "—")}</td>
          <td>${fmt(item.plan.score)}</td>
          <td><button class="btn ghost" data-plan-version="${item.version}">回滚</button></td>
        </tr>`
      )
      .join("");
    $("#plan-versions").innerHTML = `<table><thead><tr><th>版本</th><th>计划</th><th>规划器</th><th>分数</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
    $$("[data-plan-version]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          const response = await api(`/chains/${state.chain.chain_id}/plan/rollback`, {
            method: "POST",
            body: JSON.stringify({ version: Number(button.dataset.planVersion) }),
          });
          state.plan = { ...response.plan, version: response.version };
          renderPlan();
          toast(`已回滚到计划 v${response.version}`);
        } catch (error) {
          toast(error.message, "error");
        }
      });
    });
  } catch (error) {
    toast(error.message, "error");
  }
}

async function replanChain() {
  if (!state.chain) return toast("先拆解任务链", "error");
  try {
    const locked = $$("#replan-locked option:checked").map((option) => option.value);
    const response = await api(`/chains/${state.chain.chain_id}/replan`, {
      method: "POST",
      body: JSON.stringify({
        failed_node: $("#replan-failed").value,
        delay_hours: Number($("#replan-delay").value || 0),
        locked_nodes: locked,
      }),
    });
    state.plan = response;
    renderPlan();
    await loadPlanVersions();
    $("#replan-result").textContent =
      `已生成 v${response.version}；affected: ${(response.affected_nodes || []).join(", ") || "—"}；replanned: ${(response.replanned || []).join(", ") || "—"}`;
    toast("重规划完成");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function updateNodeStatus() {
  if (!state.chain) return toast("先拆解任务链", "error");
  const node = $("#status-node").value;
  const status = $("#status-value").value;
  const worker = $("#status-worker").value.trim();
  try {
    await api(`/chains/${state.chain.chain_id}/nodes/${encodeURIComponent(node)}/status`, {
      method: "POST",
      body: JSON.stringify({ status, worker_id: worker || null }),
    });
    const target = state.chain.nodes.find((item) => item.key === node);
    if (target) {
      target.status = status;
      if (worker) target.assigned_worker_id = worker;
    }
    renderChain();
    toast(`节点 ${node} → ${status}`);
  } catch (error) {
    toast(error.message, "error");
  }
}

function barsHtml(weights) {
  return Object.keys(DIM_LABELS)
    .filter((key) => weights[key] !== undefined)
    .map((key) => {
      const value = Number(weights[key] || 0);
      return `
        <div class="bar-row">
          <div class="bar-label">${DIM_LABELS[key]}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, value * 100)}%"></div></div>
          <div class="bar-value">${fmt(value, 2)}</div>
        </div>`;
    })
    .join("");
}

function rankingHtml(candidates, otherIds) {
  return candidates
    .map((candidate, index) => {
      const unique = otherIds && !otherIds.has(candidate.candidate_id);
      return `
        <div class="rank-row ${unique ? "rank-diff" : ""}">
          <span class="rank">#${index + 1}</span>
          <b>${esc(candidate.candidate_id)}</b>
          <span class="score">${fmt(candidate.score)}</span>
          ${unique ? '<span class="diff-tag">仅此选择</span>' : ""}
        </div>`;
    })
    .join("");
}

function cosineSimilarity(a, b) {
  const keys = Object.keys(DIM_LABELS);
  const dot = keys.reduce((sum, key) => sum + (a[key] || 0) * (b[key] || 0), 0);
  const normA = Math.sqrt(keys.reduce((sum, key) => sum + (a[key] || 0) ** 2, 0));
  const normB = Math.sqrt(keys.reduce((sum, key) => sum + (b[key] || 0) ** 2, 0));
  return normA > 0 && normB > 0 ? dot / (normA * normB) : 0;
}

async function resetOnboarding(workerId, preference) {
  return api(`/workers/${encodeURIComponent(workerId)}/onboarding`, {
    method: "POST",
    body: JSON.stringify({
      role: "engineer",
      industry: "software",
      experience_years: 2,
      preferences: { [preference]: 1.0 },
      reset: true,
    }),
  });
}

async function recommendForUser(taskId, workerId, topN = 5) {
  return api("/recommend/workers", {
    method: "POST",
    body: JSON.stringify({ task_id: taskId, top_n: topN, user_id: workerId }),
  });
}

async function growthProfilesFor(taskId, workerId, preferenceA, preferenceB) {
  const profileA = await resetOnboarding(workerId, preferenceA);
  const recA = await recommendForUser(taskId, workerId);
  const profileB = await resetOnboarding(workerId, preferenceB);
  const recB = await recommendForUser(taskId, workerId);
  return { profileA, recA, profileB, recB };
}

function rankingKey(rec) {
  return rec.candidates.map((item) => item.candidate_id).join("|");
}

async function growthCompare() {
  const workerId = $("#growth-worker").value.trim();
  const selectedTaskId = $("#growth-task").value;
  const preferenceA = $("#growth-pref-a").value;
  const preferenceB = $("#growth-pref-b").value;
  if (!workerId || !selectedTaskId) return toast("请填写用户 ID 并选择任务", "error");
  try {
    let taskId = selectedTaskId;
    let result = await growthProfilesFor(
      taskId,
      workerId,
      preferenceA,
      preferenceB
    );
    let autoSwitched = false;
    if (rankingKey(result.recA) === rankingKey(result.recB)) {
      for (const task of openTasks()) {
        if (task.task_id === selectedTaskId) continue;
        const candidateResult = await growthProfilesFor(
          task.task_id,
          workerId,
          preferenceA,
          preferenceB
        );
        if (rankingKey(candidateResult.recA) !== rankingKey(candidateResult.recB)) {
          taskId = task.task_id;
          result = candidateResult;
          autoSwitched = true;
          $("#growth-task").value = taskId;
          break;
        }
      }
    }
    const { profileA, recA, profileB, recB } = result;
    const idsA = new Set(recA.candidates.map((item) => item.candidate_id));
    const idsB = new Set(recB.candidates.map((item) => item.candidate_id));
    const onlyA = recA.candidates.filter((item) => !idsB.has(item.candidate_id)).length;
    const onlyB = recB.candidates.filter((item) => !idsA.has(item.candidate_id)).length;
    $("#growth-output").innerHTML = `
      <div class="growth-grid">
        <div class="growth-card">
          <div class="growth-card-head"><h4>初始选择 A<small>${PREF_LABELS[preferenceA]}</small></h4><span class="pill">${profileA.source}</span></div>
          <div class="bars">${barsHtml(profileA.weights)}</div>
          <div class="ranking">${rankingHtml(recA.candidates, idsB)}</div>
        </div>
        <div class="growth-card">
          <div class="growth-card-head"><h4>初始选择 B<small>${PREF_LABELS[preferenceB]}</small></h4><span class="pill">${profileB.source}</span></div>
          <div class="bars">${barsHtml(profileB.weights)}</div>
          <div class="ranking">${rankingHtml(recB.candidates, idsA)}</div>
        </div>
      </div>
      <div class="growth-stats">
        <div class="growth-stat"><span>仅 A 出现的候选人</span><strong>${onlyA}</strong></div>
        <div class="growth-stat"><span>仅 B 出现的候选人</span><strong>${onlyB}</strong></div>
        <div class="growth-stat"><span>权重差异 cosine</span><strong>${fmt(cosineSimilarity(profileA.weights, profileB.weights), 3)}</strong></div>
      </div>
      <p class="growth-note">同一任务（${esc(taskId)}）、同一候选池、同一个用户；只改变初始偏好，权重与 Top-N 就会不同。橙色行表示只在该选择下进入前 5。${autoSwitched ? " 当前任务对偏好不敏感，已自动切换到差异更明显的任务。" : ""}</p>`;
    toast("两种初始选择对比完成");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function growthLearn() {
  const workerId = $("#growth-worker").value.trim();
  const taskId = $("#growth-task").value;
  const targetPreference = $("#growth-pref-a").value;
  const wrongPreference = $("#growth-pref-b").value;
  if (!workerId || !taskId) return toast("请填写用户 ID 并选择任务", "error");
  try {
    const target = await resetOnboarding(workerId, targetPreference);
    const initial = await resetOnboarding(workerId, wrongPreference);
    const before = await recommendForUser(taskId, workerId);

    let completed = 0;
    let attempted = 0;
    for (const task of openTasks()) {
      if (completed >= 12 || attempted >= 36) break;
      attempted += 1;
      try {
        const assignment = await api("/assignments", {
          method: "POST",
          body: JSON.stringify({
            task_id: task.task_id,
            worker_id: workerId,
            customer_id: task.customer_id,
            recommendation_context: {
              score: 0.5,
              rank: 1,
              propensity: 1.0,
              weights_version: state.weights.version,
            },
          }),
        });
        await api("/feedback", {
          method: "POST",
          body: JSON.stringify({
            assignment_id: assignment.assignment_id,
            overall_rating: 5,
            quality_rating: 5,
            comment: "growth demo correction",
          }),
        });
        completed += 1;
      } catch (error) {
        if (!/already|已|409/.test(error.message)) throw error;
      }
    }

    const after = await api(`/workers/${encodeURIComponent(workerId)}/weight-profile`);
    const afterRecommendation = await recommendForUser(taskId, workerId);
    const curve = await api(`/workers/${encodeURIComponent(workerId)}/learning-curve`);
    const cosineBefore = cosineSimilarity(initial.weights, target.weights);
    const cosineAfter = cosineSimilarity(after.weights, target.weights);
    const changed = before.candidates.filter(
      (candidate, index) =>
        !afterRecommendation.candidates[index] ||
        afterRecommendation.candidates[index].candidate_id !== candidate.candidate_id
    ).length;

    $("#growth-output").innerHTML = `
      <div class="growth-grid">
        <div class="growth-card">
          <div class="growth-card-head"><h4>修正前<small>初始 B：${PREF_LABELS[wrongPreference]}</small></h4><span class="pill">n=${initial.sample_count}</span></div>
          <div class="bars">${barsHtml(initial.weights)}</div>
          <div class="ranking">${rankingHtml(before.candidates)}</div>
        </div>
        <div class="growth-card">
          <div class="growth-card-head"><h4>反馈修正后<small>目标 A：${PREF_LABELS[targetPreference]}</small></h4><span class="pill">n=${after.sample_count}</span></div>
          <div class="bars">${barsHtml(after.weights)}</div>
          <div class="ranking">${rankingHtml(afterRecommendation.candidates)}</div>
        </div>
      </div>
      <div class="growth-stats">
        <div class="growth-stat"><span>已完成反馈</span><strong>${completed}</strong></div>
        <div class="growth-stat"><span>与真实偏好 cosine</span><strong>${fmt(cosineBefore, 3)} → ${fmt(cosineAfter, 3)}</strong></div>
        <div class="growth-stat"><span>Top-N 排名变化</span><strong>${changed}</strong></div>
      </div>
      <p class="growth-note">用 B（${PREF_LABELS[wrongPreference]}）起步，再提交 ${completed} 条 5 分反馈；个人权重从 B 向目标 A（${PREF_LABELS[targetPreference]}）移动，Top-N 随之调整。个人学习快照：${curve.length} 条。</p>`;
    toast(`完成 ${completed} 条反馈，权重已修正`);
  } catch (error) {
    toast(error.message, "error");
  }
}

function demoLog(message, kind = "info") {
  const log = $("#demo-log");
  const time = new Date().toLocaleTimeString();
  const prefix = kind === "error" ? "✗" : kind === "ok" ? "✓" : "·";
  log.textContent += `\n[${time}] ${prefix} ${message}`;
  log.scrollTop = log.scrollHeight;
}

async function runDemo() {
  $("#demo-log").textContent = "TaskTok demo start";
  const step = async (label, fn, display = (value) => value) => {
    try {
      const result = await fn();
      const shown = display(result);
      demoLog(`${label}${shown ? ` → ${shown}` : ""}`, "ok");
      return result;
    } catch (error) {
      demoLog(`${label} → ${error.message}`, "error");
      throw error;
    }
  };
  try {
    await step("health", async () => {
      const health = await api("/health");
      return `v${health.version}`;
    });
    const tasks = await api("/tasks");
    const workers = await api("/workers");
    demoLog(`loaded ${tasks.length} tasks / ${workers.length} workers`);
    const open = tasks.filter((task) => task.status === "open");
    if (!open.length) throw new Error("no open tasks");
    const task = open[0];
    const recommendation = await step("recommend workers", async () => {
      const data = await api("/recommend/workers", {
        method: "POST",
        body: JSON.stringify({ task_id: task.task_id, top_n: 5 }),
      });
      return data.candidates.map((item) => `${item.candidate_id}:${fmt(item.score, 2)}`).join(" | ");
    });
    const candidates = await api("/recommend/workers", {
      method: "POST",
      body: JSON.stringify({ task_id: task.task_id, top_n: 5 }),
    });
    let assignment = null;
    for (const candidate of candidates.candidates) {
      try {
        assignment = await api("/assignments", {
          method: "POST",
          body: JSON.stringify({
            task_id: task.task_id,
            worker_id: candidate.candidate_id,
            customer_id: task.customer_id,
            recommendation_context: {
              score: candidate.score,
              rank: 1,
              propensity: candidate.propensity,
              weights_version: state.weights.version,
            },
          }),
        });
        break;
      } catch (error) {
        if (!/已|already|409/.test(error.message)) throw error;
      }
    }
    if (!assignment) throw new Error("could not create assignment (all candidates assigned)");
    demoLog(`assignment ${assignment.assignment_id.slice(0, 8)} → ${assignment.worker_id}`, "ok");
    const feedback = await step("feedback rating 5", async () => {
      const response = await api("/feedback", {
        method: "POST",
        body: JSON.stringify({
          assignment_id: assignment.assignment_id,
          overall_rating: 5,
          quality_rating: 5,
          comment: "demo",
        }),
      });
      return response.new_version ? `personal ${response.new_version}` : "reputation updated";
    });
    await step("personal weight", async () => {
      const profile = await api(
        `/workers/${encodeURIComponent(assignment.worker_id)}/weight-profile`
      );
      return `${profile.version} · n=${profile.sample_count}`;
    });
    await step("recompute global weights", async () => {
      const version = await api("/weights/recompute", { method: "POST" });
      state.weights = await api("/weights");
      return `${version.version} · n=${version.sample_count}`;
    });
    const weights = state.weights || (await api("/weights"));
    demoLog(`weight version ${weights.version} · sample ${weights.sample_count}`);
    await step("weights diff", async () => {
      const diff = await api(`/weights/diff?from=v0000&to=${weights.version}`);
      return Object.entries(diff)
        .filter(([, value]) => Math.abs(value.delta) > 1e-9)
        .map(([key, value]) => `${key}${value.delta > 0 ? "+" : ""}${fmt(value.delta)}`)
        .join(", ");
    });
    const chain = await step(
      "decompose chain",
      async () => {
        const response = await api("/chains/decompose", {
          method: "POST",
          body: JSON.stringify({ task_id: task.task_id, mode: "template" }),
        });
        state.chain = response;
        return response;
      },
      (response) => `${response.nodes.length} nodes`
    );
    await step(
      "plan chain",
      async () => {
        const response = await api(`/chains/${chain.chain_id}/plan`, { method: "POST" });
        state.plan = response;
        return response;
      },
      (response) => `v${response.version} ${response.planner || "greedy"}`
    );
    if (chain.critical_path && chain.critical_path.length > 1) {
      await step(
        "replan",
        async () => {
          const response = await api(`/chains/${chain.chain_id}/replan`, {
            method: "POST",
            body: JSON.stringify({
              failed_node: chain.critical_path[1],
              delay_hours: 4,
              locked_nodes: [chain.nodes[0].key],
            }),
          });
          return response;
        },
        (response) =>
          `v${response.version} affected ${(response.affected_nodes || []).length}`
      );
    }
    await step(
      "rollback plan to v1",
      async () => {
        const response = await api(`/chains/${chain.chain_id}/plan/rollback`, {
          method: "POST",
          body: JSON.stringify({ version: 1 }),
        });
        return response;
      },
      (response) => `v${response.version}`
    );
    await step(
      "rollback weights to v0000",
      async () => {
        const response = await api("/weights/rollback", {
          method: "POST",
          body: JSON.stringify({ to_version: "v0000", reason: "judge demo" }),
        });
        return response;
      },
      (response) => response.version
    );
    await refreshWeights();
    demoLog("demo complete — baseline restored", "ok");
  } catch (error) {
    demoLog(`demo stopped: ${error.message}`, "error");
    toast(error.message, "error");
  }
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function categoryBarsHtml(items) {
  return (items || [])
    .map(
      (item, index) => `
      <div class="classify-candidate ${index === 0 ? "top" : ""}">
        <span>${esc(item.label || item.category)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.max(4, Number(item.confidence || 0) * 100)}%"></div></div>
        <span class="mono">${fmt(item.confidence, 2)}</span>
      </div>`
    )
    .join("");
}

function skillsHtml(skills) {
  return (skills || [])
    .map((skill) => `<span class="reason">${esc(skill)}</span>`)
    .join("") || '<span class="muted small">未识别技能</span>';
}

function renderUploadPreview(container, title, text, sizeBytes = null) {
  if (!container) return;
  container.className = "upload-preview";
  container.innerHTML = `
    <div class="upload-preview-head">
      <strong>${esc(title || "文本预览")}</strong>
      ${sizeBytes == null ? "" : `<span class="pill subtle">${formatBytes(sizeBytes)}</span>`}
    </div>
    <div class="preview-text">${esc(text || "（无文本）")}</div>`;
}

function renderTaskUpload(data) {
  const analysis = data.analysis || {};
  const fields = analysis.fields || {};
  const budget =
    fields.budget != null
      ? `${fmtMoney(fields.budget_min)} – ${fmtMoney(fields.budget_max)}`
      : "未识别";
  const remote =
    fields.remote_ok === true ? "可远程" : fields.remote_ok === false ? "需现场" : "未提及";
  const requirements =
    (fields.requirements || []).map((item) => `<li>${esc(item)}</li>`).join("") ||
    "<li>未识别</li>";
  const confidence = Math.round(Number(analysis.confidence || 0) * 100);

  renderUploadPreview(
    $("#upload-task-preview"),
    data.filename,
    data.text_preview,
    data.size_bytes
  );
  $("#upload-task-analysis").innerHTML = `
    <article class="upload-analysis-block">
      <div class="panel-head">
        <h4>任务画像</h4>
        <span class="pill">${esc(analysis.label || analysis.category || "未分类")} · ${confidence}%</span>
      </div>
      <div class="classify-candidates">${categoryBarsHtml(analysis.top_categories)}</div>
      <div class="upload-field-grid">
        <div class="classify-field"><span>预算</span><strong>${budget}</strong></div>
        <div class="classify-field"><span>交付周期</span><strong>${fields.duration_days ? `${fields.duration_days} 天` : "未识别"}</strong></div>
        <div class="classify-field"><span>截止日期</span><strong>${esc(fields.deadline || "未识别")}</strong></div>
        <div class="classify-field"><span>远程</span><strong>${remote}</strong></div>
      </div>
      <div class="task-reqs">
        <h4>技能与要求</h4>
        <div class="reasons">${skillsHtml(fields.skills)}</div>
        <ul>${requirements}</ul>
      </div>
      <div class="draft-note">草稿 ${esc(data.draft.task_id)} · 截止 ${fmtDate(data.draft.deadline)} · 尚未写入数据</div>
    </article>`;
  renderCandidates(
    $("#upload-task-results"),
    data.candidates,
    "task",
    data.draft.task_id,
    { allowAdopt: false }
  );
  renderDraftConfirm($("#upload-task-confirm"), "task", data.draft);
}

function renderResumeUpload(data) {
  const analysis = data.analysis || {};
  const draft = data.draft || analysis.draft_worker || {};
  const expectedPay = analysis.expected_pay || {};
  const remote =
    analysis.remote_preference === true
      ? "可远程"
      : analysis.remote_preference === false
        ? "需现场"
        : "未提及";
  const pay =
    expectedPay.value == null
      ? "未识别"
      : `${fmtMoney(expectedPay.value)}${expectedPay.period ? ` / ${expectedPay.period}` : ""}`;
  const categories = (analysis.categories || []).map((item) => ({
    label: item.label,
    confidence: item.confidence,
  }));

  renderUploadPreview(
    $("#resume-preview"),
    data.filename || "粘贴文本",
    data.text_preview,
    data.size_bytes
  );
  $("#resume-analysis").innerHTML = `
    <article class="upload-analysis-block">
      <div class="panel-head">
        <h4>候选人画像</h4>
        <span class="pill">草稿</span>
      </div>
      <div class="classify-candidates">${categoryBarsHtml(categories)}</div>
      <div class="upload-field-grid">
        <div class="classify-field"><span>经验年限</span><strong>${fmt(analysis.experience_years, 1)} 年</strong></div>
        <div class="classify-field"><span>地区</span><strong>${esc(analysis.region_label || analysis.region)}</strong></div>
        <div class="classify-field"><span>远程偏好</span><strong>${remote}</strong></div>
        <div class="classify-field"><span>期望报酬</span><strong>${pay}</strong></div>
        <div class="classify-field"><span>画像等级</span><strong>L${draft.level ?? "—"}</strong></div>
        <div class="classify-field"><span>草稿 ID</span><strong class="mono">${esc(draft.worker_id || "—")}</strong></div>
      </div>
      <div class="task-reqs">
        <h4>识别到的技能</h4>
        <div class="reasons">${skillsHtml(analysis.skills)}</div>
      </div>
      <div class="draft-note">临时画像仅用于本次推荐，尚未写入数据</div>
    </article>`;
  renderCandidates(
    $("#resume-results"),
    data.candidates,
    "worker",
    draft.worker_id,
    { allowAdopt: false }
  );
  renderDraftConfirm($("#resume-confirm"), "resume", draft);
}

function renderDraftConfirm(container, kind, draft) {
  if (!container) return;
  const label = kind === "task" ? "任务" : "候选人";
  container.innerHTML = `
    <div class="confirm-box">
      <div>
        <strong>${label}草稿已生成，尚未写入数据</strong>
        <p class="muted small">确认只表示采用这份草稿；本演示不会自动创建记录。</p>
      </div>
      <button class="btn primary" data-confirm-draft>确认创建${label}草稿</button>
    </div>`;
  const button = container.querySelector("[data-confirm-draft]");
  if (button) {
    button.addEventListener("click", () =>
      confirmDraft(kind, draft, container)
    );
  }
}

function confirmDraft(kind, draft, container) {
  const label = kind === "task" ? "任务" : "候选人";
  state.confirmedDraft = { kind, draft };
  if (!container) return;
  container.innerHTML = `
    <div class="confirm-box confirmed">
      <div>
        <strong>已确认${label}草稿</strong>
        <span class="pill subtle">未写入数据</span>
      </div>
      <details>
        <summary>查看草稿 JSON</summary>
        <pre class="draft-json">${esc(JSON.stringify(draft, null, 2))}</pre>
      </details>
    </div>`;
  toast(`${label}草稿已确认（演示环境不自动写入数据）`);
}

async function runUploadTask() {
  const file = $("#upload-task-file").files[0];
  if (!file) return toast("请选择任务书文件", "error");
  const topN = Math.max(1, Number($("#upload-task-topn").value || 5));
  renderUploadPreview($("#upload-task-preview"), file.name, "正在解析…", file.size);
  $("#upload-task-analysis").innerHTML = "";
  $("#upload-task-results").innerHTML = "";
  $("#upload-task-confirm").innerHTML = "";
  const form = new FormData();
  form.append("file", file);
  form.append("top_n", String(topN));
  try {
    const data = await apiForm("/upload/task", form);
    state.uploadTask = data;
    renderTaskUpload(data);
    toast(`解析完成：Top-${data.candidates.length} 候选人`);
  } catch (error) {
    $("#upload-task-preview").className = "upload-preview empty";
    $("#upload-task-preview").textContent = "解析失败";
    toast(error.message, "error");
  }
}

async function runResumeAnalyze() {
  const file = $("#resume-file").files[0];
  const text = $("#resume-text").value.trim();
  if (!file && !text) return toast("请粘贴简历文本或选择文件", "error");
  const topN = Math.max(1, Number($("#resume-topn").value || 5));
  renderUploadPreview(
    $("#resume-preview"),
    file ? file.name : "粘贴文本",
    file ? "正在解析…" : text.slice(0, 400),
    file ? file.size : null
  );
  $("#resume-analysis").innerHTML = "";
  $("#resume-results").innerHTML = "";
  $("#resume-confirm").innerHTML = "";
  try {
    let data;
    if (file) {
      const form = new FormData();
      form.append("file", file);
      form.append("top_n", String(topN));
      data = await apiForm("/upload/resume", form);
    } else {
      data = await api("/resume/analyze", {
        method: "POST",
        body: JSON.stringify({ text, top_n: topN }),
      });
    }
    state.resumeUpload = data;
    renderResumeUpload(data);
    toast(`分析完成：Top-${data.candidates.length} 任务`);
  } catch (error) {
    $("#resume-preview").className = "upload-preview empty";
    $("#resume-preview").textContent = "分析失败";
    toast(error.message, "error");
  }
}

function bindUpload() {
  $("#upload-task-run").addEventListener("click", runUploadTask);
  $("#resume-run").addEventListener("click", runResumeAnalyze);
}

function bindClassify() {
  $("#classify-run").addEventListener("click", runClassification);
  $("#classify-sample").addEventListener("click", () => {
    $("#classify-text").value = CLASSIFY_SAMPLE;
    runClassification();
  });
}

function bindBenchmark() {
  $("#benchmark-run").addEventListener("click", runBenchmark);
  $("#benchmark-load").addEventListener("click", loadBenchmarkSummary);
}

function bindTalent() {
  $("#talent-load").addEventListener("click", loadTalentResume);
  $("#talent-select").addEventListener("change", loadTalentResume);
  $("#talent-toggle").addEventListener("click", toggleTalentRaw);
}

function bindAcceptance() {
  $("#acceptance-load").addEventListener("click", loadAcceptanceDemo);
  $("#acceptance-learn").addEventListener("click", runAcceptanceLearning);
  $("#acceptance-metrics").addEventListener("click", refreshAcceptanceMetrics);
  $("#acceptance-submit-good").addEventListener("click", () =>
    submitAcceptance(true)
  );
  $("#acceptance-submit-bad").addEventListener("click", () =>
    submitAcceptance(false)
  );
  $("#acceptance-review").addEventListener("click", reviewAcceptance);
  $("#acceptance-accept").addEventListener("click", () =>
    decideAcceptance("accepted")
  );
  $("#acceptance-rework").addEventListener("click", () =>
    decideAcceptance("rework")
  );
  $("#acceptance-reject").addEventListener("click", () =>
    decideAcceptance("rejected")
  );
}

function bindTaskToWorker() {
  $("#t2w-run").addEventListener("click", runTaskRecommendations);
  $("#t2w-task").addEventListener("change", renderTaskPreview);
}

function bindWorkerToTask() {
  $("#w2t-run").addEventListener("click", runWorkerRecommendations);
}

function bindFeedback() {
  $("#onboard-run").addEventListener("click", onboard);
  $("#load-curve").addEventListener("click", loadCurve);
  $("#diff-run").addEventListener("click", showDiff);
  $("#rollback-weights").addEventListener("click", rollbackWeights);
  $("#recompute-weights").addEventListener("click", recomputeWeights);
}

function bindChain() {
  $("#chain-mode").addEventListener("change", updateChainMode);
  $("#chain-decompose").addEventListener("click", decomposeChain);
  $("#chain-plan").addEventListener("click", planChain);
  $("#chain-plans").addEventListener("click", loadPlanVersions);
  $("#replan-run").addEventListener("click", replanChain);
  $("#status-run").addEventListener("click", updateNodeStatus);
}

function bindDemo() {
  $("#demo-run").addEventListener("click", runDemo);
  $("#demo-clear").addEventListener("click", () => {
    $("#demo-log").textContent = "等待运行…";
  });
  $("#growth-compare").addEventListener("click", growthCompare);
  $("#growth-learn").addEventListener("click", growthLearn);
}

async function init() {
  bindTabs();
  bindTheme();
  bindClassify();
  bindTalent();
  bindBenchmark();
  bindAcceptance();
  bindTaskToWorker();
  bindWorkerToTask();
  bindUpload();
  bindFeedback();
  bindChain();
  bindDemo();
  fillChainCategories();
  updateChainMode();
  try {
    const [health, tasks, workers, weights, changelog, curve, rounds] =
      await Promise.all([
        api("/health"),
        api("/tasks"),
        api("/workers"),
        api("/weights"),
        api("/learning/changelog"),
        api("/metrics/learning-curve"),
        api("/metrics/learning-rounds"),
      ]);
    state.health = health;
    state.tasks = tasks;
    state.workers = workers;
    state.weights = weights;
    state.changelog = changelog;
    state.learningCurve =
      curve && Array.isArray(curve.n) && curve.n.length ? curve : null;
    state.learningRounds =
      rounds && Array.isArray(rounds.rounds) && rounds.rounds.length
        ? rounds
        : null;
    renderProgressCharts();
    renderRoundsChart($("#rounds-chart"), state.learningRounds);
    $("#health-dot").className = "dot ok";
    $("#version-pill").textContent = health.version;
    fillTaskSelects();
    fillWorkerSelects();
    await loadTalentList();
    renderOverview();
    renderWeightsPanel();
    renderChangelog();
  } catch (error) {
    $("#health-dot").className = "dot error";
    toast(`初始化失败：${error.message}`, "error");
  }
}

document.addEventListener("DOMContentLoaded", init);
