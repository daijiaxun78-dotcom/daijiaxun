const columns = [
  ['index_key', '跟踪指数'], ['name', '基金份额'], ['code', '基金代码'], ['share_class', '类别'],
  ['ytd', '今年以来'], ['displayDate', '数据截止'], ['asset_size_billion', '规模（亿元）'],
  ['snapshot_fee', '综合费率'], ['inception_date', '成立日期'], ['limitAmount', '当前限额'], ['purchase_status', '申购状态'],
  ['manager', '基金公司'],
];

const state = { funds: [], sortKey: 'ytd', sortDirection: -1 };
const money = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function limitAmount(fund) {
  return fund.limit?.limit_amount ?? null;
}

function operatingFee(fund) {
  if ([fund.management_fee, fund.custody_fee, fund.service_fee].every(v => v == null)) return fund.snapshot_fee;
  return (fund.management_fee || 0) + (fund.custody_fee || 0) + (fund.service_fee || 0);
}

function effectiveStatus(fund) {
  if (['暂停', '暂停申购'].includes(fund.limit?.status)) return '暂停申购';
  if (fund.limit?.status === '有限额') return '限制';
  if (fund.limit?.status === '开放') return '开放申购';
  return fund.purchase_status || '待核验';
}

function filteredFunds() {
  const query = document.querySelector('#searchInput').value.trim().toLowerCase();
  const index = document.querySelector('#indexFilter').value;
  const shareClass = document.querySelector('#classFilter').value;
  const status = document.querySelector('#statusFilter').value;
  return state.funds.filter(fund => {
    const haystack = `${fund.name} ${fund.code} ${fund.manager}`.toLowerCase();
    return (!query || haystack.includes(query)) && (!index || fund.index_key === index) &&
      (!shareClass || fund.share_class === shareClass) && (!status || effectiveStatus(fund) === status);
  }).sort((a, b) => {
    const av = state.sortKey === 'limitAmount' ? limitAmount(a) : state.sortKey === 'displayDate' ? (a.nav_date || a.snapshot_date) : a[state.sortKey];
    const bv = state.sortKey === 'limitAmount' ? limitAmount(b) : state.sortKey === 'displayDate' ? (b.nav_date || b.snapshot_date) : b[state.sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return (typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv), 'zh-CN')) * state.sortDirection;
  });
}

function renderHead() {
  document.querySelector('#tableHead').innerHTML = columns.map(([key, label]) =>
    `<th><button data-sort="${key}">${label}<span>${state.sortKey === key ? (state.sortDirection === 1 ? '↑' : '↓') : '↕'}</span></button></th>`
  ).join('') + '<th>依据</th>';
}

function statusBadge(status) {
  const tone = status === '开放申购' ? 'open' : status === '待核验' ? 'unknown' : 'limited';
  return `<span class="badge ${tone}">${escapeHtml(status)}</span>`;
}

function render() {
  renderHead();
  const funds = filteredFunds();
  document.querySelector('#fundRows').innerHTML = funds.map(fund => {
    const ytd = fund.ytd == null ? '—' : `${fund.ytd >= 0 ? '+' : ''}${fund.ytd.toFixed(2)}%`;
    const limit = fund.limit;
    const limitText = !limit ? '—' : ['暂停', '暂停申购'].includes(limit.status) ? '暂停' : limit.limit_amount == null ? limit.status : `¥${money.format(limit.limit_amount)}`;
    const channelNote = fund.channel_limit && fund.official_limit
      ? `<small>天天基金：${escapeHtml(fund.channel_limit.status)}${fund.channel_limit.limit_amount == null ? '' : ` ¥${money.format(fund.channel_limit.limit_amount)}`}</small>`
      : limit ? `<small>${escapeHtml(limit.channel)}</small>` : '';
    const size = fund.asset_size_billion == null ? '—' : money.format(fund.asset_size_billion);
    const dataDate = fund.nav_date || fund.snapshot_date || '—';
    const quality = fund.ytd_source || '待更新';
    const evidence = limit?.confidence === 'channel_live' ? '天天基金渠道' : limit?.confidence === 'verified' ? '官方核验' : limit ? '快照待核验' : '待核验';
    const fee = operatingFee(fund);
    return `<tr>
      <td><span class="index-tag">${escapeHtml(fund.index_key)}</span></td>
      <td class="name"><button class="link-button" data-detail="${fund.code}">${escapeHtml(fund.name)}</button><small>${escapeHtml(fund.currency)}</small></td>
      <td class="mono">${fund.code}</td><td>${fund.share_class}</td>
      <td class="number ${fund.ytd == null ? '' : (fund.ytd >= 0 ? 'positive' : 'negative')}">${ytd}<small>${quality}</small></td>
      <td>${dataDate}${fund.ytd_base_date ? `<small>基准 ${fund.ytd_base_date}</small>` : ''}</td>
      <td class="number">${size}${fund.asset_size_date ? `<small>${fund.asset_size_date}</small>` : ''}</td>
      <td class="number">${fee == null ? '—' : fee.toFixed(2) + '%'}<small>${fund.management_fee == null ? '公开快照' : '管理+托管+销售服务'}</small></td>
      <td>${fund.inception_date || '—'}</td><td class="number">${limitText}${channelNote}</td>
      <td>${statusBadge(effectiveStatus(fund))}</td><td>${escapeHtml(fund.manager)}</td>
      <td>${limit ? `<a class="evidence ${limit.confidence === 'verified' ? 'verified' : ''}" href="${escapeHtml(limit.announcement_url)}" target="_blank" rel="noreferrer">${evidence} ↗</a>` : '<span class="muted">待补公告</span>'}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="13" class="empty">没有符合筛选条件的基金</td></tr>';
  document.querySelector('#rowCount').textContent = `显示 ${funds.length} / ${state.funds.length} 条`;
  document.querySelector('#fundCount').textContent = state.funds.length;
  document.querySelector('#limitedCount').textContent = state.funds.filter(f => ['限制', '暂停申购'].includes(effectiveStatus(f))).length;
  document.querySelector('#verifiedCount').textContent = state.funds.filter(f => f.limit?.confidence === 'verified').length;
  document.querySelector('#latestDate').textContent = state.funds.map(f => f.nav_date || f.snapshot_date).filter(Boolean).sort().at(-1) || '尚未更新';
}

async function loadFunds() {
  const response = await fetch('./data.json', { cache: 'no-store' });
  if (!response.ok) throw new Error(`数据文件返回 ${response.status}`);
  const payload = await response.json();
  state.funds = payload.funds;
  state.limits = payload.limits || {};
  document.querySelector('#updatedAt').textContent = `页面更新 ${new Date(payload.as_of).toLocaleString('zh-CN')}`;
  const indices = [...new Set(state.funds.map(f => f.index_key))];
  document.querySelector('#indexFilter').innerHTML = '<option value="">全部指数</option>' + indices.map(v => `<option>${v}</option>`).join('');
  render();
}

async function showDetail(code) {
  const fund = state.funds.find(f => f.code === code);
  const limits = state.limits[code] || [];
  const dialog = document.querySelector('#detailDialog');
  document.querySelector('#detailContent').innerHTML = `<div class="dialog-title"><div><p class="eyebrow">${fund.code}</p><h2>${escapeHtml(fund.name)}</h2></div><button class="icon" onclick="this.closest('dialog').close()">×</button></div>
    <dl class="detail-grid"><div><dt>指数</dt><dd>${fund.index_key}</dd></div><div><dt>份额类别</dt><dd>${fund.share_class}</dd></div><div><dt>管理费</dt><dd>${fund.management_fee == null ? '待补' : fund.management_fee + '%'}</dd></div><div><dt>托管费</dt><dd>${fund.custody_fee == null ? '待补' : fund.custody_fee + '%'}</dd></div><div><dt>销售服务费</dt><dd>${fund.service_fee == null ? '待补' : fund.service_fee + '%'}</dd></div><div><dt>最近净值</dt><dd>${fund.latest_nav ?? '待更新'} · ${fund.nav_date ?? '—'}</dd></div></dl>
    <h3>限额历史</h3>${limits.length ? `<div class="history">${limits.map(l => `<article><div><strong>${escapeHtml(l.status)}${l.limit_amount == null ? '' : ` · ¥${money.format(l.limit_amount)}`}</strong><span>${l.effective_from} 起 · ${escapeHtml(l.channel)} · ${escapeHtml(l.business_type)}</span></div><a href="${escapeHtml(l.announcement_url)}" target="_blank">查看公告 ↗</a><p>${escapeHtml(l.notes || l.announcement_title)}</p></article>`).join('')}</div>` : '<p class="empty">尚未登记精确的官方限额公告。</p>'}`;
  dialog.showModal();
}

document.addEventListener('click', event => {
  const sort = event.target.closest('[data-sort]');
  if (sort) {
    const key = sort.dataset.sort;
    if (state.sortKey === key) state.sortDirection *= -1;
    else { state.sortKey = key; state.sortDirection = 1; }
    render();
  }
  const detail = event.target.closest('[data-detail]');
  if (detail) showDetail(detail.dataset.detail);
  if (event.target.matches('[data-close]')) event.target.closest('dialog').close();
});

['searchInput','indexFilter','classFilter','statusFilter'].forEach(id => document.querySelector(`#${id}`).addEventListener('input', render));
document.querySelector('#costBtn').addEventListener('click', () => document.querySelector('#costDialog').showModal());
document.querySelector('#costForm').addEventListener('submit', async event => {
  event.preventDefault();
  const v = Object.fromEntries(new FormData(event.target));
  const calculate = (purchase, redemption, service, product) => {
    const amount = Number(v.amount), days = Number(v.days);
    const investor_paid_cost = amount * (Number(purchase) + Number(redemption)) / 100;
    const annual_product_cost = amount * (Number(service) + Number(product)) / 100 * days / 365;
    return { investor_paid_cost, estimated_total_cost: investor_paid_cost + annual_product_cost };
  };
  const a = calculate(v.a_purchase, v.a_redemption, v.a_service, v.a_product);
  const c = calculate(v.c_purchase, v.c_redemption, v.c_service, v.c_product);
  const winner = a.estimated_total_cost <= c.estimated_total_cost ? 'A 类' : 'C 类';
  document.querySelector('#costResult').innerHTML = `<article><span>A 类预计总成本</span><strong>¥${money.format(a.estimated_total_cost)}</strong><small>其中另行支付 ¥${money.format(a.investor_paid_cost)}</small></article><article><span>C 类预计总成本</span><strong>¥${money.format(c.estimated_total_cost)}</strong><small>其中另行支付 ¥${money.format(c.investor_paid_cost)}</small></article><p>按当前输入，<b>${winner}</b>成本较低。计算未考虑净值波动，年费仅按本金和持有天数近似。</p>`;
});

loadFunds().catch(error => {
  document.querySelector('#notice').hidden = false;
  document.querySelector('#notice').textContent = `载入失败：${error.message}`;
});
