/* 推荐：纯色卡片竖向翻页，按“要不要接”的判断顺序排列信息。
   翻页不用原生 scroll-snap（卡片内再嵌滚动时会互相抢手势、回弹卡顿），
   改为自绘分页器：拖动跟手 → 松手按距离或速度决定翻页 → transform 动画到位。 */

/* 沿用老版的短视频式卡片：满屏封面 + 底部信息叠层 + 右侧快捷栏。
   没有封面图的任务用数据柱状图做封面。 */
function feedCover(t, i){
  if(t.cover) return html`<img class="fcover" src="${t.cover}" alt="" draggable="false" decoding="async">`;
  const vals = i % 2 ? [92,78,70,64,58,52,46,40,34,28] : [26,38,30,52,44,66,58,72,61,80];
  return html`<div class="fcover datacover"><div class="databars">${vals.map(v => html`<i style="height:${16 + v}%"></i>`)}</div></div>`;
}

function feedCard(t, i, total){
  const saved = state.saved.has(t.id);
  const levelTone = t.level === 'L4' ? 'coral' : t.level === 'L3' ? 'cyan' : '';
  return html`
    <article class="fcard" data-id="${t.id}">
      ${feedCover(t, i)}
      <div class="fscrim"></div>
      <div class="ftop"><span class="chip ${levelTone}">${t.level} ${t.levelText}</span><span class="chip">${t.deadline}</span></div>
      <div class="fbody">
        <div class="fposter"><span class="avatar">${t.avatar}</span><b>${t.poster}</b><span>· 已认证</span></div>
        <h2 class="ftitle">${t.title}</h2>
        <p class="fdesc">${t.desc}</p>
        <div class="fstats">
          <div class="fstat money-stat"><b>${t.budget}</b><span>预算</span></div>
          <div class="fstat"><b>${t.rate}%</b><span>同类成功率</span></div>
          <div class="fstat"><b>${t.applicants}</b><span>已申请</span></div>
        </div>
        <div class="fcta">
          <button class="btn primary sm" data-accept="${t.id}">接下这个任务</button>
          <button class="btn dark sm" data-detail="${t.id}">查看详情</button>
        </div>
      </div>
      <div class="frail">
        <button data-detail="${t.id}" aria-label="查看详情"><span class="ring">${ico('arrow', 18)}</span><span>详情</span></button>
        <button data-save="${t.id}" class="${saved ? 'on' : ''}" aria-label="收藏"><span class="ring">${ico('bookmark', 18)}</span><span>收藏</span></button>
        <button data-share="${t.id}" aria-label="分享"><span class="ring">${ico('share', 18)}</span><span>分享</span></button>
        <button data-accept="${t.id}" aria-label="接单"><span class="ring">${ico('check', 18)}</span><span>接单</span></button>
      </div>
    </article>`;
}

const feedEnd = () => html`
  <div class="fend">
    <div class="center">
      ${ico('spark', 30)}
      <div class="h2 mt12">今天的推荐到这里</div>
      <p class="sub mt8">系统每天按能力图谱重算一次排序，错过不会丢失。</p>
      <button class="btn ghost mt12" data-go="skills">看看我的能力图谱</button>
    </div>
  </div>`;

/* ---------- 分页器 ---------- */
const pager = {
  index:0,          // 当前页（跨重绘保留）
  count:0,
  track:null,
  bar:null,
  height:0,
  drag:null,        // 拖动中：{id, y0, t0, dy, moved, samples[]}
  suppressClick:false,
  wheelAcc:0,
  wheelLockUntil:0,
  lastWheel:0
};

const PAGER = {
  DURATION:420,         // 翻页动画 ms
  DRAG_START:6,         // 移动超过多少 px 才算拖动（否则视为点击）
  DISTANCE:0.2,         // 拖过视口高度的这个比例就翻页
  FLICK:0.45,           // 或者松手速度超过这个 px/ms
  SIDE_OPEN:0.28,       // 向左拖过宽度的这个比例（或快速左甩）就进入详情
  EDGE_RESIST:0.3,      // 首尾越界时的阻尼
  WHEEL_STEP:30,        // 滚轮累计多少 px 翻一页
  WHEEL_QUIET:180       // 触控板惯性：停滚这么久才允许下一次翻页
};

// 进度条固定在视口顶部，不随卡片移动；拖动时跟着手指连续变化，松手后和翻页同一条动画
function pagerApply(offset, animate){
  const track = pager.track;
  if(!track) return;
  const transition = animate ? 'transform ' + PAGER.DURATION + 'ms cubic-bezier(.22,.8,.24,1)' : 'none';
  track.style.transition = transition;
  track.style.transform = 'translate3d(0,' + (-pager.index * pager.height + offset) + 'px,0)';
  const bar = pager.bar;
  if(bar && pager.height){
    const cards = pager.count - 1; // 最后一页是结束页
    const pos = pager.index - offset / pager.height + 1;
    bar.style.transition = transition;
    bar.style.transform = 'scaleX(' + Math.max(0, Math.min(1, pos / cards)) + ')';
  }
}

function pagerGo(next){
  const clamped = Math.max(0, Math.min(pager.count - 1, next));
  pager.index = clamped;
  pagerApply(0, true);
}

function pagerMeasure(){
  // 用实际高度（可能带小数），避免整数取整后下一张卡露出 1px
  pager.height = $('#feedScroll').getBoundingClientRect().height;
  pagerApply(0, false);
}

function onPointerDown(e){
  if(e.button !== 0 || pager.drag) return;
  // axis：起手后按先超过阈值的方向锁定，'y' 翻页，'x' 左滑进详情
  pager.drag = {id:e.pointerId, x0:e.clientX, y0:e.clientY, dx:0, dy:0, axis:null, moved:false,
    card:e.target.closest('.fcard'), samples:[[e.timeStamp, e.clientY, e.clientX]]};
}

function onPointerMove(e){
  const d = pager.drag;
  if(!d || e.pointerId !== d.id) return;
  let dy = e.clientY - d.y0;
  let dx = e.clientX - d.x0;
  if(!d.moved){
    if(Math.max(Math.abs(dx), Math.abs(dy)) < PAGER.DRAG_START) return;
    d.moved = true;
    d.axis = Math.abs(dx) > Math.abs(dy) && d.card ? 'x' : 'y';
    $('#feedScroll').setPointerCapture(d.id);
    d.x0 = e.clientX; d.y0 = e.clientY; dx = dy = 0; // 从越过阈值处开始跟手，避免起步跳一下
  }
  d.samples.push([e.timeStamp, e.clientY, e.clientX]);
  if(d.samples.length > 5) d.samples.shift();
  if(d.axis === 'x'){
    // 只允许向左拖；向右给阻尼
    d.dx = dx < 0 ? dx : dx * PAGER.EDGE_RESIST;
    d.card.style.transition = 'none';
    d.card.style.transform = 'translate3d(' + d.dx + 'px,0,0)';
    return;
  }
  const atEdge = (pager.index === 0 && dy > 0) || (pager.index === pager.count - 1 && dy < 0);
  d.dy = atEdge ? dy * PAGER.EDGE_RESIST : dy;
  pagerApply(d.dy, false);
}

function onPointerUp(e){
  const d = pager.drag;
  if(!d || e.pointerId !== d.id) return;
  pager.drag = null;
  if(!d.moved) return;
  pager.suppressClick = true; // 拖动结束时不要误触卡片上的按钮
  setTimeout(() => { pager.suppressClick = false; }, 0);
  const [t1, y1, x1] = d.samples[0];
  const [t2, y2, x2] = d.samples[d.samples.length - 1];
  if(d.axis === 'x'){ finishSideSwipe(d, (x2 - x1) / Math.max(1, t2 - t1)); return; }
  const velocity = (y2 - y1) / Math.max(1, t2 - t1);
  let step = 0;
  if(Math.abs(d.dy) > pager.height * PAGER.DISTANCE || Math.abs(velocity) > PAGER.FLICK){
    step = (Math.abs(velocity) > PAGER.FLICK ? velocity : d.dy) < 0 ? 1 : -1;
  }
  pagerGo(pager.index + step);
}

// 左滑松手：够远或够快 → 卡片滑出并进入详情；否则弹回
function finishSideSwipe(d, vx){
  const card = d.card, width = card.offsetWidth;
  const open = d.dx < -width * PAGER.SIDE_OPEN || (vx < -PAGER.FLICK && d.dx < 0);
  card.style.transition = 'transform ' + (open ? 220 : 320) + 'ms cubic-bezier(.22,.8,.24,1)';
  card.style.transform = open ? 'translate3d(' + (-width) + 'px,0,0)' : 'translate3d(0,0,0)';
  if(!open) return;
  setTimeout(() => {
    go('task', card.dataset.id);
    card.style.transition = 'none';
    card.style.transform = '';
  }, 200);
}

function onWheel(e){
  e.preventDefault();
  const now = e.timeStamp;
  const quiet = now - pager.lastWheel > PAGER.WHEEL_QUIET;
  pager.lastWheel = now;
  if(now < pager.wheelLockUntil && !quiet){ return; }
  if(quiet) pager.wheelAcc = 0;
  pager.wheelAcc += e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
  if(Math.abs(pager.wheelAcc) >= PAGER.WHEEL_STEP){
    pagerGo(pager.index + (pager.wheelAcc > 0 ? 1 : -1));
    pager.wheelAcc = 0;
    pager.wheelLockUntil = now + PAGER.DURATION; // 动画期间 + 惯性未停前只翻一页
  }
}

function onFeedKey(e){
  if(state.route !== 'feed' || e.target.closest('input, textarea, select')) return;
  const step = {ArrowDown:1, PageDown:1, j:1, ArrowUp:-1, PageUp:-1, k:-1}[e.key];
  if(!step) return;
  e.preventDefault();
  pagerGo(pager.index + step);
}

function initFeedPager(){
  const viewport = $('#feedScroll');
  viewport.addEventListener('pointerdown', onPointerDown);
  viewport.addEventListener('pointermove', onPointerMove);
  viewport.addEventListener('pointerup', onPointerUp);
  viewport.addEventListener('pointercancel', onPointerUp);
  viewport.addEventListener('wheel', onWheel, {passive:false});
  viewport.addEventListener('click', e => {
    if(pager.suppressClick){ e.preventDefault(); e.stopPropagation(); }
  }, true);
  document.addEventListener('keydown', onFeedKey);
  new ResizeObserver(pagerMeasure).observe(viewport);
}

// 演示版：复制任务链接（file:// 下剪贴板可能不可用，失败也给出提示）
onClick('[data-share]', el => {
  const url = location.href.split('#')[0] + '#/task/' + el.dataset.share;
  const done = () => toast('任务链接已复制');
  if(navigator.clipboard?.writeText) navigator.clipboard.writeText(url).then(done, () => toast('复制失败，可从详情页地址栏复制'));
  else toast('复制失败，可从详情页地址栏复制');
});

definePage('feed', {
  render(){
    pager.count = TASKS.length + 1;
    pager.index = Math.min(pager.index, pager.count - 1);
    $('#feedScroll').innerHTML = html`<div class="feed-track">${TASKS.map((t, i) => feedCard(t, i, TASKS.length))}${feedEnd()}</div>
      <div class="feed-prog" aria-hidden="true"><i></i></div>`;
    pager.track = $('#feedScroll .feed-track');
    pager.bar = $('#feedScroll .feed-prog i');
    $('#feedCount').textContent = TASKS.length;
    pagerMeasure();
  }
});
