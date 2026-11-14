/* 任务详情，以及各页面共用的任务动作：收藏、认领、查看详情。 */

// 列表里的任务缩略块：浅色底 + 分类首字，不再用深色封面图
const catTile = (t, cls) => html`<span class="${cls} cat-tile">${(t.cat || '任务').slice(0, 2)}</span>`;

const bullets = (items, dotClass = '') => items.map(text =>
  html`<div class="li"><span class="dot ${dotClass}"></span><span>${text}</span></div>`
);

function claimButtonLabel(t){
  if(isSelfPublished(t.id)) return '管理这个任务';
  const item = workItemFor(t.id);
  if(!item) return '认领任务';
  return WORK_STATUS[item.status].label + ' · 查看进度';
}

definePage('task', {
  enter(id){ state.taskId = id; },
  render(){
    const t = taskById(state.taskId);
    recordRecent(t.id);
    const self = isSelfPublished(t.id);
    $('#dTitle').textContent = t.title;
    $('#dDesc').textContent = t.desc;
    $('#dCover').hidden = !t.cover;
    if(t.cover) $('#dCover').src = t.cover;
    $('#dBudget').textContent = t.budget;
    $('#dDeadline').textContent = t.deadline;
    $('#dRate').textContent = t.rate + '%';
    $('#dRate2').textContent = t.rate + '%';
    $('#dApplicants').textContent = t.applicants + ' 人';
    $('#dPoster').textContent = t.poster;
    $('#dAv').textContent = t.avatar;
    $('#dChips').innerHTML = html`
      <span class="chip cyan">${t.level} ${t.levelText}</span>
      <span class="chip">${t.cat}</span>
      <span class="chip amber">匹配 ${t.match}%</span>`;
    $('#dContract').innerHTML = t.contract.map(([k, v]) => html`<div class="kv"><span>${k}</span><b>${v}</b></div>`).join('');
    $('#dOutput').innerHTML = bullets(t.outputs).join('');
    $('#dAccept').innerHTML = bullets(t.accept).join('');
    $('#dWhy').innerHTML = bullets(t.why, 'accent').join('');
    $('#dOwnerNote').hidden = !self;
    $('#dAcceptBtn').textContent = claimButtonLabel(t);
    $('#dAcceptBtn').dataset.accept = t.id;
  }
});

/* ---------- 认领 ---------- */

// 认领入口：自己发布的去发布管理；已在工作台的直接打开；否则弹出接单确认
function startClaim(id){
  if(isSelfPublished(id)){
    toast('这是你发布的任务，可在这里查看认领进展');
    go('pubtask', id);
    return;
  }
  if(workItemFor(id)){ go('job', id); return; }
  openClaimModal(taskById(id));
}

function openClaimModal(t){
  $('#modalBox').innerHTML = html`
    <div class="h2">认领这个任务？</div>
    <p class="sub sm mt8">${t.title}</p>
    <div class="kv mt12"><span>报酬</span><b class="money">${t.budget}</b></div>
    <div class="kv"><span>交付</span><b>${t.deadline}</b></div>
    <div class="kv"><span>验收方式</span><b>${verifyOf(t.verify).label}</b></div>
    <ol class="claim-steps">
      <li>认领后，发包方会在认领者中选定一位执行者</li>
      <li>被选中后开始做，完成后提交成果</li>
      <li>发包方按验收标准核对，通过即结算到账</li>
    </ol>
    <div class="row mt16">
      <button class="btn ghost grow" data-close-modal>再看看</button>
      <button class="btn primary grow" data-confirm-claim="${t.id}">确认认领</button>
    </div>`;
  $('#modal').classList.add('on');
}

const closeModal = () => $('#modal').classList.remove('on');

function confirmClaim(id){
  closeModal();
  claimTask(id);
  toast('认领已提交，等待发包方选定');
  setTimeout(() => go('job', id), 500);
}

/* ---------- 收藏 ---------- */
function toggleSave(btn){
  const id = btn.dataset.save;
  const saving = !state.saved.has(id);
  if(saving) state.saved.add(id); else state.saved.delete(id);
  btn.classList.toggle('on', saving);
  toast(saving ? '已收藏，会出现在「我的」里' : '已取消收藏');
  persistState();
  if(state.route === 'saved' || state.route === 'me') paint();
}

onClick('[data-save]', toggleSave);
onClick('[data-accept]', el => startClaim(el.dataset.accept));
onClick('[data-detail]', el => go('task', el.dataset.detail));
onClick('[data-confirm-claim]', el => confirmClaim(el.dataset.confirmClaim));
onClick('[data-close-modal]', closeModal);
onClick('#modal', (el, e) => { if(e.target === el) closeModal(); });
document.addEventListener('keydown', e => { if(e.key === 'Escape'){ closeModal(); closeFilterDrawer(); } });

/* ---------- 右滑返回 ----------
   适用于所有带返回按钮（[data-back]）的二级页面，效果等同点返回：回到上一页。
   起手先横向移动才算返回手势；先纵向则交给页面正常滚动（CSS 设 touch-action:pan-y）。
   页面跟手右移，松手拖过 30% 宽度或快速右甩就返回，否则弹回。 */
const SWIPE_BACK = {START:8, DISTANCE:0.3, FLICK:0.45, DURATION:260};
const swipeBack = {drag:null, suppressClick:false};

function initDetailSwipe(){
  $$('.view').forEach(view => { if(view.querySelector('[data-back]')) bindSwipeBack(view); });
}

function bindSwipeBack(view){
  view.classList.add('swipe-back');
  const reset = () => { view.style.transition = 'none'; view.style.transform = ''; view.classList.remove('dragging'); };

  view.addEventListener('pointerdown', e => {
    if(e.button !== 0 || swipeBack.drag || e.target.closest('input, textarea, select')) return;
    swipeBack.drag = {id:e.pointerId, x0:e.clientX, y0:e.clientY, dx:0, axis:null, samples:[[e.timeStamp, e.clientX]]};
  });

  view.addEventListener('pointermove', e => {
    const d = swipeBack.drag;
    if(!d || e.pointerId !== d.id) return;
    if(!d.axis){
      const dx = e.clientX - d.x0, dy = e.clientY - d.y0;
      if(Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_BACK.START) return;
      if(Math.abs(dx) <= Math.abs(dy) || dx < 0){ swipeBack.drag = null; return; } // 纵向或向左：不处理
      d.axis = 'x';
      d.x0 = e.clientX; // 从越过阈值处开始跟手
      view.setPointerCapture(d.id);
      view.classList.add('dragging');
    }
    d.dx = Math.max(0, e.clientX - d.x0);
    d.samples.push([e.timeStamp, e.clientX]);
    if(d.samples.length > 5) d.samples.shift();
    view.style.transition = 'none';
    view.style.transform = 'translate3d(' + d.dx + 'px,0,0)';
  });

  const end = e => {
    const d = swipeBack.drag;
    if(!d || e.pointerId !== d.id) return;
    swipeBack.drag = null;
    if(!d.axis) return;
    swipeBack.suppressClick = true;
    setTimeout(() => { swipeBack.suppressClick = false; }, 0);
    const [t1, x1] = d.samples[0], [t2, x2] = d.samples[d.samples.length - 1];
    const vx = (x2 - x1) / Math.max(1, t2 - t1);
    const width = view.offsetWidth;
    const back = e.type !== 'pointercancel' && (d.dx > width * SWIPE_BACK.DISTANCE || (vx > SWIPE_BACK.FLICK && d.dx > 0));
    view.style.transition = 'transform ' + SWIPE_BACK.DURATION + 'ms cubic-bezier(.22,.8,.24,1)';
    view.style.transform = back ? 'translate3d(' + width + 'px,0,0)' : 'translate3d(0,0,0)';
    setTimeout(() => {
      if(back) goBack();
      reset();
    }, back ? SWIPE_BACK.DURATION - 40 : SWIPE_BACK.DURATION);
  };
  view.addEventListener('pointerup', end);
  view.addEventListener('pointercancel', end);
  view.addEventListener('click', e => {
    if(swipeBack.suppressClick){ e.preventDefault(); e.stopPropagation(); }
  }, true);
}
