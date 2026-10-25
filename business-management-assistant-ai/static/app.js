(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const KEY = 'bma.apiKey';
  let conversationId = null;
  let me = null;

  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === 'class') node.className = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) node.setAttribute(k, v === true ? '' : v);
    }
    for (const child of children.flat()) if (child != null) node.append(child.nodeType ? child : document.createTextNode(String(child)));
    return node;
  }
  const fill = (node, ...children) => { node.replaceChildren(...children.flat()); };
  const empty = (text) => el('li', { class: 'empty' }, text);
  const date = (iso) => (iso ? iso.slice(0, 10) : '—');

  async function api(path, options = {}) {
    const headers = { 'content-type': 'application/json', ...(options.headers || {}) };
    const key = sessionStorage.getItem(KEY);
    if (key) headers['x-api-key'] = key;
    const response = await fetch(path, { ...options, headers });
    if (response.status === 401) { showAuth(); throw new Error('Authentication required'); }
    const body = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw new Error(body?.error?.message || (typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status})`));
    return body;
  }
  const post = (path, data) => api(path, { method: 'POST', body: JSON.stringify(data || {}) });
  const patch = (path, data) => api(path, { method: 'PATCH', body: JSON.stringify(data) });

  function showAuth(message) { $('auth-panel').hidden = false; $('auth-error').textContent = message || ''; }
  $('auth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    sessionStorage.setItem(KEY, $('api-key').value.trim());
    $('api-key').value = '';
    try { await boot(); $('auth-panel').hidden = true; } catch (err) { showAuth(err.message); }
  });

  function toast(message) { $('mode-text').textContent = message; setTimeout(() => { $('mode-text').textContent = me ? `${me.mode} mode` : ''; }, 4000); }
  const guard = (fn) => async (...args) => { try { await fn(...args); } catch (err) { toast(err.message); } };

  // ---------------------------------------------------------------- briefing
  async function loadBriefing() {
    const b = await api('/api/briefing');
    $('mode-text').textContent = `${b.mode} mode`;
    const metric = (label, value, cls) => el('div', { class: `metric ${cls || ''}` }, el('b', {}, value), el('span', {}, label));
    fill($('metrics'),
      metric('Open tasks', b.open_tasks), metric('Overdue', b.overdue_tasks, b.overdue_tasks ? 'bad' : ''),
      metric('Blocked', b.blocked_tasks, b.blocked_tasks ? 'warn' : ''), metric('Approvals waiting', b.pending_approvals, b.pending_approvals ? 'warn' : ''),
      metric('Goals', b.goals), metric('Projects', b.projects));
    fill($('attention'), b.attention.length
      ? b.attention.map((a) => el('li', { class: `sev-${a.severity}` }, a.message))
      : [empty('Nothing needs attention.')]);
    fill($('next-actions'), b.next_actions.length
      ? b.next_actions.map((a) => el('li', {},
        el('span', {}, a.title, el('div', { class: 'sub' }, a.reason)),
        el('button', { class: 'ghost', onclick: guard(async () => { await post(`/api/tasks/${a.id}/complete`); await refresh(); }) }, 'Done')))
      : [empty('No open tasks. Add one under Work.')]);
    fill($('goals'), b.goal_progress.length
      ? b.goal_progress.map((g) => el('li', {},
        el('span', {}, g.title, el('div', { class: 'sub' }, `${g.status}${g.target_date ? `, target ${date(g.target_date)}` : ''}${g.at_risk ? ', at risk' : ''}`)),
        el('div', { class: 'bar', title: g.progress == null ? 'No linked tasks' : `${Math.round(g.progress * 100)}% of linked tasks done` }, el('i', { style: `width:${Math.round((g.progress || 0) * 100)}%` }))))
      : [empty('No goals yet. Type "create goal: ..." in the assistant.')]);
    const nav = $('nav-approvals');
    nav.hidden = !b.pending_approvals;
    nav.textContent = b.pending_approvals;
  }

  // ---------------------------------------------------------------- approvals
  function approvalCard(a) {
    const canReview = me && me.role === 'admin';
    const run = (path, data, method) => guard(async () => { await post(path, data); await refresh(); });
    const buttons = [];
    const editor = el('textarea', { rows: 6, 'aria-label': 'Payload JSON', hidden: true, class: 'editor' }, JSON.stringify(a.payload, null, 2));
    if (canReview && a.status === 'pending') {
      buttons.push(el('button', { class: 'ok', onclick: run(`/api/approvals/${a.id}/decision`, { decision: 'approved' }) }, 'Approve'));
      buttons.push(el('button', { class: 'ok', onclick: run(`/api/approvals/${a.id}/decision`, { decision: 'approved', execute: true }) }, 'Approve and run'));
      buttons.push(el('button', { class: 'danger', onclick: run(`/api/approvals/${a.id}/decision`, { decision: 'rejected' }) }, 'Reject'));
      buttons.push(el('button', { class: 'ghost', onclick: () => { editor.hidden = !editor.hidden; save.hidden = editor.hidden; } }, 'Edit payload'));
    } else if (canReview && a.status === 'approved') {
      buttons.push(el('button', { class: 'ok', onclick: run(`/api/approvals/${a.id}/execute`) }, 'Run now'));
    } else if (canReview && a.status === 'failed' && a.result && a.result.retryable) {
      buttons.push(el('button', { class: 'ok', onclick: run(`/api/approvals/${a.id}/retry?execute=true`) }, 'Retry (nothing was done)'));
    }
    const save = el('button', { class: 'ok', hidden: true, onclick: guard(async () => {
      let payload;
      try { payload = JSON.parse(editor.value); } catch { throw new Error('Payload is not valid JSON'); }
      await post(`/api/approvals/${a.id}/amend`, { payload });
      await refresh();
    }) }, 'Save changes');
    const outcome = a.result && a.result.detail ? `${a.result.dry_run ? 'Dry run: ' : ''}${a.result.detail}` : null;
    return el('article', { class: `card risk-${a.risk}` },
      el('header', {}, el('h3', {}, `${a.action_type} to ${a.target}`), el('span', {}, el('span', { class: `tag ${a.risk}` }, `${a.risk} risk`), ' ', el('span', { class: 'tag' }, a.status))),
      el('div', { class: 'sub' }, a.reason),
      el('pre', {}, JSON.stringify(a.payload, null, 2)),
      editor,
      el('div', { class: 'sub' }, a.policy_reasons.join('; ')),
      outcome ? el('div', { class: a.status === 'failed' ? 'error' : 'sub' }, outcome) : null,
      el('div', { class: 'actions' }, buttons, save));
  }
  async function loadApprovals() {
    const [waiting, approved, failed] = await Promise.all([
      api('/api/approvals?status=pending&limit=50'), api('/api/approvals?status=approved&limit=20'), api('/api/approvals?status=failed&limit=10')]);
    const all = [...waiting, ...approved, ...failed];
    fill($('approval-list'), all.length ? all.map(approvalCard) : [el('p', { class: 'sub' }, 'No requests waiting. Anything that sends, publishes, pays, signs, deletes or launches will appear here.')]);
    $('approvals-hint').textContent = me && me.role !== 'admin' ? 'You can view requests; an admin must approve them.' : 'Each card shows the exact payload that would be sent. Edit it before approving if it is incomplete.';
  }

  // ---------------------------------------------------------------- work
  async function loadTasks() {
    const tasks = await api('/api/tasks?limit=100');
    const body = $('tasks').tBodies[0];
    const writable = me && me.role !== 'viewer';
    fill(body, tasks.length ? tasks.map((t) => {
      const select = el('select', { 'aria-label': `Status of ${t.title}`, disabled: !writable, onchange: guard(async (e) => { await patch(`/api/tasks/${t.id}`, { status: e.target.value }); await refresh(); }) },
        ['planned', 'active', 'blocked', 'done'].map((s) => el('option', { value: s, selected: s === t.status }, s)));
      return el('tr', {}, el('td', { class: t.status === 'done' ? 'done' : '' }, t.title), el('td', {}, t.priority), el('td', {}, date(t.due_at)), el('td', {}, select));
    }) : [el('tr', {}, el('td', { colspan: 4, class: 'sub' }, 'No tasks yet.'))]);
  }
  $('task-form').addEventListener('submit', guard(async (e) => {
    e.preventDefault();
    const due = $('task-due').value;
    await post('/api/tasks', { title: $('task-title').value, priority: $('task-priority').value, due_at: due ? `${due}T23:59:00Z` : null });
    $('task-title').value = ''; $('task-due').value = '';
    await refresh();
  }));

  // ---------------------------------------------------------------- assistant
  function say(role, text, via) {
    const log = $('chat-log');
    log.append(el('p', { class: `msg ${role}` }, el('small', {}, role === 'user' ? 'You' : (via === 'llm' ? 'Assistant (model-planned)' : 'Assistant')), text));
    log.scrollTop = log.scrollHeight;
  }
  function chips(items) {
    fill($('chips'), (items || []).map((s) => el('button', { type: 'button', onclick: () => { $('chat-input').value = s; $('chat-input').focus(); } }, s)));
  }
  $('chat-form').addEventListener('submit', guard(async (e) => {
    e.preventDefault();
    const input = $('chat-input');
    const text = input.value;
    input.value = '';
    say('user', text);
    const r = await post('/api/chat', { conversation_id: conversationId, message: text });
    conversationId = r.conversation_id;
    say('assistant', r.message, r.via);
    chips(r.suggestions);
    await refresh();
  }));

  // ---------------------------------------------------------------- audit
  async function loadAudit() {
    if (!me || me.role !== 'admin') return;
    const events = await api('/api/audit?limit=15');
    fill($('audit-list'), events.length ? events.map((e) => el('li', {}, el('span', {}, `${e.ts.slice(0, 19)}Z ${e.event_type}`), el('span', { class: 'sub' }, `${e.actor} ${String(e.target).slice(0, 8)}`))) : [empty('No events yet.')]);
  }
  $('verify').addEventListener('click', guard(async () => {
    const r = await api('/api/audit/verify');
    $('verify-result').textContent = r.ok ? `Chain intact (${r.checked} entries).` : `Broken at entry ${r.first_bad_id}: ${r.reason}`;
    $('verify-result').style.color = r.ok ? 'var(--ok)' : 'var(--red)';
  }));

  // ---------------------------------------------------------------- boot
  async function loadModels() {
    try {
      const r = await api('/api/ai/models');
      const live = r.models.filter((m) => m.model && m.available);
      $('models-line').textContent = !r.enabled ? 'Model assistance is off (rules only).'
        : live.length ? `${live.length} model${live.length === 1 ? '' : 's'} available: ${live.slice(0, 4).map((m) => m.model).join(', ')}${live.length > 4 ? ', ...' : ''}`
        : 'No model is reachable right now; built-in commands are used.';
    } catch { $('models-line').textContent = ''; }
  }
  async function refresh() { await Promise.all([loadBriefing(), loadApprovals(), loadTasks(), loadAudit()]); }
  async function boot() {
    me = await api('/api/me');
    $('who').textContent = `${me.name} (${me.role})${me.open_mode ? ', open mode' : ''}\nassistant: ${me.assistant_mode}`;
    document.querySelectorAll('[data-admin]').forEach((n) => { n.hidden = me.role !== 'admin'; });
    chips(['brief me', 'create task: ', 'list tasks', 'help']);
    await refresh();
    loadModels();
    me.mode = (await fetch('/health').then((r) => r.json())).environment;
    $('mode-text').textContent = `${me.mode} mode`;
    if (me.mode !== 'sandbox') document.querySelectorAll('[data-docs]').forEach((n) => { n.hidden = true; });
  }
  const links = [...document.querySelectorAll('nav a[href^="#"]')];
  addEventListener('hashchange', () => links.forEach((a) => a.classList.toggle('active', a.getAttribute('href') === location.hash)));
  boot().catch((err) => { if (err.message !== 'Authentication required') showAuth(err.message); });
})();
