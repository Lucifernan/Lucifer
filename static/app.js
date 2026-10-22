/* 学小助 前端逻辑 */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

async function api(path, opts = {}) {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error((await res.text().catch(() => '')) || res.status);
  return res.json();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* 把纯文本里的 URL 变成可点链接（输入须已 esc） */
function linkify(html) {
  return html.replace(/https?:\/\/[^\s<>"']+/g,
    (u) => `<a href="${u}" target="_blank" rel="noopener" class="chat-link">${u}</a>`);
}

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3000);
}

/* ---------------- 导航 ---------------- */
const renderers = {
  dashboard: loadDashboard, notices: loadNotices, files: loadFiles,
  chat: loadChatHistory, settings: loadSettings,
};
let current = 'dashboard';

function goto(page) {
  current = page;
  $$('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  $$('.page').forEach((p) => p.classList.toggle('active', p.id === 'page-' + page));
  (renderers[page] || (() => {}))();
}
$$('.nav-item').forEach((b) => b.addEventListener('click', () => goto(b.dataset.page)));
document.addEventListener('click', (e) => {
  const g = e.target.closest('[data-goto]');
  if (g) { e.preventDefault(); goto(g.dataset.goto); }
});

/* ---------------- 仪表盘 ---------------- */
function noticeRow(n) {
  const src = n.source === 'chaoxing'
    ? '<span class="tag cx">超星</span>'
    : '<span class="tag zhs">智慧树</span>';
  const kind = n.kind && n.kind !== 'notice' ? `<span class="tag hw">${esc(n.kind)}</span>` : '';
  const link = n.url
    ? `<a class="link-btn" href="${esc(n.url)}" target="_blank" rel="noopener" title="查看原文">
        <svg viewBox="0 0 24 24"><path d="M14 3h7v7h-2V6.4l-8.3 8.3-1.4-1.4L17.6 5H14V3zM5 5h5v2H6v11h11v-4h2v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" fill="currentColor"/></svg>
        查看原文</a>`
    : '';
  return `<div class="list-item notice-item clickable${n.is_read ? ' read' : ''}" data-id="${n.id}">
    ${n.is_read ? '' : '<div class="unread-dot"></div>'}
    <div class="body">
      <div class="title">${src}${kind}${esc(n.title)}</div>
      <div class="meta">${esc(n.published_at || n.fetched_at || '')}</div>
      <div class="notice-content">${esc(n.content || '')}</div>
      ${link}
    </div>
  </div>`;
}

/* 简报：每日 / 每周 */
let briefScope = 'today';
async function loadBriefing() {
  const box = $('#briefBox');
  const b = await api(`/briefing?scope=${briefScope}`).catch(() => null);
  if (!b) { box.innerHTML = '<div class="empty">简报生成失败</div>'; return; }
  box.innerHTML = `<div class="brief-title">${esc(b.title)}</div>`
    + (b.lines || []).map((l) => `<div class="brief-line">${linkify(esc(l))}</div>`).join('');
}
$$('.brief-tab').forEach((t) => t.addEventListener('click', () => {
  briefScope = t.dataset.scope;
  $$('.brief-tab').forEach((x) => x.classList.toggle('active', x === t));
  loadBriefing();
}));

async function loadDashboard() {
  const d = await api('/overview').catch(() => null);
  if (!d) return;
  $('#stUnread').textContent = d.unread;
  $('#stNotices').textContent = d.notices_total;
  $('#stCourses').textContent = d.courses_total;
  $('#stFiles').textContent = d.files_total;
  $('#badgeUnread').style.display = d.unread ? '' : 'none';
  $('#badgeUnread').textContent = d.unread;
  $('#dashSub').textContent = `今日新增通知 ${d.new_today ?? 0} 条 · 本周新增 ${d.new_week ?? 0} 条 · 数据截至最近一次同步`;

  $('#dashNotices').innerHTML = d.latest_notices.length
    ? d.latest_notices.map(noticeRow).join('')
    : '<div class="empty">暂无通知</div>';

  $('#weekCount').textContent = `本周 ${d.new_week ?? 0} 条`;
  $('#dashWeek').innerHTML = (d.week_notices || []).length
    ? d.week_notices.map(noticeRow).join('')
    : '<div class="empty">本周暂无通知</div>';

  loadBriefing();

  const logs = await api('/sync/log?limit=6').catch(() => []);
  $('#dashSync').innerHTML = logs.length
    ? logs.map((l) => `<div class="list-item"><div class="body">
        <div class="title">${esc(l.source)} · ${l.status === 'ok' ? '✓' : '⚠'} ${esc(l.detail || '')}</div>
        <div class="meta">${esc(l.created_at || '')}</div>
      </div></div>`).join('')
    : '<div class="empty">尚未同步</div>';
  renderSyncState(d.sync_state);
}

/* ---------------- 通知 ---------------- */
async function loadNotices() {
  const src = $('#filterSource').value;
  const unread = $('#filterUnread').checked ? 1 : 0;
  const rows = await api(`/notices?source=${src}&unread=${unread}`).catch(() => []);
  $('#noticeList').innerHTML = rows.length
    ? rows.map(noticeRow).join('')
    : '<div class="empty">暂无数据</div>';
}
$('#filterSource').addEventListener('change', loadNotices);
$('#filterUnread').addEventListener('change', loadNotices);
$('#btnReadAll').addEventListener('click', async () => {
  await api('/notices/read', { method: 'POST', body: { all: true } });
  toast('已全部标记为已读');
  const b = $('#badgeUnread');
  b.style.display = 'none';
  b.textContent = '0';
  loadNotices();
});
document.addEventListener('click', async (e) => {
  const item = e.target.closest('.notice-item');
  if (!item || e.target.closest('a')) return;
  item.classList.toggle('open');
  if (item.classList.contains('open') && !item.dataset.read) {
    item.dataset.read = '1';
    const dot = item.querySelector('.unread-dot');
    if (dot) dot.remove();
    await api('/notices/read', { method: 'POST', body: { ids: [Number(item.dataset.id)] } }).catch(() => {});
    const b = $('#badgeUnread');
    const n = Math.max(0, Number(b.textContent || 0) - 1);
    b.textContent = n;
    b.style.display = n ? '' : 'none';
  }
});

/* ---------------- 文件 ---------------- */
async function loadFiles() {
  const q = $('#fileSearch').value.trim();
  const rows = await api(`/files?q=${encodeURIComponent(q)}`).catch(() => []);
  $('#fileCount').textContent = `共 ${rows.length} 个文件`;
  $('#fileTable tbody').innerHTML = rows.length
    ? rows.map((f) => `<tr>
        <td>${esc(f.course_name || '-')}</td>
        <td>${esc(f.title)}</td>
        <td>${esc(f.file_type || '-')}</td>
        <td>${f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">打开</a>` : '-'}</td>
      </tr>`).join('')
    : '<tr><td colspan="4" class="empty">暂无数据</td></tr>';
}
let fileTimer;
$('#fileSearch').addEventListener('input', () => {
  clearTimeout(fileTimer);
  fileTimer = setTimeout(loadFiles, 300);
});

/* ---------------- 聊天 ---------------- */
/* 对话以内存数组为唯一数据源，统一 renderChat 重绘，
   避免历史加载与发送并发时 innerHTML 清空导致气泡丢失 */
const WELCOME = '你好，我是学小助！先在「设置」里填好 Cookie，然后点「立即同步」，就可以问我：\n「最近有什么新通知？」「我有哪些课程？」「有哪些课程文件？」';
let chatLog = []; // {role, text, pending?}

function renderChat() {
  const box = $('#chatMsgs');
  const list = chatLog.length ? chatLog : [{ role: 'assistant', text: WELCOME }];
  box.innerHTML = list.map((m) =>
    `<div class="msg ${m.role}"><div class="bubble">${linkify(esc(m.text))}</div></div>`).join('');
  box.scrollTop = box.scrollHeight;
}

async function loadChatHistory() {
  const rows = await api('/chat/history').catch(() => []);
  // 保留发送中（pending）的气泡，避免在途请求响应被清掉
  const pending = chatLog.filter(
    (m) => m.pending && !rows.some((r) => r.role === m.role && r.content === m.text),
  );
  chatLog = rows.map((r) => ({ role: r.role, text: r.content })).concat(pending);
  renderChat();
}

let sending = false;
async function sendChat(text) {
  text = (text || '').trim();
  if (!text || sending) return;
  $('#chatInput').value = '';
  sending = true;
  const userMsg = { role: 'user', text, pending: true };
  const botMsg = { role: 'assistant', text: '思考中…', pending: true };
  chatLog.push(userMsg, botMsg);
  renderChat();
  try {
    const d = await api('/chat', { method: 'POST', body: { message: text } });
    botMsg.text = d.reply;
  } catch (e) {
    botMsg.text = '发送失败：' + e.message;
  }
  userMsg.pending = false;
  botMsg.pending = false;
  sending = false;
  renderChat();
}
$('#btnSend').addEventListener('click', () => sendChat($('#chatInput').value));
$('#chatInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat($('#chatInput').value); });
$$('.chip').forEach((c) => c.addEventListener('click', () => sendChat(c.textContent)));
$('#btnClearChat').addEventListener('click', async () => {
  await api('/chat/history', { method: 'DELETE' });
  toast('对话已清空');
  loadChatHistory();
});

/* ---------------- 设置 ---------------- */
const FIELDS = {
  setChxCookie: 'chaoxing_cookie', setChxInteraction: 'chaoxing_interaction',
  setChxFiles: 'chaoxing_fetch_files',
  setZhsCookie: 'zhihuishu_cookie', setZhsMessageUrl: 'zhihuishu_message_url',
  setInterval: 'sync_interval_minutes', setDigest: 'daily_digest_time',
  setNtNotice: 'notify_new_notice', setNtDigest: 'notify_digest',
  setNtWeekly: 'notify_weekly',
};

async function loadSettings() {
  const cfg = await api('/settings').catch(() => ({}));
  Object.entries(FIELDS).forEach(([id, key]) => {
    const el = $('#' + id);
    if (!el) return;
    if (el.type === 'checkbox') el.checked = !!cfg[key];
    else el.value = cfg[key] ?? '';
  });
}

$('#btnSave').addEventListener('click', async () => {
  const patch = {};
  Object.entries(FIELDS).forEach(([id, key]) => {
    const el = $('#' + id);
    if (!el) return;
    patch[key] = el.type === 'checkbox' ? el.checked
      : (el.type === 'number' ? Number(el.value) : el.value);
  });
  await api('/settings', { method: 'POST', body: patch }).catch((e) => {
    $('#saveTip').textContent = '保存失败: ' + e.message;
  });
  $('#saveTip').textContent = '已保存 ' + new Date().toLocaleTimeString();
  toast('设置已保存');
});

const PING_EL = { chaoxing: '#pingCx', zhihuishu: '#pingZhs' };
$$('[data-ping]').forEach((b) => b.addEventListener('click', async () => {
  const el = $(PING_EL[b.dataset.ping] || '#pingCx');
  el.textContent = '测试中…';
  const d = await api('/ping', { method: 'POST', body: { site: b.dataset.ping } }).catch((e) => ({ ok: false, error: e.message }));
  el.textContent = d.ok ? '连接正常 ✓ ' + (d.url || '') : '失败：' + (d.error || JSON.stringify(d));
}));

$('#btnTestNotify').addEventListener('click', async () => {
  const d = await api('/test/notify', { method: 'POST', body: {} }).catch((e) => ({ ok: false }));
  toast(d.ok ? '测试提醒已发送' : '发送失败（通知组件不可用）');
});

/* 一键获取超星 Cookie：账号密码 → 系统自动登录保存 */
$('#btnChxLogin').addEventListener('click', async () => {
  const tip = $('#chxLoginTip');
  const user = $('#chxUser').value.trim();
  const pwd = $('#chxPwd').value;
  if (!user || !pwd) { tip.textContent = '请先填写超星账号和密码'; return; }
  const btn = $('#btnChxLogin');
  btn.disabled = true;
  tip.textContent = '正在登录超星并获取 Cookie，请稍候…';
  const d = await api('/chaoxing/login', { method: 'POST', body: { username: user, password: pwd } })
    .catch((e) => ({ ok: false, error: e.message }));
  btn.disabled = false;
  if (d.ok) {
    tip.textContent = '获取成功！Cookie 已自动保存 ✓ 现在可以点「立即同步」了。';
    $('#setChxCookie').value = d.cookie || '';
    $('#chxPwd').value = '';
    toast('超星 Cookie 获取成功');
  } else {
    tip.textContent = '自动登录失败：' + (d.error || '未知原因') + '。可改用下方手动方式复制 Cookie。';
  }
});

/* ---------------- 同步 ---------------- */
function renderSyncState(st) {
  if (!st) return;
  if (st.running) $('#syncStatus').textContent = '正在同步…';
  else if (st.last) {
    const parts = [];
    Object.entries(st.last).forEach(([k, v]) => {
      if (!v || typeof v !== 'object' || Array.isArray(v)) return;
      Object.entries(v).forEach(([k2, n]) => { if (n) parts.push(`${k2}+${n}`); });
    });
    const err = (st.last.errors || []).join('; ');
    $('#syncStatus').textContent = (parts.length ? '新增: ' + parts.join(' ') : '无新增') + (err ? ' ⚠ ' + err : '');
  }
}

async function doSync() {
  const btn = $('#btnSync');
  btn.disabled = true;
  const d = await api('/sync', { method: 'POST', body: {} }).catch((e) => ({ started: false, reason: e.message }));
  if (!d.started) { toast(d.reason || '同步失败'); btn.disabled = false; return; }
  $('#syncStatus').textContent = '正在同步…';
  const timer = setInterval(async () => {
    const st = await api('/sync/status').catch(() => null);
    if (!st) return;
    renderSyncState(st);
    if (!st.running) {
      clearInterval(timer);
      btn.disabled = false;
      toast('同步完成');
      (renderers[current] || (() => {}))();
    }
  }, 2000);
}
$('#btnSync').addEventListener('click', doSync);

/* ---------------- 启动 ---------------- */
loadDashboard();
loadSettings();
