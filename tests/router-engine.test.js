import test from "node:test";
import assert from "node:assert/strict";

import {
  TASKS,
  PRESET_FEEDBACK
} from "../src/data.js";
import {
  POLICY_V1,
  createRunSnapshot,
  learnPolicyV2,
  routeTask,
  runPolicy,
  verifyRollback
} from "../src/router-engine.js";

const taskById = new Map(TASKS.map((task) => [task.id, task]));

test("v1 因关键词缺项产生三个可解释的校准集误分", () => {
  const run = runPolicy(POLICY_V1);
  const picks = new Map(run.results.map((result) => [result.taskId, result.selected]));

  assert.equal(picks.get("T3"), "D");
  assert.equal(picks.get("T4"), "A");
  assert.equal(picks.get("T6"), "A");

  const t3 = routeTask(taskById.get("T3"), POLICY_V1);
  assert.equal(t3.taskType, "research_analysis");
  assert.deepEqual(t3.riskTags, []);
  assert.match(t3.rationale, /关键词/);
});

test("v2 校准集 8/8，隐藏集由 2/4 提升到 4/4", () => {
  const v1 = runPolicy(POLICY_V1);
  const v2Policy = learnPolicyV2(POLICY_V1, PRESET_FEEDBACK);
  const v2 = runPolicy(v2Policy);

  assert.deepEqual(v1.metrics.calibrationTop1, { correct: 4, total: 8, rate: 0.5 });
  assert.deepEqual(v1.metrics.hiddenTop1, { correct: 2, total: 4, rate: 0.5 });
  assert.deepEqual(v1.metrics.complianceCoverage, { covered: 0, total: 4, rate: 0 });
  assert.deepEqual(v2.metrics.calibrationTop1, { correct: 8, total: 8, rate: 1 });
  assert.deepEqual(v2.metrics.hiddenTop1, { correct: 4, total: 4, rate: 1 });

  assert.equal(v2.results.find((result) => result.taskId === "H1").selected, "C");
  assert.equal(v2.results.find((result) => result.taskId === "H4").selected, "D");
});

test("v2 高风险任务合规覆盖率为 100%", () => {
  const v2Policy = learnPolicyV2(POLICY_V1, PRESET_FEEDBACK);
  const v2 = runPolicy(v2Policy);

  assert.deepEqual(v2.metrics.complianceCoverage, { covered: 4, total: 4, rate: 1 });
  for (const result of v2.results) {
    const task = taskById.get(result.taskId);
    if (task.riskTags.length > 0) {
      assert.equal(result.safetyCovered, true);
      assert.ok(result.requiredReviewers.includes("C"));
      assert.ok(result.requiredReviewers.includes("人工复核"));
    }
  }
});

test("学习只读取结构化反馈，不读取隐藏任务或隐藏标签", () => {
  const poisonedTasks = new Proxy([], {
    get() {
      throw new Error("学习函数不应读取任务集");
    },
    ownKeys() {
      throw new Error("学习函数不应枚举任务集");
    }
  });

  const policy = learnPolicyV2(POLICY_V1, PRESET_FEEDBACK, poisonedTasks);
  const evidenceIds = policy.evidenceEvents.map((event) => event.eventId);

  assert.deepEqual(evidenceIds.sort(), ["FB-T3", "FB-T4", "FB-T6"]);
  assert.equal(policy.learningSummary.hiddenLabelsRead, false);
  assert.ok(policy.rules.every((rule) => !rule.id.startsWith("H")));
});

test("无反馈或非法反馈不能生成 v2", () => {
  assert.throws(() => learnPolicyV2(POLICY_V1, []), /至少需要一条/);
  assert.throws(
    () => learnPolicyV2(POLICY_V1, [{ ...PRESET_FEEDBACK[0], correctType: "unknown" }]),
    /未知任务类型/
  );
  assert.throws(
    () => learnPolicyV2(POLICY_V1, [{ ...PRESET_FEEDBACK[0], correctExecutor: "Z" }]),
    /未知执行者/
  );
});

test("回滚与恢复通过不可变快照重新运行验证", () => {
  const v1 = createRunSnapshot(POLICY_V1);
  const v2Policy = learnPolicyV2(POLICY_V1, PRESET_FEEDBACK);
  const v2 = createRunSnapshot(v2Policy);
  const verification = verifyRollback(v1, v2);

  assert.equal(Object.isFrozen(v1), true);
  assert.equal(Object.isFrozen(v2), true);
  assert.equal(Object.isFrozen(v1.results[0]), true);
  assert.equal(verification.consistent, true);
  assert.equal(verification.v1Matches, true);
  assert.equal(verification.v2Matches, true);

  const replayV1 = runPolicy(POLICY_V1);
  assert.equal(replayV1.signature, v1.signature);
});

test("v2 对新版会员权益 FAQ 和条款比较保持正确迁移", () => {
  const v2Policy = learnPolicyV2(POLICY_V1, PRESET_FEEDBACK);
  const h2 = routeTask(taskById.get("H2"), v2Policy);
  const h3 = routeTask(taskById.get("H3"), v2Policy);

  assert.equal(h2.selected, "E");
  assert.equal(h2.taskType, "product_docs");
  assert.equal(h3.selected, "D");
  assert.equal(h3.taskType, "research_analysis");
  assert.ok(h3.top3.some((candidate) => candidate.executorId === "C"));
  assert.equal(h3.safetyCovered, true);
});
