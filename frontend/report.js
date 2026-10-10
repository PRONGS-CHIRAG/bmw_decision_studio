/* Printable reports: feature, requirement list, single requirement, decision log. Uses common.js + car.js. */
'use strict';

const params = new URLSearchParams(location.search);
const today = new Date().toISOString().slice(0, 10);
let META = null;

$('#print').addEventListener('click', () => window.print());
$('#close').addEventListener('click', () => window.close());

const head = (kicker, title, sub) => `<header class="doc-head"><div><div class="kicker">${esc(kicker)}</div><h1>${esc(title)}</h1><div class="muted">${esc(sub)}</div></div>
  <div class="doc-meta">Requirements Cockpit<br>Generated ${esc(today)}<br>${esc(params.get('vehicle') || '')}</div></header>`;
const foot = () => `<footer class="doc-foot">Generated from BMW customer verbatims, customer studies, the sales plan and German price lists${META ? ` (data built ${esc(META.manifest.built_at)})` : ''}. AI-proposed content is marked; decisions shown are those recorded by product managers in the audit trail. Assumptions are listed with each item.</footer>`;
const tierName = (t) => ({ P1: 'P1 - address first', P2: 'P2 - plan', P3: 'P3 - monitor' }[t] || t);
const TONE_BG = { critical: 'linear-gradient(135deg,#c43333,#e2604a)', accent: 'linear-gradient(135deg,#1c5cab,#2a78d6)', good: 'linear-gradient(135deg,#0b7f3a,#1baf7a)', warning: 'linear-gradient(135deg,#b8700b,#e9a21a)', neutral: 'linear-gradient(135deg,#45484f,#6d717a)' };

function kpiR(ic, value, label) {
  return `<div class="kpi"><div class="kico">${icon(ic, 18)}</div><div><div class="kval">${esc(value)}</div><div class="klab">${esc(label)}</div></div></div>`;
}

async function main() {
  const doc = $('#doc');
  try {
    META = await api('/api/meta');
    const type = params.get('type');
    if (type === 'feature') await featureReport(doc);
    else if (type === 'requirements') await requirementsReport(doc);
    else if (type === 'requirement') await requirementReport(doc);
    else if (type === 'audit') await auditReport(doc);
    else doc.innerHTML = '<p>Unknown report type.</p>';
    document.title = `${$('h1', doc)?.textContent || 'Report'} · Requirements Cockpit`;
  } catch (e) {
    doc.innerHTML = `<div class="banner">${icon('alert')} ${esc(e.message)}</div>`;
  }
}

/* ------------------------------------------------------------------ feature */
async function featureReport(doc) {
  const vehicle = params.get('vehicle') || 'G60';
  const q = params.get('q') || '';
  const p = new URLSearchParams({ q, derivative: vehicle, horizon: params.get('horizon') || META.default_horizon });
  const b = await api(`/api/brief?${p}`);
  const v = verdictOf(b);
  const d = b.demand;
  const names = META.regions;
  const m = b.materials;
  const mats = [...m.feature.map((x) => ({ ...x, scope: 'This feature' })), ...m.vehicle.map((x) => ({ ...x, scope: 'Whole car' }))];
  const comp = b.competitors.mentions.length ? b.competitors.mentions : b.competitors.vehicle_mentions;
  doc.innerHTML = `${head('Feature report', b.resolution.label, `${b.scope.vehicle} (${vehicle}) · horizon ${b.scope.horizon} · ${fmt(b.scope.verbatims)} customer voices`)}
    <div class="stage blk">${carSVG({ code: vehicle, highlight: b.zones.slice(0, 2) })}</div>
    <div class="verdict-r blk" style="background:${TONE_BG[v.tone]}">${icon(v.icon, 28)}<div><b>${esc(v.label)}</b>${esc(v.line)}</div></div>
    <div class="kgrid blk">${kpiR('users', fmt(d.per_1000, 1), 'per 1,000 voices')}${kpiR('alert', fmt(d.complaints), 'complaints')}${kpiR('request', fmt(d.requests + d.inferred_requests), 'requests')}${kpiR('car', compact(b.sales.units_at_stake), 'cars at stake')}</div>
    <p style="margin-top:12px">${esc(d.headline)}</p>
    ${b.coverage_warning ? `<div class="banner small">${esc(b.coverage_warning)}</div>` : ''}

    <h2>${icon('globe')} Market strategy</h2>
    <p><b>${esc(marketsSentence(b, names))}</b></p>
    <table class="blk"><thead><tr><th>Market</th><th>Recommendation</th><th>Why</th><th class="num">Voices</th><th class="num">Volume ${esc(b.scope.horizon)}</th></tr></thead>
      <tbody>${Object.entries(b.regions).map(([k, r]) => `<tr><td><b>${esc(r.name)}</b></td><td>${esc(r.recommendation.label)}</td><td class="small">${esc(r.recommendation.why)}</td><td class="num">${fmt(r.mentions)} / ${fmt(r.verbatim_base)}</td><td class="num">${fmt(r.volume)}</td></tr>`).join('')}</tbody></table>

    <h2>${icon('scale')} Have it or not?</h2>
    <p><b>${esc(b.kano.class)}</b> - ${esc(b.kano.why)}</p>
    <div class="two blk"><div class="havebox yes"><h4>If we have it</h4>${esc(b.have_vs_not.have)}</div><div class="havebox no"><h4>If we don't</h4>${esc(b.have_vs_not.not_have)}</div></div>
    <p class="muted small" style="margin-top:8px">Today (German price list): ${esc(b.equipment[vehicle]?.status || 'n/a')}.</p>

    <h2>${icon('car')} Cars at stake</h2>
    <p>About <b>${compact(b.sales.units_at_stake)}</b> cars at stake out of <b>${compact(b.sales.exposure)}</b> planned; <b>${compact(b.sales.customers_who_care)}</b> customers care.</p>
    <ul class="small muted">${b.sales.assumptions.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>

    <h2>${icon('alert')} What customers complain about or ask for</h2>
    ${b.issues.length ? `<table class="blk"><thead><tr><th>Signal</th><th>Issue</th><th class="num">Customers</th></tr></thead><tbody>${b.issues.slice(0, 10).map((i) => `<tr><td>${esc(i.signal)}</td><td>${esc(i.issue)}</td><td class="num">${fmt(i.verbatims)}</td></tr>`).join('')}</tbody></table>` : '<p class="muted">No classified complaints or requests.</p>'}

    <h2>${icon('palette')} Materials</h2>
    ${mats.length ? `<table class="blk"><thead><tr><th>Material</th><th>Scope</th><th class="num">Positive</th><th class="num">Negative</th><th>Verdict</th></tr></thead><tbody>${mats.slice(0, 12).map((x) => `<tr><td>${swatch(x.material, 'sm')} ${esc(x.material)}</td><td class="small">${esc(x.scope)}</td><td class="num">${fmt(x.positive)}</td><td class="num">${fmt(x.negative)}</td><td>${x.net > 0 ? 'Liked' : x.net < 0 ? 'Criticised' : 'Mixed'}</td></tr>`).join('')}</tbody></table>` : ''}
    <p class="muted small">${esc(m.note)}</p>

    <h2>${icon('trophy')} Competitors</h2>
    ${comp.length ? `<ul>${comp.slice(0, 6).map((c) => `<li><b>${esc(c.brand)}</b> - ${fmt(c.verbatims)} voices${c.quotes[0] ? `<div class="qbox">“${esc(c.quotes[0].text)}” (${esc(c.quotes[0].verbatim_id)})</div>` : ''}</li>`).join('')}</ul>` : '<p class="muted">No competitor mentions.</p>'}
    ${b.competitors.research.map((r) => `<h3>Web research · ${esc(names[r.region])} · ${esc(r.created_at.slice(0, 10))}</h3><p>${esc(r.result.summary)}</p>
      <table class="blk"><thead><tr><th>Rival</th><th>Has it?</th><th>Detail</th><th>Sources</th></tr></thead><tbody>${r.result.competitors.map((x) => `<tr><td>${esc(x.brand)} ${esc(x.model)}</td><td>${esc(x.availability)}</td><td>${esc(x.detail)}</td><td class="small">${x.source_urls.map((u) => esc(u)).join('<br>')}</td></tr>`).join('')}</tbody></table>`).join('')}

    <h2>${icon('quote')} Customer voices</h2>
    ${b.quotes.slice(0, 8).map((qq) => `<div class="qbox blk">“${esc(qq.text)}” <span class="idcode">- ${esc(qq.verbatim_id)}, ${esc(qq.country)}, ${esc(qq.signal)}</span></div>`).join('')}

    <h2>${icon('book')} Evidence & sources</h2>
    <ul class="small"><li>Evidence: <b>${esc(b.evidence.level)}</b> (${esc(b.evidence.reasons.join(', '))})</li>
      <li>${esc(b.resolution.note)}</li>
      <li>Feedback components: ${esc(b.resolution.components.join(', ') || '–')}</li>
      <li>Customer-study attributes: ${esc(b.resolution.survey_attributes.join(', ') || '–')}</li>
      <li>Price-list items: ${esc((b.equipment[vehicle]?.items || []).map((i) => i.name).join(', ') || '–')}</li></ul>
    ${foot()}`;
}

/* ------------------------------------------------------------------ requirement list */
async function requirementsReport(doc) {
  const vehicle = params.get('vehicle') || 'G60';
  const status = params.get('status') || '';
  const region = params.get('region') || '';
  const top = Number(params.get('top') || 15);
  const p = new URLSearchParams({ derivative: vehicle });
  if (status) p.set('status', status);
  if (region) p.set('region', region);
  const op = new URLSearchParams({ derivative: vehicle });
  if (region) op.set('region', region);
  const [reqs, ov] = await Promise.all([api(`/api/requirements?${p}`), api(`/api/overview?${op}`)]);
  const details = await Promise.all(reqs.slice(0, top).map((r) => api(`/api/requirements/${encodeURIComponent(r.id)}`)));
  const names = META.regions;
  const count = (f) => reqs.filter(f).length;
  const scope = `${status || 'All open'} requirements${region ? ` · ${names[region]}` : ''}`;
  const max = Math.max(1, ...ov.zones.map((z) => z.verbatims));
  const spots = ov.zones.filter((z) => z.verbatims || z.top_tier).map((z) => ({ key: z.key, label: z.label, tier: z.top_tier, size: 9 + 10 * Math.sqrt(z.verbatims / max) }));
  doc.innerHTML = `${head('Requirements report', `${ov.vehicle.name} (${vehicle})`, `${scope} · ranked by priority`)}
    <div class="kgrid blk">${kpiR('board', fmt(reqs.length), 'requirements')}${kpiR('alert', fmt(count((r) => r.priority.tier === 'P1')), 'P1 - address first')}${kpiR('check', fmt(count((r) => r.status === 'Approved')), 'approved')}${kpiR('spark', fmt(count((r) => r.status === 'Proposed')), 'awaiting decision')}</div>
    <h2>${icon('car')} Where customers feel it</h2>
    <div class="stage blk">${carSVG({ code: vehicle, hotspots: spots })}</div>
    <p class="muted small">Dot size = customer voices; colour = most urgent open item (red P1, orange P2, blue P3).</p>
    <table class="blk"><thead><tr><th>Car area</th><th class="num">Voices</th><th class="num">Complaints</th><th class="num">Requests</th><th>Top problem</th></tr></thead>
      <tbody>${[...ov.zones].filter((z) => z.verbatims).sort((a, c) => c.verbatims - a.verbatims).slice(0, 10).map((z) => `<tr><td>${esc(z.label)}</td><td class="num">${fmt(z.verbatims)}</td><td class="num">${fmt(z.complaints)}</td><td class="num">${fmt(z.requests)}</td><td class="small">${esc(z.issues[0] ? `${z.issues[0].issue} (${z.issues[0].component})` : '–')}</td></tr>`).join('')}</tbody></table>

    <h2>${icon('board')} Priority list</h2>
    <table><thead><tr><th>#</th><th>Requirement</th><th>Type</th><th>Tier</th><th class="num">Score</th><th>Evidence</th><th>Markets</th><th>Status</th></tr></thead>
      <tbody>${reqs.slice(0, 60).map((r, i) => `<tr class="blk"><td>${i + 1}</td><td><b>${esc(r.title)}</b><div class="idcode">${esc(r.id)}</div></td><td>${esc(TYPE_INFO[r.type]?.label || r.type)}</td><td>${esc(r.priority.tier)}</td>
        <td class="num">${fmt(r.priority.score, 1)}</td><td>${esc(r.evidence.level)}</td><td class="small">${Object.entries(r.regions).map(([k, g]) => `<span style="white-space:nowrap">${esc(k)} ${esc(shortRec(g.recommendation))}</span>`).join(' · ')}</td><td>${esc(r.status === 'Proposed' ? 'Awaiting decision' : r.status)}</td></tr>`).join('')}</tbody></table>
    ${reqs.length > 60 ? `<p class="muted small">… and ${fmt(reqs.length - 60)} more (see the data export).</p>` : ''}

    <h2>${icon('report')} Top ${fmt(details.length)} in detail</h2>
    ${details.map((r) => reqBlock(r)).join('')}
    ${foot()}`;
}

function reqBlock(r, withHistory = false) {
  const names = META.regions;
  return `<section class="req-item">
    <div class="rh">${scoreRing(r.priority.score, 50, r.priority.tier)}<div><div class="idcode">${esc(r.id)} · ${esc(TYPE_INFO[r.type]?.label || r.type)} · ${esc(tierName(r.priority.tier))} · ${esc(r.status === 'Proposed' ? 'Awaiting decision' : r.status)}</div><h3 style="margin:2px 0">${esc(r.title)}</h3></div></div>
    <p>${esc(r.description)}</p>
    <h3>Done when</h3><ul>${r.acceptance_criteria.map((c) => `<li>${esc(c)}</li>`).join('')}</ul>
    <h3>Why this priority</h3><p class="small">${esc(r.priority_rationale)}</p>
    <h3>Evidence: ${esc(r.evidence.level)}</h3><p class="small">${esc(r.evidence.reasons.join(' · '))}</p>
    ${r.quotes.slice(0, 2).map((q) => `<div class="qbox">“${esc(q.text)}” <span class="idcode">- ${esc(q.verbatim_id)}, ${esc(q.country)}</span></div>`).join('')}
    <h3>Market strategy</h3><p class="small">${Object.entries(r.regions).map(([k, g]) => `<b>${esc(names[k])}</b>: ${esc(g.recommendation.label)}`).join(' · ')}</p>
    <h3>Assumptions & uncertainties</h3><ul class="small">${r.assumptions.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
    <h3>Sources</h3><p class="small">${r.sources.map((s) => `${esc(s.type)} (${esc(s.file || '')}${s.count ? `, ${fmt(s.count)} findings` : ''})`).join(' · ')} · ${fmt(r.linked_findings.length)} linked finding IDs</p>
    ${withHistory ? `<h3>Decision history</h3><table><thead><tr><th>When</th><th>Who</th><th>What</th><th>Why</th></tr></thead><tbody>${(r.audit || []).map((a) => `<tr><td class="idcode">${esc(a.ts.slice(0, 16).replace('T', ' '))}</td><td>${esc(a.actor)} (${esc(a.actor_type)})</td><td>${esc(a.action.replace(/_/g, ' '))}${a.field ? `: ${esc(a.field)}` : ''}</td><td class="small">${esc(String(a.rationale || '').slice(0, 220))}</td></tr>`).join('')}</tbody></table>` : ''}
  </section>`;
}

/* ------------------------------------------------------------------ single requirement */
async function requirementReport(doc) {
  const r = await api(`/api/requirements/${encodeURIComponent(params.get('id'))}`);
  doc.innerHTML = `${head('Requirement', r.title, `${r.vehicle} (${r.derivative}) · ${r.id}`)}
    <div class="stage blk">${carSVG({ code: r.derivative, highlight: [r.zone] })}</div>
    ${reqBlock(r, true)}
    <h2>${icon('up')} Score breakdown</h2>
    <table class="blk"><thead><tr><th>Factor</th><th class="num">Value</th><th class="num">Weight</th><th class="num">Points</th><th>Basis</th></tr></thead>
      <tbody>${Object.entries(r.priority.weights).filter(([, w]) => w > 0).map(([k, w]) => `<tr><td>${esc(k.replace('_', ' '))}</td><td class="num">${fmt(r.factors[k], 2)}</td><td class="num">${fmt(w, 2)}</td><td class="num">${fmt(r.priority.contributions[k], 1)}</td><td class="small">${esc(r.factor_notes[k])}</td></tr>`).join('')}</tbody></table>
    ${foot()}`;
  grow(doc);
}

/* ------------------------------------------------------------------ audit */
async function auditReport(doc) {
  const rows = await api('/api/audit?limit=2000');
  const pm = rows.filter((a) => a.actor_type === 'pm');
  doc.innerHTML = `${head('Decision log', 'Audit trail', `${fmt(rows.length)} events · ${fmt(pm.length)} by product managers`)}
    <table><thead><tr><th>When (UTC)</th><th>Who</th><th>What</th><th>Requirement</th><th>Change</th><th>Why</th></tr></thead>
      <tbody>${rows.map((a) => `<tr class="blk"><td class="idcode">${esc(a.ts.replace('T', ' ').replace('+00:00', ''))}</td><td>${esc(a.actor)} <span class="muted">(${esc(a.actor_type)})</span></td><td>${esc(a.action.replace(/_/g, ' '))}</td>
        <td class="idcode">${esc(a.requirement_id || '–')}</td><td class="small">${a.field ? `${esc(a.field)}: ${esc(JSON.stringify(a.old_value ?? '–').slice(0, 60))} → ${esc(JSON.stringify(a.new_value ?? '–').slice(0, 60))}` : ''}</td>
        <td class="small">${esc(String(a.rationale || '').slice(0, 240))}</td></tr>`).join('')}</tbody></table>
    ${foot()}`;
}

main().then(() => grow(document));
