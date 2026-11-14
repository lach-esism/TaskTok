/* 工作台（接单方）：一级页按“已认领 / 进行中 / 待验收 / 已结束”分组列出任务；
   点开一条进入子页面 #/job/<id>，看进度和下一步操作。状态定义见 core/flow.js。 */

const tabOf = item => (WORK_STATUS[item.status] || WORK_STATUS.accepted).tab;

function selectWorkItem(id){
  state.ws = id;
  const item = workItemFor(id);
  if(item) state.wsStatus = tabOf(item);
}

function renderWorkspace(){
  if(!WORK_TABS.some(([k]) => k === state.wsStatus)) state.wsStatus = 'active';
  const count = k => state.workItems.filter(item => tabOf(item) === k).length;
  $('#wsTabs').innerHTML = WORK_TABS.map(([k, label]) => html`
    <button class="${k === state.wsStatus ? 'on' : ''}" data-ws-status="${k}">${label} <span class="n">${count(k)}</span></button>`).join('');
  const items = state.workItems.filter(item => tabOf(item) === state.wsStatus);
  const label = WORK_TABS.find(([k]) => k === state.wsStatus)[1];
  $('#wsList').innerHTML = items.length ? items.map(workRow).join('')
    : html`<div class="ws-empty">「${label}」里暂时没有任务</div>`;
}

const doneRatio = t => { const n = (state.checks[t.id] || []).length; return [n, t.checks.length]; };

// 列表行：标题 + 状态标签 + 一句“下一步”
function workRow(item){
  const t = taskById(item.taskId);
  const meta = WORK_STATUS[item.status];
  const [n, total] = doneRatio(t);
  const note = item.status === 'active' ? '子任务 ' + n + ' / ' + total
    : item.status === 'completed' ? '到账 ' + yuanCents(netIncome(t.budgetNum))
    : meta.note;
  return html`
    <button class="taskrow ${item.status === 'rework' ? 'attn' : ''}" data-job="${t.id}">
      <span class="grow">
        <span class="row between"><span class="h3">${t.title}</span><span class="chip ${meta.tone}">${meta.label}</span></span>
        <span class="sub sm block">${t.poster} · ${t.budget}</span>
        <span class="taskrow-foot"><span>${note}</span>${item.status === 'active'
          ? html`<span class="bar"><i style="width:${Math.round(n / total * 100)}%"></i></span>` : ''}</span>
      </span>
      ${ico('chev', 16)}
    </button>`;
}

/* ---------- 单个任务 ---------- */
const jobHead = (t, item) => html`
  <div class="row between top">
    <h1 class="h1 page grow">${t.title}</h1>
    <span class="chip ${WORK_STATUS[item.status].tone}">${WORK_STATUS[item.status].label}</span>
  </div>
  <div class="pub-facts">
    <div><span>报酬</span><b class="money-text">${t.budget}</b></div>
    <div><span>发包方</span><b>${t.poster}</b></div>
    <div><span>交付</span><b>${t.deadline}</b></div>
  </div>`;

// 演示区：原型里没有真实发包方，用这里的按钮模拟发包方的决定
const demoBox = buttons => html`
  <section class="stage demo-box">
    <div class="sub sm">演示：模拟发包方的操作</div>
    <div class="row mt8">${buttons}</div>
  </section>`;

function acceptedDetail(t, item){
  return html`
    <div class="notice mt16"><b>等待发包方选定执行者</b><p>你在 ${formatDateCN(item.addedAt)} 认领了这个任务。发包方会在认领截止后比较认领者，选定前你可以随时取消。</p></div>
    ${demoBox(html`
      <button class="btn ghost" data-demo-select="${t.id}" data-chosen="1">发包方选定了我</button>
      <button class="btn ghost" data-demo-select="${t.id}" data-chosen="0">发包方选了别人</button>`)}
    <div class="sticky-cta">
      <button class="btn ghost" data-detail="${t.id}">查看任务要求</button>
      <button class="btn danger" data-cancel-claim="${t.id}">取消认领</button>
    </div>`;
}

// 环形进度：r=28 的圆周长约 176
function progressRing(percent){
  return html`
    <div class="ring">
      <svg viewBox="0 0 64 64" width="64" height="64">
        <circle class="ring-track" cx="32" cy="32" r="28"/>
        <circle class="ring-fill" cx="32" cy="32" r="28" stroke-dasharray="176" stroke-dashoffset="${176 * (1 - percent / 100)}" transform="rotate(-90 32 32)"/>
      </svg>
      <div class="ring-label"><span><span data-ring-num>${percent}</span>%</span></div>
    </div>`;
}

// 数字从旧值滚到新值，和环形进度的过渡同时长
function countTo(el, to, ms = 420){
  const from = Number(el.textContent) || 0;
  if(from === to) return;
  const t0 = performance.now();
  const step = now => {
    const k = Math.min(1, (now - t0) / ms);
    el.textContent = Math.round(from + (to - from) * (1 - Math.pow(1 - k, 3)));
    if(k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// 勾选后只更新受影响的元素，不整块重绘，这样环形、数字和勾选框都能平滑过渡
function updateProgress(t){
  const [n, total] = doneRatio(t);
  const percent = Math.round(n / total * 100);
  const box = $('#wsDetail');
  box.querySelector('.ring-fill')?.setAttribute('stroke-dashoffset', 176 * (1 - percent / 100));
  const num = box.querySelector('[data-ring-num]');
  if(num) countTo(num, percent);
  box.querySelectorAll('[data-done-count]').forEach(el => { el.textContent = n; });
  const done = state.checks[t.id] || [];
  box.querySelectorAll('[data-check]').forEach(row => {
    const on = done.includes(Number(row.dataset.check));
    row.classList.toggle('on', on);
    row.setAttribute('aria-checked', on);
  });
}

// 进行中 / 需返工：自己记录进度，然后提交
function activeDetail(t, item){
  const done = state.checks[t.id] || [];
  const [n, total] = doneRatio(t);
  const rework = item.status === 'rework' && item.review;
  return html`
    ${rework ? html`<div class="notice coral mt16"><b>发包方要求返工</b><p>${item.review.reason}</p></div>` : ''}
    <section class="stage">
      <div class="row gap-lg">
        ${progressRing(Math.round(n / total * 100))}
        <div class="grow">
          <div class="sub md">已完成 <b class="strong" data-done-count>${n}</b> / ${total} 项</div>
          <p class="sub sm mt8">进度只给你自己记录用，发包方看不到。做完后提交成果，由发包方验收。</p>
        </div>
      </div>
    </section>
    <section class="stage">
      <div class="sec-head"><h2 class="h2">进度清单</h2></div>
      <div>${t.checks.map((c, i) => {
        const on = done.includes(i);
        // 整行都是开关：点勾选框或文字都能切换
        return html`
        <button class="checkitem toggle ${on ? 'on' : ''}" role="checkbox" aria-checked="${on}" data-check="${i}">
          <span class="cbox">${ico('check', 14)}</span><span class="grow">${c}</span>
        </button>`;
      })}</div>
    </section>
    <div class="sticky-cta">
      <button class="btn ghost" data-detail="${t.id}">查看任务要求</button>
      <button class="btn primary" data-submit="${t.id}">${rework ? '修改后重新提交' : '提交成果'}</button>
    </div>`;
}

const filesOf = sub => html`<div class="files">${sub.files.map(f => html`<span class="filechip">${ico('doc', 14)}${f}</span>`)}</div>`;

function submittedDetail(t, item){
  return html`
    <div class="notice mt16"><b>已提交，等待发包方验收</b><p>${formatDateCN(item.submission.at)} 提交。验收结果出来后会显示在这里；如需返工，会附上修改意见。</p></div>
    <section class="stage">
      <div class="sec-head"><h2 class="h2">你提交的内容</h2></div>
      ${filesOf(item.submission)}
      ${item.submission.note ? html`<p class="submission-note">${item.submission.note}</p>` : ''}
    </section>
    <section class="stage">
      <div class="sec-head"><h2 class="h2">验收标准</h2></div>
      <div class="list">${bullets(t.accept)}</div>
    </section>
    ${demoBox(html`
      <button class="btn ghost" data-demo-review="${t.id}" data-pass="1">验收通过</button>
      <button class="btn ghost" data-demo-review="${t.id}" data-pass="0">要求返工</button>`)}`;
}

function completedDetail(t, item){
  const gross = Number(t.budgetNum) || 0;
  return html`
    <section class="stage settle-box">
      <div class="row between"><span class="h3">验收通过，已结算</span>${ico('check', 22)}</div>
      <div class="kv mt12"><span>任务金额</span><b class="money">${yuanCents(gross)}</b></div>
      <div class="kv"><span>平台服务费（${PLATFORM_FEE_RATE * 100}%）</span><b class="money muted">- ${yuanCents(gross * PLATFORM_FEE_RATE)}</b></div>
      <div class="kv"><span>实际到账</span><b class="money money-text lg">${yuanCents(netIncome(gross))}</b></div>
      <p class="sub sm mt8">${formatDateCN(item.completedAt)} 验收通过</p>
    </section>
    ${item.submission ? html`<section class="stage">
      <div class="sec-head"><h2 class="h2">交付物</h2></div>
      ${filesOf(item.submission)}
    </section>` : ''}`;
}

function declinedDetail(){
  return html`<div class="notice mt16"><b>发包方选择了其他执行者</b><p>这个任务已不再需要你。可以回推荐页看看其他任务。</p></div>`;
}

function renderWsDetail(){
  const box = $('#wsDetail');
  const item = state.ws && workItemFor(state.ws);
  if(!item){ box.innerHTML = html`<div class="ws-empty">这条任务已不在工作台</div>`; return; }
  const t = taskById(state.ws);
  const view = {accepted:acceptedDetail, active:activeDetail, rework:activeDetail,
    submitted:submittedDetail, completed:completedDetail, declined:declinedDetail}[item.status];
  box.innerHTML = html`${jobHead(t, item)}${view(t, item)}`;
}

definePage('workspace', {render:renderWorkspace});
definePage('job', {enter:selectWorkItem, render:renderWsDetail});

onClick('[data-job]', el => go('job', el.dataset.job));
onClick('[data-submit]', el => go('submit', el.dataset.submit));
onClick('[data-ws-status]', el => { state.wsStatus = el.dataset.wsStatus; renderWorkspace(); });
onClick('[data-cancel-claim]', el => {
  cancelClaim(el.dataset.cancelClaim);
  toast('已取消认领');
  goBack();
});
onClick('[data-check]', el => {
  const id = state.ws;
  const i = Number(el.dataset.check);
  const done = state.checks[id] || [];
  const at = done.indexOf(i);
  if(at > -1) done.splice(at, 1); else done.push(i);
  state.checks[id] = done;
  persistState();
  const t = taskById(id);
  updateProgress(t);
  if(done.length === t.checks.length) toast('全部完成，可以提交成果了');
});
onClick('[data-demo-select]', el => {
  const chosen = el.dataset.chosen === '1';
  demoSelect(el.dataset.demoSelect, chosen);
  state.wsStatus = chosen ? 'active' : 'done';
  toast(chosen ? '你被选为执行者，可以开始做了' : '发包方选择了其他执行者');
  renderWsDetail();
});
onClick('[data-demo-review]', el => {
  const pass = el.dataset.pass === '1';
  demoReview(el.dataset.demoReview, pass);
  state.wsStatus = pass ? 'done' : 'active';
  toast(pass ? '验收通过，报酬已到账' : '发包方要求返工，请查看修改意见');
  renderWsDetail();
});
