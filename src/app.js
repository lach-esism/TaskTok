import {
  EXECUTORS,
  PRESET_FEEDBACK,
  TASKS,
  TASK_TYPE_LABELS,
  RISK_LABELS
} from "./data.js";
import {
  POLICY_V1,
  createRunSnapshot,
  learnPolicyV2,
  routeTask,
  verifyRollback
} from "./router-engine.js";

const executorById = new Map(EXECUTORS.map((executor) => [executor.id, executor]));
const USER_POLICY = learnPolicyV2(POLICY_V1, PRESET_FEEDBACK);
const BASE_USER_RESULTS = new Map(
  TASKS.map((task) => [task.id, routeTask(task, USER_POLICY)])
);

const TASK_PRESENTATION = Object.freeze({
  T1: { status: "进行中", requester: "产品运营组", due: "今天 18:00" },
  T2: { status: "待分配", requester: "客户数据组", due: "今天 16:30" },
  T3: { status: "待验收", requester: "会员产品组", due: "今天 14:00" },
  T4: { status: "待分配", requester: "市场研究组", due: "明天 10:00" },
  T5: { status: "进行中", requester: "课程运营组", due: "明天 12:00" },
  T6: { status: "已完成", requester: "市场活动组", due: "已交付" },
  T7: { status: "待验收", requester: "客服支持组", due: "今天 17:00" },
  T8: { status: "待分配", requester: "用户运营组", due: "明天 15:00" },
  H1: { status: "已完成", requester: "会员产品组", due: "已交付" },
  H2: { status: "待分配", requester: "会员运营组", due: "明天 11:00" },
  H3: { status: "进行中", requester: "课程法务组", due: "明天 16:00" },
  H4: { status: "已完成", requester: "课程运营组", due: "已交付" }
});

const STATUS_ORDER = new Map([
  ["待分配", 0],
  ["待验收", 1],
  ["进行中", 2],
  ["已完成", 3]
]);

const state = {
  view: "home",
  filter: "all",
  search: "",
  selectedTaskId: "T2",
  statusOverrides: new Map(),
  clarifiedTasks: new Set(),
  customTasks: [],
  nextTaskId: 1,
  v1Snapshot: null,
  v2Snapshot: null,
  activeLabVersion: "none",
  feedbackSubmitted: false,
  rollbackCheck: null,
  audit: [],
  toastTimer: null,
  busy: false
};

const elements = {
  taskList: document.querySelector("#task-list"),
  emptyResults: document.querySelector("#empty-results"),
  taskDetail: document.querySelector("#task-detail"),
  resultsCount: document.querySelector("#results-count"),
  taskSearch: document.querySelector("#task-search"),
  recentList: document.querySelector("#recent-list"),
  quickForm: document.querySelector("#quick-route"),
  quickInput: document.querySelector("#quick-task"),
  publishDialog: document.querySelector("#publish-dialog"),
  publishForm: document.querySelector("#publish-form"),
  feedbackDialog: document.querySelector("#feedback-dialog"),
  feedbackList: document.querySelector("#feedback-list"),
  toast: document.querySelector("#toast"),
  labMetrics: document.querySelector("#lab-metrics"),
  labBody: document.querySelector("#lab-table-body"),
  labLedger: document.querySelector("#lab-ledger-content"),
  labVersion: document.querySelector("#lab-version"),
  ledgerStatus: document.querySelector("#ledger-status"),
  auditLog: document.querySelector("#audit-log"),
  runV1: document.querySelector("#run-v1"),
  openFeedback: document.querySelector("#open-feedback"),
  generateV2: document.querySelector("#generate-v2"),
  rollbackV1: document.querySelector("#rollback-v1"),
  restoreV2: document.querySelector("#restore-v2"),
  automate: document.querySelector("#automate-lab")
};

function init() {
  elements.feedbackList.innerHTML = renderFeedbackCards();
  bindEvents();
  renderAll();
  applyPreviewState();
}

function bindEvents() {
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.viewTarget));
  });
  document.querySelectorAll("[data-open-publish]").forEach((button) => {
    button.addEventListener("click", () => elements.publishDialog.showModal());
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog").close());
  });
  [elements.publishDialog, elements.feedbackDialog].forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  document.querySelector("#task-filters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((chip) => {
      chip.classList.toggle("is-active", chip === button);
    });
    renderTaskList();
  });

  document.querySelectorAll("[data-task-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.taskFilter;
      document.querySelectorAll("[data-filter]").forEach((chip) => {
        chip.classList.toggle("is-active", chip.dataset.filter === state.filter);
      });
      showView("market");
      renderTaskList();
    });
  });

  elements.taskSearch.addEventListener("input", () => {
    state.search = elements.taskSearch.value.trim();
    renderTaskList();
  });

  document.querySelector("#clear-filters").addEventListener("click", () => {
    state.filter = "all";
    state.search = "";
    elements.taskSearch.value = "";
    document.querySelectorAll("[data-filter]").forEach((chip) => {
      chip.classList.toggle("is-active", chip.dataset.filter === "all");
    });
    renderTaskList();
  });

  elements.taskList.addEventListener("click", (event) => {
    const card = event.target.closest("[data-task-id]");
    if (!card) return;
    selectTask(card.dataset.taskId);
  });

  elements.taskDetail.addEventListener("click", (event) => {
    const action = event.target.closest("[data-task-action]");
    if (!action) return;
    handleTaskAction(action.dataset.taskAction);
  });

  document.addEventListener("click", (event) => {
    const compactTask = event.target.closest("[data-open-task]");
    if (!compactTask) return;
    state.selectedTaskId = compactTask.dataset.openTask;
    showView("market");
    renderTaskList();
    renderTaskDetail();
    requestAnimationFrame(() => document.querySelector("#task-browser").scrollIntoView());
  });

  elements.quickForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = elements.quickInput.value.trim();
    if (text.length < 4) {
      toast("请用一句话说明你要完成的任务。", true);
      elements.quickInput.focus();
      return;
    }
    addTask({
      title: summarizeTitle(text),
      request: text,
      deliverable: "一份可验收的线上交付物"
    });
    elements.quickInput.value = "";
  });

  elements.publishForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(elements.publishForm);
    const title = String(data.get("title") ?? "").trim();
    const request = String(data.get("request") ?? "").trim();
    const deliverable = String(data.get("deliverable") ?? "").trim();
    if (!title || !request || !deliverable) {
      toast("请把任务、需求和交付物填写完整。", true);
      return;
    }
    elements.publishDialog.close();
    elements.publishForm.reset();
    addTask({ title, request, deliverable });
  });

  elements.runV1.addEventListener("click", () => runV1());
  elements.openFeedback.addEventListener("click", () => elements.feedbackDialog.showModal());
  document.querySelector("#submit-feedback").addEventListener("click", submitFeedback);
  elements.generateV2.addEventListener("click", generateAndRunV2);
  elements.rollbackV1.addEventListener("click", rollbackToV1);
  elements.restoreV2.addEventListener("click", restoreV2);
  elements.automate.addEventListener("click", runAutomation);
}

function showView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("is-active", section.id === `${view}-view`);
  });
  const activeNavView = view === "market" ? "market" : view;
  document.querySelectorAll(".mode-button").forEach((button) => {
    const isActive = button.dataset.view === activeNavView;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-current", isActive ? "page" : "false");
  });
  if (view === "home") renderHome();
  if (view === "market") renderTaskList();
  if (view === "profile") renderProgress();
  if (view === "lab") renderLab();
  window.scrollTo({ top: 0, behavior: "instant" });
}

function allUserTasks() {
  return [...state.customTasks, ...TASKS];
}

function presentationFor(task) {
  return (
    TASK_PRESENTATION[task.id] ?? {
      status: "待分配",
      requester: "你",
      due: "待确认"
    }
  );
}

function statusFor(task) {
  return state.statusOverrides.get(task.id) ?? presentationFor(task).status;
}

function userResult(task) {
  return BASE_USER_RESULTS.get(task.id) ?? routeTask(task, USER_POLICY);
}

function visibleTasks() {
  const query = state.search.toLocaleLowerCase("zh-CN");
  return allUserTasks()
    .filter((task) => {
      const result = userResult(task);
      return state.filter === "all" || result.taskType === state.filter;
    })
    .filter((task) => {
      if (!query) return true;
      const result = userResult(task);
      return [task.title, task.request, task.deliverable, result.taskTypeLabel]
        .join(" ")
        .toLocaleLowerCase("zh-CN")
        .includes(query);
    })
    .sort((left, right) => {
      const statusDelta =
        STATUS_ORDER.get(statusFor(left)) - STATUS_ORDER.get(statusFor(right));
      if (statusDelta !== 0) return statusDelta;
      return allUserTasks().indexOf(left) - allUserTasks().indexOf(right);
    });
}

function renderAll() {
  renderHome();
  renderTaskList();
  renderTaskDetail();
  renderProgress();
  renderLab();
}

function renderHome() {
  const recent = [...allUserTasks()]
    .sort((left, right) => {
      const statusDelta =
        STATUS_ORDER.get(statusFor(left)) - STATUS_ORDER.get(statusFor(right));
      if (statusDelta !== 0) return statusDelta;
      return allUserTasks().indexOf(left) - allUserTasks().indexOf(right);
    })
    .slice(0, 3);
  elements.recentList.innerHTML = recent
    .map((task) => {
      const result = userResult(task);
      const executor = executorById.get(result.selected);
      const status = statusFor(task);
      return `
        <button type="button" class="recent-task" data-open-task="${escapeHtml(task.id)}">
          <i class="recent-dot" data-status="${escapeHtml(status)}"></i>
          <strong>${escapeHtml(task.title)}</strong>
          <span>${status} · ${result.selected} ${escapeHtml(executor.shortName)}</span>
        </button>
      `;
    })
    .join("");
}

function renderTaskList() {
  const tasks = visibleTasks();
  elements.resultsCount.textContent = `${tasks.length} 个任务`;
  elements.emptyResults.hidden = tasks.length > 0;
  elements.taskList.hidden = tasks.length === 0;

  if (tasks.length > 0 && !tasks.some((task) => task.id === state.selectedTaskId)) {
    state.selectedTaskId = tasks[0].id;
    renderTaskDetail();
  }

  elements.taskList.innerHTML = tasks
    .map((task) => {
      const result = userResult(task);
      const presentation = presentationFor(task);
      const status = statusFor(task);
      const executor = executorById.get(result.selected);
      const riskText = result.riskTags.length
        ? `<span class="risk-label">需要合规复核</span>`
        : "";
      return `
        <button
          type="button"
          class="task-card ${task.id === state.selectedTaskId ? "is-selected" : ""}"
          data-task-id="${escapeHtml(task.id)}"
        >
          <span class="task-card-aside">
            <span class="status-label" data-status="${escapeHtml(status)}">${escapeHtml(status)}</span>
            <span class="task-category">${escapeHtml(result.taskTypeLabel)}</span>
          </span>
          <span class="task-copy">
            <h3>${escapeHtml(task.title)}</h3>
            <p>${escapeHtml(task.request)}</p>
            <span class="task-meta">
              <span>${escapeHtml(presentation.requester)}</span>
              <span>${escapeHtml(presentation.due)}</span>
              ${riskText}
            </span>
          </span>
          <span class="task-recommendation">
            <span class="executor-avatar">${result.selected}</span>
            <span>
              <span>建议执行者</span>
              <strong>${escapeHtml(executor.name)}</strong>
            </span>
          </span>
        </button>
      `;
    })
    .join("");
}

function renderTaskDetail() {
  const task = allUserTasks().find((item) => item.id === state.selectedTaskId);
  if (!task) {
    elements.taskDetail.innerHTML = `
      <div class="ledger-empty">
        <strong>选择一个任务</strong>
        点击左侧任务，查看交付要求、推荐执行者和下一步操作。
      </div>
    `;
    return;
  }

  const result = userResult(task);
  const executor = executorById.get(result.selected);
  const presentation = presentationFor(task);
  const status = statusFor(task);
  const primaryAction = actionForTask(task, result, status);
  const safetyNote = result.riskTags.length
    ? `<div class="safety-note">这个任务涉及 ${escapeHtml(
        result.riskTags.join("、")
      )}，分配后必须包含合规预审和人工复核。</div>`
    : "";
  const clarifyNote =
    result.clarifyFirst && !state.clarifiedTasks.has(task.id)
      ? `<div class="safety-note">任务边界还不够清楚。建议先确认要检查的范围，再开始执行。</div>`
      : "";

  elements.taskDetail.innerHTML = `
    <div class="detail-topline">
      <span class="detail-id">${escapeHtml(task.id)} · ${escapeHtml(presentation.requester)}</span>
      <span class="status-label" data-status="${escapeHtml(status)}">${escapeHtml(status)}</span>
    </div>
    <h2 class="detail-title">${escapeHtml(task.title)}</h2>
    <p class="detail-request">${escapeHtml(task.request)}</p>

    <section class="detail-section">
      <h3>建议执行者</h3>
      <div class="recommended-executor">
        <span class="executor-avatar">${result.selected}</span>
        <span>
          <strong>${escapeHtml(executor.name)}</strong>
          <span>${escapeHtml(executor.type)} · ${escapeHtml(result.taskTypeLabel)}</span>
        </span>
        <span class="match-score">${result.top1.score}</span>
      </div>
      <div class="reason-box">${escapeHtml(result.rationale)}</div>
      ${safetyNote}
      ${clarifyNote}
    </section>

    <section class="detail-section">
      <h3>交付要求</h3>
      <ul class="detail-list">
        <li>${escapeHtml(task.deliverable)}</li>
        ${task.requiredEvidence.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>

    <div class="detail-actions">
      <button
        type="button"
        class="${primaryAction.primary ? "primary-button" : "secondary-button"}"
        data-task-action="${primaryAction.action}"
      >
        ${primaryAction.label}
      </button>
      ${
        result.clarifyFirst && status === "待分配"
          ? `<button type="button" class="secondary-button" data-task-action="assign">仍然分配</button>`
          : `<button type="button" class="secondary-button" data-task-action="details">查看执行者</button>`
      }
    </div>
  `;
}

function actionForTask(task, result, status) {
  if (status === "已完成") {
    return { action: "viewResult", label: "查看交付结果", primary: false };
  }
  if (status === "进行中") {
    return { action: "viewProgress", label: "查看执行进度", primary: false };
  }
  if (status === "待验收") {
    return { action: "accept", label: "验收这份交付", primary: true };
  }
  if (result.clarifyFirst && !state.clarifiedTasks.has(task.id)) {
    return { action: "clarify", label: "先追问发布者", primary: true };
  }
  return {
    action: "assign",
    label: `分配给 ${executorById.get(result.selected).name}`,
    primary: true
  };
}

function handleTaskAction(action) {
  const task = allUserTasks().find((item) => item.id === state.selectedTaskId);
  if (!task) return;

  if (action === "assign") {
    state.statusOverrides.set(task.id, "进行中");
    toast(`任务已分配给 ${executorById.get(userResult(task).selected).name}。`);
    renderAll();
    return;
  }
  if (action === "clarify") {
    state.clarifiedTasks.add(task.id);
    toast("已向发布者追问缺失信息，确认后再进入分配。");
    renderTaskDetail();
    return;
  }
  if (action === "accept") {
    state.statusOverrides.set(task.id, "已完成");
    toast("验收已通过。这次结果会作为下一次推荐的证据。");
    renderAll();
    return;
  }
  if (action === "viewProgress") {
    toast("执行者正在处理，预计会在截止时间前提交。");
    return;
  }
  if (action === "viewResult") {
    toast("交付物已通过验收，可以在任务记录中查看。");
    return;
  }
  if (action === "details") {
    const executor = executorById.get(userResult(task).selected);
    toast(`${executor.name}：${executor.evidence[0]}`);
  }
}

function renderSummary() {
  const tasks = allUserTasks();
  const counts = countStatuses(tasks);
  document.querySelector("#summary-task-count").textContent = String(tasks.length);
  document.querySelector("#summary-pending").textContent = String(counts["待分配"]);
  document.querySelector("#summary-review").textContent = String(counts["待验收"]);
  document.querySelector("#summary-done").textContent = String(counts["已完成"]);
}

function countStatuses(tasks) {
  return tasks.reduce(
    (counts, task) => {
      counts[statusFor(task)] += 1;
      return counts;
    },
    { 待分配: 0, 进行中: 0, 待验收: 0, 已完成: 0 }
  );
}

function renderProgress() {
  const tasks = allUserTasks();
  const counts = countStatuses(tasks);
  document.querySelector("#progress-summary").innerHTML = [
    ["待分配", counts["待分配"]],
    ["进行中", counts["进行中"]],
    ["待验收", counts["待验收"]],
    ["已完成", counts["已完成"]]
  ]
    .map(
      ([label, count]) => `
        <div>
          <strong>${count}</strong>
          <span>${label}</span>
        </div>
      `
    )
    .join("");

  const reviewTasks = tasks.filter((task) => statusFor(task) === "待验收");
  const activeTasks = tasks.filter((task) => statusFor(task) === "进行中");
  document.querySelector("#review-count").textContent = `${reviewTasks.length} 个`;
  document.querySelector("#active-count").textContent = `${activeTasks.length} 个`;
  document.querySelector("#review-list").innerHTML = renderCompactTasks(
    reviewTasks,
    "没有等待验收的任务"
  );
  document.querySelector("#active-list").innerHTML = renderCompactTasks(
    activeTasks,
    "没有正在执行的任务"
  );
}

function renderCompactTasks(tasks, emptyText) {
  if (tasks.length === 0) return `<div class="progress-empty">${emptyText}</div>`;
  return tasks
    .map((task) => {
      const result = userResult(task);
      const executor = executorById.get(result.selected);
      return `
        <button type="button" class="compact-task" data-open-task="${escapeHtml(task.id)}">
          <span>
            <h3>${escapeHtml(task.title)}</h3>
            <p>${escapeHtml(presentationFor(task).due)} · ${escapeHtml(result.taskTypeLabel)}</p>
          </span>
          <span>${result.selected} · ${escapeHtml(executor.shortName)}</span>
        </button>
      `;
    })
    .join("");
}

function addTask({ title, request, deliverable }) {
  const task = {
    id: `N${state.nextTaskId++}`,
    set: "custom",
    title: title.slice(0, 60),
    request,
    deliverable,
    expected: "",
    alternatives: [],
    riskTags: [],
    requiredEvidence: [deliverable, "按照任务描述完成交付"],
    clarity: "clear",
    missingInfo: "",
    fixedCost: 50
  };
  state.customTasks.unshift(task);
  state.statusOverrides.set(task.id, "待分配");
  state.selectedTaskId = task.id;
  state.filter = "all";
  state.search = "";
  elements.taskSearch.value = "";
  document.querySelectorAll("[data-filter]").forEach((chip) => {
    chip.classList.toggle("is-active", chip.dataset.filter === "all");
  });
  showView("market");
  renderAll();
  requestAnimationFrame(() => document.querySelector("#task-browser").scrollIntoView());
  const result = userResult(task);
  toast(`任务已发布，建议交给 ${executorById.get(result.selected).name}。`);
}

function summarizeTitle(text) {
  const firstClause = text.split(/[，。；,.!?！？]/)[0].trim();
  return (firstClause || text).slice(0, 28);
}

function applyPreviewState() {
  const params = new URLSearchParams(window.location.search);
  const requestedView = params.get("view");
  if (["home", "market", "profile", "lab"].includes(requestedView)) {
    showView(requestedView);
  }

  const preview = params.get("preview");
  if (!preview) return;
  runV1({ automated: true });
  if (preview === "feedback") {
    submitFeedback({ automated: true });
  } else if (preview === "v2" || preview === "rollback") {
    submitFeedback({ automated: true });
    generateAndRunV2({ automated: true });
    if (preview === "rollback") rollbackToV1({ automated: true });
  }
  if (requestedView === "lab") renderLab();
}

function runV1({ automated = false } = {}) {
  state.v1Snapshot = createRunSnapshot(POLICY_V1, TASKS, EXECUTORS);
  state.v2Snapshot = null;
  state.activeLabVersion = "v1";
  state.feedbackSubmitted = false;
  state.rollbackCheck = null;
  logAudit("v1", "运行 12 个任务，记录校准集与隐藏集 Top-1、合规覆盖和验收结果。");
  renderLab();
  if (!automated) {
    const errorCount = state.v1Snapshot.results.filter((result) => {
      const task = TASKS.find((item) => item.id === result.taskId);
      return (
        result.selected !== task.expected ||
        (task.riskTags.length > 0 && result.requiredReviewers.length === 0)
      );
    }).length;
    toast(`v1 基线已运行，发现 ${errorCount} 个需要复核的分配结果。`);
  }
}

function submitFeedback({ automated = false } = {}) {
  if (!state.v1Snapshot) {
    toast("请先运行 v1 基线。", true);
    return;
  }
  state.feedbackSubmitted = true;
  PRESET_FEEDBACK.forEach((event) => {
    logAudit(event.taskId, `${event.eventId} 写入 ${event.correctExecutor} / ${TASK_TYPE_LABELS[event.correctType]}。`);
  });
  if (elements.feedbackDialog.open) elements.feedbackDialog.close();
  renderLab();
  if (!automated) toast("3 条纠错已写入证据事件，可以生成 v2。");
}

function generateAndRunV2({ automated = false } = {}) {
  if (!state.feedbackSubmitted) {
    toast("还没有结构化反馈，不能生成 v2。", true);
    return;
  }
  state.v2Snapshot = createRunSnapshot(USER_POLICY, TASKS, EXECUTORS);
  state.activeLabVersion = "v2";
  state.rollbackCheck = null;
  logAudit("v2", `生成候选策略，隐藏任务 Top-1 ${formatFraction(state.v2Snapshot.metrics.hiddenTop1)}，合规覆盖 ${formatPercent(state.v2Snapshot.metrics.complianceCoverage.rate)}。`);
  renderLab();
  if (!automated) {
    toast(
      `v2 已运行：隐藏任务 ${formatFraction(
        state.v2Snapshot.metrics.hiddenTop1
      )}，合规覆盖 ${formatPercent(state.v2Snapshot.metrics.complianceCoverage.rate)}。`
    );
  }
}

function rollbackToV1({ automated = false } = {}) {
  if (!state.v1Snapshot || !state.v2Snapshot) return;
  state.rollbackCheck = verifyRollback(state.v1Snapshot, state.v2Snapshot, TASKS);
  state.activeLabVersion = "v1";
  logAudit("rollback", `回滚到 v1，重放签名一致=${state.rollbackCheck.consistent}。`);
  renderLab();
  if (!automated) toast("已回滚到 v1，历史结果与快照完全一致。");
}

function restoreV2() {
  if (!state.v2Snapshot) return;
  state.activeLabVersion = "v2";
  logAudit("v2", "恢复 v2 快照，排名与指标回到第二轮结果。");
  renderLab();
  toast("已恢复 v2。");
}

async function runAutomation() {
  if (state.busy) return;
  state.busy = true;
  renderLabControls();
  runV1({ automated: true });
  await delay(650);
  submitFeedback({ automated: true });
  await delay(650);
  generateAndRunV2({ automated: true });
  await delay(1000);
  rollbackToV1({ automated: true });
  await delay(850);
  restoreV2();
  state.busy = false;
  renderLab();
  toast("自动预演完成：v1 / 反馈 / v2 / 回滚 / 恢复。");
}

function renderLab() {
  renderLabMetrics();
  renderLabTable();
  renderLabLedger();
  renderLabControls();
  renderAudit();
}

function renderLabMetrics() {
  const snapshot =
    state.activeLabVersion === "v1"
      ? state.v1Snapshot
      : state.activeLabVersion === "v2"
        ? state.v2Snapshot
        : null;
  if (!snapshot) {
    elements.labMetrics.innerHTML = [
      ["隐藏任务 Top-1", "—", "未参与反馈学习"],
      ["高风险合规覆盖", "—", "需要合规或人工节点"],
      ["校准任务 Top-1", "—", "8 个已知任务"],
      ["回滚一致性", "—", "回滚后重新运行"]
    ]
      .map(
        ([label, value, note]) => `
          <div class="lab-metric">
            <span>${label}</span>
            <strong>${value}</strong>
            <small>${note}</small>
          </div>
        `
      )
      .join("");
    return;
  }

  const metrics = snapshot.metrics;
  const rollbackValue = state.rollbackCheck
    ? state.rollbackCheck.consistent
      ? "100%"
      : "失败"
    : "待验证";
  elements.labMetrics.innerHTML = [
    [
      "隐藏任务 Top-1",
      formatFraction(metrics.hiddenTop1),
      state.activeLabVersion === "v2" && state.v1Snapshot
        ? `由 ${formatFraction(state.v1Snapshot.metrics.hiddenTop1)} 提升`
        : "未参与反馈学习"
    ],
    [
      "高风险合规覆盖",
      formatPercent(metrics.complianceCoverage.rate),
      `${metrics.complianceCoverage.covered} / ${metrics.complianceCoverage.total} 高风险任务`
    ],
    [
      "校准任务 Top-1",
      formatFraction(metrics.calibrationTop1),
      `一次验收 ${formatPercent(metrics.acceptance.rate)}`
    ],
    ["回滚一致性", rollbackValue, "v1 与 v2 重放签名比较"]
  ]
    .map(
      ([label, value, note]) => `
        <div class="lab-metric">
          <span>${label}</span>
          <strong>${value}</strong>
          <small>${note}</small>
        </div>
      `
    )
    .join("");
}

function renderLabTable() {
  const v1Map = new Map((state.v1Snapshot?.results ?? []).map((item) => [item.taskId, item]));
  const v2Map = new Map((state.v2Snapshot?.results ?? []).map((item) => [item.taskId, item]));
  elements.labBody.innerHTML = TASKS.map((task) => {
    const v1 = v1Map.get(task.id);
    const v2 = v2Map.get(task.id);
    const isError = v1 && (v1.selected !== task.expected || (task.riskTags.length > 0 && !task.riskTags.every((tag) => v1.riskTags.includes(tag))));
    const change = !v2
      ? v1
        ? "待生成 v2"
        : "等待运行"
      : v2.riskTags.length
        ? "进入合规通道"
        : v1?.selected !== v2.selected
          ? "任务类型重新校准"
          : "保持稳定";
    return `
      <tr class="${isError ? "is-error" : ""}">
        <td>
          <div class="lab-task-name">
            <strong>${escapeHtml(task.title)}</strong>
            <span>${task.id} · ${task.set === "hidden" ? "隐藏任务" : "校准任务"}</span>
          </div>
        </td>
        <td><span class="lab-executor">${v1?.selected ?? "—"}</span></td>
        <td><span class="lab-executor ${v2 && v2.selected !== v1?.selected ? "is-fixed" : ""}">${v2?.selected ?? "—"}</span></td>
        <td><span class="lab-change">${change}</span></td>
      </tr>
    `;
  }).join("");
}

function renderLabLedger() {
  if (!state.v2Snapshot) {
    elements.ledgerStatus.textContent = state.feedbackSubmitted ? "反馈待生成" : "尚无新规则";
    elements.labLedger.innerHTML = state.feedbackSubmitted
      ? `
        <div class="ledger-empty">
          <strong>3 条纠错已进入证据账本</strong>
          现在可以生成 v2。系统只会更新任务类型、高风险护栏、研究任务区分和先追问规则。
        </div>
      `
      : `
        <div class="ledger-empty">
          <strong>先运行 v1</strong>
          基线会暴露合理误分。提交结构化反馈后，页面才显示新增规则、置信度和权重变化。
        </div>
      `;
    return;
  }

  elements.ledgerStatus.textContent = state.activeLabVersion === "v1" ? "v1 已回滚" : "v2 已生成";
  const policy = state.v2Snapshot.policy;
  elements.labLedger.innerHTML = `
    ${policy.rules
      .map(
        (rule) => `
          <article class="rule-item">
            <div class="rule-item-head">
              <strong>${escapeHtml(rule.title)}</strong>
              <span>${Math.round(rule.confidence * 100)}%</span>
            </div>
            <p>${escapeHtml(rule.detail)}</p>
            <div class="evidence-list">
              ${rule.evidence.map((event) => `<span>${escapeHtml(event)}</span>`).join("")}
            </div>
          </article>
        `
      )
      .join("")}
    <article class="rule-item">
      <div class="rule-item-head">
        <strong>路由权重</strong>
        <span>有界更新</span>
      </div>
      ${renderWeight("能力适配", POLICY_V1.weights.capability, policy.weights.capability)}
      ${renderWeight("历史验收", POLICY_V1.weights.history, policy.weights.history)}
      ${renderWeight("风险证据", POLICY_V1.weights.riskEvidence, policy.weights.riskEvidence)}
      ${renderWeight("完成成本", POLICY_V1.weights.cost, policy.weights.cost)}
    </article>
  `;
}

function renderWeight(label, v1, v2) {
  const percentage = Math.round(v2 * 100);
  return `
    <div class="weight-row">
      <span>${label}</span>
      <span class="weight-bar"><i style="width: ${percentage}%"></i></span>
      <span class="weight-value">${Math.round(v1 * 100)} 到 ${percentage}</span>
    </div>
  `;
}

function renderLabControls() {
  elements.runV1.disabled = state.busy;
  elements.openFeedback.disabled = !state.v1Snapshot || state.busy;
  elements.generateV2.disabled = !state.feedbackSubmitted || state.busy;
  elements.rollbackV1.disabled =
    !state.v2Snapshot || state.activeLabVersion !== "v2" || state.busy;
  elements.restoreV2.disabled =
    !state.v2Snapshot || state.activeLabVersion !== "v1" || state.busy;
  elements.automate.disabled = state.busy;
  elements.labVersion.className = "lab-version";
  if (!state.activeLabVersion || state.activeLabVersion === "none") {
    elements.labVersion.textContent = "等待运行";
  } else if (state.activeLabVersion === "v2") {
    elements.labVersion.textContent = "v2 已验证";
    elements.labVersion.classList.add("is-v2");
  } else {
    elements.labVersion.textContent = state.v2Snapshot ? "v1 已回滚" : "v1 基线";
    elements.labVersion.classList.add("is-rollback");
  }
}

function renderFeedbackCards() {
  return PRESET_FEEDBACK.map((event) => {
    const task = TASKS.find((item) => item.id === event.taskId);
    return `
      <article class="feedback-card">
        <div class="feedback-card-head">
          <strong>${event.eventId}</strong>
          <span>${event.correctExecutor} · ${TASK_TYPE_LABELS[event.correctType]}</span>
        </div>
        <p><b>${escapeHtml(task.title)}</b>：${escapeHtml(event.reason)}</p>
        <small>${escapeHtml(event.suggestion)}</small>
        <span class="clarity-tag">${event.taskClear ? "任务描述清楚" : "任务需要追问"}</span>
      </article>
    `;
  }).join("");
}

function logAudit(version, message) {
  state.audit.push({
    time: new Date().toLocaleTimeString("zh-CN", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    }),
    version,
    message
  });
  if (state.audit.length > 100) state.audit.shift();
}

function renderAudit() {
  elements.auditLog.innerHTML =
    state.audit.length === 0
      ? `<div class="progress-empty">还没有实验操作。</div>`
      : [...state.audit]
          .reverse()
          .map(
            (entry) => `
              <div class="audit-row">
                <time>${entry.time}</time>
                <span>${escapeHtml(entry.version)}</span>
                <p>${escapeHtml(entry.message)}</p>
              </div>
            `
          )
          .join("");
}

function formatFraction(fraction) {
  return `${fraction.correct}/${fraction.total}`;
}

function formatPercent(value) {
  return `${Math.round(value * 100)}%`;
}

function toast(message, isError = false) {
  clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("is-error", isError);
  elements.toast.classList.add("is-visible");
  state.toastTimer = setTimeout(() => elements.toast.classList.remove("is-visible"), 3600);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

init();
