"use strict";

const stores = { CC01: "青禾店（合成）", CC02: "河畔店（合成）", CC03: "星桥店（合成）" };
const staffStores = ["CC01", "CC02", "CC03"];
const creatorStores = ["CC01"];
const statusOptions = ["待处理", "处理中", "已关闭"];
const categoryOptions = ["设备故障", "环境设施", "其他"];
const samples = [
  { id: "CC-DEMO-106", store: "CC01", summary: "冷藏展示柜温度偏高", status: "待处理", category: "设备故障", created: "2026-08-14 10:20", updated: "2026-08-14 10:20", description: "展示柜运行时温度升高，请客服核实。商品已按门店流程转移。", records: [] },
  { id: "CC-DEMO-105", store: "CC02", summary: "入口灯带间歇闪烁", status: "处理中", category: "环境设施", created: "2026-08-14 09:10", updated: "2026-08-14 09:40", description: "入口左侧灯带偶发闪烁，暂未影响通行。", records: [{ time: "2026-08-14 09:40", actor: "客服甲（合成）", text: "已核实情况，现有客服系统记录处理中。" }] },
  { id: "CC-DEMO-104", store: "CC01", summary: "收银台旁插座松动", status: "已关闭", category: "环境设施", created: "2026-08-13 16:00", updated: "2026-08-14 08:30", description: "插座外壳松动，门店已停止使用。", records: [{ time: "2026-08-14 08:30", actor: "客服乙（合成）", text: "现有客服系统提供的处理结果：已完成检查。" }] },
  { id: "CC-DEMO-103", store: "CC03", summary: "标签打印设备无法出纸", status: "待处理", category: "设备故障", created: "2026-08-13 13:20", updated: "2026-08-13 13:20", description: "更换演示耗材后仍无法出纸，需要核实设备情况。", records: [] },
  { id: "CC-DEMO-102", store: "CC02", summary: "库房门把手转动不畅", status: "处理中", category: "其他", created: "2026-08-12 11:30", updated: "2026-08-13 10:00", description: "开关库房门时门把手阻力偏大。", records: [{ time: "2026-08-13 10:00", actor: "客服甲（合成）", text: "已登记现象，处理中。" }] },
  { id: "CC-DEMO-101", store: "CC03", summary: "服务台照明不亮", status: "已关闭", category: "环境设施", created: "2026-08-11 08:00", updated: "2026-08-12 09:00", description: "服务台一处照明无法点亮。", records: [{ time: "2026-08-12 09:00", actor: "客服乙（合成）", text: "现有客服系统记录已关闭。" }] },
  { id: "CC-DEMO-OUTSIDE", store: "CC18", summary: "权限边界合成样本", status: "待处理", category: "其他", created: "2026-08-15 08:00", updated: "2026-08-15 08:00", description: "该样本不可出现在当前客服视图。", records: [] }
];
const filters = { status: "", store: "", query: "", page: 1 };
const pageSize = 2;
const app = document.getElementById("app");

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

function options(values, selected, first) {
  return `<option value="">${first}</option>` + values.map(([value, label]) => `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`).join("");
}

function filteredTickets(selection = filters) {
  const query = selection.query.trim().toLowerCase();
  return samples.filter(ticket => staffStores.includes(ticket.store)
    && (!selection.status || ticket.status === selection.status)
    && (!selection.store || ticket.store === selection.store)
    && (!query || `${ticket.id} ${ticket.summary}`.toLowerCase().includes(query)))
    .sort((left, right) => right.created.localeCompare(left.created) || right.id.localeCompare(left.id));
}

function renderList() {
  const rows = filteredTickets();
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  filters.page = Math.min(filters.page, pages);
  const visible = rows.slice((filters.page - 1) * pageSize, filters.page * pageSize);
  app.innerHTML = `<section class="panel"><p class="route">/tickets · 演示身份：客服，授权门店 CC01—CC03</p>
    <h2>客服工单队列</h2><p>初次进入默认全部状态。处理进展由现有客服系统提供。</p>
    <form id="filters" class="filters">
      <label>状态<select name="status">${options(statusOptions.map(value => [value, value]), filters.status, "全部状态")}</select></label>
      <label>门店<select name="store">${options(staffStores.map(value => [value, stores[value]]), filters.store, "全部授权门店")}</select></label>
      <label class="grow">摘要或工单编号<input name="query" maxlength="80" value="${escapeHtml(filters.query)}" placeholder="例如：灯"></label>
      <button type="submit">筛选</button><button type="button" data-action="clear" class="secondary">清除筛选</button>
    </form>
    ${visible.length ? `<div class="table-scroll"><table><thead><tr><th>工单编号</th><th>门店</th><th>摘要</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${visible.map(ticket => `<tr><td>${ticket.id}</td><td>${stores[ticket.store]}</td><td>${escapeHtml(ticket.summary)}</td><td><span class="badge">${ticket.status}</span></td><td>${ticket.created}</td><td><a href="#/tickets/${ticket.id}">查看详情</a></td></tr>`).join("")}</tbody></table></div>` : '<p class="empty" role="status">没有匹配工单。可调整条件或清除筛选。</p>'}
    <div class="pager"><button type="button" data-action="previous"${filters.page <= 1 ? " disabled" : ""}>上一页</button><span>共 ${rows.length} 条 · 第 ${filters.page} / ${pages} 页</span><button type="button" data-action="next"${filters.page >= pages ? " disabled" : ""}>下一页</button></div>
    <p><a href="#/tickets/CC-DEMO-MISSING">未找到示例</a> · <a href="#/tickets/CC-DEMO-OUTSIDE">门店越权示例</a></p></section>`;
}

function renderDetail(id) {
  const ticket = samples.find(item => item.id === id && staffStores.includes(item.store));
  if (!ticket) {
    app.innerHTML = '<section class="panel"><h2>工单不存在或不可访问</h2><p>不存在与不在授权门店范围内使用相同提示。</p><a href="#/tickets">返回队列</a></section>';
    return;
  }
  const recordHtml = ticket.records.length ? `<ol class="timeline">${ticket.records.map(record => `<li><time>${record.time}</time> · ${record.actor}<p>${record.text}</p></li>`).join("")}</ol>` : '<p class="empty">暂无处理记录</p>';
  app.innerHTML = `<section class="panel"><p class="route">/tickets/${escapeHtml(id)} · 客服只读视图</p><a href="#/tickets">← 返回队列（保留筛选与页码）</a>
    <h2>${escapeHtml(ticket.summary)}</h2><dl class="details">
    <dt>工单编号</dt><dd>${ticket.id}</dd><dt>门店</dt><dd>${stores[ticket.store]}</dd>
    <dt>报修人</dt><dd>门店员工甲（合成）</dd><dt>联系手机号</dt><dd>138****0000（合成掩码）</dd>
    <dt>故障类别</dt><dd>${ticket.category}</dd><dt>当前状态</dt><dd>${ticket.status}</dd>
    <dt>问题描述</dt><dd>${escapeHtml(ticket.description)}</dd><dt>创建时间</dt><dd>${ticket.created}</dd>
    <dt>更新时间</dt><dd>${ticket.updated}</dd><dt>最后处理时间</dt><dd>${ticket.records.at(-1)?.time || "暂无"}</dd></dl>
    <h3>只读处理记录</h3>${recordHtml}<p class="muted">此处仅展示现有客服系统提供的合成记录，不提供处理操作。</p></section>`;
}

function renderCreate() {
  app.innerHTML = `<section class="panel narrow"><p class="route">/tickets/new · 演示身份：青禾店报修人员</p>
    <h2>新建报修</h2><p>标有 * 的内容必填。提交仅校验此页面，不会保存真实工单。</p>
    <form id="ticket-form" novalidate>
      <label>门店 *<select name="store_id" aria-describedby="error-store_id">${creatorStores.map(value => `<option value="${value}">${stores[value]}</option>`).join("")}</select><span class="error" id="error-store_id"></span></label>
      <label>报修人姓名 *<input name="reporter_name" maxlength="40" autocomplete="off" aria-describedby="error-reporter_name"><span class="error" id="error-reporter_name"></span></label>
      <label>联系手机号 *<input name="reporter_mobile" type="tel" inputmode="numeric" maxlength="11" autocomplete="off" aria-describedby="error-reporter_mobile"><span class="error" id="error-reporter_mobile"></span></label>
      <label>故障类别 *<select name="category" aria-describedby="error-category">${options(categoryOptions.map(value => [value, value]), "", "请选择类别")}</select><span class="error" id="error-category"></span></label>
      <label>问题摘要 *<input name="summary" maxlength="80" aria-describedby="error-summary"><span class="error" id="error-summary"></span></label>
      <label>问题描述 *<textarea name="description" rows="5" maxlength="1000" aria-describedby="error-description"></textarea><span class="error" id="error-description"></span></label>
      <button type="submit">校验报修内容（不保存）</button><p id="submit-note" role="status" aria-live="polite"></p>
    </form></section>`;
}

function validateCreate(data) {
  const errors = {};
  if (!creatorStores.includes(data.store_id)) errors.store_id = "请选择有报修权限的门店。";
  if (!data.reporter_name.trim() || data.reporter_name.trim().length > 40) errors.reporter_name = "请填写 1—40 字的报修人姓名。";
  if (!/^\d{11}$/.test(data.reporter_mobile.trim())) errors.reporter_mobile = "请填写 11 位数字手机号。";
  if (!categoryOptions.includes(data.category)) errors.category = "请选择故障类别。";
  if (!data.summary.trim() || data.summary.trim().length > 80) errors.summary = "请填写 1—80 字的问题摘要。";
  if (!data.description.trim() || data.description.trim().length > 1000) errors.description = "请填写 1—1000 字的问题描述。";
  return errors;
}

function renderRoute() {
  const route = window.location.hash.slice(1) || "/tickets/new";
  if (route === "/tickets/new") renderCreate();
  else if (route === "/tickets") renderList();
  else if (/^\/tickets\/[^/]+$/.test(route)) renderDetail(route.slice("/tickets/".length));
  else app.innerHTML = '<section class="panel"><h2>页面不存在</h2><a href="#/tickets">返回队列</a></section>';
}

document.addEventListener("submit", event => {
  if (!["filters", "ticket-form"].includes(event.target.id)) return;
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  if (event.target.id === "filters") {
    Object.assign(filters, { status: data.status, store: data.store, query: data.query, page: 1 });
    renderList();
    return;
  }
  const errors = validateCreate(data);
  for (const field of ["store_id", "reporter_name", "reporter_mobile", "category", "summary", "description"]) {
    document.getElementById(`error-${field}`).textContent = errors[field] || "";
    event.target.elements.namedItem(field).setAttribute("aria-invalid", errors[field] ? "true" : "false");
  }
  document.getElementById("submit-note").textContent = Object.keys(errors).length
    ? "请修正标出的内容。输入仍保留在当前表单。"
    : "本地校验通过。实际后端保存尚未实现：未创建工单、未生成编号、未发送事件。重复点击仍只校验。";
});

document.addEventListener("click", event => {
  const button = event.target.closest("button[data-action]");
  if (!button || button.disabled) return;
  if (button.dataset.action === "clear") Object.assign(filters, { status: "", store: "", query: "", page: 1 });
  if (button.dataset.action === "previous") filters.page = Math.max(1, filters.page - 1);
  if (button.dataset.action === "next") filters.page += 1;
  renderList();
});

window.addEventListener("hashchange", renderRoute);
renderRoute();
