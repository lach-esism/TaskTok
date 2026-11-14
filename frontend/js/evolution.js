/* 自我进化演示页：跑一次 → 提交客户选择 → 系统学习出新版本 → 再跑一次；随时可退回。
   数据全部来自后端 /evolution 接口（需要由 TaskTok 后端在 /app/ 下提供本页）。 */

const state = {overview:null, run:null, picks:{}, busy:false};
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = v => Math.round(v * 100) + '%';

async function call(method, path, body){
  const options = {method, headers:{}};
  if(body !== undefined){
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = await response.json().catch(() => null);
  if(!response.ok){
    const detail = data && data.detail;
    throw new Error(typeof detail === 'string' ? detail : '服务暂时不可用（' + response.status + '）');
  }
  return data;
}

let toastTimer = null;
function toast(text){
  const el = $('toast');
  el.textContent = text;
  el.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('on'), 2600);
}

async function act(fn){
  if(state.busy) return;
  state.busy = true;
  renderButtons();
  try{ await fn(); }
  catch(error){ toast(error.message); }
  finally{ state.busy = false; renderButtons(); }
}

/* ---------- 动作 ---------- */
function setOverview(overview){
  state.overview = overview;
  const last = overview.lastRun;
  if(!state.run || !last || state.run.runId !== last.runId){
    state.run = last;
    state.picks = {};
  }
  render();
}

const doRun = () => act(async () => {
  const data = await call('POST', '/evolution/run');
  state.run = data.run;
  state.picks = {};
  setOverview(data.overview);
  const b = data.run.batch;
  toast(`第 ${data.run.number} 次运行：命中 ${b.hits}/${b.total}，用时 ${data.run.elapsedMs} ms`);
});

const doFeedback = () => act(async () => {
  const data = await call('POST', '/evolution/feedback', {run_id:state.run.runId, picks:state.picks});
  state.run = {...state.run, learned:true};
  setOverview(data.overview);
  const m = data.memory;
  toast(`学到新版本 ${m.toVersion}：${m.pairs} 组“选了谁、没选谁”，其中 ${m.corrections} 次纠正了系统第 1 名`);
});

const doRollback = () => act(async () => {
  const data = await call('POST', '/evolution/rollback', {});
  setOverview(data.overview);
  toast(`已退回：${data.from} → ${data.to}。再跑一次，成绩会和那一版完全一样`);
});

const doReset = () => act(async () => {
  if(!confirm('清空本演示的运行记录和学到的版本，回到初始权重？（不影响任务市场）')) return;
  state.run = null;
  setOverview(await call('POST', '/evolution/reset'));
  toast('已重置到初始权重 v0000');
});

/* ---------- 渲染 ---------- */
function canRollback(o){
  return o.memory.some(m => m.toVersion === o.activeVersion && !m.rolledBack);
}

function renderButtons(){
  const o = state.overview;
  const run = state.run;
  const canLearn = !!(o && run && !run.learned && run.version === o.activeVersion);
  $('btn-run').disabled = state.busy || !o;
  $('btn-feedback').disabled = state.busy || !canLearn;
  $('btn-rollback').disabled = state.busy || !o || !canRollback(o);
  $('btn-reset').disabled = state.busy || !o;
  $('btn-run').className = 'btn ' + (canLearn ? 'ghost' : 'primary');
  $('btn-feedback').className = 'btn ' + (canLearn ? 'primary' : 'ghost');

  let hint = '';
  if(o && !run) hint = '先跑一次，看看系统用初始权重派单的命中率。';
  else if(canLearn) hint = '客户已经在每个任务的 5 人里选好了人。提交这些选择，系统会从中学出一个新权重版本。';
  else if(o && run && run.version !== o.activeVersion) hint = `权重已换成 ${o.activeVersion}，再跑一次看成绩变化。`;
  else if(o && run && run.learned) hint = '已经学过这次的反馈。再跑一次，用新版本派同一批任务。';
  $('hint').textContent = hint;
}

function deltaTag(now, before, better){
  if(before === undefined) return '';
  const d = now - before;
  if(Math.abs(d) < 1e-9) return '<span class="delta">持平</span>';
  const good = better === 'up' ? d > 0 : d < 0;
  return `<span class="delta ${good ? 'up' : 'down'}">${d > 0 ? '+' : ''}${better === 'up' ? Math.round(d * 100) + '%' : d.toFixed(2)}</span>`;
}

function renderRuns(){
  const runs = state.overview.runs;
  if(!runs.length){
    $('runs').innerHTML = '<div class="panel evo-empty">还没有运行记录</div>';
    return;
  }
  $('runs').innerHTML = runs.map((r, i) => {
    const prev = runs[i - 1];
    const b = r.batch, h = r.holdout;
    return `<div class="panel evo-run ${i === runs.length - 1 ? 'latest' : ''}">
      <div class="row between"><span class="kicker">第 ${r.number} 次 · ${esc(r.version)}</span><span class="sub xs">${r.elapsedMs} ms</span></div>
      <div class="row between"><div class="big">${pct(b.hit_rate)}<small>${b.hits}/${b.total} 命中</small></div>${deltaTag(b.hit_rate, prev && prev.batch.hit_rate, 'up')}</div>
      <div class="bar"><i style="width:${b.hit_rate * 100}%"></i></div>
      <div class="kv"><span>满意度差距（越低越好）</span><b class="mono">${b.satisfaction_gap.toFixed(2)} ${deltaTag(b.satisfaction_gap, prev && prev.batch.satisfaction_gap, 'down')}</b></div>
      <div class="kv"><span>最佳人选平均排第</span><b class="mono">${b.avg_gold_rank}</b></div>
      <div class="kv"><span>没参与学习的 ${h.total} 个任务命中率</span><b class="mono">${pct(h.hit_rate)}</b></div>
    </div>`;
  }).join('');
}

function renderTasks(){
  const run = state.run;
  if(!run){
    $('run-label').textContent = '';
    $('tasks').innerHTML = '<div class="panel evo-empty">点“跑一次派单”开始</div>';
    return;
  }
  const editable = !run.learned && run.version === state.overview.activeVersion;
  $('run-label').textContent = `第 ${run.number} 次 · 权重 ${run.version}`;
  $('tasks').innerHTML = run.tasks.map(t => {
    const chosen = state.picks[t.taskId] || t.clientPick;
    const top = t.shown[0];
    const pickName = t.shown.find(s => s.workerId === chosen).name;
    const corrected = state.picks[t.taskId] && state.picks[t.taskId] !== t.clientPick;
    const note = chosen === top.workerId ? `客户选了系统第 1 名 ${esc(pickName)}` : `客户没选第 1 名，选了 ${esc(pickName)}`;
    return `<details class="evo-task">
      <summary>
        <span class="mark ${t.hit ? 'hit' : 'miss'}" title="${t.hit ? '第 1 名就是客户最想要的人' : '第 1 名不是客户最想要的人'}">${t.hit ? '✓' : '✕'}</span>
        <span class="grow"><span class="title" style="display:block">${esc(t.title)}</span>
        <span class="meta">${esc(t.category)} · ${note}${corrected ? ' · <span class="accent">人工改选</span>' : ''}</span></span>
        <span class="sub xs">最佳人选排第 ${t.goldRank}</span>
      </summary>
      <div class="evo-cands">${t.shown.map((s, i) => `
        <label class="evo-cand ${s.workerId === chosen ? 'chosen' : ''} ${editable ? '' : 'locked'}">
          <span class="rank">${i + 1}</span>
          <span class="name">${esc(s.name)}${s.workerId === t.clientPick ? ' <span class="chip cyan" style="height:20px">客户选择</span>' : ''}</span>
          <span class="score">${s.score.toFixed(3)}</span>
          <input type="radio" name="pick-${esc(t.taskId)}" value="${esc(s.workerId)}" ${s.workerId === chosen ? 'checked' : ''} ${editable ? '' : 'disabled'}>
        </label>`).join('')}
      </div>
    </details>`;
  }).join('');
}

function renderWeights(){
  const o = state.overview;
  const max = Math.max(...o.weights.map(w => Math.max(w.value, w.initial)), 0.01) * 1.1;
  const changed = o.weights.some(w => Math.abs(w.value - w.initial) > 1e-4);
  $('diff-label').textContent = changed ? `${o.activeVersion} 对比初始 v0000` : '还是初始权重';
  $('weights').innerHTML = `<p class="sub sm" style="margin-bottom:6px">推荐打分里各项的权重。白线是初始值，绿条是当前值。</p>` +
    o.weights.map(w => {
      const d = w.value - w.initial;
      const cls = Math.abs(d) < 1e-4 ? '' : (d > 0 ? 'up' : 'down');
      const text = Math.abs(d) < 1e-4 ? '—' : (d > 0 ? '+' : '') + d.toFixed(3);
      return `<div class="evo-w"><span class="lab">${esc(w.label)}</span>
        <span class="evo-wbar"><i style="width:${w.value / max * 100}%"></i><s style="left:${w.initial / max * 100}%"></s></span>
        <span class="val">${w.value.toFixed(3)}</span><span class="chg ${cls}">${text}</span></div>`;
    }).join('');
}

function renderMemory(){
  const memory = state.overview.memory.slice().reverse();
  if(!memory.length){
    $('memory').innerHTML = '<div class="panel evo-empty">还没有学习记录</div>';
    return;
  }
  $('memory').innerHTML = memory.map(m => {
    const fixes = m.items.filter(i => i.corrected);
    return `<div class="evo-mem ${m.rolledBack ? 'rolled' : ''}">
      <div class="row between"><b class="mono">${esc(m.fromVersion)} → ${esc(m.toVersion)}</b>
        ${m.rolledBack ? '<span class="chip coral">已退回</span>' : (m.toVersion === state.overview.activeVersion ? '<span class="chip cyan">当前版本</span>' : '')}</div>
      <div class="sub sm">${m.items.length} 个任务的客户选择，${m.pairs} 组“选了谁、没选谁”，${m.corrections} 次纠正了系统第 1 名</div>
      <ul>${fixes.slice(0, 4).map(i => `<li>${esc(i.title)}：系统推 ${esc(i.systemTopName)}，客户选 <b>${esc(i.chosenName)}</b>${i.source === 'manual' ? '（人工改选）' : ''}</li>`).join('')}
      ${fixes.length > 4 ? `<li>…另外 ${fixes.length - 4} 条</li>` : ''}</ul>
    </div>`;
  }).join('');
}

function renderStandard(){
  $('standard').innerHTML = state.overview.clientStandard.map(s =>
    `<div class="kv"><span>${esc(s.label)}</span><b class="mono">${s.value.toFixed(2)}</b></div>`).join('');
}

function render(){
  const o = state.overview;
  $('active-version').textContent = o.activeVersion;
  renderRuns();
  renderTasks();
  renderWeights();
  renderMemory();
  renderStandard();
  renderButtons();
}

/* ---------- 事件 ---------- */
$('btn-run').addEventListener('click', doRun);
$('btn-feedback').addEventListener('click', doFeedback);
$('btn-rollback').addEventListener('click', doRollback);
$('btn-reset').addEventListener('click', doReset);
$('tasks').addEventListener('change', event => {
  const input = event.target;
  if(input.type !== 'radio') return;
  const taskId = input.name.slice('pick-'.length);
  const task = state.run.tasks.find(t => t.taskId === taskId);
  if(input.value === task.clientPick) delete state.picks[taskId];
  else state.picks[taskId] = input.value;
  const openIds = [...document.querySelectorAll('.evo-task[open] input')].map(i => i.name);
  renderTasks();
  openIds.forEach(name => {
    const el = document.querySelector(`input[name="${CSS.escape(name)}"]`);
    if(el) el.closest('details').open = true;
  });
});

call('GET', '/evolution').then(setOverview).catch(error => {
  $('hint').textContent = '连不上后端：' + error.message + '。请用 scripts/run_demo.py 启动，再打开 /app/evolution.html。';
  renderButtons();
});
