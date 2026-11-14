/* DOM 与格式化工具。所有拼接 HTML 都走 html``，插值默认转义。 */

const $ = sel => document.querySelector(sel);
const $$ = sel => Array.from(document.querySelectorAll(sel));

/* ---------- 安全的 HTML 模板 ---------- */
class SafeHTML {
  constructor(text){ this.text = text; }
  toString(){ return this.text; }
}

function escapeHTML(value){
  return String(value ?? '').replace(/[&<>"']/g, ch => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]
  ));
}

function toHTML(value){
  if(value === null || value === undefined || value === false) return '';
  if(value instanceof SafeHTML) return value.text;
  if(Array.isArray(value)) return value.map(toHTML).join('');
  return escapeHTML(value);
}

// 标签模板：html`<b>${name}</b>`。字符串插值会被转义；数组会拼接；html`` 结果原样嵌入。
function html(strings, ...values){
  let out = strings[0];
  values.forEach((value, i) => { out += toHTML(value) + strings[i + 1]; });
  return new SafeHTML(out);
}

// 图标引用 index.html 顶部的 <symbol id="i-xxx">
function ico(name, size){
  const sizeClass = size ? ' ico-' + size : '';
  return new SafeHTML('<svg class="ico' + sizeClass + '" aria-hidden="true"><use href="#i-' + name + '"/></svg>');
}

/* ---------- 事件委托 ----------
   onClick(selector, handler)：从点击目标往上找，最近的匹配元素触发对应 handler，只触发一个。
   页面重绘后依然有效，不需要重新绑定。 */
const delegated = {click:[], input:[], change:[]};

function onEvent(type, selector, handler){ delegated[type].push([selector, handler]); }
const onClick = (selector, handler) => onEvent('click', selector, handler);
const onInput = (selector, handler) => onEvent('input', selector, handler);
const onChange = (selector, handler) => onEvent('change', selector, handler);

Object.keys(delegated).forEach(type => {
  document.addEventListener(type, event => {
    for(let node = event.target; node && node !== document; node = node.parentElement){
      const hit = delegated[type].find(([selector]) => node.matches(selector));
      if(hit){ hit[1](node, event); return; }
    }
  });
});

/* ---------- 提示 ---------- */
let toastTimer = null;
function toast(message){
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('on'), 2200);
}

/* ---------- 金额 ---------- */
const yuan = amount => '¥' + (Number(amount) || 0).toLocaleString();
const yuanCents = amount => '¥' + (Number(amount) || 0).toLocaleString('zh-CN', {minimumFractionDigits:2, maximumFractionDigits:2});

/* ---------- 日期 ---------- */
const DAY_MS = 86400000;

function isoDaysFromNow(days, hour){
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
}
const isoDaysAgo = (days, hour = 10) => isoDaysFromNow(-days, hour);
const isoDaysAhead = (days, hour = 18) => isoDaysFromNow(days, hour);

// ISO → <input type="date"> 用的 YYYY-MM-DD（本地时区）
function dateValue(iso){
  const d = new Date(iso);
  return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
}

// <input type="date"> 的值 → 当天 18:00 的 ISO，用作截止时间
const deadlineISO = value => new Date(value + 'T18:00:00').toISOString();

function formatDateCN(value){
  const d = new Date(value);
  if(Number.isNaN(d.getTime())) return '未设置';
  return (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日';
}

function sameLocalDay(a, b){
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

const clone = value => JSON.parse(JSON.stringify(value));
