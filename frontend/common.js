/* Shared helpers: formatting, API, icons, chips, verdicts, swatches, animation. All data strings go through esc(). */
'use strict';

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n, d = 0) => (n == null || Number.isNaN(Number(n)) ? '–' : Number(n).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }));
const pct = (x, d = 0) => (x == null ? '–' : `${(x * 100).toFixed(d)}%`);
const compact = (n) => (n == null ? '–' : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}K` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : fmt(n));
const REDUCED_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { const body = await res.json(); msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch { /* not json */ }
    throw new Error(msg);
  }
  return res.json();
}

/* ------------------------------------------------------------------ icons (24px stroke) */
const ICONS = {
  users: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5"/><circle cx="17.5" cy="9" r="2.5"/><path d="M16 14.6c2.8.2 5 1.9 5 4.9"/>',
  alert: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5"/><path d="M12 17.2v.1"/>',
  request: '<path d="M4 5h16v11H9.5L4 20z"/><path d="M12 8v5M9.5 10.5h5"/>',
  thumb: '<path d="M7 11v9H4v-9z"/><path d="M7 11l4-7c1.6 0 2.6 1.2 2.1 3L12.4 10H18c1.2 0 2 1 1.7 2.2l-1.6 6.4c-.3 1-1 1.4-2 1.4H7"/>',
  thumbdown: '<path d="M7 13V4H4v9z"/><path d="M7 13l4 7c1.6 0 2.6-1.2 2.1-3L12.4 14H18c1.2 0 2-1 1.7-2.2l-1.6-6.4c-.3-1-1-1.4-2-1.4H7"/>',
  car: '<path d="M3 16v-2.5l2-4.6C5.4 8 6.2 7.5 7.2 7.5h9.6c1 0 1.8.5 2.2 1.4l2 4.6V16"/><path d="M3 16h2m4 0h6m4 0h2"/><circle cx="7" cy="16.5" r="2"/><circle cx="17" cy="16.5" r="2"/><path d="M4.5 12.5h15"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c3.2 3.4 3.2 14.6 0 18-3.2-3.4-3.2-14.6 0-18z"/>',
  report: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9 12h7M9 16h7"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  undo: '<path d="M9 7 4 12l5 5"/><path d="M4 12h10a5 5 0 0 1 0 10h-2"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.3-4.3"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/>',
  board: '<rect x="3.5" y="4" width="5" height="16" rx="1.5"/><rect x="9.5" y="4" width="5" height="11" rx="1.5"/><rect x="15.5" y="4" width="5" height="7" rx="1.5"/>',
  history: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8v.1"/>',
  left: '<path d="M15 6l-6 6 6 6"/>',
  right: '<path d="M9 6l6 6-6 6"/>',
  download: '<path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M5 20h14"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.4 0 2-1 2-2s-.9-1.9 0-2.8c.8-.8 2-.7 3-.7a4 4 0 0 0 4-4C21 6.8 17 3 12 3z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10.5" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/>',
  trophy: '<path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 5.5H4.5v1.5a3 3 0 0 0 3.5 3M16 5.5h3.5v1.5a3 3 0 0 1-3.5 3"/><path d="M12 13v4M9 21h6M10 17h4"/>',
  quote: '<path d="M6 7h4v5c0 2.8-1.8 4.6-4 5"/><path d="M14 7h4v5c0 2.8-1.8 4.6-4 5"/>',
  scale: '<path d="M12 4v16M6 20h12M4 8h16"/><path d="M7 8l-3 6.5h6zM17 8l-3 6.5h6z"/>',
  up: '<path d="M4 17l6-6 4 4 6-7"/><path d="M15 8h5v5"/>',
  wrench: '<path d="M14.5 6.5a4 4 0 0 0 5 5L11 20a2.1 2.1 0 0 1-3-3l8.5-8.5"/><path d="M14.5 6.5 17 4l3 3-2.5 2.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  shield: '<path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
  map: '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
  book: '<path d="M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h9"/>',
  print: '<path d="M7 9V3h10v6"/><rect x="3.5" y="9" width="17" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
  zone: '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/>',
};
function icon(name, size = 18, cls = '') {
  return `<svg class="ico ${cls}" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
}
const ZONE_ICON = {
  exterior: 'car', lights: 'spark', wheels: 'zone', dynamics: 'up', powertrain: 'wrench', charging: 'spark', assist: 'shield',
  screens: 'board', connect: 'globe', seats: 'users', climate: 'zone', roof: 'spark', interior: 'palette', space: 'board',
  access: 'check', ownership: 'book',
};

/* ------------------------------------------------------------------ chips & status */
const STATUS = {
  good: { color: 'var(--good)', icon: '✓' }, warning: { color: 'var(--warning)', icon: '◐' },
  serious: { color: 'var(--serious)', icon: '!' }, critical: { color: 'var(--critical)', icon: '▲' },
  neutral: { color: 'var(--axis)', icon: '○' }, accent: { color: 'var(--accent)', icon: '●' },
};
function chip(label, kind = 'neutral', tip = '', cls = '') {
  const s = STATUS[kind] || STATUS.neutral;
  return `<span class="chip ${cls}" ${tip ? `data-tip="${esc(tip)}"` : ''}><span class="dot" style="background:${s.color}"></span><span aria-hidden="true" class="chip-ico">${s.icon}</span>${esc(label)}</span>`;
}
const TIER_KIND = { P1: 'critical', P2: 'warning', P3: 'neutral' };
const TIER_TIP = { P1: 'P1 - address first', P2: 'P2 - plan', P3: 'P3 - monitor' };
const tierChip = (t, cls) => chip(t, TIER_KIND[t], TIER_TIP[t], cls);
const evidenceChip = (ev, cls) => chip(`${ev.level || ev} evidence`, { High: 'good', Medium: 'warning', Low: 'serious' }[ev.level || ev], (ev.reasons || []).join(' · '), cls);
const STATUS_KIND = { Approved: 'good', Rejected: 'critical', 'Changes requested': 'warning', Proposed: 'accent', Obsolete: 'neutral' };
const statusChip = (s, cls) => chip(s === 'Proposed' ? 'Awaiting decision' : s, STATUS_KIND[s], '', cls);
const LEVEL_KIND = { high: 'good', medium: 'accent', 'medium-low': 'warning', low: 'serious', unknown: 'neutral', none: 'neutral' };
const TYPE_INFO = {
  FIX: { label: 'Fix', icon: 'wrench', tip: 'Customers complain about something the car has' },
  ADD: { label: 'Add', icon: 'plus', tip: 'Customers ask for something they do not have' },
  PROTECT: { label: 'Protect', icon: 'shield', tip: 'A strength the next car must not lose' },
  FEATURE: { label: 'Feature', icon: 'search', tip: 'Created by a PM from the explorer' },
};
const typeTag = (t) => `<span class="type-tag type-${esc(t)}" data-tip="${esc(TYPE_INFO[t]?.tip || '')}">${icon(TYPE_INFO[t]?.icon || 'info', 14)}${esc(TYPE_INFO[t]?.label || t)}</span>`;

function shortRec(rec) {
  const l = rec.label || '';
  if (l.startsWith('Standard - fix')) return 'Fix';
  if (l.startsWith('Standard - high')) return 'Standard';
  if (l.startsWith('Standard or')) return 'Std / pack';
  if (l.startsWith('Optional')) return 'Optional';
  if (l.startsWith('Low')) return 'Low';
  if (l.startsWith('Not sold')) return 'Not sold';
  if (l.startsWith('Likely')) return 'Validate';
  return 'Research';
}
function marketStrip(regions, names) {
  return `<div class="mstrip">${Object.entries(regions).map(([k, r]) => {
    const rec = r.recommendation;
    return `<span class="mcell lv-${esc(rec.level)}" data-tip="${esc(`${names[k] || k}: ${rec.label} - ${rec.why}`)}">${esc(k)}</span>`;
  }).join('')}</div>`;
}

/* score ring: animated stroke from 0 to score */
function scoreRing(score, size = 46, tier = '') {
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  return `<svg class="ring tier-${esc(tier)}" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="score ${fmt(score)}">
    <circle class="ring-track" cx="${size / 2}" cy="${size / 2}" r="${r}"/>
    <circle class="ring-fill" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${c.toFixed(1)}" data-offset="${(c * (1 - Math.min(100, score) / 100)).toFixed(1)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
    <text x="50%" y="50%" text-anchor="middle" dy="0.35em">${fmt(score)}</text></svg>`;
}

/* ------------------------------------------------------------------ verdicts (plain language) */
function verdictOf(b) {
  const d = b.demand;
  const k = b.kano.class;
  const req = d.requests + d.inferred_requests;
  if (d.verbatims_mentioning < 5) return { key: 'research', label: 'Research first', tone: 'neutral', icon: 'search', line: `Only ${d.verbatims_mentioning} customers mention it - not enough to decide. Validate with a clinic or web research.` };
  if (k === 'Must-be') return { key: 'fix', label: 'Fix it', tone: 'critical', icon: 'wrench', line: `Customers expect it to just work - ${d.complaints} complain about today's version.` };
  if (k === 'Unmet need') return { key: 'add', label: 'Add it', tone: 'accent', icon: 'plus', line: `Customers are asking for it - ${req} requests.` };
  if (k === 'Attractive') return { key: 'keep', label: 'Keep & promote', tone: 'good', icon: 'shield', line: `A delighter - ${d.praise} customers praise it. Don't lose it.` };
  if (k === 'Performance') return { key: 'improve', label: 'Improve it', tone: 'warning', icon: 'up', line: `The better it works, the happier customers are (${d.praise} praise vs ${d.complaints} complaints).` };
  return { key: 'research', label: 'Research first', tone: 'neutral', icon: 'search', line: b.kano.why };
}

function marketsSentence(b, names) {
  const groups = {};
  Object.entries(b.regions).forEach(([k, r]) => { const s = shortRec(r.recommendation); (groups[s] = groups[s] || []).push(names[k] || k); });
  const order = ['Fix', 'Standard', 'Std / pack', 'Optional', 'Validate', 'Research', 'Low', 'Not sold'];
  const verbs = { Fix: 'fix it in', Standard: 'make it standard in', 'Std / pack': 'standard or a package in', Optional: 'offer as an option in', Validate: 'validate in', Research: 'research', Low: 'low relevance in', 'Not sold': 'not sold in' };
  return order.filter((o) => groups[o]).map((o) => `${verbs[o]} ${groups[o].join(' & ')}`).join('; ').replace(/^./, (c) => c.toUpperCase()) + '.';
}

/* ------------------------------------------------------------------ material swatches */
const SWATCH = {
  'Leather (Merino / Nappa)': 'leather', 'Vegan leather (Veganza / Sensatec)': 'vegan', 'Alcantara / suede': 'alcantara',
  'Wood trim': 'wood', 'Carbon fibre': 'carbon', 'Aluminium / metal': 'alu', 'Piano black / high gloss': 'piano',
  'Hard plastic': 'plastic', Chrome: 'chrome', 'Fabric / cloth': 'fabric', 'Crystal / glass applications': 'glass',
};
function swatch(material, size = 'md') { return `<span class="swatch-tex sw-${SWATCH[material] || 'plastic'} ${size}" aria-hidden="true"></span>`; }

/* ------------------------------------------------------------------ animation helpers */
function countUp(root = document) {
  $$('[data-count]', root).forEach((el) => {
    const target = Number(el.dataset.count);
    const dec = Number(el.dataset.dec || 0);
    const fmtFn = el.dataset.compact ? compact : (v) => fmt(v, dec);
    if (REDUCED_MOTION || !Number.isFinite(target)) { el.textContent = fmtFn(target); return; }
    const t0 = performance.now();
    const dur = 900;
    const step = (t) => {
      const p = Math.min(1, (t - t0) / dur);
      const e = 1 - (1 - p) ** 3;
      el.textContent = fmtFn(dec ? target * e : Math.round(target * e));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}
function grow(root = document) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    $$('[data-w]', root).forEach((el) => { el.style.width = el.dataset.w; });
    $$('.ring-fill[data-offset]', root).forEach((el) => { el.style.strokeDashoffset = `${el.dataset.offset}px`; });
  }));
}
function animateIn(root) { countUp(root); grow(root); }

/* single-series horizontal bars that grow in */
function barRows(rows, { max, color = 'var(--seq-fill)', valueFmt = (v) => fmt(v) } = {}) {
  const m = max ?? Math.max(1, ...rows.map((r) => r.value));
  return `<div class="bars">${rows.map((r) => `<div class="lab" title="${esc(r.label)}">${esc(r.label)}</div>
    <div class="bar-track" data-tip="${esc(r.tip || `${r.label}: ${valueFmt(r.value)}`)}"><div class="bar" data-w="${((r.value / m) * 86).toFixed(1)}%" style="width:0;background:${r.color || color}"></div><span class="bar-val">${valueFmt(r.value)}</span></div>`).join('')}</div>`;
}

function setupTooltips() {
  const tip = document.createElement('div');
  tip.className = 'tip';
  tip.setAttribute('role', 'tooltip');
  tip.hidden = true;
  document.body.appendChild(tip);
  document.addEventListener('mouseover', (e) => {
    const el = e.target.closest('[data-tip]');
    if (!el || !el.dataset.tip) { tip.hidden = true; return; }
    tip.textContent = el.dataset.tip;
    tip.hidden = false;
  });
  document.addEventListener('mousemove', (e) => {
    if (tip.hidden) return;
    tip.style.left = `${Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${Math.min(e.clientY + 16, window.innerHeight - tip.offsetHeight - 8)}px`;
  });
}
