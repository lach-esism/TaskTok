export const EXECUTORS = Object.freeze([
  Object.freeze({
    id: "A",
    name: "中文内容编辑",
    shortName: "内容编辑",
    type: "AI Agent",
    costLevel: 0.18,
    capabilities: Object.freeze({
      writing: 0.95,
      data: 0.28,
      compliance: 0.2,
      research: 0.38,
      docs: 0.58
    }),
    reliability: Object.freeze({
      writing: 0.91,
      data: 0.62,
      compliance: 0.36,
      research: 0.51,
      docs: 0.68
    }),
    evidence: Object.freeze([
      "公众号与官网文案历史通过率高",
      "普通营销表达稳定，但高风险消费者权益任务证据不足"
    ])
  }),
  Object.freeze({
    id: "B",
    name: "数据整理分析",
    shortName: "数据分析",
    type: "AI Agent",
    costLevel: 0.36,
    capabilities: Object.freeze({
      writing: 0.37,
      data: 0.96,
      compliance: 0.3,
      research: 0.56,
      docs: 0.42
    }),
    reliability: Object.freeze({
      writing: 0.56,
      data: 0.94,
      compliance: 0.44,
      research: 0.65,
      docs: 0.54
    }),
    evidence: Object.freeze([
      "表格清洗、去重和缺失值检查稳定",
      "能完成封闭口径统计，不负责开放式用户洞察"
    ])
  }),
  Object.freeze({
    id: "C",
    name: "合规预审",
    shortName: "合规预审",
    type: "人机组合",
    costLevel: 0.78,
    capabilities: Object.freeze({
      writing: 0.55,
      data: 0.43,
      compliance: 0.97,
      research: 0.61,
      docs: 0.65
    }),
    reliability: Object.freeze({
      writing: 0.67,
      data: 0.58,
      compliance: 0.95,
      research: 0.72,
      docs: 0.76
    }),
    evidence: Object.freeze([
      "广告绝对化用语、个人信息和自动续费初审经验",
      "关键风险结论必须进入企业人员人工复核"
    ])
  }),
  Object.freeze({
    id: "D",
    name: "用户研究",
    shortName: "用户研究",
    type: "AI Agent",
    costLevel: 0.62,
    capabilities: Object.freeze({
      writing: 0.69,
      data: 0.72,
      compliance: 0.42,
      research: 0.94,
      docs: 0.59
    }),
    reliability: Object.freeze({
      writing: 0.74,
      data: 0.77,
      compliance: 0.51,
      research: 0.92,
      docs: 0.66
    }),
    evidence: Object.freeze([
      "竞品资料核验、反馈聚类和代表原话提炼",
      "能区分事实、来源和研究者判断"
    ])
  }),
  Object.freeze({
    id: "E",
    name: "产品文档",
    shortName: "产品文档",
    type: "AI Agent",
    costLevel: 0.42,
    capabilities: Object.freeze({
      writing: 0.72,
      data: 0.34,
      compliance: 0.36,
      research: 0.4,
      docs: 0.96
    }),
    reliability: Object.freeze({
      writing: 0.78,
      data: 0.52,
      compliance: 0.48,
      research: 0.55,
      docs: 0.93
    }),
    evidence: Object.freeze([
      "FAQ、帮助中心、版本说明和服务知识库",
      "善用固定术语，对不确定事实会先追问"
    ])
  })
]);

export const TASKS = Object.freeze([
  Object.freeze({
    id: "T1",
    set: "calibration",
    title: "功能说明改 FAQ",
    request: "把三条新版功能说明改成 FAQ，保留适用版本，语气适合官网帮助中心。",
    deliverable: "三问三答 FAQ，并保留适用版本信息",
    expected: "E",
    alternatives: Object.freeze(["A"]),
    riskTags: Object.freeze([]),
    requiredEvidence: Object.freeze(["每个答案对应一个具体问题", "保留适用版本"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 22
  }),
  Object.freeze({
    id: "T2",
    set: "calibration",
    title: "CRM 表格清洗",
    request: "清洗 CRM 导出表中的重复和缺失记录，补齐必填客户字段并输出问题清单。",
    deliverable: "清理后的表格和异常记录清单",
    expected: "B",
    alternatives: Object.freeze([]),
    riskTags: Object.freeze([]),
    requiredEvidence: Object.freeze(["完成去重", "缺失值有处理说明"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 38
  }),
  Object.freeze({
    id: "T3",
    set: "calibration",
    title: "个人信息条款审查",
    request: "检查会员协议中的个人信息收集条款，指出风险点并给出修改建议。",
    deliverable: "风险点、依据、修改建议和待人工复核项",
    expected: "C",
    alternatives: Object.freeze([]),
    riskTags: Object.freeze(["个人信息"]),
    requiredEvidence: Object.freeze(["标明风险位置", "给出依据", "进入人工复核"]),
    clarity: "needs_clarification",
    missingInfo: "未说明要检查的收集渠道、使用目的和保存期限",
    fixedCost: 54
  }),
  Object.freeze({
    id: "T4",
    set: "calibration",
    title: "竞品差异摘要",
    request: "根据三份竞品公开资料写一页差异摘要，事实和判断分开并附来源链接。",
    deliverable: "一页差异摘要、来源引用和事实/判断分区",
    expected: "D",
    alternatives: Object.freeze(["A"]),
    riskTags: Object.freeze([]),
    requiredEvidence: Object.freeze(["来源链接可追溯", "事实与判断分离"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 46
  }),
  Object.freeze({
    id: "T5",
    set: "calibration",
    title: "课程公众号介绍",
    request: "为在线课程写一篇公众号介绍，800 字左右，包含标题、受众和报名引导。",
    deliverable: "800 字中文文章和一个标题",
    expected: "A",
    alternatives: Object.freeze([]),
    riskTags: Object.freeze([]),
    requiredEvidence: Object.freeze(["面向明确受众", "含报名引导"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 28
  }),
  Object.freeze({
    id: "T6",
    set: "calibration",
    title: "促销文案合规检查",
    request: "检查促销文案中的绝对化用语，给出风险说明和合规改写版本。",
    deliverable: "风险说明和合规改写文案",
    expected: "C",
    alternatives: Object.freeze([]),
    riskTags: Object.freeze(["绝对化用语"]),
    requiredEvidence: Object.freeze(["指出风险表达", "给出替换写法", "进入人工复核"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 48
  }),
  Object.freeze({
    id: "T7",
    set: "calibration",
    title: "版本日志改客服问答",
    request: "把版本日志改成客服标准问答，共五条，面向首次使用会员的用户。",
    deliverable: "五条客服标准问答",
    expected: "E",
    alternatives: Object.freeze([]),
    riskTags: Object.freeze([]),
    requiredEvidence: Object.freeze(["五条问答", "面向首次使用者"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 24
  }),
  Object.freeze({
    id: "T8",
    set: "calibration",
    title: "用户反馈聚类",
    request: "聚类 100 条用户反馈并提炼 Top 5 问题，附代表原话和数量。",
    deliverable: "五个主题、数量、代表原话和归纳理由",
    expected: "D",
    alternatives: Object.freeze(["B"]),
    riskTags: Object.freeze([]),
    requiredEvidence: Object.freeze(["主题互斥且可解释", "代表原话可追溯"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 52
  }),
  Object.freeze({
    id: "H1",
    set: "hidden",
    title: "自动续费提示检查",
    request: "检查自动续费服务的提示文案是否清楚，指出消费者权益风险和修改建议。",
    deliverable: "风险点、消费者提示改写建议和人工复核项",
    expected: "C",
    alternatives: Object.freeze([]),
    riskTags: Object.freeze(["自动续费", "消费者权益"]),
    requiredEvidence: Object.freeze(["突出续费时间和取消方式", "进入人工复核"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 56
  }),
  Object.freeze({
    id: "H2",
    set: "hidden",
    title: "会员权益 FAQ",
    request: "将新版会员权益整理为官网 FAQ，保留适用版本和限制条件。",
    deliverable: "六问六答官网 FAQ，含适用版本与限制条件",
    expected: "E",
    alternatives: Object.freeze([]),
    riskTags: Object.freeze([]),
    requiredEvidence: Object.freeze(["权益和限制不能被省略", "适用版本清楚"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 26
  }),
  Object.freeze({
    id: "H3",
    set: "hidden",
    title: "课程条款比较",
    request: "比较两家在线教育产品公开的课程服务条款，输出对比结论和引用来源，并标出消费者权益风险。",
    deliverable: "条款差异摘要、引用来源和消费者权益风险标注",
    expected: "D",
    alternatives: Object.freeze(["C"]),
    riskTags: Object.freeze(["消费者权益"]),
    requiredEvidence: Object.freeze(["来源可追溯", "风险进入合规复核"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 58
  }),
  Object.freeze({
    id: "H4",
    set: "hidden",
    title: "课程评价洞察",
    request: "整理 60 条课程评价并输出 Top 5 问题，按频次排序并附代表评价。",
    deliverable: "五个高频问题、频次和代表评价",
    expected: "D",
    alternatives: Object.freeze(["B"]),
    riskTags: Object.freeze([]),
    requiredEvidence: Object.freeze(["频次计算正确", "代表评价保留原意"]),
    clarity: "clear",
    missingInfo: "",
    fixedCost: 50
  })
]);

export const PRESET_FEEDBACK = Object.freeze([
  Object.freeze({
    eventId: "FB-T3",
    taskId: "T3",
    correctExecutor: "C",
    correctType: "compliance_review",
    reason: "涉及个人信息收集，属于高风险合规任务，用户研究不能替代合规初审。",
    taskClear: false,
    suggestion: "下一轮先追问收集渠道、使用目的和保存期限，再交给合规通道。"
  }),
  Object.freeze({
    eventId: "FB-T6",
    taskId: "T6",
    correctExecutor: "C",
    correctType: "compliance_review",
    reason: "促销文案含绝对化表述，合规风险高于普通内容创作。",
    taskClear: true,
    suggestion: "检测到绝对化用语时，至少加入 C 的合规预审和人工复核节点。"
  }),
  Object.freeze({
    eventId: "FB-T4",
    taskId: "T4",
    correctExecutor: "D",
    correctType: "research_analysis",
    reason: "核心工作是公开资料核验、比较和引用，不是通用文案写作。",
    taskClear: true,
    suggestion: "把竞品、公开资料、来源引用识别为研究任务，不再按写作任务派发。"
  })
]);

export const TASK_TYPE_LABELS = Object.freeze({
  content_creation: "内容创作",
  data_cleaning: "数据整理",
  compliance_review: "合规预审",
  research_analysis: "研究核验",
  product_docs: "产品文档"
});

export const RISK_LABELS = Object.freeze({
  "个人信息": "个人信息",
  "绝对化用语": "绝对化用语",
  "自动续费": "自动续费",
  "消费者权益": "消费者权益"
});
