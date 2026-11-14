/* 接入后端：后端在线时，用 /market 接口的数据替换 mock.js 的示例数据，
   并让 core/flow.js 的每个流程动作同时提交到后端。

   做法：
   - 流程函数先照常在本地改状态（页面立即有反馈），再调用接口；
     接口成功后用后端返回的数据整体刷新，失败则提示原因并按后端数据回滚。
   - TASKS / CATS / APPLICANT_POOL / INCOME_SERIES 是 const 数组，原地替换内容。
   - 工作台和“我发布的任务”以后端为准，不再写进 localStorage（避免和离线示例数据混在一起）。
   后端离线（file:// 打开或接口不可用）时，这个文件什么都不改。 */

const remote = {me:null, loaded:false};

// 原地替换数组内容（这些数组在其他脚本里是 const）
const replaceArray = (target, items) => { target.splice(0, target.length, ...items); };

function rememberApplicants(list){
  list.forEach(a => {
    const at = APPLICANT_POOL.findIndex(x => x.id === a.id);
    if(at > -1) APPLICANT_POOL[at] = a; else APPLICANT_POOL.push(a);
  });
}

function applyWorkItems(data){
  state.workItems = data.items;
  replaceArray(KNOWN_TASKS, data.tasks);
}

function applyPublished(list){
  state.published = list;
  list.forEach(t => {
    rememberApplicants(t.applicantList || []);
    if(t.worker) rememberApplicants([t.worker]);
  });
}

function applyFeed(feed){
  API.requestId = feed.request_id;
  replaceArray(TASKS, feed.items);
  const cats = [];
  feed.items.forEach(t => { if(t.cat && !cats.includes(t.cat)) cats.push(t.cat); });
  replaceArray(CATS, ['全部'].concat(cats));
  if(!CATS.includes(state.filters.category)) state.filters.category = '全部';
}

async function loadMarket(){
  const [feed, work, published, me] = await Promise.all([
    apiGet('/market/feed'), apiGet('/market/work-items'), apiGet('/market/published'), apiGet('/market/me')
  ]);
  applyFeed(feed);
  applyWorkItems(work);
  applyPublished(published);
  remote.me = me;
  replaceArray(INCOME_SERIES, me.incomeSeries);
  CURRENT_USER.name = me.name;
  CURRENT_USER.avatar = me.avatar;
}

// 流程动作之后：刷新工作台、发布列表和个人数据（推荐流不重拉，避免翻页位置和顺序跳动）
async function refreshMarket(){
  const [work, published, me] = await Promise.all([
    apiGet('/market/work-items'), apiGet('/market/published'), apiGet('/market/me')
  ]);
  applyWorkItems(work);
  applyPublished(published);
  remote.me = me;
  replaceArray(INCOME_SERIES, me.incomeSeries);
  pages[state.route]?.render?.();
}

function sendAction(method, path, body){
  return apiRequest(method, path, body)
    .catch(error => { toast(error.message); })
    .finally(() => refreshMarket().catch(error => toast(error.message)));
}

const taskPath = id => '/market/tasks/' + encodeURIComponent(id);

/* ---------- 流程动作：本地先更新，再提交后端 ---------- */
function bindFlowToBackend(){
  const local = {claimTask, cancelClaim, submitWork, selectWorker, simulateDelivery, reviewPass, reviewRework, buildTask};

  claimTask = id => {
    local.claimTask(id);
    sendAction('POST', taskPath(id) + '/applications', {request_id:API.requestId});
  };
  cancelClaim = id => {
    local.cancelClaim(id);
    sendAction('DELETE', taskPath(id) + '/applications');
  };
  submitWork = (id, files, note) => {
    const problem = local.submitWork(id, files, note);
    if(!problem) sendAction('POST', taskPath(id) + '/submission', {files, note});
    return problem;
  };
  selectWorker = (taskId, workerId) => {
    const problem = local.selectWorker(taskId, workerId);
    if(!problem) sendAction('POST', taskPath(taskId) + '/select', {worker_id:workerId});
    return problem;
  };
  simulateDelivery = taskId => {
    local.simulateDelivery(taskId);
    sendAction('POST', taskPath(taskId) + '/simulate-delivery');
  };
  reviewPass = taskId => {
    const passed = (state.reviewDraft[taskId] || []).slice();
    const problem = local.reviewPass(taskId);
    if(!problem) sendAction('POST', taskPath(taskId) + '/review', {passed});
    return problem;
  };
  reviewRework = (taskId, reason) => {
    const problem = local.reviewRework(taskId, reason);
    if(!problem) sendAction('POST', taskPath(taskId) + '/review', {decision:'rework', reason:reason.trim()});
    return problem;
  };
  // 工作台里的演示按钮：替发包方选定 / 拒绝 / 验收，走后端的同一套接口
  const localDemo = {demoSelect, demoReview};
  demoSelect = (id, chosen) => {
    localDemo.demoSelect(id, chosen);
    sendAction('POST', taskPath(id) + (chosen ? '/select' : '/decline'), {worker_id:remote.me.workerId});
  };
  demoReview = (id, pass) => {
    localDemo.demoReview(id, pass);
    const t = taskById(id);
    sendAction('POST', taskPath(id) + '/review', pass
      ? {passed:t.accept.map((_, i) => i)}
      : {decision:'rework', reason:workItemFor(id)?.review?.reason || demoReworkReason(t)});
  };
  // 新建任务：沿用前端生成的对象，id 换成后端认可的 pub_ 格式，发布到后端后以后端数据为准
  buildTask = d => {
    const task = local.buildTask(d);
    task.id = 'pub_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    task.applicantList = [];
    const payload = {
      id:task.id, title:task.title, desc:task.desc, budget:task.budgetNum, level:task.level,
      claimDeadline:task.claimDeadline, deliverDeadline:task.deliverDeadline,
      verify:task.verify, outputs:task.outputs, accept:task.accept
    };
    setTimeout(() => sendAction('POST', '/market/tasks', payload), 0);
    return task;
  };
  // 认领者名单来自后端（发布时按推荐结果邀请，加上真实认领）
  applicantsOf = task => task.applicantList || [];

  // 修改任务：publish.js 的保存按钮先在本地校验并更新，这里在它之后把结果提交后端
  document.addEventListener('click', e => {
    if(!e.target.closest('#savePublished') || state.pubEditing) return;
    const t = publishedById(state.selectedPublishedId);
    if(!t) return;
    sendAction('PATCH', taskPath(t.id), {
      title:t.title, desc:t.desc, budget:t.budgetNum, deliverDeadline:t.deliverDeadline
    });
  });
}

/* ---------- 个人数据：把 index.html 里的示例数字换成后端数据 ---------- */
const pct = v => v + '%';
const shortDate = iso => { const d = new Date(iso); return (d.getMonth() + 1) + '/' + String(d.getDate()).padStart(2, '0'); };

function setText(el, text){ if(el) el.textContent = text; }

function fillProfile(){
  const me = remote.me;
  if(!me) return;
  const head = $('#view-me .pf-head');
  setText(head.querySelector('.avatar'), me.avatar);
  setText(head.querySelector('.pf-name'), me.name);
  setText(head.querySelector('.chip'), me.level + ' ' + me.levelText);
  setText(head.querySelector('p.sub'), me.headline);
  const stats = $$('#view-me .pf-stats b');
  setText(stats[0], yuan(me.monthIncome));
  setText(stats[1], me.completed);
  setText(stats[2], pct(me.onTime));
  const level = Number(me.level.slice(1));
  setText($('#view-me .level-card .h3'), me.level + ' ' + me.levelText + ' · 已完成 ' + me.completed + ' 个任务');
  $$('#view-me .level-card .level i').forEach((dot, i) => dot.classList.toggle('on', i < level));
}

function fillSkills(){
  const me = remote.me;
  if(!me) return;
  const metrics = $$('#view-skills .metric');
  setText(metrics[0], me.completed);
  setText(metrics[1], pct(me.onTime));
  setText(metrics[2], pct(me.repeat));
  $('#view-skills .cap').innerHTML = me.capability.map(c => html`
    <div class="caprow"><span class="n">${c.label}</span><div class="bar ${c.score < 60 ? 'coral' : ''}"><i style="width:${c.score}%"></i></div><span class="v">${c.score}</span></div>`).join('');
}

function fillIncome(){
  const me = remote.me;
  if(!me) return;
  setText($('#view-income .metric'), yuan(me.monthIncome));
  const ends = $$('#view-income .sub.xs');
  setText(ends[0], shortDate(me.incomeFrom));
  setText(ends[1], shortDate(me.incomeTo));
}

function fillFeedSide(){
  const me = remote.me;
  const top = TASKS[0];
  const [matchPanel, weekPanel] = $$('#view-feed .feed-side .panel');
  if(top && matchPanel){
    setText(matchPanel.querySelector('.accent'), pct(top.match));
    matchPanel.querySelector('.bar i').style.width = pct(top.match);
    matchPanel.querySelector('.list').innerHTML = (top.why || []).map(text =>
      html`<div class="li"><span class="dot"></span><span>${text}</span></div>`).join('');
  }
  if(weekPanel){
    const count = (...statuses) => state.workItems.filter(w => statuses.includes(w.status)).length;
    setText(weekPanel.querySelector('.chip'), '进行中 ' + count('active', 'rework'));
    setText(weekPanel.querySelector('.money'), count('submitted') + ' 个');
    if(me) setText(weekPanel.querySelector('.money-text'), yuan(me.monthIncome));
  }
}

function wrapRender(route, fill){
  const page = pages[route] || (pages[route] = {});  // 能力图谱页原本是纯静态，没有注册 render
  const render = page.render;
  page.render = function(){ if(render) render.apply(this, arguments); fill(); };
}

/* ---------- 启动 ---------- */
async function connectBackend(){
  if(!(await detectBackend())) return false;
  try{
    await loadMarket();
  }catch(error){
    API.online = false;
    toast('后端数据加载失败，当前显示示例数据');
    console.warn(error);
    return false;
  }
  // 工作台和发布列表以后端为准，不再存本地
  ['workItems', 'published'].forEach(key => {
    const at = PERSISTED_KEYS.indexOf(key);
    if(at > -1) PERSISTED_KEYS.splice(at, 1);
  });
  state.saved = new Set(Array.from(state.saved).filter(id => findTask(id)));
  state.recent = state.recent.filter(id => findTask(id));
  if(!findTask(state.taskId) && TASKS[0]) state.taskId = TASKS[0].id;
  bindFlowToBackend();
  wrapRender('me', fillProfile);
  wrapRender('skills', fillSkills);
  wrapRender('income', fillIncome);
  wrapRender('feed', fillFeedSide);
  remote.loaded = true;
  return true;
}
