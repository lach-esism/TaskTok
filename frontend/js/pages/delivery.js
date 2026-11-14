/* 接单方提交成果：#/submit/<任务 id>。
   只有“进行中”或“需返工”的任务能提交；提交后状态变为“待验收”，由发包方在自己的任务管理页验收。 */

const DEMO_FILES = ['调研报告.pdf', '数据表.xlsx', '来源清单.md', '补充访谈记录.docx', '附录-原始数据.csv'];
const submitDraftOf = id => state.submitDraft[id] || (state.submitDraft[id] = {files:[], note:''});

function renderSubmit(){
  const id = state.ws;
  const t = taskById(id);
  const item = workItemFor(id);
  const d = submitDraftOf(id);
  const canSubmit = item && (item.status === 'active' || item.status === 'rework');
  $('#submitTask').textContent = t.title + (canSubmit ? '' : ' · 当前状态不能提交');
  $('#submitRework').innerHTML = item?.status === 'rework' && item.review
    ? html`<div class="notice coral"><b>发包方要求返工</b><p>${item.review.reason}</p></div>` : '';
  $('#submitExpect').textContent = '需要交付：' + t.outputs.join('；');
  $('#fileList').innerHTML = d.files.map((f, i) => html`
    <span class="filechip">${ico('doc', 14)}${f}<button type="button" class="chip-x" data-remove-file="${i}" aria-label="移除">×</button></span>`).join('');
  $('#fileCount').textContent = d.files.length ? d.files.length + ' 个文件' : '';
  $('#submitNote').value = d.note;
  $('#submitAccept').innerHTML = bullets(t.accept).join('');
  $('#submitWork').disabled = !canSubmit;
}

definePage('submit', {enter:id => { state.ws = id; }, render:renderSubmit});

onClick('#dropZone', () => {
  const d = submitDraftOf(state.ws);
  const name = DEMO_FILES.find(f => !d.files.includes(f));
  if(!name){ toast('示例文件已全部添加'); return; }
  d.files.push(name);
  persistStateSoon();
  renderSubmit();
});
onClick('[data-remove-file]', el => {
  submitDraftOf(state.ws).files.splice(Number(el.dataset.removeFile), 1);
  persistStateSoon();
  renderSubmit();
});
onInput('#submitNote', el => { submitDraftOf(state.ws).note = el.value; persistStateSoon(); });
onClick('#submitWork', () => {
  const id = state.ws;
  const d = submitDraftOf(id);
  const problem = submitWork(id, d.files, d.note);
  if(problem){ toast(problem); return; }
  toast('已提交，等待发包方验收');
  state.wsStatus = 'review';
  goBack();
});
