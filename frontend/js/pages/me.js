/* 我的：概览页只放身份、三个关键数字和入口列表；收藏、浏览记录、能力、收入、设置各是一个子页面。 */

function taskMiniCard(task, removable){
  return html`
    <div class="saved-card">
      <button class="grow row saved-main" data-detail="${task.id}">
        ${catTile(task, 'cover')}
        <span class="grow">
          <span class="h3 block">${task.title}</span>
          <span class="meta"><span>${task.budget}</span><span>${task.cat}</span><span>${formatDateCN(task.publishedAt || task.createdAt)}</span></span>
        </span>
      </button>
      ${removable ? html`<button class="remove" data-save="${task.id}" aria-label="取消收藏">${ico('bookmark', 16)}</button>` : ''}
    </div>`;
}

const tasksByIds = ids => ids.map(findTask).filter(Boolean);
const recentTasks = () => tasksByIds(state.recent).slice(0, 8);

definePage('me', {
  render(){
    $('#savedCount').textContent = state.saved.size || '';
    $('#recentCount').textContent = recentTasks().length || '';
  }
});

definePage('saved', {
  render(){
    const saved = tasksByIds(Array.from(state.saved));
    $('#savedList').innerHTML = saved.length
      ? saved.map(t => taskMiniCard(t, true)).join('')
      : '<div class="ws-empty">还没有收藏任务。在推荐页点“收藏”后会出现在这里。</div>';
  }
});

definePage('history', {
  render(){
    const recent = recentTasks();
    $('#recentList').innerHTML = recent.length
      ? recent.map(t => taskMiniCard(t, false)).join('')
      : '<div class="ws-empty">还没有浏览记录。</div>';
  }
});

definePage('income', {
  render(){
    const max = Math.max(...INCOME_SERIES);
    $('#incomeBars').innerHTML = INCOME_SERIES.map(v => html`<i style="height:${Math.round(v / max * 100)}%"></i>`).join('');
  }
});

onClick('.switch', el => {
  el.classList.toggle('on');
  toast(el.classList.contains('on') ? '已开启' : '已关闭');
});
