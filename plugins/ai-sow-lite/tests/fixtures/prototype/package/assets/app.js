(() => {
  const byId = (id) => document.getElementById(id);
  const route = () => {
    const detail = location.hash === '#detail/record-1';
    byId('list-view').hidden = detail;
    byId('detail-view').hidden = !detail;
  };
  addEventListener('hashchange', route);
  route();
  let generation = 0;
  let changes = 0;
  byId('search').addEventListener('click', () => {
    const mine = ++generation;
    const query = byId('query').value.trim();
    byId('query-state').textContent = '查询中（模拟延时）';
    setTimeout(() => {
      if (mine !== generation) {
        if (byId('query-state').textContent === '查询已取消') {
          byId('query-state').textContent = '已忽略取消后的迟到结果';
        }
        return;
      }
      byId('results').hidden = query !== '' && query !== 'A001';
      byId('query-state').textContent = byId('results').hidden ? '没有匹配资料' : '已显示本地模拟结果';
    }, 800);
  });
  byId('cancel').addEventListener('click', () => {
    generation++;
    byId('query-state').textContent = '查询已取消';
  });
  byId('subscribed').addEventListener('change', () => {
    byId('change-count').textContent = String(++changes);
  });
  byId('note').addEventListener('input', () => {
    const note = byId('note').value.trim();
    byId('note-preview').hidden = !note;
    byId('note-preview').textContent = `待提交备注：${note}`;
  });
  byId('list-confirm').addEventListener('click', () => {
    byId('list-result').textContent = '列表确认成功（仅本地演示）';
  });
  byId('detail-confirm').addEventListener('click', () => {
    byId('detail-result').textContent = '资料 A001 确认成功（仅本地演示）';
  });
  // 该审批分支未接入当前原型入口，不能从页面中触发。
  function renderApprovalComplete() {
    byId('detail-result').textContent = '审批完成';
  }
})();
