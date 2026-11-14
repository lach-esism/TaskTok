/* 搜索：关键词 + 筛选栏。
   交互参照常见电商/招聘类应用：
   - 每个维度一个按钮，显示当前取值；点开只看这一项，选完点“查看 N 个结果”生效
   - “全部筛选”一次改多项；面板里实时显示会有多少结果，避免筛到 0 才发现
   - 已生效的维度高亮，结果数旁边一键清除全部 */

const SORT_OPTIONS = {
  match:{label:'推荐优先', compare:(a, b) => b.match - a.match},
  newest:{label:'最新发布', compare:(a, b) => new Date(b.publishedAt) - new Date(a.publishedAt)},
  'budget-desc':{label:'金额从高到低', compare:(a, b) => b.budgetNum - a.budgetNum},
  'budget-asc':{label:'金额从低到高', compare:(a, b) => a.budgetNum - b.budgetNum},
  deadline:{label:'截止时间最近', compare:(a, b) => (a.hours || 9999) - (b.hours || 9999)}
};
const DATE_LABELS = {any:'全部时间', today:'今天', week:'最近一周', month:'最近一月', custom:'自定义日期'};
const BUDGET_RANGES = {
  any:{label:'全部金额', test:() => true},
  'under-1000':{label:'¥1,000 以下', test:n => n < 1000},
  '1000-3000':{label:'¥1,000–3,000', test:n => n >= 1000 && n <= 3000},
  '3000-5000':{label:'¥3,000–5,000', test:n => n > 3000 && n <= 5000},
  'over-5000':{label:'¥5,000 以上', test:n => n > 5000},
  custom:{label:'自定义金额', test:(n, f) =>
    (f.budgetMin === '' || n >= Number(f.budgetMin)) && (f.budgetMax === '' || n <= Number(f.budgetMax))}
};

function matchesPublishedDate(task, f){
  if(f.date === 'any') return true;
  const published = new Date(task.publishedAt || task.createdAt);
  if(Number.isNaN(published.getTime())) return false;
  const age = Date.now() - published.getTime();
  switch(f.date){
    case 'today': return sameLocalDay(published, new Date());
    case 'week': return age <= 7 * DAY_MS;
    case 'month': return age <= 30 * DAY_MS;
    case 'custom':
      if(f.dateFrom && published < new Date(f.dateFrom + 'T00:00:00')) return false;
      if(f.dateTo && published > new Date(f.dateTo + 'T23:59:59')) return false;
      return true;
  }
  return true;
}

function getFilteredTasks(f = state.filters){
  const q = state.q.trim().toLowerCase();
  const budgetTest = (BUDGET_RANGES[f.budget] || BUDGET_RANGES.any).test;
  return TASKS.filter(t =>
    (f.category === '全部' || t.cat === f.category)
    && (!q || (t.title + t.desc + t.poster + t.cat).toLowerCase().includes(q))
    && (f.level === 'any' || t.level === f.level)
    && (f.verify === 'any' || t.verify === f.verify)
    && matchesPublishedDate(t, f)
    && budgetTest(Number(t.budgetNum) || 0, f)
  ).sort((SORT_OPTIONS[f.sort] || SORT_OPTIONS.match).compare);
}


/* ---------- 筛选维度 ----------
   每个维度：名称、选项、当前取值的显示文字、是否已生效。排序单独放第一位且不算“筛选”。 */
const FILTER_GROUPS = {
  sort:{label:'排序', options:() => Object.entries(SORT_OPTIONS).map(([v, o]) => [v, o.label]),
    text:f => SORT_OPTIONS[f.sort].label},
  category:{label:'类型', options:() => CATS.map(c => [c, c === '全部' ? '不限' : c]),
    text:f => f.category},
  budget:{label:'金额', options:() => Object.entries(BUDGET_RANGES).map(([v, o]) => [v, v === 'any' ? '不限' : o.label]),
    text:f => f.budget === 'custom' ? '¥' + (f.budgetMin || 0) + '–' + (f.budgetMax || '不限') : BUDGET_RANGES[f.budget].label},
  date:{label:'发布时间', options:() => Object.entries(DATE_LABELS).map(([v, l]) => [v, v === 'any' ? '不限' : l]),
    text:f => f.date === 'custom' ? (f.dateFrom || '不限') + ' 至 ' + (f.dateTo || '不限') : DATE_LABELS[f.date]},
  level:{label:'难度', options:() => [['any','不限']].concat(Object.entries(LEVEL_TEXT).map(([k, v]) => [k, k + ' ' + v])),
    text:f => f.level + ' ' + LEVEL_TEXT[f.level]},
  verify:{label:'验收方式', options:() => [['any','不限']].concat(Object.entries(VERIFY_METHODS).map(([k, v]) => [k, v.label])),
    text:f => verifyOf(f.verify).label}
};
const FILTER_KEYS = ['category', 'budget', 'date', 'level', 'verify'];
const isActive = (key, f) => f[key] !== DEFAULT_FILTERS[key];
const activeCount = f => FILTER_KEYS.filter(k => isActive(k, f)).length;

function renderFilterBar(){
  const f = state.filters;
  const n = activeCount(f);
  const pill = key => {
    const on = key === 'sort' ? f.sort !== 'match' : isActive(key, f);
    const g = FILTER_GROUPS[key];
    return html`<button class="filter-btn ${on ? 'on' : ''}" data-open-filter="${key}">
      ${on || key === 'sort' ? g.text(f) : g.label}${ico('chev', 14)}</button>`;
  };
  $('#filterBar').innerHTML = html`
    <button class="filter-btn all ${n ? 'on' : ''}" data-open-filter="all">${ico('filter', 16)}全部筛选${n ? html`<span class="filter-count">${n}</span>` : ''}</button>
    ${['sort'].concat(FILTER_KEYS).map(pill)}`;
  $('#clearAllFilters').hidden = !n;
}

function resultRow(t){
  return html`
    <button class="result" data-detail="${t.id}">
      ${catTile(t, 'thumb')}
      <div class="grow">
        <div class="h3">${t.title}</div>
        <div class="sub sm">${t.poster} · ${t.level} ${t.levelText} · ${formatDateCN(t.publishedAt)}</div>
        <div class="meta">
          <span class="chip amber">${t.budget}</span>
          <span class="chip">${t.deadline}</span>
          <span class="chip ${t.match >= 93 ? 'cyan' : ''}">匹配 ${t.match}%</span>
          <span class="chip">${verifyOf(t.verify).label}</span>
        </div>
      </div>
      ${ico('chev', 16)}
    </button>`;
}

function renderResults(){
  const list = getFilteredTasks();
  $('#resultCount').textContent = list.length + ' 个开放任务';
  $('#results').innerHTML = list.length
    ? list.map(resultRow).join('')
    : html`<div class="empty">没有符合条件的任务。<button class="link-btn" data-clear-all>清除筛选</button></div>`;
  renderFilterBar();
}

function setFilters(next){
  state.filters = next;
  state.draftFilters = clone(next);
  persistState();
  renderResults();
}

/* ---------- 筛选面板 ----------
   sheet.key 为某个维度时只显示这一项；为 'all' 时显示全部维度。 */
const sheet = {key:'all'};

function customInputs(key, d){
  if(key === 'date' && d.date === 'custom') return html`
    <div class="date-range">
      <input data-draft="dateFrom" type="date" value="${d.dateFrom}" aria-label="开始日期"><span>至</span>
      <input data-draft="dateTo" type="date" value="${d.dateTo}" aria-label="结束日期">
    </div>`;
  if(key === 'budget' && d.budget === 'custom') return html`
    <div class="range-inputs">
      <input data-draft="budgetMin" type="number" min="0" inputmode="numeric" placeholder="最低" value="${d.budgetMin}" aria-label="最低金额"><span>至</span>
      <input data-draft="budgetMax" type="number" min="0" inputmode="numeric" placeholder="最高" value="${d.budgetMax}" aria-label="最高金额">
    </div>`;
  return '';
}

function filterGroup(key, d, single){
  const g = FILTER_GROUPS[key];
  return html`
    <div class="filter-group" data-filter-group="${key}">
      ${single ? '' : html`<div class="filter-label">${g.label}</div>`}
      <div class="filter-choices">${g.options().map(([v, l]) =>
        html`<button class="filter-choice ${d[key] === v ? 'on' : ''}" data-filter-value="${v}">${l}</button>`)}</div>
      ${customInputs(key, d)}
    </div>`;
}

function renderSheet(){
  const d = state.draftFilters;
  const single = sheet.key !== 'all';
  const keys = single ? [sheet.key] : ['sort'].concat(FILTER_KEYS);
  $('#filterTitle').textContent = single ? FILTER_GROUPS[sheet.key].label : '全部筛选';
  $('#filterBody').innerHTML = keys.map(k => filterGroup(k, d, single)).join('');
  updateSheetCount();
}

// 面板里实时显示“查看 N 个结果”，筛到 0 时直接提示
function updateSheetCount(){
  const n = getFilteredTasks(state.draftFilters).length;
  const btn = $('#applyFilters');
  btn.textContent = n ? '查看 ' + n + ' 个结果' : '没有符合的任务';
  btn.disabled = !n;
  const keys = sheet.key === 'all' ? FILTER_KEYS.concat('sort') : [sheet.key];
  $('#resetFilters').disabled = keys.every(k => state.draftFilters[k] === DEFAULT_FILTERS[k]);
}

// 宽屏下单项筛选以下拉框形式出现在按钮下方；窄屏和“全部筛选”用底部/侧边面板
function placeSheet(anchor){
  const drawer = $('#filterDrawer'), box = drawer.querySelector('.filter-sheet');
  const pop = sheet.key !== 'all' && anchor && matchMedia('(min-width:621px)').matches;
  drawer.classList.toggle('pop', pop);
  if(!pop){ box.style.left = box.style.top = ''; return; }
  const r = anchor.getBoundingClientRect();
  box.style.top = (r.bottom + 8) + 'px';
  box.style.left = Math.min(r.left, innerWidth - 380) + 'px';
}

function openFilterDrawer(key = 'all', anchor){
  sheet.key = key;
  state.draftFilters = clone(state.filters);
  renderSheet();
  placeSheet(anchor);
  $('#filterDrawer').classList.add('on');
  $('#filterDrawer').setAttribute('aria-hidden', 'false');
}

function closeFilterDrawer(){
  $('#filterDrawer').classList.remove('on');
  $('#filterDrawer').setAttribute('aria-hidden', 'true');
}

function draftError(d){
  if(d.date === 'custom' && d.dateFrom && d.dateTo && d.dateFrom > d.dateTo) return '开始日期不能晚于结束日期';
  if(d.budget === 'custom' && d.budgetMin !== '' && d.budgetMax !== '' && Number(d.budgetMin) > Number(d.budgetMax)) return '最低金额不能高于最高金额';
  return '';
}

function applyDraftFilters(){
  const err = draftError(state.draftFilters);
  if(err){ toast(err); return; }
  closeFilterDrawer();
  setFilters(clone(state.draftFilters));
}

// 重置：单项面板只重置这一项，全部筛选重置全部
function resetDraft(){
  const keys = sheet.key === 'all' ? Object.keys(DEFAULT_FILTERS) : [sheet.key];
  if(sheet.key === 'date') keys.push('dateFrom', 'dateTo');
  if(sheet.key === 'budget') keys.push('budgetMin', 'budgetMax');
  keys.forEach(k => { state.draftFilters[k] = DEFAULT_FILTERS[k]; });
  renderSheet();
}

definePage('search', {render:renderResults});

onInput('#searchInput', el => { state.q = el.value; renderResults(); });
onClick('#clearSearch', () => { state.q = ''; $('#searchInput').value = ''; renderResults(); });
onClick('[data-open-filter]', el => openFilterDrawer(el.dataset.openFilter, el));
onClick('#clearAllFilters, [data-clear-all]', () => setFilters(Object.assign(clone(DEFAULT_FILTERS), {sort:state.filters.sort})));
onClick('[data-close-filter]', closeFilterDrawer);
onClick('#filterBody [data-filter-value]', el => {
  state.draftFilters[el.closest('[data-filter-group]').dataset.filterGroup] = el.dataset.filterValue;
  renderSheet();
});
onInput('#filterBody [data-draft]', el => {
  const k = el.dataset.draft;
  state.draftFilters[k] = el.type === 'number' ? (el.value === '' ? '' : Number(el.value)) : el.value;
  updateSheetCount();
});
onClick('#resetFilters', resetDraft);
onClick('#applyFilters', applyDraftFilters);
