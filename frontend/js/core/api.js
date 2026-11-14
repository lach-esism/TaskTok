/* 后端连接。页面由 TaskTok 后端在 /app/ 提供时，接口在同一个域名下；
   双击打开 index.html（file://）或后端不可用时，API.online 为 false，全站继续用 mock.js 的示例数据。 */

const API = {
  online:false,
  requestId:null,   // 推荐流这次曝光的 id，认领时带上，后端据此记录“从推荐里认领”
  timeoutMs:2500
};

async function apiRequest(method, path, body){
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
const apiGet = path => apiRequest('GET', path);

// 用 /health 探测后端；file:// 下直接视为离线
async function detectBackend(){
  if(!/^https?:$/.test(location.protocol)) return false;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), API.timeoutMs);
  try{
    const response = await fetch('/health', {signal:ctrl.signal});
    API.online = response.ok;
  }catch(error){
    API.online = false;
  }finally{
    clearTimeout(timer);
  }
  return API.online;
}
