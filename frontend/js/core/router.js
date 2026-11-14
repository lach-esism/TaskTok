/* 导航与哈希路由：#/<route>[/<id>]
   ROUTES 是路由注册表，页面模块在加载时把自己的 render 填进来。
   nav:true 的项出现在侧栏和底部栏（宽窄屏一致）；其余页面只能从页面内链接进入。 */

const ROUTES = [
  {r:'feed',      label:'推荐',        icon:'feed',   nav:true},
  {r:'search',    label:'搜索',        icon:'search', nav:true},
  {r:'publish',   label:'发布',        icon:'plus',   nav:true},
  {r:'workspace', label:'工作台',      icon:'grid',   nav:true},
  {r:'me',        label:'我的',        icon:'user',   nav:true},
  // 子页面：
  //   parent  所属一级页面，决定导航高亮
  //   up(id)  没有上一页可退时（直接打开链接）逻辑上的上一级，默认是 parent
  {r:'task',      label:'任务详情',     up:id => isSelfPublished(id) ? ['pubtask', id] : ['feed']},
  {r:'saved',     label:'我的收藏',     parent:'me'},
  {r:'history',   label:'浏览记录',     parent:'me'},
  {r:'skills',    label:'能力图谱',     parent:'me'},
  {r:'income',    label:'收入明细',     parent:'me'},
  {r:'settings',  label:'偏好设置',     parent:'me'},
  {r:'published', label:'我发布的任务', parent:'publish'},
  {r:'pubtask',   label:'任务管理',     parent:'publish', up:() => ['published']},
  {r:'job',       label:'任务进度',     parent:'workspace'},
  {r:'submit',    label:'提交成果',     parent:'workspace', up:id => ['job', id]}
];
const routeOf = r => ROUTES.find(x => x.r === r);
const parentOf = r => routeOf(r)?.parent;

const pages = {}; // route → {render(), enter(id)}
function definePage(route, page){ pages[route] = page; }

function renderNav(){
  const items = ROUTES.filter(n => n.nav);
  $('#railnav').innerHTML = items.map(n =>
    html`<button class="nav-item" data-go="${n.r}">${ico(n.icon, 18)}<span>${n.label}</span></button>`
  ).join('');
  $('#tabbar').innerHTML = items.map(n =>
    html`<button class="tab" data-go="${n.r}">${ico(n.icon, 22)}<span>${n.label}</span></button>`
  ).join('');
}

function markNav(){
  const top = parentOf(state.route) || state.route;
  $$('.nav-item, .tab').forEach(b => b.classList.toggle('on', b.dataset.go === top));
}

// 进入某个路由；带 id 时交给页面的 enter() 记录选中项。
// 改 hash 会触发 hashchange 再 paint 一次，所以这里只在 hash 不变时直接 paint。
// （file:// 下 history.pushState 不可靠，故用 location.hash。）
const hashOf = (route, id) => '#/' + route + (id && pages[route]?.enter ? '/' + id : '');

function go(route, id){
  applyRoute(route, id);
  const hash = hashOf(state.route, id);
  if(location.hash !== hash) location.hash = hash;
  else paint();
}

function applyRoute(route, id){
  state.route = ROUTES.some(r => r.r === route) ? route : 'feed';
  state.routeId = id || null;
  const page = pages[state.route];
  if(id && page?.enter) page.enter(id);
}

/* ---------- 返回 ----------
   返回 = 回到上一个页面（和浏览器后退一致），而不是固定跳到某个一级页。
   stack 记录本次打开以来的页面顺序；直接打开深链接、没有上一页时，按 upOf() 回到逻辑上的上一级。 */
const nav = {stack:[]};

// 逻辑上一级：子页面可以声明 up(id) 返回 [route, id]，否则回到 parent，再否则回推荐
function upOf(route, id){
  const r = routeOf(route);
  if(r?.up) return r.up(id);
  return [r?.parent || 'feed', null];
}

function trackHistory(hash){
  const s = nav.stack;
  if(s[s.length - 2] === hash) s.pop();          // 后退到上一页
  else if(s[s.length - 1] !== hash) s.push(hash); // 前进到新页面
}

function goBack(){
  if(nav.stack.length > 1){ history.back(); return; }
  const [route, id] = upOf(state.route, state.routeId);
  // 没有上一页时用 replace，避免“后退”又回到当前页
  location.replace(hashOf(route, id));
}

// 当前页返回后会落在哪：用来显示返回按钮上的文字
function backLabel(){
  const prev = nav.stack[nav.stack.length - 2];
  const route = prev ? prev.replace(/^#\/?/, '').split('/')[0] : upOf(state.route, state.routeId)[0];
  return routeOf(route)?.label || '返回';
}

function paint(){
  $$('.view').forEach(v => v.classList.toggle('on', v.id === 'view-' + state.route));
  markNav();
  pages[state.route]?.render?.();
  const view = $('.view.on');
  if(view){
    view.scrollTop = 0;
    view.querySelectorAll('[data-back] .back-text').forEach(el => { el.textContent = backLabel(); });
  }
}

function syncFromHash(){
  const [route, id] = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  applyRoute(route || 'feed', id);
  trackHistory(hashOf(state.route, state.routeId));
}

window.addEventListener('hashchange', () => { syncFromHash(); paint(); });
onClick('[data-go]', el => go(el.dataset.go));
onClick('[data-back]', goBack);
