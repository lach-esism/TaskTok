import {
  EXECUTORS,
  TASKS,
  TASK_TYPE_LABELS
} from "./data.js";

const TYPE_TO_CAPABILITY = Object.freeze({
  content_creation: "writing",
  data_cleaning: "data",
  compliance_review: "compliance",
  research_analysis: "research",
  product_docs: "docs"
});

const SIGNAL_GROUPS = Object.freeze({
  docs: Object.freeze([
    ["FAQ", 4],
    ["帮助中心", 3],
    ["知识库", 3],
    ["标准问答", 3],
    ["客服问答", 3],
    ["版本日志", 3],
    ["功能说明", 2.5],
    ["会员权益", 2]
  ]),
  data: Object.freeze([
    ["表格", 3],
    ["清洗", 3],
    ["重复", 2],
    ["缺失", 2],
    ["CRM", 3],
    ["聚类", 3],
    ["Top 5", 2],
    ["整理", 1.5],
    ["频次", 1.5],
    ["数量", 1]
  ]),
  content: Object.freeze([
    ["公众号", 3],
    ["文案", 3],
    ["文章", 3],
    ["标题", 2],
    ["介绍", 2],
    ["宣传", 2],
    ["写", 3.7],
    ["摘要", 3.5]
  ]),
  research: Object.freeze([
    ["竞品", 2.5],
    ["资料", 1.5],
    ["比较", 3],
    ["研究", 3],
    ["核验", 3],
    ["来源", 1.5],
    ["公开", 1.5],
    ["反馈", 2],
    ["评价", 2.5],
    ["检查", 0.35]
  ]),
  compliance: Object.freeze([
    ["合规", 4]
  ])
});

const RISK_PATTERNS = Object.freeze([
  {
    tag: "个人信息",
    pattern: /个人信息|隐私|收集条款|数据保存期限/
  },
  {
    tag: "绝对化用语",
    pattern: /绝对化用语|“最”|第一品牌|顶级|唯一/
  },
  {
    tag: "自动续费",
    pattern: /自动续费|续费提示|到期扣款/
  },
  {
    tag: "消费者权益",
    pattern: /消费者权益|自动续费|取消方式|退款权益/
  }
]);

const TASK_TYPES = Object.freeze(Object.keys(TASK_TYPE_LABELS));

export const POLICY_V1 = deepFreeze({
  version: "v1",
  label: "关键词 + 通用能力",
  createdAt: "2026-11-13T09:00:00+08:00",
  weights: {
    capability: 0.48,
    history: 0.32,
    riskEvidence: 0,
    cost: 0.2
  },
  rules: [
    {
      id: "V1-KEYWORD",
      kind: "task_type",
      title: "关键词决定主要任务类型",
      detail: "按 FAQ、表格、文案、资料等字面信号选择通用能力。",
      confidence: 0.64,
      evidence: ["baseline"]
    },
    {
      id: "V1-GENERIC",
      kind: "routing",
      title: "通用历史表现参与排序",
      detail: "使用执行者的整体一次验收率，不区分具体风险条件。",
      confidence: 0.58,
      evidence: ["baseline"]
    }
  ],
  evidenceEvents: [],
  previousVersion: null
});

function scoreSignalGroup(text, group) {
  return group.reduce((score, [token, weight]) => {
    return score + (text.includes(token) ? weight : 0);
  }, 0);
}

function scoreV1Signals(task) {
  const text = task.request;
  const scores = {
    content_creation: scoreSignalGroup(text, SIGNAL_GROUPS.content),
    data_cleaning: scoreSignalGroup(text, SIGNAL_GROUPS.data),
    compliance_review: scoreSignalGroup(text, SIGNAL_GROUPS.compliance),
    research_analysis: scoreSignalGroup(text, SIGNAL_GROUPS.research),
    product_docs: scoreSignalGroup(text, SIGNAL_GROUPS.docs)
  };
  const winner = TASK_TYPES.reduce((best, current) => {
    return scores[current] > scores[best] ? current : best;
  }, "research_analysis");
  return { scores, type: winner };
}

export function classifyTaskV1(task) {
  const { scores, type } = scoreV1Signals(task);
  const keywordHits = Object.entries(SIGNAL_GROUPS)
    .flatMap(([group, tokens]) => {
      return tokens
        .filter(([token]) => task.request.includes(token))
        .map(([token, weight]) => ({ group, token, weight }));
    })
    .sort((a, b) => b.weight - a.weight);

  return {
    type,
    typeLabel: TASK_TYPE_LABELS[type],
    scores,
    keywordHits,
    riskTags: [],
    rationale: `v1 按关键词把任务归为“${TASK_TYPE_LABELS[type]}”，未检查合规风险条件。`
  };
}

export function extractRiskTagsV2(task) {
  return RISK_PATTERNS
    .filter(({ pattern }) => pattern.test(task.request))
    .map(({ tag }) => tag);
}

function isCompliancePrimary(task, riskTags) {
  if (riskTags.length === 0) return false;
  const text = task.request;
  const hasReviewVerb = /检查|审查|审核|是否清楚|风险说明/.test(text);
  const hasComparison = /比较|对比|两家|多份/.test(text);
  return hasReviewVerb && !hasComparison;
}

export function classifyTaskV2(task) {
  const text = task.request;
  const riskTags = extractRiskTagsV2(task);
  const signalScores = {
    content_creation: scoreSignalGroup(text, SIGNAL_GROUPS.content),
    data_cleaning: scoreSignalGroup(text, SIGNAL_GROUPS.data),
    compliance_review: riskTags.length > 0 ? 6 : 0,
    research_analysis: scoreSignalGroup(text, SIGNAL_GROUPS.research),
    product_docs: scoreSignalGroup(text, SIGNAL_GROUPS.docs)
  };

  if (isCompliancePrimary(task, riskTags)) {
    signalScores.compliance_review += 8;
  }

  if (/竞品|公开资料|比较|来源|核验|评价|反馈|课程服务条款/.test(text)) {
    signalScores.research_analysis += 5;
  }

  if (/FAQ|标准问答|客服问答|版本日志|帮助中心/.test(text)) {
    signalScores.product_docs += 5;
  }

  if (/表格|清洗|CRM|重复记录|缺失记录/.test(text)) {
    signalScores.data_cleaning += 5;
  }

  const type = TASK_TYPES.reduce((best, current) => {
    return signalScores[current] > signalScores[best] ? current : best;
  }, "research_analysis");

  const learningNotes = [];
  if (riskTags.length > 0) {
    learningNotes.push("命中 V2-RISK-GUARD 高风险条件");
  }
  if (type === "research_analysis" && /竞品|公开|比较|来源|评价|反馈/.test(text)) {
    learningNotes.push("命中 V2-RESEARCH-NOT-WRITING 研究任务规则");
  }
  if (type === "product_docs") {
    learningNotes.push("命中产品文档结构规则");
  }
  if (type === "data_cleaning") {
    learningNotes.push("命中封闭数据口径规则");
  }

  return {
    type,
    typeLabel: TASK_TYPE_LABELS[type],
    scores: signalScores,
    keywordHits: Object.entries(SIGNAL_GROUPS)
      .flatMap(([group, tokens]) => {
        return tokens
          .filter(([token]) => text.includes(token))
          .map(([token, weight]) => ({ group, token, weight }));
      })
      .sort((a, b) => b.weight - a.weight),
    riskTags,
    learningNotes,
    rationale:
      type === "research_analysis"
        ? "识别为资料核验/研究任务，证据引用优先于普通写作能力。"
        : type === "compliance_review"
          ? "识别到高风险表述，任务进入合规初审通道。"
          : `按更新后的“${TASK_TYPE_LABELS[type]}”规则排序。`
  };
}

function scoreExecutor(executor, task, classification, policy) {
  const capabilityKey = TYPE_TO_CAPABILITY[classification.type];
  const capability = executor.capabilities[capabilityKey];
  const history = executor.reliability[capabilityKey];
  const riskEvidence =
    classification.riskTags.length > 0 ? executor.capabilities.compliance : 0;
  const costEfficiency = 1 - executor.costLevel;
  const weighted =
    capability * policy.weights.capability +
    history * policy.weights.history +
    riskEvidence * policy.weights.riskEvidence +
    costEfficiency * policy.weights.cost;
  const score = Math.round(weighted * 100);

  return {
    executorId: executor.id,
    executorName: executor.name,
    score,
    capability: round(capability, 2),
    history: round(history, 2),
    riskEvidence: round(riskEvidence, 2),
    reasons: [
      `${taskTypeCapabilityLabel(classification.type)} ${Math.round(capability * 100)}`,
      `同类一次验收 ${Math.round(history * 100)}%`,
      classification.riskTags.length > 0
        ? `合规证据 ${Math.round(riskEvidence * 100)}`
        : "无高风险约束"
    ]
  };
}

function taskTypeCapabilityLabel(type) {
  return {
    content_creation: "内容能力",
    data_cleaning: "数据能力",
    compliance_review: "合规能力",
    research_analysis: "研究能力",
    product_docs: "文档能力"
  }[type];
}

export function routeTask(task, policy, executors = EXECUTORS) {
  const classification =
    policy.version === "v1" ? classifyTaskV1(task) : classifyTaskV2(task);
  const ranking = executors
    .map((executor) => scoreExecutor(executor, task, classification, policy))
    .sort((a, b) => b.score - a.score || a.executorId.localeCompare(b.executorId));
  const top3 = ranking.slice(0, 3);
  const requiredReviewers =
    classification.riskTags.length > 0 ? Object.freeze(["C", "人工复核"]) : Object.freeze([]);
  const safetyCovered =
    classification.riskTags.length === 0 ||
    top3[0].executorId === "C" ||
    requiredReviewers.includes("C");

  return deepFreeze({
    taskId: task.id,
    version: policy.version,
    taskType: classification.type,
    taskTypeLabel: classification.typeLabel,
    riskTags: classification.riskTags,
    keywordHits: classification.keywordHits,
    rationale: classification.rationale,
    selected: top3[0].executorId,
    top1: top3[0],
    top3,
    requiredReviewers,
    safetyCovered,
    clarifyFirst:
      policy.version !== "v1" &&
      task.clarity === "needs_clarification" &&
      policy.rules.some((rule) => rule.id === "V2-CLARIFY-FIRST"),
    learningNotes: classification.learningNotes ?? Object.freeze([])
  });
}

export function runPolicy(policy, tasks = TASKS, executors = EXECUTORS) {
  const results = tasks.map((task) => routeTask(task, policy, executors));
  return deepFreeze({
    policyVersion: policy.version,
    results,
    metrics: computeMetrics(results, tasks, executors),
    signature: signatureFor({ policy, results })
  });
}

export function learnPolicyV2(basePolicy, feedbackEvents) {
  if (!Array.isArray(feedbackEvents) || feedbackEvents.length === 0) {
    throw new Error("至少需要一条结构化反馈才能生成 v2");
  }

  const seen = new Set();
  for (const event of feedbackEvents) {
    if (!event.eventId || !event.taskId) {
      throw new Error("反馈缺少 eventId 或 taskId");
    }
    if (seen.has(event.eventId)) {
      throw new Error(`反馈事件重复：${event.eventId}`);
    }
    if (!TASK_TYPES.includes(event.correctType)) {
      throw new Error(`未知任务类型：${event.correctType}`);
    }
    if (!EXECUTORS.some((executor) => executor.id === event.correctExecutor)) {
      throw new Error(`未知执行者：${event.correctExecutor}`);
    }
    seen.add(event.eventId);
  }

  const evidenceEvents = feedbackEvents.map((event) => ({
    eventId: event.eventId,
    taskId: event.taskId,
    correctExecutor: event.correctExecutor,
    correctType: event.correctType,
    taskClear: event.taskClear,
    reason: event.reason
  }));
  const ruleEvidence = {
    risk: feedbackEvents
      .filter((event) => event.correctType === "compliance_review")
      .map((event) => event.eventId),
    research: feedbackEvents
      .filter((event) => event.correctType === "research_analysis")
      .map((event) => event.eventId),
    clarify: feedbackEvents
      .filter((event) => event.taskClear === false)
      .map((event) => event.eventId)
  };

  const rules = [
    {
      id: "V2-TYPE",
      kind: "task_type",
      title: "任务类型重新校准",
      detail: "规则触发优先级高于单个关键词；短文本不再直接等同于普通写作。",
      confidence: 0.8,
      evidence: evidenceEvents.map((event) => event.eventId)
    },
    {
      id: "V2-RESEARCH-NOT-WRITING",
      kind: "routing",
      title: "资料核验不等于文案写作",
      detail: "竞品、公开资料、比较、来源和评价任务优先匹配研究证据。",
      confidence: clamp(0.62 + ruleEvidence.research.length * 0.13, 0, 0.9),
      evidence: ruleEvidence.research
    },
    {
      id: "V2-RISK-GUARD",
      kind: "safety",
      title: "高风险任务进入合规通道",
      detail: "个人信息、自动续费、消费者权益和绝对化用语必须加入 C 或人工复核。",
      confidence: clamp(0.66 + ruleEvidence.risk.length * 0.11, 0, 0.94),
      evidence: ruleEvidence.risk
    },
    {
      id: "V2-CLARIFY-FIRST",
      kind: "clarification",
      title: "信息不足先追问",
      detail: "缺少数据范围、检查边界或交付格式时，保留候选但不直接开始执行。",
      confidence: ruleEvidence.clarify.length > 0 ? 0.82 : 0.55,
      evidence: ruleEvidence.clarify
    }
  ].filter((rule) => rule.evidence.length > 0 || rule.id === "V2-TYPE");

  return deepFreeze({
    version: "v2",
    label: "反馈驱动策略",
    createdAt: "2026-11-13T09:08:00+08:00",
    weights: {
      capability: 0.42,
      history: 0.18,
      riskEvidence: 0.3,
      cost: 0.1
    },
    rules,
    evidenceEvents,
    previousVersion: basePolicy.version,
    learningSummary: {
      feedbackCount: feedbackEvents.length,
      learnedTypes: [...new Set(feedbackEvents.map((event) => event.correctType))],
      learnedExecutors: [...new Set(feedbackEvents.map((event) => event.correctExecutor))],
      hiddenLabelsRead: false
    }
  });
}

export function computeMetrics(results, tasks, executors = EXECUTORS) {
  const byId = new Map(results.map((result) => [result.taskId, result]));
  const taskById = new Map(tasks.map((task) => [task.id, task]));
  const calibration = tasks.filter((task) => task.set === "calibration");
  const hidden = tasks.filter((task) => task.set === "hidden");
  const correctTop1 = (task) => byId.get(task.id)?.selected === task.expected;
  const safetyCovered = (task) => {
    const result = byId.get(task.id);
    if (task.riskTags.length === 0) return true;
    return Boolean(
      result?.requiredReviewers?.includes("C") &&
      result?.requiredReviewers?.includes("人工复核")
    );
  };
  const accepted = (task) => {
    const result = byId.get(task.id);
    const executorAccepted =
      result.selected === task.expected || task.alternatives.includes(result.selected);
    const safetyAccepted = safetyCovered(task);
    return executorAccepted && safetyAccepted;
  };
  const highRisk = tasks.filter((task) => task.riskTags.length > 0);
  const highRiskCovered = highRisk.filter(safetyCovered);
  const acceptedTasks = tasks.filter(accepted);
  const totalCost = tasks.reduce((sum, task) => {
    const result = byId.get(task.id);
    const executor = executors.find((item) => item.id === result.selected);
    return sum + task.fixedCost * (0.7 + executor.costLevel * 0.6);
  }, 0);
  const rerouted = results.filter((result) => result.selected !== taskById.get(result.taskId).expected);
  const missingBeforeRoute = results.filter((result) => result.clarifyFirst).length;

  return {
    calibrationTop1: {
      correct: calibration.filter(correctTop1).length,
      total: calibration.length,
      rate: calibration.filter(correctTop1).length / calibration.length
    },
    hiddenTop1: {
      correct: hidden.filter(correctTop1).length,
      total: hidden.length,
      rate: hidden.filter(correctTop1).length / hidden.length
    },
    complianceCoverage: {
      covered: highRiskCovered.length,
      total: highRisk.length,
      rate: highRisk.length === 0 ? 1 : highRiskCovered.length / highRisk.length
    },
    acceptance: {
      accepted: acceptedTasks.length,
      total: tasks.length,
      rate: acceptedTasks.length / tasks.length
    },
    rework: tasks.length - acceptedTasks.length,
    totalCost: Math.round(totalCost),
    costPerAccepted: Math.round(totalCost / Math.max(acceptedTasks.length, 1)),
    errorsBeforeRoute: rerouted.length,
    clarified: missingBeforeRoute,
    generatedAt: "deterministic"
  };
}

export function verifyRollback(v1Snapshot, v2Snapshot, tasks = TASKS) {
  const replayV1 = runPolicy(POLICY_V1, tasks);
  const replayV2 = runPolicy(v2Snapshot.policy, tasks);
  return deepFreeze({
    v1Matches: replayV1.signature === v1Snapshot.signature,
    v2Matches: replayV2.signature === v2Snapshot.signature,
    consistent: replayV1.signature === v1Snapshot.signature &&
      replayV2.signature === v2Snapshot.signature
  });
}

export function createRunSnapshot(policy, tasks = TASKS, executors = EXECUTORS) {
  const run = runPolicy(policy, tasks, executors);
  return deepFreeze({
    policy,
    results: run.results,
    metrics: run.metrics,
    signature: run.signature
  });
}

function signatureFor(value) {
  return fnv1a(stableStringify(value));
}

function fnv1a(text) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function stableStringify(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
}

function deepFreeze(value) {
  if (value === null || typeof value !== "object" || Object.isFrozen(value)) {
    return value;
  }
  Object.freeze(value);
  for (const child of Object.values(value)) deepFreeze(child);
  return value;
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function round(value, digits) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}
