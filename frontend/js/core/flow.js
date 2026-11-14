/* 任务流程：发布 → 认领 → 选定执行者 → 提交成果 → 验收（通过结算 / 要求返工）。
   接单方和发包方的状态变化都集中在这里，页面只调用这些函数，不直接改状态字段。
   各状态的含义见 data/mock.js 顶部注释。 */

const PLATFORM_FEE_RATE = 0.05;
const netIncome = gross => gross - gross * PLATFORM_FEE_RATE;

// 接单方状态：工作台分组、标签文字
const WORK_STATUS = {
  accepted:{label:'已认领', tab:'accepted', tone:'', note:'等待发包方选定执行者'},
  active:{label:'进行中', tab:'active', tone:'cyan', note:''},
  rework:{label:'需返工', tab:'active', tone:'coral', note:'发包方要求修改后重新提交'},
  submitted:{label:'待验收', tab:'review', tone:'amber', note:'已提交，等待发包方验收'},
  completed:{label:'已完成', tab:'done', tone:'cyan', note:''},
  declined:{label:'未选中', tab:'done', tone:'', note:'发包方选择了其他执行者'}
};
const WORK_TABS = [['accepted','已认领'], ['active','进行中'], ['review','待验收'], ['done','已结束']];

// 发包方状态
const PUB_STATUS = {
  recruiting:{label:'招募中', tone:'cyan'},
  working:{label:'执行中', tone:''},
  reviewing:{label:'待你验收', tone:'amber'},
  done:{label:'已完成', tone:''}
};

const nowISO = () => new Date().toISOString();

/* ---------- 接单方 ---------- */
function claimTask(id){
  if(!workItemFor(id)) state.workItems.push({taskId:id, status:'accepted', addedAt:nowISO()});
  persistState();
}

function cancelClaim(id){
  state.workItems = state.workItems.filter(item => item.taskId !== id);
  persistState();
}

// 提交成果：进行中或返工中的任务才能提交；提交后不能再改，等发包方验收
function submitWork(id, files, note){
  const item = workItemFor(id);
  if(!item || (item.status !== 'active' && item.status !== 'rework')) return '当前任务不能提交';
  if(!files.length) return '至少上传一个交付文件';
  item.submission = {files:files.slice(), note:note.trim(), at:nowISO()};
  item.status = 'submitted';
  delete state.submitDraft[id];
  persistState();
  return '';
}

/* ---------- 演示：替发包方推进接单方的任务 ----------
   原型里没有第二个真实用户，接单方页面用这几个函数模拟发包方的选定和验收结果。 */
// 返工原因取该任务的第一条验收标准，保证和任务内容对得上
const demoReworkReason = t => '「' + t.accept[0] + '」这一条还没有达到，请修改后重新提交，并在说明里写清改了什么。';

function demoSelect(id, chosen){
  const item = workItemFor(id);
  if(!item || item.status !== 'accepted') return;
  Object.assign(item, chosen ? {status:'active', selectedAt:nowISO()} : {status:'declined', closedAt:nowISO()});
  persistState();
}

function demoReview(id, pass){
  const item = workItemFor(id);
  if(!item || item.status !== 'submitted') return;
  if(pass) Object.assign(item, {status:'completed', completedAt:nowISO(), review:{decision:'pass', at:nowISO()}});
  else Object.assign(item, {status:'rework', review:{decision:'rework', reason:demoReworkReason(taskById(id)), at:nowISO()}});
  persistState();
}

/* ---------- 发包方 ---------- */
// 认领者：按任务 id 稳定地取几位示例认领者（演示用）
function applicantsOf(task){
  const seed = [...task.id].reduce((n, c) => n + c.charCodeAt(0), 0);
  const count = 2 + seed % 3;
  return Array.from({length:count}, (_, i) => APPLICANT_POOL[(seed + i) % APPLICANT_POOL.length]);
}
const applicantById = id => APPLICANT_POOL.find(a => a.id === id);

function selectWorker(taskId, applicantId){
  const task = publishedById(taskId);
  if(!task || task.status !== 'recruiting') return '任务已不在招募阶段';
  Object.assign(task, {status:'working', workerId:applicantId, selectedAt:nowISO()});
  persistState();
  return '';
}

// 演示：执行者“提交了成果”。真实环境由执行者端触发，这里给发包方一个按钮模拟
function simulateDelivery(taskId){
  const task = publishedById(taskId);
  if(!task || task.status !== 'working') return;
  Object.assign(task, {status:'reviewing', submission:Object.assign({at:nowISO()}, clone(DEMO_SUBMISSION))});
  persistState();
}

// 验收：passed 是勾选通过的验收标准下标。全部通过才能结算；要求返工必须写原因
function reviewPass(taskId){
  const task = publishedById(taskId);
  if(!task || task.status !== 'reviewing') return '没有待验收的成果';
  const passed = state.reviewDraft[taskId] || [];
  if(passed.length < task.accept.length) return '还有验收标准没有勾选通过';
  Object.assign(task, {status:'done', review:{decision:'pass', passed:passed.slice(), at:nowISO()}});
  delete state.reviewDraft[taskId];
  persistState();
  return '';
}

function reviewRework(taskId, reason){
  const task = publishedById(taskId);
  if(!task || task.status !== 'reviewing') return '没有待验收的成果';
  if(reason.trim().length < 6) return '请写清需要修改的地方（至少 6 个字）';
  task.reworks = (task.reworks || []).concat({reason:reason.trim(), at:nowISO(), submission:task.submission});
  Object.assign(task, {status:'working', submission:null});
  delete state.reviewDraft[taskId];
  persistState();
  return '';
}
