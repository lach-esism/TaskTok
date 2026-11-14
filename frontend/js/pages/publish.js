/* 发布方：新建任务（一页表单）、我发布的任务列表、单个任务管理页。
   任务管理页按状态显示不同内容：
     招募中   → 认领者名单，选定执行者；可修改任务
     执行中   → 执行者信息和截止时间（演示：模拟执行者交付）
     待你验收 → 交付文件 + 验收标准逐条核对 → 通过结算 / 要求返工
     已完成   → 验收记录和结算金额 */

/* ---------- 新建任务表单 ---------- */
const PUB_DEFAULT = () => ({
  title:'TikTok 美国区投放：CAC 降到 35 美元以下',
  desc:'3 月美国区广告 CAC 在 42 美元左右，希望 3 月 28 日前连续 7 天降到 35 美元以下。可以提供近 90 天投放报表、素材库和后台只读权限。',
  budget:8000, level:'L3',
  claimDeadline:dateValue(isoDaysAhead(3)), deliverDeadline:dateValue(isoDaysAhead(14)),
  verify:'metrics',
  outputs:['投放诊断报告：CAC 构成和主要损耗点', '两组 A/B 测试方案及执行记录', '达标后的投放 SOP'],
  accept:['以投放后台数据为准，CAC 连续 7 天低于 35 美元', '测试方案执行前需经我确认', '报告中的每个结论都有数据支撑']
});
const draft = () => state.pubDraft || (state.pubDraft = PUB_DEFAULT());

// 可增删的文字列表（交付物、验收标准）
function listEditor(kind, items){
  return html`${items.map((text, i) => html`
    <div class="list-row">
      <span class="list-idx">${i + 1}</span>
      <input value="${text}" data-list-item="${i}" aria-label="第 ${i + 1} 项">
      <button type="button" class="icon-mini" data-list-remove="${i}" aria-label="删除">${ico('trash', 14)}</button>
    </div>`)}
    <button type="button" class="list-add" data-list-add>${ico('plus', 14)}添加一项</button>`;
}

function renderListEditors(){
  $$('#pubForm [data-list]').forEach(box => {
    box.innerHTML = listEditor(box.dataset.list, draft()[box.dataset.list]);
  });
}

function renderVerifyOptions(){
  const d = draft();
  if(!VERIFY_METHODS[d.verify]) d.verify = 'manual';
  $('#pubVerifyOptions').innerHTML = Object.entries(VERIFY_METHODS).map(([key, m]) => html`
    <button type="button" class="verify-option ${key === d.verify ? 'on' : ''}" data-verify="${key}">
      <span class="verify-radio"><i></i></span>
      <span class="verify-copy"><b>${m.label}</b><span>${m.hint}</span></span>
    </button>`).join('');
}

function fillPublishForm(){
  const d = draft();
  $$('#pubForm [data-pub]').forEach(el => { el.value = d[el.dataset.pub] ?? ''; });
  renderListEditors();
  renderVerifyOptions();
}

const cleanList = list => list.map(s => String(s).trim()).filter(Boolean);

// 发布前校验；返回第一条错误，同时定位到对应输入框
function validateDraft(d){
  const claim = new Date(d.claimDeadline + 'T18:00:00');
  const deliver = new Date(d.deliverDeadline + 'T18:00:00');
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const checks = [
    [d.title.trim().length < 4, 'pubTitle', '任务标题至少写 4 个字'],
    [d.desc.trim().length < 10, 'pubDesc', '背景和要求再具体一点'],
    [!cleanList(d.outputs).length, null, '至少写一项交付物'],
    [!(Number(d.budget) >= 100), 'pubBudget', '预算至少 ¥100'],
    [!d.claimDeadline || Number.isNaN(claim.getTime()), 'pubClaimDeadline', '请填写认领截止时间'],
    [claim < today, 'pubClaimDeadline', '认领截止不能早于今天'],
    [!d.deliverDeadline || Number.isNaN(deliver.getTime()), 'pubDeliverDeadline', '请填写交付截止时间'],
    [deliver < claim, 'pubDeliverDeadline', '交付截止不能早于认领截止'],
    [!cleanList(d.accept).length, null, '至少写一条验收标准']
  ];
  const hit = checks.find(([bad]) => bad);
  if(!hit) return '';
  if(hit[1]) $('#' + hit[1])?.focus();
  return hit[2];
}

function buildTask(d){
  const now = nowISO();
  const budget = Number(d.budget);
  const outputs = cleanList(d.outputs), accept = cleanList(d.accept);
  return {
    id:'published-' + Date.now(),
    title:d.title.trim(), desc:d.desc.trim(),
    poster:CURRENT_USER.name, avatar:CURRENT_USER.avatar, cover:null, cat:'增长投放',
    level:d.level, levelText:LEVEL_TEXT[d.level],
    budget:yuan(budget), budgetNum:budget,
    deadline:'至 ' + formatDateCN(deadlineISO(d.deliverDeadline)), hours:0, match:0, rate:0,
    publishedAt:now, createdAt:now,
    claimDeadline:deadlineISO(d.claimDeadline), deliverDeadline:deadlineISO(d.deliverDeadline),
    verify:d.verify, status:'recruiting',
    outputs, accept,
    checks:outputs.slice(),
    why:['这是你发布的任务'],
    contract:[['目标', d.title.trim()], ['交付物', outputs.join('；')], ['验收方式', verifyOf(d.verify).label]]
  };
}

function submitNewTask(){
  const d = draft();
  const problem = validateDraft(d);
  if(problem){ toast(problem); return; }
  const task = buildTask(d);
  task.applicants = applicantsOf(task).length;
  state.published.unshift(task);
  state.pubDraft = null;
  persistState();
  toast('任务已发布，等待执行者认领');
  go('pubtask', task.id);
}

/* ---------- 我发布的任务 ---------- */
const isRecruitingOpen = t => t.status === 'recruiting' && new Date(t.claimDeadline).getTime() >= Date.now();
const statusChip = t => { const s = PUB_STATUS[t.status] || PUB_STATUS.recruiting; return html`<span class="chip ${s.tone}">${s.label}</span>`; };

// 列表行的一句话状态：发包方最关心的“下一步要我做什么”
function pubNextStep(t){
  return {
    recruiting:applicantsOf(t).length + ' 人认领，去选定执行者',
    working:'执行中 · ' + formatDateCN(t.deliverDeadline) + ' 前交付',
    reviewing:'执行者已提交，等你验收',
    done:'已验收 · 结算 ' + yuan(t.budgetNum)
  }[t.status] || '';
}

function publishedCard(t){
  return html`
    <button class="published-card ${t.status === 'reviewing' ? 'attn' : ''}" data-published="${t.id}">
      <span class="grow">
        <span class="row between"><span class="title">${t.title}</span>${statusChip(t)}</span>
        <span class="meta"><span>${t.budget}</span><span>${pubNextStep(t)}</span></span>
      </span>
      ${ico('chev', 16)}
    </button>`;
}

function renderPublished(){
  const list = state.published;
  $('#pubPublishedEmpty').hidden = list.length > 0;
  $('#pubTaskList').innerHTML = list.map(publishedCard).join('');
}

/* ---------- 单个任务管理 ---------- */
const selectedPublished = () => publishedById(state.selectedPublishedId);

function taskSummary(t){
  return html`
    <div class="row between top">
      <h1 class="h1 page grow">${t.title}</h1>
      ${statusChip(t)}
    </div>
    <div class="pub-facts">
      <div><span>预算</span><b class="money-text">${t.budget}</b></div>
      <div><span>认领截止</span><b>${formatDateCN(t.claimDeadline)}</b></div>
      <div><span>交付截止</span><b>${formatDateCN(t.deliverDeadline)}</b></div>
    </div>`;
}

function personRow(a, action){
  return html`
    <div class="person">
      <span class="avatar">${a.avatar}</span>
      <span class="grow">
        <span class="h3 block">${a.name} <span class="chip">${a.level}</span></span>
        <span class="sub sm block">完成 ${a.done} 个任务 · 按时率 ${a.onTime}%</span>
        ${a.note ? html`<span class="person-note">${a.note}</span>` : ''}
      </span>
      ${action || ''}
    </div>`;
}

function recruitingStage(t){
  const list = applicantsOf(t);
  return html`
    <section class="stage">
      <div class="sec-head"><h2 class="h2">认领者</h2><span class="sub sm">${list.length} 人</span></div>
      <p class="sub sm stage-hint">看看他们的完成记录和留言，选一位执行者。选定后任务开始执行，其他人会收到未选中通知。</p>
      <div class="people">${list.map(a => personRow(a, html`<button class="btn primary sm" data-select-worker="${a.id}">选定</button>`))}</div>
    </section>
    ${isRecruitingOpen(t) ? html`<button class="btn ghost block mt16" data-pub-edit="${t.id}">${ico('edit', 16)}修改任务</button>` : ''}`;
}

function workingStage(t){
  const w = applicantById(t.workerId);
  const last = (t.reworks || []).slice(-1)[0];
  return html`
    <section class="stage">
      <div class="sec-head"><h2 class="h2">执行者</h2></div>
      ${w ? personRow(w) : ''}
      ${last ? html`<div class="notice coral mt12"><b>你要求了返工</b><p>${last.reason}</p></div>` : ''}
      <p class="sub sm mt12">执行者提交成果后，这里会出现交付物和验收清单。</p>
      <button class="btn ghost block mt12" data-simulate-delivery="${t.id}">演示：模拟执行者提交成果</button>
    </section>`;
}

function filesList(files){
  return html`<div class="files">${files.map(f => html`<span class="filechip">${ico('doc', 14)}${f}</span>`)}</div>`;
}

function reviewingStage(t){
  const passed = state.reviewDraft[t.id] || [];
  const all = passed.length === t.accept.length;
  const w = applicantById(t.workerId);
  return html`
    <section class="stage">
      <div class="sec-head"><h2 class="h2">交付物</h2><span class="sub sm">${w ? w.name + ' · ' : ''}${formatDateCN(t.submission.at)} 提交</span></div>
      ${filesList(t.submission.files)}
      ${t.submission.note ? html`<p class="submission-note">${t.submission.note}</p>` : ''}
    </section>
    <section class="stage">
      <div class="sec-head"><h2 class="h2">逐条核对验收标准</h2><span class="sub sm" data-review-count>${passed.length} / ${t.accept.length}</span></div>
      <div>${t.accept.map((c, i) => html`
        <button class="checkitem toggle ${passed.includes(i) ? 'on' : ''}" role="checkbox" aria-checked="${passed.includes(i)}" data-review-check="${i}">
          <span class="cbox">${ico('check', 14)}</span><span class="grow">${c}</span>
        </button>`)}</div>
    </section>
    <section class="stage">
      <div class="field mb0">
        <label for="reworkReason">不通过的话，写下需要修改的地方</label>
        <textarea id="reworkReason" rows="3" placeholder="比如：第二个环节的转化率和原始数据对不上，请重算"></textarea>
      </div>
    </section>
    <div class="sticky-cta">
      <button class="btn ghost" data-review-rework="${t.id}">要求返工</button>
      <button class="btn primary" data-review-pass="${t.id}" ${all ? '' : 'disabled'}>验收通过并结算</button>
    </div>`;
}

function doneStage(t){
  const w = applicantById(t.workerId);
  return html`
    <section class="stage settle-box">
      <div class="row between"><span class="h3">已验收通过</span>${ico('check', 22)}</div>
      <div class="kv mt12"><span>执行者</span><b>${w ? w.name : '—'}</b></div>
      <div class="kv"><span>验收时间</span><b>${formatDateCN(t.review.at)}</b></div>
      <div class="kv"><span>支付金额</span><b class="money-text">${yuanCents(t.budgetNum)}</b></div>
      ${(t.reworks || []).length ? html`<div class="kv"><span>返工次数</span><b>${t.reworks.length}</b></div>` : ''}
    </section>
    ${t.submission ? html`<section class="stage">
      <div class="sec-head"><h2 class="h2">交付物</h2></div>
      ${filesList(t.submission.files)}
    </section>` : ''}`;
}

function renderPublishedDetail(){
  const t = selectedPublished();
  const box = $('#pubTaskDetail');
  if(!t){ box.innerHTML = html`<div class="ws-empty">这条任务不存在或已删除</div>`; return; }
  if(state.pubEditing && isRecruitingOpen(t)){ box.innerHTML = editForm(t); return; }
  const stage = {recruiting:recruitingStage, working:workingStage, reviewing:reviewingStage, done:doneStage}[t.status] || recruitingStage;
  box.innerHTML = html`${taskSummary(t)}${stage(t)}
    <button class="link-btn mt16" data-detail="${t.id}">查看任务详情页</button>`;
}

/* ---------- 修改任务（仅招募中、认领截止前） ---------- */
function editForm(t){
  return html`
    <h1 class="h1 page">修改任务</h1>
    <p class="sub">认领截止前可以修改，已认领的人会看到更新。</p>
    <div class="field mt16"><label for="editTitle">任务标题</label><input id="editTitle" value="${t.title}"></div>
    <div class="field"><label for="editDesc">背景和要求</label><textarea id="editDesc" rows="4">${t.desc}</textarea></div>
    <div class="two">
      <div class="field"><label for="editBudget">预算（元）</label><input id="editBudget" type="number" min="100" step="100" value="${t.budgetNum}"></div>
      <div class="field"><label for="editDeliver">交付截止</label><input id="editDeliver" type="date" value="${dateValue(t.deliverDeadline)}"></div>
    </div>
    <div class="sticky-cta">
      <button class="btn ghost" data-cancel-pub-edit>取消</button>
      <button class="btn primary" id="savePublished">保存修改</button>
    </div>`;
}

function savePublishedEdit(){
  const t = selectedPublished();
  if(!t || !isRecruitingOpen(t)){ toast('认领已截止，任务信息已锁定'); return; }
  const title = $('#editTitle').value.trim(), desc = $('#editDesc').value.trim();
  const budget = Number($('#editBudget').value), deliver = $('#editDeliver').value;
  const problem = title.length < 4 ? '任务标题至少写 4 个字' : desc.length < 10 ? '背景和要求再具体一点'
    : !(budget >= 100) ? '预算至少 ¥100' : !deliver || deliver < dateValue(t.claimDeadline) ? '交付截止不能早于认领截止' : '';
  if(problem){ toast(problem); return; }
  Object.assign(t, {title, desc, budgetNum:budget, budget:yuan(budget),
    deliverDeadline:deadlineISO(deliver), deadline:'至 ' + formatDateCN(deadlineISO(deliver))});
  state.pubEditing = false;
  persistState();
  renderPublishedDetail();
  toast('任务已更新');
}

/* ---------- 页面 ---------- */
definePage('publish', {
  render(){
    fillPublishForm();
    const pending = state.published.filter(t => t.status === 'reviewing').length;
    $('#publishedCount').textContent = pending ? pending + ' 个待验收' : (state.published.length || '');
    $('#publishedCount').classList.toggle('attn', pending > 0);
  }
});
definePage('published', {render:renderPublished});
definePage('pubtask', {
  enter(id){ state.selectedPublishedId = id; state.pubEditing = false; },
  render:renderPublishedDetail
});

/* ---------- 事件：新建表单 ---------- */
onInput('#pubForm [data-pub]', el => { draft()[el.dataset.pub] = el.value; persistStateSoon(); });
onChange('#pubForm select[data-pub]', el => { draft()[el.dataset.pub] = el.value; persistStateSoon(); });
onInput('#pubForm [data-list-item]', el => {
  draft()[el.closest('[data-list]').dataset.list][Number(el.dataset.listItem)] = el.value;
  persistStateSoon();
});
onClick('#pubForm [data-list-add]', el => {
  const box = el.closest('[data-list]');
  draft()[box.dataset.list].push('');
  renderListEditors();
  [...box.querySelectorAll('[data-list-item]')].pop()?.focus();
  persistStateSoon();
});
onClick('#pubForm [data-list-remove]', el => {
  const list = draft()[el.closest('[data-list]').dataset.list];
  list.splice(Number(el.dataset.listRemove), 1);
  renderListEditors();
  persistStateSoon();
});
onClick('#pubVerifyOptions [data-verify]', el => {
  draft().verify = el.dataset.verify;
  renderVerifyOptions();
  persistStateSoon();
});
onClick('#pubSubmit', submitNewTask);
document.addEventListener('submit', e => { if(e.target.id === 'pubForm') e.preventDefault(); });

/* ---------- 事件：任务管理 ---------- */
onClick('[data-published]', el => go('pubtask', el.dataset.published));
onClick('[data-select-worker]', el => {
  const a = applicantById(el.dataset.selectWorker);
  const problem = selectWorker(state.selectedPublishedId, a.id);
  if(problem){ toast(problem); return; }
  toast('已选定 ' + a.name + '，任务开始执行');
  renderPublishedDetail();
});
onClick('[data-simulate-delivery]', el => { simulateDelivery(el.dataset.simulateDelivery); renderPublishedDetail(); toast('执行者已提交成果，请验收'); });
onClick('[data-review-check]', el => {
  const id = state.selectedPublishedId;
  const list = state.reviewDraft[id] || (state.reviewDraft[id] = []);
  const i = Number(el.dataset.reviewCheck);
  const at = list.indexOf(i);
  if(at > -1) list.splice(at, 1); else list.push(i);
  const on = list.includes(i);
  el.classList.toggle('on', on);
  el.setAttribute('aria-checked', on);
  const t = selectedPublished();
  $('[data-review-count]').textContent = list.length + ' / ' + t.accept.length;
  $('[data-review-pass]').disabled = list.length < t.accept.length;
});
onClick('[data-review-pass]', el => {
  const problem = reviewPass(el.dataset.reviewPass);
  if(problem){ toast(problem); return; }
  toast('验收通过，已向执行者支付');
  renderPublishedDetail();
  $('.view.on').scrollTop = 0;
});
onClick('[data-review-rework]', el => {
  const problem = reviewRework(el.dataset.reviewRework, $('#reworkReason').value);
  if(problem){ toast(problem); $('#reworkReason').focus(); return; }
  toast('已退回返工，执行者会看到你的意见');
  renderPublishedDetail();
});
onClick('[data-pub-edit]', () => { state.pubEditing = true; renderPublishedDetail(); });
onClick('[data-cancel-pub-edit]', () => { state.pubEditing = false; renderPublishedDetail(); });
onClick('#savePublished', savePublishedEdit);
