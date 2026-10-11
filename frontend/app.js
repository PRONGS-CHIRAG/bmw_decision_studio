/* Requirements Cockpit - ask a question, watch the agent reason, decide. No page scroll anywhere. */
'use strict';

const STAGES = [
  { id: 'question', label: 'Question' }, { id: 'clarify', label: 'Clarify' }, { id: 'filter', label: 'Filter' },
  { id: 'read', label: 'AI reads' }, { id: 'compute', label: 'Compute' }, { id: 'decide', label: 'Decide' },
  { id: 'recommend', label: 'Recommend' },
];
const AGENTS = {
  system: { label: 'System', glyph: '·', bg: 'var(--surface-2)', fg: 'var(--text-2)' },
  parser: { label: 'Inquiry parser', glyph: '◆', bg: 'var(--accent-soft)', fg: 'var(--accent)' },
  clarify: { label: 'Clarification', glyph: '?', bg: 'var(--warning-soft)', fg: 'var(--warning)' },
  you: { label: 'You', glyph: '✓', bg: 'var(--success-soft)', fg: 'var(--success)' },
  filter: { label: 'Data filter', glyph: '▤', bg: 'var(--info-soft)', fg: 'var(--info)' },
  model: { label: 'Review model', glyph: '◎', bg: '#f5f3ff', fg: '#7c3aed' },
  compute: { label: 'Calculator', glyph: 'Σ', bg: 'var(--surface-2)', fg: 'var(--text-2)' },
  decide: { label: 'Decision rules', glyph: '⚖', bg: 'var(--warning-soft)', fg: 'var(--warning)' },
  recommend: { label: 'Recommendation', glyph: '★', bg: 'var(--success-soft)', fg: 'var(--success)' },
};
const EXAMPLES = [
  'Should the 5 Series get ventilated seats in China?',
  'Is a heated steering wheel worth it for the 1 Series?',
  'What do 7 Series owners complain about on the touchscreen?',
  'How many cars do we lose if the 7 Series has no massage seats in the US?',
  'Which markets want a panoramic roof on the 5 Series?',
  'What do people complain about?',
];
const SIG_COLOR = { praise: 'var(--s-praise)', defect: 'var(--s-complaint)', usability: 'var(--s-complaint)', request: 'var(--s-request)' };
const SIG_LABEL = { praise: 'praise', defect: 'defect', usability: 'hard to use', request: 'request' };
const FACTORS = ['customer_signal', 'market_reach', 'survey_gap', 'competitive', 'feasibility'];
const FACTOR_LABEL = { customer_signal: 'Customer signal', market_reach: 'Market reach', survey_gap: 'Survey agrees', competitive: 'Competitive', feasibility: 'Feasibility' };
const FACTOR_COLOR = { customer_signal: '#2f6fed', market_reach: '#0284c7', survey_gap: '#7c3aed', competitive: '#d97706', feasibility: '#059669' };
const tierTone = (t) => (t === 'P1' ? 'tone-danger' : t === 'P2' ? 'tone-warning' : 'tone-neutral');
const app = { meta: null, card: null, view: 'decision', metadataError: null };
const ask = { run: 0, text: '', overrides: {}, parsed: null, result: null, status: {}, viewing: null, t0: 0, count: 0, seen: new Set(), clarified: false, busy: false };

/* ================================================================ boot */
async function boot() {
  setupTooltips();
  const actor = $('#actor');
  actor.value = store.get('actor', '');
  actor.addEventListener('input', () => store.set('actor', actor.value.trim()));
  $$('.nav [data-view]').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));
  window.DecisionWorkspace.init();
  const q = new URLSearchParams(location.search);
  showView(q.get('view') || (q.get('q') ? 'ask' : 'decision'));
  try {
    [app.meta, app.card] = await Promise.all([api('/api/meta'), api('/api/model').catch(() => null)]);
  } catch (e) { app.metadataError = e.message; $('#hero').innerHTML = `<div class="pending" role="alert"><span>${esc(e.message)}</span></div>`; if (['reqs', 'model'].includes(app.view)) showView(app.view); return; }
  renderHero();
  if (['reqs', 'model'].includes(app.view)) showView(app.view);
  if (q.get('q')) startAsk(q.get('q'));
}

function showView(v) {
  if (!['decision', 'ask', 'reqs', 'model'].includes(v)) v = 'decision';
  if (app.view === 'ask' && v !== 'ask' && ask.busy) resetAsk();
  app.view = v;
  $$('.nav [data-view]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.view === v)));
  $$('#app > .view').forEach((s) => { s.hidden = s.id !== `view-${v}`; });
  window.DecisionWorkspace.setActive(v === 'decision');
  if (['reqs', 'model'].includes(v) && !app.meta) {
    $(`#view-${v}`).innerHTML = app.metadataError ? `<div class="pending" role="alert">${esc(app.metadataError)}</div>` : pending('Loading source metadata', 'This view will open when source metadata is available.');
    return;
  }
  if (v === 'reqs') renderReqs();
  if (v === 'model') renderModel();
}

function toast(msg, ms = 3200) {
  const t = $('#toast');
  t.textContent = msg; t.hidden = false;
  t.style.animation = 'none'; void t.offsetWidth; t.style.animation = '';
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, ms);
}
function actorOrAsk() {
  const a = $('#actor').value.trim();
  if (!a) { toast('Add your name (top right) - decisions are recorded with who made them.'); $('#actor').focus(); }
  return a;
}
function fitRows(el, rowH, min = 3) { return Math.max(min, Math.floor((el.clientHeight - 12) / rowH)); }
function pending(label, detail) {
  return `<div class="pending reveal"><span class="spinner"></span><div><div style="font-weight:600">${esc(label)}</div><div class="faint small">${esc(detail)}</div></div></div>`;
}

/* ================================================================ hero */
function renderHero() {
  const c = app.card;
  const reviews = app.meta.manifest.rows.verbatims;
  $('#hero').innerHTML = `
    <span class="kicker reveal">Customer-evidence requirements · BMW</span>
    <h1 class="reveal reveal-1">Ask the customers.</h1>
    <p class="sub reveal reveal-2">Ask about a feature in plain English. The agent checks what is missing, filters ${fmt(reviews)} reviews, lets a trained review model read them, and shows every calculation behind the recommendation.</p>
    <form class="askbox reveal reveal-3" id="askform">
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18" style="color:var(--accent);flex:none"><rect x="1" y="1" width="9" height="9" stroke="currentColor" stroke-width="1.4" fill="none"/><rect x="8" y="8" width="9" height="9" fill="currentColor"/></svg>
      <textarea id="askq" rows="1" placeholder="e.g. Should the 5 Series get ventilated seats in China?" aria-label="Your question"></textarea>
      <button class="send" type="submit" aria-label="Ask">${icon('right', 18)}</button>
    </form>
    <div class="quick reveal reveal-4">${EXAMPLES.map((x) => `<button type="button" data-q="${esc(x)}">${esc(x)}</button>`).join('')}</div>
    <p class="faint small reveal reveal-5" style="margin-top:14px"><span class="kbd">Enter</span> to ask</p>
    <div class="hero-meta reveal reveal-5">
      <span>${fmt(reviews)} reviews · 3 vehicles · 4 markets</span><span class="sep"></span>
      <span style="color:var(--accent);font-weight:600">Trained review model, no LLM</span><span class="sep"></span>
      <span>${c ? `${c.hierarchy.categories} categories · ${c.hierarchy.components} components · ${c.hierarchy.issues} issue types` : ''}</span><span class="sep"></span>
      <span class="key"><span class="live-dot"></span>${c ? `${pct(c.metrics.component.top1_accuracy)} component accuracy on unseen reviews` : 'model not trained'}</span>
    </div>`;
  const ta = $('#askq');
  ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#askform').requestSubmit(); } });
  $('#askform').addEventListener('submit', (e) => { e.preventDefault(); if (ta.value.trim()) startAsk(ta.value.trim()); });
  $$('.quick [data-q]').forEach((b) => b.addEventListener('click', () => { ta.value = b.dataset.q; ta.focus(); }));
  setTimeout(() => ta.focus(), 50);
}

/* ================================================================ inquiry flow */
function resetAsk() {
  ask.controller?.abort();
  ask.run += 1;
  Object.assign(ask, { text: '', overrides: {}, parsed: null, result: null, status: {}, viewing: null, count: 0, seen: new Set(), clarified: false, busy: false });
  $('#feed').innerHTML = '';
  $('#feed-count').textContent = '';
}
function newQuestion() {
  resetAsk();
  $('#work').hidden = true; $('#hero').hidden = false;
  renderHero();
}

async function startAsk(text) {
  if (app.view !== 'ask') showView('ask');
  resetAsk();
  ask.text = text;
  ask.t0 = performance.now();
  $('#hero').hidden = true; $('#work').hidden = false;
  STAGES.forEach((s) => { ask.status[s.id] = 'todo'; });
  setStage('question', 'active');
  pushFeed('system', 'Question received', `“${text}”`);
  renderBottom();
  $('#canvas').innerHTML = pending('Reading your question', 'Looking for vehicle, feature, market, powertrain and what you want to know');
  await callAsk();
}

async function callAsk() {
  const run = ask.run;
  ask.controller?.abort();
  ask.controller = new AbortController();
  ask.busy = true; renderBottom();
  let resp;
  try {
    resp = await api('/api/ask', { method: 'POST', signal: ask.controller.signal, body: JSON.stringify({ text: ask.text, overrides: ask.overrides, horizon: app.meta.default_horizon }) });
  } catch (e) { if (run !== ask.run || e.name === 'AbortError') return; $('#canvas').innerHTML = `<div class="pending" role="alert"><div><b>Analysis unavailable</b><p>${esc(e.message)}</p></div></div>`; ask.busy = false; renderBottom(); return; }
  if (run !== ask.run) return;
  ask.parsed = resp.parsed;
  for (const ev of resp.parsed.events) pushFeed(ev.agent, ev.title, ev.detail);
  setStage('question', 'done');
  if (!resp.parsed.ready) {
    setStage('clarify', 'wait');
    view('clarify');
    pushFeed('clarify', 'Waiting for your answer', resp.parsed.missing.map((m) => m.question).join(' · '), true);
    ask.busy = false; renderBottom();
    return;
  }
  setStage('clarify', ask.clarified ? 'done' : 'skipped');
  if (!ask.clarified) pushFeed('clarify', 'Nothing missing - no clarification needed', '');
  ask.result = resp.result;
  for (const st of ['filter', 'read', 'compute', 'decide', 'recommend']) {
    for (const ev of stage(st).events || []) pushFeed(ev.agent, ev.title, ev.detail);
    setStage(st, 'done');
  }
  view('recommend');
  pushFeed('system', 'Analysis complete', 'click any stage above to revisit its reasoning');
  ask.busy = false; renderBottom();
}

const stage = (id) => ask.result?.stages.find((s) => s.id === id) || {};

function setStage(id, status) { ask.status[id] = status; renderStrip(); }

function renderStrip() {
  $('#strip').innerHTML = STAGES.map((s, i) => {
    const st = ask.status[s.id] || 'todo';
    const clickable = ['done', 'wait', 'skipped'].includes(st) && !(s.id !== 'question' && s.id !== 'clarify' && !ask.result);
    return `<div class="st ${st} ${ask.viewing === s.id ? 'viewing' : ''}"><button data-stage="${s.id}" ${clickable ? '' : 'disabled'}>
      <span class="sdot ${st === 'active' ? 'pulse-ring' : ''}">${st === 'done' ? icon('check', 10) : ''}</span>${esc(s.label)}</button>${i < STAGES.length - 1 ? '<span class="sline"></span>' : ''}</div>`;
  }).join('');
  $$('#strip [data-stage]').forEach((b) => b.addEventListener('click', () => view(b.dataset.stage)));
}

function renderBottom() {
  const done = ask.status.recommend === 'done';
  const waiting = ask.status.clarify === 'wait';
  $('#bottombar').innerHTML = `<button class="linkbtn" id="newq">← New question</button>
    <span class="status-txt">${ask.busy ? '<span class="spinner"></span> Analysing…' : waiting ? '<span style="color:var(--warning)">● Waiting for your answer</span>' : done ? '<span style="color:var(--success)">● Analysis complete</span>' : 'Standby'}</span>
    <span style="display:flex;gap:8px">${done ? `<button class="btn" id="b-report">${icon('report', 14)} Report</button>${ask.viewing !== 'recommend' ? '<button class="btn primary" id="b-rec">Recommendation →</button>' : ''}` : ''}</span>`;
  $('#newq').addEventListener('click', newQuestion);
  const r = $('#b-rec'); if (r) r.addEventListener('click', () => view('recommend'));
  const rp = $('#b-report'); if (rp) rp.addEventListener('click', openFeatureReport);
}

function pushFeed(agent, title, detail = '', wait = false) {
  const key = `${agent}|${title}`;
  if (ask.seen.has(key)) return;
  ask.seen.add(key);
  const a = AGENTS[agent] || AGENTS.system;
  const li = document.createElement('li');
  li.className = `feed-row ${wait ? 'wait' : ''}`;
  li.innerHTML = `<span class="glyph" style="background:${a.bg};color:${a.fg}">${a.glyph}</span>
    <div style="min-width:0;flex:1"><div class="fw" style="color:${a.fg}">${esc(a.label)}</div>
    <div class="t">${esc(title)}</div>${detail ? `<div class="d">${esc(detail)}</div>` : ''}</div>`;
  $('#feed').appendChild(li);
  ask.count += 1;
  $('#feed-count').textContent = `${ask.count} recorded steps`;
}

function view(id) {
  ask.viewing = id;
  renderStrip(); renderBottom();
  const c = $('#canvas');
  const fn = { question: panelQuestion, clarify: panelClarify, filter: panelFilter, read: panelRead, compute: panelCompute, decide: panelDecide, recommend: panelRecommend }[id];
  c.innerHTML = fn();
  bindPanel(id);
  animateIn(c);
}

const title = (n, t, sub = '') => `<div class="panel-title"><span class="sec-letter">${n}</span><h2>${esc(t)}</h2>${sub ? `<span class="muted small">${sub}</span>` : ''}</div>`;

/* ---------------------------------------------------------------- 1 question */
function highlight(text, slots) {
  let html = esc(text);
  const marks = [];
  const quoted = (src, cls) => { const m = /'([^']+)'/.exec(src || ''); if (m) marks.push([m[1], cls]); };
  quoted(slots.vehicle?.source, 'mk-vehicle'); quoted(slots.market?.source, 'mk-market'); quoted(slots.powertrain?.source, 'mk-powertrain');
  const fm = /matched words: ([^;]+)/.exec(slots.feature?.source || '');
  if (fm) fm[1].split(',').map((x) => x.trim()).forEach((w) => marks.push([w, 'mk-feature']));
  marks.forEach(([w, cls]) => {
    const rx = new RegExp(`(${esc(w).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'i');
    html = html.replace(rx, `<mark class="${cls}">$1</mark>`);
  });
  return html;
}

function panelQuestion() {
  const p = ask.parsed;
  const s = p.slots;
  const missing = new Set(p.missing.map((m) => m.slot));
  const slot = (key, name, i) => {
    const v = s[key];
    const cls = missing.has(key) ? 'missing' : v && v.value ? 'ok' : 'default';
    return `<div class="slot ${cls} reveal reveal-${i}"><div class="label">${esc(name)}</div><div class="v">${esc(missing.has(key) ? 'Missing - will ask' : v?.label || '–')}</div><div class="s">${esc(missing.has(key) ? 'not found in your question' : v?.source || '')}</div></div>`;
  };
  const cands = p.candidates.slice(0, 4);
  const hier = stage('read').hierarchy?.[0];
  return `<div class="panel" style="grid-template-rows:auto auto auto minmax(0,1fr)">
    ${title(1, 'What you asked', 'every slot shows how it was detected')}
    <div class="qline reveal">“${highlight(p.text, s)}”</div>
    <div class="slots">${slot('vehicle', 'Vehicle', 1)}${slot('feature', 'Feature', 2)}${slot('market', 'Market', 3)}${slot('powertrain', 'Powertrain', 4)}${slot('intent', 'Question type', 5)}</div>
    <div style="display:grid;grid-template-columns:1.2fr 1fr;gap:14px;min-height:0">
      <div class="card card-pad reveal reveal-2" style="overflow:hidden"><div class="card-head"><div class="card-title">How the feature was identified</div><span class="faint small">score = 0.65 × word match + 0.35 × model probability</span></div>
        ${cands.length ? cands.map((c) => `<div style="margin-bottom:9px"><div style="display:flex;justify-content:space-between;font-size:12px"><b>${esc(c.label)}</b><span class="num">${fmt(c.score, 2)}</span></div>
          <div class="stack" style="height:8px;margin:4px 0" data-tip="word match ${c.text_score} · model p ${c.model_p}"><span style="flex:${0.65 * c.text_score};background:var(--warning)"></span><span style="flex:${0.35 * c.model_p};background:#7c3aed"></span><span style="flex:${Math.max(0, 1 - c.score)};background:var(--surface-2)"></span></div>
          <div class="faint small">${esc(c.category)} · ${esc(c.evidence)}</div></div>`).join('') : '<p class="faint">No feature words found in the question.</p>'}
        <div class="legend"><span class="key"><span class="swatch" style="background:var(--warning)"></span>word match (feature dictionary)</span><span class="key"><span class="swatch" style="background:#7c3aed"></span>review model probability</span></div></div>
      <div class="card card-pad reveal reveal-3" style="overflow:hidden"><div class="card-head"><div class="card-title">Where it sits in BMW's feedback taxonomy</div></div>
        ${hier ? `<div class="crumb"><span class="lvl"><small>Category · L1</small>${esc(hier.name)}</span><span class="arr">›</span>
          <span class="lvl"><small>Component · VFC L2</small>${esc(hier.components[0].name)}</span><span class="arr">›</span>
          <span class="lvl"><small>Issues · VFC L3</small>${fmt(hier.components[0].issues.length)} types</span></div>
          <div class="faint small" style="margin-top:10px">${hier.components[0].issues.slice(0, 4).map((i) => `${esc(i.name)} (${i.reviews})`).join(' · ')}</div>`
          : `<p class="faint">${missing.size ? 'Shown once the question is complete.' : 'No labelled reviews for this feature.'}</p>`}</div>
    </div></div>`;
}

/* ---------------------------------------------------------------- 2 clarify */
function panelClarify() {
  const p = ask.parsed;
  if (ask.status.clarify === 'skipped') {
    return `<div class="panel" style="grid-template-rows:auto 1fr">${title(2, 'Clarify', 'nothing was missing')}
      <div class="empty-state"><div><div style="font-size:15px;font-weight:600;color:var(--text-1)">Your question had everything needed</div><div>Vehicle and feature were found; market and powertrain default to all.</div></div></div></div>`;
  }
  if (ask.status.clarify === 'done') {
    return `<div class="panel" style="grid-template-rows:auto 1fr">${title(2, 'Clarify', 'answered')}
      <div class="empty-state"><div>You answered: ${Object.entries(ask.overrides).map(([k, v]) => `<b>${esc(k)}</b> = ${esc(v)}`).join(', ')}</div></div></div>`;
  }
  return `<div class="panel" style="grid-template-rows:auto ${p.missing.map(() => 'auto').join(' ')} minmax(0,1fr)">
    ${title(2, 'I need a bit more', 'pick an option - the analysis continues straight away')}
    ${p.missing.map((m) => `<div class="card card-pad reveal"><div class="card-head"><div class="card-title">${esc(m.question)}</div></div>
      <div class="optgrid">${m.options.map((o) => `<button class="opt" data-slot="${m.slot}" data-val="${esc(o.value)}">
        ${m.slot === 'vehicle' ? `<span class="car-mini">${carSVG({ code: o.value, compact: true })}</span>` : ''}
        <b>${esc(o.label)}</b><span class="faint small">${esc(o.detail || '')}</span>
        ${o.score != null ? `<span class="scorebar"><span data-w="${Math.min(100, o.score * 100)}%"></span></span>` : ''}</button>`).join('')}</div>
      ${m.slot === 'feature' ? '<form class="reason" id="feat-free" style="margin-top:10px"><input id="feat-text" placeholder="…or type the feature, e.g. seat massage" /><button class="btn">Use</button></form>' : ''}
    </div>`).join('')}<div></div></div>`;
}

/* ---------------------------------------------------------------- 3 filter */
function panelFilter() {
  const f = stage('filter');
  const max = Math.log10(f.funnel[0].reviews + 1);
  const sp = f.split;
  const tot = Math.max(1, sp.vfc + sp.model + sp.text);
  const names = app.meta.regions;
  return `<div class="panel" style="grid-template-rows:auto auto minmax(0,1fr)">
    ${title(3, 'Filtering the data', 'each step narrows the evidence; bar length on a log scale')}
    <div class="card card-pad funnel reveal">${f.funnel.map((r) => `<div class="frow"><div class="fl"><b data-count="${r.reviews}">0</b><span>${esc(r.label)}</span></div>
      <div class="fbar-wrap"><div class="fbar" data-w="${Math.max(0.6, (Math.log10(r.reviews + 1) / max) * 100)}%"></div><div class="frule" title="${esc(r.rule)}">${esc(r.rule)}</div></div></div>`).join('')}</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;min-height:0">
      <div class="card card-pad reveal reveal-2" style="overflow:hidden"><div class="card-head"><div class="card-title">Where the matching reviews come from</div></div>
        <div class="stack" style="height:16px"><span style="flex:${sp.vfc / tot};background:var(--accent)"></span><span style="flex:${sp.model / tot};background:#7c3aed"></span><span style="flex:${sp.text / tot};background:var(--warning)"></span></div>
        <div class="legend" style="margin-top:8px"><span class="key"><span class="swatch" style="background:var(--accent)"></span>BMW VFC label <b>${sp.vfc}</b></span><span class="key"><span class="swatch" style="background:#7c3aed"></span>labelled by the review model <b>${sp.model}</b></span><span class="key"><span class="swatch" style="background:var(--warning)"></span>free-text match <b>${sp.text}</b></span></div>
        <p class="faint small" style="margin-top:10px">VFC labels come from BMW's own classification. Reviews it left empty were read sentence by sentence by the trained model. Free-text matches catch mentions without any label; their tone is read from wording, so they count as lower confidence.</p></div>
      <div class="card card-pad reveal reveal-3" style="overflow:hidden"><div class="card-head"><div class="card-title">Matches by market</div><span class="faint small">mentions / all reviews from that market</span></div>
        ${Object.entries(f.by_region).map(([k, r]) => `<div class="factor" style="grid-template-columns:110px minmax(0,1fr) 90px;margin-bottom:8px"><span>${esc(names[k])}</span>
          <div class="meter"><span data-w="${r.base ? Math.min(100, (r.mentions / r.base) * 2000) : 0}%"></span></div><span class="num faint">${fmt(r.mentions)} / ${fmt(r.base)}</span></div>`).join('')}
        <p class="faint small">Countries fold into sales regions (GB, FR, SE → Europe; JP, KR, CA → Rest of World). Fewer than 30 reviews = market not covered; it then relies on the customer survey.</p></div>
    </div></div>`;
}

/* ---------------------------------------------------------------- 4 read */
function panelRead() {
  const r = stage('read');
  const hier = r.hierarchy || [];
  const fc = new Set(r.feature_components || []);
  const comps = hier.flatMap((h) => h.components).slice(0, 5);
  const issues = comps[0]?.issues.slice(0, 6) || [];
  const s = r.signals;
  const m = r.model;
  return `<div class="panel" style="grid-template-rows:auto auto minmax(0,1fr)">
    ${title(4, 'What the AI read', 'review model: TF-IDF + logistic regression, trained on BMW\'s labelled reviews')}
    <div class="metric-cards reveal">${['category', 'component', 'issue', 'signal'].map((h) => `<div class="card mcard"><div class="label">${esc(h)} head</div><div class="acc">${pct(m[h])}</div><div class="faint small">top-1 accuracy on unseen reviews</div></div>`).join('')}</div>
    <div style="display:grid;grid-template-columns:1.05fr 1fr;gap:14px;min-height:0">
      <div class="card card-pad reveal reveal-2" style="display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:10px;overflow:hidden">
        <div class="card-head" style="margin:0"><div class="card-title">Category › component › issue</div><span class="faint small">unique reviews</span></div>
        <div class="tree">
          <div class="tcol"><div class="label">Category · L1</div>${hier.map((h, i) => `<div class="tnode ${i === 0 ? 'sel' : ''}"><span class="nm">${esc(h.name)}</span><span class="n">${h.reviews}</span></div>`).join('')}</div>
          <div class="tcol"><div class="label">Component · VFC L2</div>${comps.map((c, i) => `<div class="tnode ${i === 0 ? 'sel' : ''}"><span class="nm">${esc(c.name)}</span><span class="n">${c.reviews}</span></div>`).join('')}</div>
          <div class="tcol"><div class="label">Issue · VFC L3</div>${issues.map((i) => `<div class="tnode"><span class="nm"><span class="swatch" style="background:${SIG_COLOR[i.signal] || 'var(--text-3)'}"></span>${esc(i.name)}</span><span class="n">${i.reviews}</span></div>`).join('')}</div>
        </div>
        <div><div class="stack" style="height:12px"><span style="flex:${s.praise};background:var(--s-praise)"></span><span style="flex:${s.complaints};background:var(--s-complaint)"></span><span style="flex:${s.requests + s.inferred_requests};background:var(--s-request)"></span></div>
          <div class="legend" style="margin-top:6px"><span class="key"><span class="swatch" style="background:var(--s-praise)"></span>praise <b>${s.praise}</b></span><span class="key"><span class="swatch" style="background:var(--s-complaint)"></span>complaints <b>${s.complaints}</b> (${s.defects} defects, ${s.usability} hard to use)</span><span class="key"><span class="swatch" style="background:var(--s-request)"></span>requests <b>${s.requests + s.inferred_requests}</b></span></div></div>
      </div>
      <div style="display:grid;grid-template-rows:auto repeat(2, minmax(0,1fr));gap:8px;min-height:0">
        <div class="faint small">How the model reads a review: it splits it into sentences and predicts a component, a signal and an issue for each. Highlighted words drove the prediction; blue rows belong to your feature.</div>
        ${(r.examples || []).slice(0, 2).map((e) => `<div class="review reveal reveal-3"><div style="display:flex;justify-content:space-between;gap:8px"><span class="idcode">${esc(e.verbatim_id)} · ${esc(e.country)}</span><span class="chip">VFC: ${esc(e.vfc)}</span></div>
          <div class="txt">${esc(e.text)}</div>
          ${e.aspects.slice(0, 2).map((a) => `<div class="aspect ${fc.has(a.component) ? 'hit' : ''}"><span class="sent">“${esc(a.sentence)}”</span>
            <span><b>${esc(a.component)}</b> · <span style="color:${SIG_COLOR[a.signal]}">${esc(SIG_LABEL[a.signal] || a.signal)}</span> · ${esc(a.issue)}</span><span class="num faint">p ${fmt(a.p, 2)}</span>
            <span class="terms" style="grid-column:1/-1">${a.terms.map((t) => `<b>${esc(t)}</b>`).join('')}</span></div>`).join('') || '<span class="faint small">No confident aspect in this review.</span>'}</div>`).join('')}
      </div>
    </div></div>`;
}

/* ---------------------------------------------------------------- 5 compute */
function panelCompute() {
  const c = stage('compute');
  return `<div class="panel" style="grid-template-rows:auto auto minmax(0,1fr)">
    ${title(5, 'The numbers', 'every figure with the formula that produced it')}
    <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px">
      <div class="card card-pad reveal"><div class="label">Mention rate</div><div class="big"><span data-count="${c.rate.per_1000}" data-dec="1">0</span><span class="faint" style="font-size:13px;font-weight:500"> per 1,000 reviews</span></div><div class="formula" style="margin-top:8px" title="${esc(c.rate.formula)}">${esc(c.rate.formula)}</div></div>
      <div class="card card-pad reveal reveal-1"><div class="label">Small-sample correction</div><div class="big" style="font-size:20px;margin-top:6px">prior = ${fmt(c.prior * 1000, 2)} / 1,000</div><div class="faint small" style="margin-top:6px">Markets with few reviews are pulled toward the vehicle-wide rate by 50 pseudo-reviews, so one lucky mention cannot crown a market.</div></div>
      <div class="card card-pad reveal reveal-2"><div class="label">Cars at stake</div><div class="big"><span data-count="${c.sales.units_at_stake}">0</span><span class="faint" style="font-size:13px;font-weight:500"> of ${compact(c.sales.exposure)} planned</span></div><div class="formula" style="margin-top:8px" title="${esc(c.sales.formula)}">${esc(c.sales.formula)}</div></div>
    </div>
    <div class="card card-pad reveal reveal-3" style="overflow:hidden"><div class="card-head"><div class="card-title">Per market</div><span class="faint small">shrunk rate = (mentions + 50 × prior) / (reviews + 50) · index = shrunk / prior · survey z = study score vs this car's average</span></div>
      <table class="tbl"><thead><tr><th>Market</th><th class="r">Mentions / reviews</th><th class="r">Raw / 1,000</th><th>Shrunk rate</th><th class="r">Index</th><th class="r">Survey z</th><th class="r">Volume</th><th class="r">Cars at stake</th></tr></thead>
      <tbody>${c.markets.map((m) => `<tr><td><b>${esc(m.name)}</b></td><td class="r">${fmt(m.mentions)} / ${fmt(m.base)}</td><td class="r">${m.rate_per_1000 == null ? '–' : fmt(m.rate_per_1000, 1)}</td>
        <td class="mono small">${esc(m.shrunk_formula)}</td><td class="r">${m.index == null ? '–' : fmt(m.index, 2)}</td>
        <td class="r" ${m.survey ? `data-tip="${esc(m.survey.attributes.map((a) => `${a.attribute}: ${a.score.toFixed(1)}/10`).join(' | '))}"` : ''}>${m.survey ? `${m.survey.mean_z >= 0 ? '+' : ''}${fmt(m.survey.mean_z, 2)}` : '–'}</td>
        <td class="r">${fmt(m.volume)}</td><td class="r">${fmt(m.sales.units_at_stake)}</td></tr>`).join('')}</tbody></table></div>
  </div>`;
}

/* ---------------------------------------------------------------- 6 decide */
function panelDecide() {
  const d = stage('decide');
  const k = d.kano;
  const names = app.meta.regions;
  const pr = d.priority;
  const cs = k.metrics.complaint_share;
  const mk = Object.entries(d.markets);
  return `<div class="panel" style="grid-template-rows:auto minmax(0,1fr)">
    ${title(6, 'Decision logic', 'rules are checked top to bottom - the highlighted one fired')}
    <div style="display:grid;grid-template-columns:1fr 1.05fr 1.15fr;gap:14px;min-height:0">
      <div class="card card-pad reveal" style="overflow:hidden"><div class="card-head"><div class="card-title">Have it or not? (Kano class)</div></div>
        <div class="faint small">Complaint share of opinions: <b style="color:var(--text-1)">${pct(cs)}</b> (${k.metrics.complaints} complaints vs ${k.metrics.praise} praise)</div>
        <div class="gauge" style="margin-top:8px"><span class="needle" data-left="${Math.min(99, cs * 100)}%"></span></div><div class="gauge-l"><span>0%</span><span>30% delighter</span><span>60% must-be</span><span>100%</span></div>
        <div class="rules" style="margin-top:10px">${k.path.map((p) => `<div class="rule ${p.fired ? 'fired' : ''}"><span class="rk">${p.fired ? '✓' : '✗'}</span><span><b>${esc(p.rule)}</b> - ${esc(p.test)}</span></div>`).join('')}</div>
        <div class="faint small" style="margin-top:8px">${esc(k.why)}</div></div>
      <div class="card card-pad reveal reveal-1" style="overflow:hidden"><div class="card-head"><div class="card-title">Which markets?</div></div>
        <div style="display:grid;gap:8px;grid-template-columns:${mk.length > 1 ? '1fr 1fr' : '1fr'}">${mk.map(([r, rec]) => `<div style="border:1px solid var(--border);border-radius:10px;padding:8px 10px;min-width:0">
          <b>${esc(names[r])}</b><div class="small" style="font-weight:600;color:var(--accent);margin:2px 0 4px">${esc(rec.label)}</div>
          <div class="rules">${rec.path.slice(-(mk.length > 1 ? 3 : 6)).map((p, i, arr) => `<div class="rule ${i === arr.length - 1 ? 'fired' : p.result ? 'yes' : ''}" style="padding:3px 6px;font-size:10.5px"><span class="rk" style="width:15px;height:15px;font-size:9px">${p.result ? '✓' : '✗'}</span><span>${esc(p.test)}</span></div>`).join('')}</div></div>`).join('')}</div></div>
      <div class="card card-pad reveal reveal-2" style="overflow:hidden">${pr ? `<div class="card-head"><div class="card-title">Priority score</div><span class="chip ${tierTone(pr.tier)}">${pr.tier} · ${fmt(pr.score, 1)}</span></div>
        <div class="waterfall">${FACTORS.filter((f) => pr.weights[f]).map((f) => `<span data-w="${pr.contributions[f]}%" style="background:${FACTOR_COLOR[f]}" data-tip="${esc(`${FACTOR_LABEL[f]}: ${pr.contributions[f]} pts`)}">${pr.contributions[f] >= 6 ? fmt(pr.contributions[f], 0) : ''}</span>`).join('')}</div>
        <div class="faint small" style="margin:4px 0 10px">raw ${fmt(pr.raw, 1)} × evidence ${pr.evidence_multiplier} (${esc(pr.evidence.level)}) = <b style="color:var(--text-1)">${fmt(pr.score, 1)}</b> · P1 ≥ 55, P2 ≥ 38</div>
        ${FACTORS.filter((f) => pr.weights[f]).map((f) => `<div class="factor" style="margin-bottom:6px" data-tip="${esc(pr.notes[f])}"><span><span class="swatch" style="background:${FACTOR_COLOR[f]}"></span> ${FACTOR_LABEL[f]} <span class="faint">×${pr.weights[f]}</span></span><div class="meter"><span data-w="${pr.factors[f] * 100}%" style="background:${FACTOR_COLOR[f]}"></span></div><span class="num">${fmt(pr.factors[f], 2)}</span></div>`).join('')}
        <div class="faint small" style="margin-top:6px">Hover a factor for its basis. Evidence: ${esc(pr.evidence.reasons.join(' · '))}</div>` : '<p class="faint">No evidence to score.</p>'}</div>
    </div></div>`;
}

/* ---------------------------------------------------------------- 7 recommend */
function panelRecommend() {
  const r = stage('recommend');
  const q = ask.result.query;
  const v = r.verdict;
  const kn = r.key_numbers;
  const names = app.meta.regions;
  const pr = stage('decide').priority;
  const comps = stage('read').feature_components || [];
  return `<div class="panel" style="grid-template-rows:auto minmax(0,1fr)">
    ${title(7, 'Recommendation', `${esc(app.meta.derivatives[q.vehicle].name)} · ${esc(q.feature.replace('component: ', ''))}${q.market ? ` · ${esc(names[q.market])}` : ''}`)}
    <div style="display:grid;grid-template-columns:1.5fr 1fr;gap:14px;min-height:0">
      <div class="card rec t-${v.tone} reveal" style="display:flex;flex-direction:column;gap:12px;overflow:hidden">
        <div class="rec-meta"><span class="label">Recommendation</span><span class="rule-line"></span><span class="chip">${esc(r.intent_label)}</span>${pr ? `<span class="chip ${tierTone(pr.tier)}">${pr.tier} · ${fmt(pr.score, 1)}</span>` : ''}</div>
        <div><div class="verdict-big">${esc(v.label)}</div><div class="answer">${esc(r.answer)}</div></div>
        <div class="kgrid">${[['per_1000', 'per 1,000 reviews', 1], ['complaints', 'complaints'], ['requests', 'requests'], ['praise', 'praise'], ['units_at_stake', 'cars at stake']].map(([key, l, dec]) => `<div class="kcell"><b data-count="${kn[key]}" ${dec ? 'data-dec="1"' : ''}>0</b><span>${l}</span></div>`).join('')}</div>
        <div class="mkts">${Object.entries(r.markets).map(([k, m]) => `<div class="mk lv-${esc(m.level)} ${q.market === k ? 'focus' : ''}" data-tip="${esc(m.why)}"><div class="c">${esc(k)}</div><div class="l">${esc(m.label)}</div><div class="w">${compact(m.volume)} planned</div></div>`).join('')}</div>
        <div class="faint small">Today (German price list): <b style="color:var(--text-2)">${esc(r.equipment)}</b>${r.coverage_warning ? ` · ${esc(r.coverage_warning)}` : ''}</div>
        <div style="margin-top:auto;border-top:1px solid var(--border);padding-top:12px;display:flex;flex-direction:column;gap:8px">
          <div class="label">Your decision</div>
          <div class="reason"><input id="dec-reason" placeholder="Why? (stored in the audit trail)" />
            <button class="btn success" data-dec="Approved">${icon('check', 14)} Approve</button>
            <button class="btn danger" data-dec="Rejected">${icon('x', 14)} Reject</button>
            <button class="btn" data-dec="Proposed">Save for later</button></div>
          <div id="dec-done" class="faint small"></div></div>
      </div>
      <div style="display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:12px;min-height:0">
        <div class="carstage reveal reveal-1" style="height:130px">${carSVG({ code: q.vehicle, highlight: comps.length ? [zoneOf(comps[0])] : [] })}</div>
        <div class="card card-pad reveal reveal-2" style="overflow:hidden;display:flex;flex-direction:column;gap:8px"><div class="card-title">What customers said</div>
          ${r.quotes.slice(0, 3).map((x) => `<div class="quote">“${esc(x.text)}” <span class="idcode">${esc(x.verbatim_id)}</span></div>`).join('') || '<span class="faint">No quotes.</span>'}</div>
        <div class="card card-pad reveal reveal-3" style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div><div class="label" style="margin-bottom:4px">Materials</div>${r.materials.slice(0, 3).map((m) => `<div class="small" style="display:flex;gap:6px;align-items:center">${swatch(m.material, 'sm')}<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(m.material)}</span><span class="num faint">+${m.positive}/-${m.negative}</span></div>`).join('') || '<span class="faint small">none mentioned</span>'}</div>
          <div><div class="label" style="margin-bottom:4px">Rivals named</div>${r.rivals.map((c) => `<div class="small">${esc(c.brand)} <span class="faint">· ${c.verbatims} reviews</span></div>`).join('') || '<span class="faint small">none named</span>'}</div>
        </div>
      </div>
    </div></div>`;
}

/* car-sketch zone of a component (same idea as the backend's zone rules) */
function zoneOf(component) {
  const l = component.toLowerCase();
  const rules = [['heated steering', 'climate'], ['steering wheel', 'screens'], ['touch screen', 'screens'], ['operating', 'screens'], ['navigation', 'screens'], ['head-up', 'screens'],
    ['seat', 'seats'], ['panorama', 'roof'], ['roof', 'roof'], ['ambient', 'roof'], ['mobile device', 'connect'], ['charg', 'charging'], ['range', 'charging'], ['battery', 'charging'],
    ['tire', 'wheels'], ['wheels', 'wheels'], ['riding', 'wheels'], ['cushion', 'wheels'], ['luggage', 'space'], ['trunk', 'space'], ['storage', 'space'], ['cupholder', 'space'],
    ['space', 'space'], ['door', 'access'], ['key', 'access'], ['climat', 'climate'], ['air condition', 'climate'], ['blower', 'climate'], ['acoustic', 'climate'], ['assist', 'assist'],
    ['parking', 'assist'], ['camera', 'assist'], ['cruise', 'assist'], ['drivetrain', 'powertrain'], ['engine', 'powertrain'], ['transmission', 'powertrain'], ['exterior', 'exterior'],
    ['grille', 'exterior'], ['light', 'lights'], ['mirror', 'lights'], ['interior', 'interior'], ['upholstery', 'interior'], ['carplay', 'connect'], ['app', 'connect'],
    ['bluetooth', 'connect'], ['usb', 'connect'], ['dynamics', 'dynamics'], ['brak', 'dynamics']];
  return (rules.find(([k]) => l.includes(k)) || [null, 'interior'])[1];
}

function bindPanel(id) {
  if (id === 'clarify') {
    $$('#canvas .opt').forEach((b) => b.addEventListener('click', () => pickOption(b.dataset.slot, b.dataset.val, b.querySelector('b').textContent)));
    const ff = $('#feat-free');
    if (ff) ff.addEventListener('submit', (e) => { e.preventDefault(); const v = $('#feat-text').value.trim(); if (v) pickOption('feature', v, v); });
  }
  if (id === 'decide') requestAnimationFrame(() => requestAnimationFrame(() => $$('.needle[data-left]').forEach((n) => { n.style.left = n.dataset.left; })));
  if (id === 'recommend') $$('#canvas [data-dec]').forEach((b) => b.addEventListener('click', () => decideFeature(b.dataset.dec)));
}

async function pickOption(slot, value, label) {
  ask.overrides[slot] = value;
  ask.clarified = true;
  pushFeed('you', `${slot === 'vehicle' ? 'Vehicle' : 'Feature'}: ${label}`, 'picked in the clarification step');
  const still = ask.parsed.missing.filter((m) => !ask.overrides[m.slot]);
  if (still.length) { ask.parsed.missing = still; view('clarify'); return; }
  setStage('clarify', 'done');
  $('#canvas').innerHTML = pending('Continuing the analysis', 'with your answer');
  await callAsk();
}

async function decideFeature(status) {
  const actor = actorOrAsk();
  if (!actor) return;
  const reason = $('#dec-reason').value.trim();
  if (status !== 'Proposed' && reason.length < 3) { toast('Add a short reason - it is stored with the decision.'); $('#dec-reason').focus(); return; }
  const q = ask.result.query;
  try {
    const req = await api('/api/requirements/from-feature', { method: 'POST', body: JSON.stringify({ query: q.feature, derivative: q.vehicle, actor, horizon: q.horizon, rationale: reason || `Saved from the question “${ask.text}”.` }) });
    if (status !== 'Proposed') await api(`/api/requirements/${encodeURIComponent(req.id)}/decision`, { method: 'POST', body: JSON.stringify({ status, actor, rationale: reason }) });
    const verb = { Approved: 'approved', Rejected: 'rejected', Proposed: 'saved for later' }[status];
    $('#dec-done').innerHTML = `${icon('check', 12)} ${esc(req.id)} ${verb} by ${esc(actor)} - see <a href="#" id="go-req">Requirements</a>.`;
    $('#go-req').addEventListener('click', (e) => { e.preventDefault(); rq.sel = req.id; rq.status = status; showView('reqs'); });
    pushFeed('you', `Requirement ${verb}`, `${req.id}${reason ? ` · “${reason}”` : ''}`);
    toast(`${req.id} ${verb}.`);
  } catch (e) { toast(e.message, 6000); }
}

function openFeatureReport() {
  const q = ask.result.query;
  window.open(`report.html?${new URLSearchParams({ type: 'feature', q: q.feature, vehicle: q.vehicle, horizon: q.horizon })}`, '_blank', 'noopener');
}

/* ================================================================ requirements */
const rq = { status: 'Proposed', vehicle: '', q: '', page: 0, sel: null, tab: 'summary', items: [], detail: null };

async function renderReqs() {
  const v = $('#view-reqs');
  if (!v.querySelector('.split')) {
    v.innerHTML = `<div class="split"><div class="list-col">
        <div class="list-tools">
          <div class="seg" id="rq-status">${[['Proposed', 'Awaiting'], ['Approved', 'Approved'], ['Rejected', 'Rejected'], ['', 'All']].map(([k, l]) => `<button data-s="${k}">${l}</button>`).join('')}</div>
          <div class="tools-row"><select id="rq-veh" aria-label="Vehicle"><option value="">All vehicles</option>${Object.entries(app.meta.derivatives).map(([k, d]) => `<option value="${k}">${esc(d.name)}</option>`).join('')}</select><input id="rq-q" placeholder="Search…" aria-label="Search" /></div>
        </div>
        <div class="rlist" id="rq-list"></div><div class="pager" id="rq-pager"></div></div>
      <div class="detail" id="rq-detail"></div></div>`;
    $$('#rq-status button').forEach((b) => b.addEventListener('click', () => { rq.status = b.dataset.s; rq.page = 0; rq.sel = null; loadReqs(); }));
    $('#rq-veh').addEventListener('change', (e) => { rq.vehicle = e.target.value; rq.page = 0; rq.sel = null; loadReqs(); });
    $('#rq-q').addEventListener('input', (e) => { rq.q = e.target.value.toLowerCase(); rq.page = 0; drawList(); });
  }
  await loadReqs();
}

async function loadReqs() {
  $$('#rq-status button').forEach((x) => x.classList.toggle('on', x.dataset.s === rq.status));
  const p = new URLSearchParams();
  if (rq.status) p.set('status', rq.status);
  if (rq.vehicle) p.set('derivative', rq.vehicle);
  $('#rq-list').innerHTML = pending('Loading requirements', '');
  rq.items = await api(`/api/requirements?${p}`);
  if (!rq.sel || !rq.items.some((r) => r.id === rq.sel)) rq.sel = filtered()[0]?.id || null;
  const idx = filtered().findIndex((r) => r.id === rq.sel);
  if (idx >= 0) rq.page = Math.floor(idx / fitRows($('#rq-list'), 68));
  drawList();
  if (rq.sel) loadDetail(rq.sel); else $('#rq-detail').innerHTML = '<div class="empty-state">No requirements here yet.</div>';
}

const filtered = () => rq.items.filter((r) => !rq.q || `${r.id} ${r.title}`.toLowerCase().includes(rq.q));

function drawList() {
  const list = $('#rq-list');
  const per = fitRows(list, 68);
  const items = filtered();
  const pages = Math.max(1, Math.ceil(items.length / per));
  rq.page = Math.max(0, Math.min(rq.page, pages - 1));
  const slice = items.slice(rq.page * per, rq.page * per + per);
  list.innerHTML = slice.map((r) => `<button class="ritem ${r.id === rq.sel ? 'sel' : ''}" data-id="${esc(r.id)}">${scoreRing(r.priority.score, 38, r.priority.tier)}
    <span style="min-width:0"><span class="t">${esc(r.title)}</span><span class="m">${typeTag(r.type)}<span class="chip ${tierTone(r.priority.tier)}">${esc(r.priority.tier)}</span><span class="idcode" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.derivative)} · ${esc(r.evidence.level)} evidence</span></span></span></button>`).join('') || '<div class="empty-state">Nothing matches.</div>';
  $('#rq-pager').innerHTML = `<button class="btn" id="pg-prev" ${rq.page === 0 ? 'disabled' : ''} aria-label="Previous page">${icon('left', 13)}</button><span>${fmt(items.length)} requirements · page ${rq.page + 1} / ${pages}</span><button class="btn" id="pg-next" ${rq.page >= pages - 1 ? 'disabled' : ''} aria-label="Next page">${icon('right', 13)}</button>`;
  $('#pg-prev').addEventListener('click', () => { rq.page -= 1; drawList(); });
  $('#pg-next').addEventListener('click', () => { rq.page += 1; drawList(); });
  $$('#rq-list .ritem').forEach((b) => b.addEventListener('click', () => { rq.sel = b.dataset.id; $$('#rq-list .ritem').forEach((x) => x.classList.toggle('sel', x === b)); loadDetail(rq.sel); }));
  grow(list);
}

async function loadDetail(id) {
  try { rq.detail = await api(`/api/requirements/${encodeURIComponent(id)}`); } catch (e) { $('#rq-detail').innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; return; }
  drawDetail();
}

function drawDetail() {
  const r = rq.detail;
  const p = r.priority;
  const tabs = [['summary', 'Summary'], ['why', 'Why this score'], ['evidence', 'Evidence'], ['history', 'History']];
  $('#rq-detail').innerHTML = `<div style="display:flex;gap:14px;align-items:center" class="reveal">${scoreRing(p.score, 54, p.tier)}<div style="min-width:0">
      <div style="display:flex;gap:6px;flex-wrap:wrap">${typeTag(r.type)}<span class="chip ${tierTone(p.tier)}">${p.tier}${p.overridden ? ' · override' : ''}</span>
        <span class="chip ${r.status === 'Approved' ? 'tone-success' : r.status === 'Rejected' ? 'tone-danger' : 'tone-accent'}">${esc(r.status === 'Proposed' ? 'Awaiting decision' : r.status)}</span><span class="chip">${esc(r.evidence.level)} evidence</span></div>
      <h2 style="font-size:17px;margin-top:6px">${esc(r.title)}</h2><div class="idcode">${esc(r.id)} · ${esc(r.vehicle)} · v${r.version}</div></div>
      <button class="btn" id="rq-report" style="margin-left:auto">${icon('report', 14)} Report</button></div>
    <div class="tabs">${tabs.map(([k, l]) => `<button data-t="${k}" aria-selected="${k === rq.tab}">${l}</button>`).join('')}</div>
    <div class="tab-body" id="rq-tab">${detailTab(r)}</div>`;
  $$('#rq-detail .tabs button').forEach((b) => b.addEventListener('click', () => { rq.tab = b.dataset.t; drawDetail(); }));
  $('#rq-report').addEventListener('click', () => window.open(`report.html?type=requirement&id=${encodeURIComponent(r.id)}`, '_blank', 'noopener'));
  $$('#rq-tab [data-dec]').forEach((b) => b.addEventListener('click', () => decideReq(b.dataset.dec)));
  animateIn($('#rq-detail'));
}

function detailTab(r) {
  if (rq.tab === 'summary') {
    return `<div style="display:grid;grid-template-rows:auto auto auto minmax(0,1fr);gap:12px;height:100%">
      <p style="font-size:13.5px;line-height:1.55;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden">${esc(r.description)}</p>
      <div><div class="label" style="margin-bottom:6px">Done when</div>${r.acceptance_criteria.slice(0, 3).map((c) => `<div class="small" style="display:flex;gap:6px;margin-bottom:3px">${icon('check', 13)}<span>${esc(c)}</span></div>`).join('')}</div>
      <div class="mkts">${Object.entries(r.regions).map(([k, g]) => `<div class="mk lv-${esc(g.recommendation.level)}" data-tip="${esc(g.recommendation.why)}"><div class="c">${esc(k)}</div><div class="l">${esc(g.recommendation.label)}</div><div class="w">${fmt(g.verbatims)} reviews · ${compact(g.volume)} planned</div></div>`).join('')}</div>
      <div style="align-self:end;border-top:1px solid var(--border);padding-top:12px"><div class="label" style="margin-bottom:6px">Your decision</div>
        <div class="reason"><input id="rq-reason" placeholder="Why? (stored in the audit trail)" />
        <button class="btn success" data-dec="Approved">${icon('check', 14)} Approve</button><button class="btn" data-dec="Changes requested">${icon('undo', 14)} Changes</button><button class="btn danger" data-dec="Rejected">${icon('x', 14)} Reject</button></div></div></div>`;
  }
  if (rq.tab === 'why') {
    const p = r.priority;
    return `<div style="display:grid;gap:10px">
      <div class="faint small">score = 100 × Σ weight × factor × evidence adjustment = ${fmt(p.raw, 1)} × ${p.evidence_multiplier} = <b style="color:var(--text-1)">${fmt(p.score, 1)}</b> → ${p.tier} (P1 ≥ 55, P2 ≥ 38)</div>
      ${FACTORS.filter((k) => p.weights[k]).map((k) => `<div><div class="factor"><span><b>${FACTOR_LABEL[k]}</b> <span class="faint">×${p.weights[k]}</span></span><div class="meter"><span data-w="${r.factors[k] * 100}%" style="background:${FACTOR_COLOR[k]}"></span></div><span class="num">+${fmt(p.contributions[k], 1)}</span></div><div class="faint small" style="margin:2px 0 0 138px">${esc(r.factor_notes[k])}</div></div>`).join('')}
      <div class="card card-pad" style="margin-top:4px"><b>${esc(r.kano.class)}</b> - <span class="muted">${esc(r.kano.why)}</span></div></div>`;
  }
  if (rq.tab === 'evidence') {
    return `<div style="display:grid;grid-template-columns:1.2fr 1fr;gap:14px;height:100%;min-height:0">
      <div class="card card-pad" style="overflow:hidden;display:flex;flex-direction:column;gap:8px"><div class="card-title">Customer voices · ${fmt(r.linked_findings.length)} linked findings</div>
        ${r.quotes.slice(0, 4).map((q) => `<div class="quote">“${esc(q.text)}” <span class="idcode">${esc(q.verbatim_id)} · ${esc(q.country)}</span></div>`).join('')}</div>
      <div style="display:grid;grid-template-rows:auto minmax(0,1fr);gap:12px;min-height:0">
        <div class="card card-pad"><div class="card-title" style="margin-bottom:6px">Evidence: ${esc(r.evidence.level)}</div><div class="small muted">${esc(r.evidence.reasons.join(' · '))}</div></div>
        <div class="card card-pad" style="overflow:hidden"><div class="card-title" style="margin-bottom:6px">Assumptions & uncertainties</div>${r.assumptions.slice(0, 5).map((a) => `<div class="small muted" style="margin-bottom:4px">• ${esc(a)}</div>`).join('')}</div></div></div>`;
  }
  return `<ul class="timeline">${(r.audit || []).slice(0, 9).map((a) => `<li><span class="glyph" style="background:${a.actor_type === 'pm' ? 'var(--success-soft)' : 'var(--accent-soft)'};color:${a.actor_type === 'pm' ? 'var(--success)' : 'var(--accent)'}">${a.actor_type === 'pm' ? '✓' : '◆'}</span>
    <div style="min-width:0"><b>${esc(a.action.replace(/_/g, ' '))}</b> · ${esc(a.actor)} <span class="faint">${esc(a.ts.replace('T', ' ').slice(0, 16))}</span>${a.field ? ` <span class="muted">${esc(a.field)}: ${esc(String(a.old_value ?? '–').slice(0, 30))} → ${esc(String(a.new_value ?? '–').slice(0, 30))}</span>` : ''}
    ${a.rationale ? `<div class="faint" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(a.rationale)}</div>` : ''}</div></li>`).join('')}</ul>`;
}

async function decideReq(status) {
  const actor = actorOrAsk();
  if (!actor) return;
  const reason = $('#rq-reason').value.trim();
  if (reason.length < 3) { toast('Add a short reason - it is stored with the decision.'); $('#rq-reason').focus(); return; }
  try {
    await api(`/api/requirements/${encodeURIComponent(rq.detail.id)}/decision`, { method: 'POST', body: JSON.stringify({ status, actor, rationale: reason }) });
    toast(`${rq.detail.id}: ${status}`);
    await loadReqs();
  } catch (e) { toast(e.message, 6000); }
}

/* ================================================================ model & data */
const md = { tab: 'taxonomy', tax: null, cat: 0, comp: 0, compPage: 0 };

async function renderModel() {
  const v = $('#view-model');
  v.innerHTML = `<div class="model-view"><div class="tabs">${[['taxonomy', 'Taxonomy'], ['model', 'AI model'], ['coverage', 'Data coverage']].map(([k, l]) => `<button data-mt="${k}" aria-selected="${k === md.tab}">${l}</button>`).join('')}</div><div class="model-body" id="md-body"></div></div>`;
  $$('#view-model [data-mt]').forEach((b) => b.addEventListener('click', () => { md.tab = b.dataset.mt; renderModel(); }));
  if (md.tab === 'taxonomy') {
    if (!md.tax) { $('#md-body').innerHTML = pending('Loading taxonomy', ''); md.tax = await api('/api/taxonomy'); }
    drawTaxonomy();
  } else if (md.tab === 'model') drawModelCard();
  else drawCoverage();
}

function drawTaxonomy() {
  const t = md.tax;
  const u = t.unique;
  $('#md-body').innerHTML = `<div class="panel" style="grid-template-rows:auto minmax(0,1fr)">
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><b style="font-size:15px">BMW feedback taxonomy</b>
      <span class="chip tone-accent">${u.categories} categories (L1)</span><span class="chip tone-accent">${u.components} unique components (VFC L2)</span><span class="chip tone-accent">${u.issues} issue types (VFC L3)</span><span class="chip">${fmt(u.pairs)} component × issue pairs</span>
      <span class="faint small">Counts are unique reviews, including those labelled by the review model.</span></div>
    <div class="tree" style="grid-template-columns:1fr 1.3fr 1.3fr;min-height:0">
      <div class="card card-pad tcol" id="tx-cat"></div><div class="card card-pad tcol" id="tx-comp"></div><div class="card card-pad tcol" id="tx-issue"></div></div></div>`;
  const cats = t.categories;
  $('#tx-cat').innerHTML = `<div class="label">Category · L1</div>${cats.map((c, i) => `<button class="tnode ${i === md.cat ? 'sel' : ''}" data-cat="${i}"><span class="nm">${esc(c.name)}</span><span class="n">${fmt(c.reviews)}</span></button>`).join('')}`;
  const compCol = $('#tx-comp');
  const comps = cats[md.cat].components;
  const per = Math.max(4, Math.floor((compCol.clientHeight - 70) / 38));
  const pages = Math.max(1, Math.ceil(comps.length / per));
  md.compPage = Math.min(md.compPage, pages - 1);
  const slice = comps.slice(md.compPage * per, md.compPage * per + per);
  compCol.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center"><span class="label">Component · VFC L2 · ${comps.length}</span>
    <span style="display:flex;gap:4px;align-items:center"><button class="btn" style="padding:3px 8px" id="cp-prev" ${md.compPage ? '' : 'disabled'} aria-label="Previous">${icon('left', 12)}</button><span class="faint small">${md.compPage + 1}/${pages}</span><button class="btn" style="padding:3px 8px" id="cp-next" ${md.compPage < pages - 1 ? '' : 'disabled'} aria-label="Next">${icon('right', 12)}</button></span></div>
    ${slice.map((c, i) => { const idx = md.compPage * per + i; return `<button class="tnode ${idx === md.comp ? 'sel' : ''}" data-comp="${idx}"><span class="nm">${esc(c.name)}${c.model_reviews ? ` <span class="chip" style="height:16px;font-size:9.5px" data-tip="reviews labelled by the review model">+${c.model_reviews} AI</span>` : ''}</span><span class="n">${fmt(c.reviews)}</span></button>`; }).join('')}`;
  const comp = comps[md.comp] || comps[0];
  const issueCol = $('#tx-issue');
  const iper = Math.max(4, Math.floor((issueCol.clientHeight - 90) / 38));
  issueCol.innerHTML = `<div class="label">Issue · VFC L3 · ${esc(comp.name)}</div>${comp.issues.slice(0, iper).map((i) => `<div class="tnode"><span class="nm"><span class="swatch" style="background:${SIG_COLOR[i.signal] || 'var(--text-3)'}"></span>${esc(i.name)}</span><span class="n">${fmt(i.reviews)}</span></div>`).join('')}
    ${comp.issues.length > iper ? `<div class="faint small">+${comp.issues.length - iper} more issue types</div>` : ''}
    <div class="legend" style="margin-top:auto"><span class="key"><span class="swatch" style="background:var(--s-praise)"></span>praise</span><span class="key"><span class="swatch" style="background:var(--s-complaint)"></span>complaint</span><span class="key"><span class="swatch" style="background:var(--s-request)"></span>request</span></div>`;
  $$('#tx-cat [data-cat]').forEach((b) => b.addEventListener('click', () => { md.cat = Number(b.dataset.cat); md.comp = 0; md.compPage = 0; drawTaxonomy(); }));
  $$('#tx-comp [data-comp]').forEach((b) => b.addEventListener('click', () => { md.comp = Number(b.dataset.comp); drawTaxonomy(); }));
  const pv = $('#cp-prev'); if (pv) pv.addEventListener('click', () => { md.compPage -= 1; drawTaxonomy(); });
  const nx = $('#cp-next'); if (nx) nx.addEventListener('click', () => { md.compPage += 1; drawTaxonomy(); });
}

function drawModelCard() {
  const c = app.card;
  const body = $('#md-body');
  if (!c) { body.innerHTML = '<div class="empty-state">Model not trained - run python -m pm_copilot build.</div>'; return; }
  const m = c.metrics;
  const aug = c.augmented || {};
  body.innerHTML = `<div class="panel" style="grid-template-rows:auto minmax(0,1fr)">
    <div class="metric-cards">${['category', 'component', 'issue', 'signal'].map((h) => `<div class="card mcard"><div class="label">${h} head · ${m[h].classes} classes</div>
      <div style="display:flex;gap:12px;align-items:baseline"><span class="acc">${pct(m[h].top1_accuracy)}</span><span class="faint small">top-1 · top-3 ${pct(m[h].top3_accuracy)} · F1 ${fmt(m[h].micro_f1, 2)}</span></div>
      <div class="faint small" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">best: ${esc((m[h].best[0] || [''])[0])} (${fmt((m[h].best[0] || [0, 0])[1], 2)})</div></div>`).join('')}</div>
    <div style="display:grid;grid-template-columns:1fr 1.2fr;gap:14px;min-height:0">
      <div class="card card-pad" style="overflow:hidden;display:flex;flex-direction:column;gap:8px"><div class="card-title">How it was built</div>
        <div class="small muted">${esc(c.method)}.</div>
        <div class="small">Trained on <b>${fmt(c.train_reviews)}</b> labelled reviews, tested on <b>${fmt(c.test_reviews)}</b> it never saw (split by review). Vocabulary ${fmt(c.vocabulary)} terms. A component or issue needs ≥ ${c.min_examples_per_class} examples to get its own class (${c.hierarchy.components_modelled} of ${c.hierarchy.components} components, ${c.hierarchy.issues_modelled} of ${c.hierarchy.issues} issues).</div>
        <div class="small">Applied sentence by sentence to the <b>${fmt(aug.reviews_without_label || 0)}</b> reviews BMW's classification left empty: <b>${fmt(aug.reviews_labelled_by_model || 0)}</b> got at least one confident aspect (p ≥ 0.40), adding <b>${fmt(aug.aspects_added || 0)}</b> findings marked as AI-labelled.</div>
        <div class="label" style="margin-top:6px">Weakest components (more data needed)</div><div class="small muted">${m.component.worst.map((w) => `${esc(w[0])} (${fmt(w[1], 2)})`).join(' · ')}</div>
        <div class="label" style="margin-top:6px">Why no LLM</div><div class="small muted">Every prediction is reproducible, runs offline in milliseconds and is explained by the words that drove it.</div></div>
      <div class="card card-pad" style="overflow:hidden;display:grid;grid-template-rows:auto auto minmax(0,1fr);gap:10px"><div class="card-title">Try it on any review</div>
        <form class="reason" id="try-form"><input id="try-text" aria-label="Review text" value="The screen freezes every morning and the seat ventilation is far too weak in summer, but I love how it drives." /><button class="btn primary">Analyse</button></form>
        <div id="try-out" style="min-height:0;overflow:hidden"></div></div>
    </div></div>`;
  $('#try-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const out = $('#try-out');
    out.innerHTML = pending('The model is reading', '');
    try {
      const r = await api('/api/model/analyse', { method: 'POST', body: JSON.stringify({ text: $('#try-text').value }) });
      out.innerHTML = `<div style="display:flex;flex-direction:column;gap:6px">${r.aspects.slice(0, 4).map((a) => `<div class="aspect hit reveal"><span class="sent">“${esc(a.sentence)}”</span>
        <span>${esc(a.category)} › <b>${esc(a.component)}</b> · <span style="color:${SIG_COLOR[a.signal]}">${esc(SIG_LABEL[a.signal] || a.signal)}</span> · ${esc(a.issue)}</span><span class="num faint">p ${fmt(a.p, 2)}</span>
        <span class="terms" style="grid-column:1/-1">${a.terms.map((t) => `<b>${esc(t)}</b>`).join('')}</span></div>`).join('') || '<span class="faint">No confident aspect - try a more specific sentence.</span>'}
        <div class="faint small">Whole review → category <b>${esc(r.category[0].label)}</b> (${fmt(r.category[0].p, 2)}), signal <b>${esc(r.signal[0].label)}</b> (${fmt(r.signal[0].p, 2)}).</div></div>`;
    } catch (err) { out.innerHTML = `<span class="faint">${esc(err.message)}</span>`; }
  });
  $('#try-form').requestSubmit();
}

function drawCoverage() {
  const m = app.meta;
  const regions = Object.keys(m.regions);
  const rows = m.manifest.rows;
  const aug = m.manifest.model_augmented || {};
  $('#md-body').innerHTML = `<div class="panel" style="grid-template-rows:auto minmax(0,1fr)">
    <div class="metric-cards">
      <div class="card mcard"><div class="label">Customer reviews</div><div class="acc">${fmt(rows.verbatims)}</div><div class="faint small">${fmt(rows.findings)} classified findings</div></div>
      <div class="card mcard"><div class="label">AI-labelled</div><div class="acc">${fmt(aug.reviews_labelled_by_model || 0)}</div><div class="faint small">of ${fmt(aug.reviews_without_label || 0)} reviews without a VFC label</div></div>
      <div class="card mcard"><div class="label">Survey scores</div><div class="acc">${fmt(rows.survey)}</div><div class="faint small">CN/EU means + US 7-point scale</div></div>
      <div class="card mcard"><div class="label">Equipment items</div><div class="acc">${fmt(rows.equipment)}</div><div class="faint small">German price lists 07/2026</div></div></div>
    <div class="card card-pad" style="overflow:hidden"><div class="card-head"><div class="card-title">Reviews vs planned ${esc(m.default_horizon)} volume, per vehicle and market</div><span class="faint small">red = sold there but fewer than 30 reviews: the answer relies on the survey</span></div>
      <table class="tbl"><thead><tr><th>Vehicle</th>${regions.map((r) => `<th class="r">${esc(m.regions[r])}</th>`).join('')}</tr></thead>
      <tbody>${Object.entries(m.coverage).map(([d, c]) => `<tr><td><b>${esc(m.derivatives[d].name)}</b> <span class="idcode">${d}</span></td>${regions.map((r) => { const v = m.volumes[d][m.default_horizon][r]; const thin = v && c[r] < 30; return `<td class="r" style="${thin ? 'color:var(--danger)' : ''}">${fmt(c[r])} reviews<br><span class="faint">${compact(v)} units</span></td>`; }).join('')}</tr>`).join('')}</tbody></table>
      <p class="faint small" style="margin-top:12px">Sources: customer verbatims (public reviews, dealer reports, quality survey, loyalty survey), customer studies (China/EU means, US distributions), sales plan 2024/2025/2030, German price lists. Built ${esc(m.manifest.built_at)}.</p></div></div>`;
}

boot();
