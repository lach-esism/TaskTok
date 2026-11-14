/* 应用状态与本地持久化。
   state 分两类：PERSISTED_KEYS 里的字段写入 localStorage，其余只在本次会话有效。 */

// v3：任务流程改成“发布 → 认领 → 选定 → 提交 → 验收”，旧存档字段不兼容，换新 key
const STORAGE_KEY = 'tasktok-market-prototype-v3';

const DEFAULT_FILTERS = {
  sort:'match', date:'any', dateFrom:'', dateTo:'', budget:'any', budgetMin:'', budgetMax:'',
  category:'全部', level:'any', verify:'any'
};

const state = {
  // 路由
  route:'feed',
  taskId:'t1',                 // 详情页当前任务

  // 接单侧
  saved:new Set(SEED.saved),
  recent:SEED.recent.slice(),
  workItems:clone(SEED.workItems), // {taskId, status, addedAt, submission?, review?, completedAt?}  状态见 mock.js
  checks:clone(SEED.checks),       // taskId → 已完成的子任务下标
  ws:'t1',                     // 工作台选中的任务
  wsStatus:'active',           // 工作台当前分组

  // 搜索
  q:'',
  filters:clone(DEFAULT_FILTERS),
  draftFilters:clone(DEFAULT_FILTERS), // 筛选抽屉里尚未应用的条件

  // 发布侧
  pubDraft:null,               // 新建表单草稿 {title, desc, budget, level, claimDeadline, deliverDeadline, verify, outputs[], accept[]}
  published:[],                // 我发布的任务，状态见 mock.js
  selectedPublishedId:null,
  pubEditing:false,
  reviewDraft:{},              // 发包方验收时勾选的标准：taskId → [下标]

  // 提交页
  submitDraft:{}               // taskId → {files[], note}
};

const PERSISTED_KEYS = [
  'saved', 'recent', 'workItems', 'checks', 'published', 'filters',
  'pubDraft', 'selectedPublishedId', 'submitDraft'
];

const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);

// 每个字段的读取规则：通过校验才覆盖默认值，避免旧版本或损坏的数据把页面搞挂。
const RESTORE = {
  saved:v => Array.isArray(v) && new Set(v),
  recent:v => Array.isArray(v) && v,
  workItems:v => Array.isArray(v) && v,
  checks:v => isObject(v) && v,
  published:v => Array.isArray(v) && v,
  filters:v => isObject(v) && Object.assign(clone(DEFAULT_FILTERS), v),
  pubDraft:v => isObject(v) && v,
  selectedPublishedId:v => v || false,
  submitDraft:v => isObject(v) && v
};

function loadPersisted(){
  try{
    const raw = localStorage.getItem(STORAGE_KEY);
    if(!raw) return;
    const saved = JSON.parse(raw);
    PERSISTED_KEYS.forEach(key => {
      const value = RESTORE[key](saved[key]);
      if(value) state[key] = value;
    });
    state.draftFilters = clone(state.filters);
  }catch(error){
    console.warn('无法读取本地原型状态，将使用示例数据。', error);
  }
}

function persistState(){
  clearTimeout(persistTimer);
  persistTimer = null;
  const data = {};
  PERSISTED_KEYS.forEach(key => { data[key] = state[key]; });
  data.saved = Array.from(state.saved);
  data.recent = state.recent.slice(0, 12);
  try{
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  }catch(error){
    console.warn('无法保存本地原型状态。', error);
  }
}

// 输入过程中频繁变更时用这个，合并成一次写入
let persistTimer = null;
function persistStateSoon(){
  clearTimeout(persistTimer);
  persistTimer = setTimeout(persistState, 160);
}

/* ---------- 查询 ---------- */
// KNOWN_TASKS：后端返回的、不在推荐流里的任务（如工作台里已结束的任务），离线时为空
const KNOWN_TASKS = [];
const allTasks = () => TASKS.concat(state.published, KNOWN_TASKS);
const findTask = id => allTasks().find(t => t.id === id);
const taskById = id => findTask(id) || TASKS[0];
const workItemFor = id => state.workItems.find(w => w.taskId === id);
const isSelfPublished = id => state.published.some(t => t.id === id);
const verifyOf = key => VERIFY_METHODS[key] || VERIFY_METHODS.manual;
const publishedById = id => state.published.find(t => t.id === id);

function recordRecent(id){
  if(!id || !findTask(id)) return;
  const next = [id].concat(state.recent.filter(item => item !== id)).slice(0, 12);
  const changed = next.join('|') !== state.recent.join('|');
  state.recent = next;
  if(changed) persistState();
}
