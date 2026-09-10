"use strict";

const stores = { CC01: "青禾店（合成）", CC02: "河畔店（合成）", CC03: "星桥店（合成）" };
const staffStores = ["CC01", "CC02", "CC03"];
const activePartner = "PARTNER-DEMO-A";
const pageSize = 2;
// 样本集只服务于本期交互，不编码一期最终确认的默认状态范围。
const samples = [
  { id: "CC-DEMO-206", store: "CC01", summary: "冷藏展示柜温度波动", category: "设备故障", status: "处理中", priority: "紧急", partner: "PARTNER-DEMO-A", description: "营业期间展示柜温度出现波动，门店已临时转移商品。请按现有安排核查设备。", created: "2026-09-02 10:20", updated: "2026-09-02 11:10", internalNote: "内部备注（合成）：门店交接由区域客服协调。", records: [{ time: "2026-09-02 10:50", actor: "客服甲（合成）", text: "已核对故障现象，可按当前分配查看。", visibleTo: "PARTNER-DEMO-A" }, { time: "2026-09-02 11:10", actor: "内部员工乙（合成）", text: "内部沟通：等待区域负责人核对门店交接。", visibleTo: null }] },
  { id: "CC-DEMO-205", store: "CC02", summary: "入口灯带接触不良", category: "环境设施", status: "待处理", priority: "普通", partner: "PARTNER-DEMO-B", description: "入口灯带间歇熄灭，需要现场核查。", created: "2026-09-02 09:30", updated: "2026-09-02 09:30", internalNote: "内部备注（合成）：由另一服务商跟进。", records: [] },
  { id: "CC-DEMO-204", store: "CC03", summary: "排风设备有异响", category: "设备故障", status: "待处理", priority: "紧急", partner: "PARTNER-DEMO-A", description: "排风设备开启时有持续异响，现已暂停使用。", created: "2026-09-01 14:00", updated: "2026-09-01 14:00", internalNote: "内部备注（合成）：先确认门店安全隔离。", records: [] },
  { id: "CC-DEMO-203", store: "CC01", summary: "库房门把手松动", category: "其他", status: "已关闭", priority: "普通", partner: "PARTNER-DEMO-A", description: "库房门把手松动的处理记录供查询。", created: "2026-08-31 09:00", updated: "2026-09-01 12:00", internalNote: "内部备注（合成）：门店已完成内部回访。", records: [{ time: "2026-09-01 12:00", actor: "客服甲（合成）", text: "现有系统记录检查完成。", visibleTo: "PARTNER-DEMO-A" }] },
  { id: "CC-DEMO-202", store: "CC02", summary: "服务台照明偏暗", category: "环境设施", status: "待处理", priority: "普通", partner: null, description: "服务台一处照明亮度不足。", created: "2026-08-30 16:00", updated: "2026-08-30 16:00", internalNote: "内部备注（合成）：尚未分配服务商。", records: [] }
];
const filters = { priority: "", query: "", page: 1 };
const app = document.getElementById("app");

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

function filteredTickets(selection = filters) {
  const query = selection.query.trim().toLowerCase();
  return samples.filter(ticket => staffStores.includes(ticket.store)
    && (!selection.priority || ticket.priority === selection.priority)
    && (!query || `${ticket.id} ${ticket.summary}`.toLowerCase().includes(query)))
    .sort((left, right) => right.created.localeCompare(left.created) || right.id.localeCompare(left.id));
}

function renderList() {
  const rows = filteredTickets();
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  filters.page = Math.min(filters.page, pages);
  const visible = rows.slice((filters.page - 1) * pageSize, filters.page * pageSize);
  app.innerHTML = `<section class="panel"><p class="route">/tickets · 现有客服队列本期调整</p>
    <h2>按优先级查看工单</h2><p>优先级由外部客服后台提供，创建工单仍沿用一期。本页只演示本期优先级变化。</p>
    <p class="muted">状态基线：沿用一期最后确认的列表默认筛选。以下样本不代表该默认筛选的实际结果。</p>
    <form id="filters" class="filters">
      <label>优先级<select name="priority"><option value="">不限优先级</option>${["普通", "紧急"].map(value => `<option value="${value}"${filters.priority === value ? " selected" : ""}>${value}</option>`).join("")}</select></label>
      <label class="grow">摘要或工单编号<input name="query" maxlength="80" value="${escapeHtml(filters.query)}" placeholder="例如：照明"></label>
      <button type="submit">筛选</button><button type="button" data-action="clear" class="secondary">清除本页条件</button>
    </form>
    ${visible.length ? `<div class="table-scroll"><table><thead><tr><th>工单编号</th><th>门店</th><th>摘要</th><th>状态</th><th>优先级</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${visible.map(ticket => `<tr><td>${ticket.id}</td><td>${stores[ticket.store]}</td><td>${escapeHtml(ticket.summary)}</td><td>${ticket.status}</td><td><span class="badge${ticket.priority === "紧急" ? " urgent" : ""}">${ticket.priority}</span></td><td>${ticket.created}</td><td><a href="#/tickets/${ticket.id}">员工详情</a></td></tr>`).join("")}</tbody></table></div>` : '<p class="empty" role="status">没有匹配工单。可调整优先级或清除本页条件。</p>'}
    <div class="pager"><button type="button" data-action="previous"${filters.page <= 1 ? " disabled" : ""}>上一页</button><span>共 ${rows.length} 条 · 第 ${filters.page} / ${pages} 页</span><button type="button" data-action="next"${filters.page >= pages ? " disabled" : ""}>下一页</button></div>
    </section>`;
}

// 仅为页面演示构造白名单视图；真实接口须在服务端鉴权和裁剪。
function partnerView(ticket, partnerId = activePartner) {
  if (!ticket || !partnerId || ticket.partner !== partnerId) return null;
  return {
    ticket_id: ticket.id,
    store_display_name: stores[ticket.store],
    category: ticket.category,
    summary: ticket.summary,
    description: ticket.description,
    status: ticket.status,
    priority: ticket.priority,
    reporter_mobile: "138****0000",
    created_at: ticket.created,
    updated_at: ticket.updated,
    processing_records: ticket.records.filter(record => record.visibleTo === partnerId)
      .map(record => ({ time: record.time, actor: record.actor, text: record.text }))
  };
}

function renderUnavailable() {
  app.innerHTML = '<section class="panel"><h2>工单不存在或不可访问</h2><p>不存在、未分配或分配不属于当前演示身份时，使用相同提示。</p><a href="#/tickets">返回演示队列</a></section>';
}

function recordsHtml(records, emptyText) {
  return records.length ? `<ol class="timeline">${records.map(record => `<li><time>${record.time}</time> · ${escapeHtml(record.actor)}<p>${escapeHtml(record.text)}</p></li>`).join("")}</ol>` : `<p class="empty">${emptyText}</p>`;
}

function renderPartner(id) {
  const view = partnerView(samples.find(ticket => ticket.id === id));
  if (!view) return renderUnavailable();
  app.innerHTML = `<section class="panel mobile-preview"><p class="route">/partner/tickets/${escapeHtml(id)}</p>
    <p>演示身份：澄川协作服务商甲（合成）</p><h2>${escapeHtml(view.summary)}</h2>
    <dl class="details"><dt>工单编号</dt><dd>${view.ticket_id}</dd><dt>门店</dt><dd>${view.store_display_name}</dd>
    <dt>故障类别</dt><dd>${view.category}</dd><dt>当前状态</dt><dd>${view.status}</dd>
    <dt>优先级</dt><dd><span class="badge${view.priority === "紧急" ? " urgent" : ""}">${view.priority}</span></dd>
    <dt>联系手机号</dt><dd>${view.reporter_mobile}（合成掩码）</dd><dt>问题描述</dt><dd>${escapeHtml(view.description)}</dd>
    <dt>创建时间</dt><dd>${view.created_at}</dd><dt>更新时间</dt><dd>${view.updated_at}</dd></dl>
    <h3>对本服务商可见的处理记录</h3>${recordsHtml(view.processing_records, "暂无可见处理记录")}
    <p class="muted">此页只读，仅展示当前分配工单的允许字段。静态页面不证明真实后端授权。</p>
    <p><a href="#/partner/tickets/CC-DEMO-204">无可见处理记录示例</a></p>
    <p><a href="#/partner/tickets/CC-DEMO-202">未分配示例</a> · <a href="#/partner/tickets/CC-DEMO-MISSING">未找到示例</a></p>
    <a href="#/tickets">返回演示队列</a></section>`;
}

function renderEmployee(id) {
  const ticket = samples.find(item => item.id === id && staffStores.includes(item.store));
  if (!ticket) return renderUnavailable();
  app.innerHTML = `<section class="panel"><p class="route">/tickets/${escapeHtml(id)} · 既有员工视图示意</p>
    <a href="#/tickets">← 返回队列（保留条件与页码）</a><h2>${escapeHtml(ticket.summary)}</h2>
    <dl class="details"><dt>工单编号</dt><dd>${ticket.id}</dd><dt>门店</dt><dd>${stores[ticket.store]}</dd>
    <dt>报修人</dt><dd>门店员工甲（合成）</dd><dt>联系手机号</dt><dd>138****0000（合成掩码）</dd>
    <dt>故障类别</dt><dd>${ticket.category}</dd><dt>当前状态</dt><dd>${ticket.status}</dd>
    <dt>问题描述</dt><dd>${escapeHtml(ticket.description)}</dd><dt>创建时间</dt><dd>${ticket.created}</dd>
    <dt>更新时间</dt><dd>${ticket.updated}</dd><dt>最后处理时间</dt><dd>${ticket.records.at(-1)?.time || "暂无"}</dd></dl>
    <h3>只读处理记录</h3>${recordsHtml(ticket.records, "暂无处理记录")}
    <p class="muted">服务商页面的接口选择仍待确认，员工页面与其业务相关不代表旧接口已经适用。</p>
    <a href="#/partner/tickets/${ticket.id}">切换为服务商甲演示视图</a></section>`;
}

function renderRoute() {
  const route = window.location.hash.slice(1) || "/tickets";
  if (route === "/tickets") renderList();
  else if (/^\/partner\/tickets\/[^/]+$/.test(route)) renderPartner(route.slice("/partner/tickets/".length));
  else if (/^\/tickets\/[^/]+$/.test(route)) renderEmployee(route.slice("/tickets/".length));
  else app.innerHTML = '<section class="panel"><h2>页面不存在</h2><a href="#/tickets">返回队列</a></section>';
}

document.addEventListener("submit", event => {
  if (event.target.id !== "filters") return;
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  Object.assign(filters, { priority: data.priority, query: data.query, page: 1 });
  renderList();
});

document.addEventListener("click", event => {
  const button = event.target.closest("button[data-action]");
  if (!button || button.disabled) return;
  if (button.dataset.action === "clear") Object.assign(filters, { priority: "", query: "", page: 1 });
  if (button.dataset.action === "previous") filters.page = Math.max(1, filters.page - 1);
  if (button.dataset.action === "next") filters.page += 1;
  renderList();
});

window.addEventListener("hashchange", renderRoute);
renderRoute();
