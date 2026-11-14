/* 启动。脚本按 index.html 中的顺序加载：core → data → pages → remote → app。
   页面模块只注册 render 和事件，真正的首屏渲染在这里统一触发。
   先尝试连接后端（data/remote.js），连不上就用 mock.js 的示例数据。 */

loadPersisted();
renderNav();
initFeedPager();
initDetailSwipe();
connectBackend().finally(() => {
  syncFromHash();
  paint();
});

window.addEventListener('beforeunload', persistState);
