/* Feature decisions in the existing vanilla application. All evaluation happens in Python. */
'use strict';

window.DecisionWorkspace = (() => {
  const criteriaLabels = { customer: 'Customer value', future: 'Future relevance', delivery: 'Delivery maturity', regional: 'Regional fit', experience: 'BMW experience' };
  const actionLabels = { improve: 'Improve', add: 'Add', retain: 'Retain', remove: 'Remove' };
  const tabs = [{ id: 'evidence', label: 'Evidence & actions' }, { id: 'scenarios', label: 'Scenarios & weights' }, { id: 'alternatives', label: 'Alternatives' }, { id: 'review', label: 'Review & history' }];
  const state = {
    meta: null, metaError: '', active: true, tab: 'evidence', revision: 0, dirty: false,
    context: { project_id: 'default', vehicle: '', launch_year: null, markets: ['EU', 'CN', 'US'], powertrain: null },
    featureInput: '', features: [], evidence: null, evidenceError: '', candidates: [], nextId: 1,
    config: { weights: {}, market_weights: {}, budget: null, currency: '', cost_basis: 'development investment', scenario: 'baseline', reviewer: '', rationale: '', value_floor: .85 },
    run: null, selectedPortfolio: '', history: [], historyError: '', runError: '', lastMessage: '',
    question: '', answer: null, questionError: '', reader: null, readerError: '', research: null, researchError: '', researchMarket: '',
    decisionStatus: 'Approved', decisionRationale: '', acknowledge: false, decisionError: '',
    busy: new Set(), requests: new Map(), dialog: null, dialogOpener: null,
  };
  let root;
  const e = value => esc(value);
  const n = (value, decimals = 0) => value == null || value === '' ? 'Unknown' : fmt(value, decimals);
  const list = value => Array.isArray(value) ? value : [];
  const tag = (label, type = '') => `<span class="dw-tag ${type}">${e(label)}</span>`;
  const option = (value, label, selected) => `<option value="${e(value)}" ${value === selected ? 'selected' : ''}>${e(label)}</option>`;
  const empty = (title, text) => `<div class="dw-empty"><h3>${e(title)}</h3><p>${e(text)}</p></div>`;
  const errorBox = message => message ? `<div class="dw-error" role="alert">${e(message)}</div>` : '';
  const progress = (key, label) => state.busy.has(key) ? `<div class="dw-progress" role="status"><span class="spinner" aria-hidden="true"></span>${e(label)}</div>` : '';
  const marketName = id => state.meta?.markets?.[id] || id;
  const featureName = id => state.evidence?.features?.find(feature => feature.id === id)?.label || state.meta?.features?.find(feature => feature.key === id)?.label || id;
  const plain = value => typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? 'Unknown');
  const numericInput = (id, label, value, attrs, hint = '', max = 100, min = 0) => `<div><label for="${e(id)}">${e(label)}</label><input id="${e(id)}" type="number" min="${min}" ${max == null ? '' : `max="${max}"`} step="any" value="${value == null ? '' : e(value)}" placeholder="Unknown" ${attrs}><span class="dw-help">${e(hint || 'PM planning assumption')}</span></div>`;
  const textInput = (id, label, value, attrs, hint = '') => `<div><label for="${e(id)}">${e(label)}</label><input id="${e(id)}" value="${e(value)}" ${attrs}><span class="dw-help">${e(hint)}</span></div>`;
  const currentPortfolio = () => list(state.run?.portfolios).find(portfolio => portfolio.id === state.selectedPortfolio);

  async function request(key, path, options = {}) {
    state.requests.get(key)?.abort();
    const controller = new AbortController();
    state.requests.set(key, controller);
    state.busy.add(key);
    try {
      const response = await api(path, { ...options, signal: controller.signal });
      if (state.requests.get(key) !== controller) throw new DOMException('Superseded request', 'AbortError');
      return response;
    } finally {
      if (state.requests.get(key) === controller) {
        state.requests.delete(key);
        state.busy.delete(key);
      }
    }
  }

  const post = body => ({ method: 'POST', body: JSON.stringify(body) });
  function cancel(key) { state.requests.get(key)?.abort(); state.requests.delete(key); state.busy.delete(key); }
  function reportError(error, field) { if (error.name !== 'AbortError') state[field] = error.message || 'The request could not be completed.'; }
  function markDirty() {
    state.revision += 1;
    state.dirty = true;
    state.lastMessage = '';
    updateStatus();
  }
  function updateStatus() {
    const draft = root?.querySelector('#dw-draft-status');
    if (draft) draft.textContent = state.dirty ? 'Unapplied changes' : state.run ? `Saved run ${state.run.id || state.run.run_id}` : 'New planning draft';
    const runState = root?.querySelector('#dw-run-note');
    if (runState) runState.textContent = state.lastMessage || (state.dirty && state.run ? 'Edits will create a new run. The saved result remains unchanged.' : state.run ? 'Saved inputs and results are frozen. Decisions are recorded separately.' : 'Enter context, review evidence, then supply your planning assumptions.');
  }
  function invalidateEvidence() {
    ['evidence', 'reader', 'question', 'research'].forEach(cancel);
    state.evidence = null;
    state.reader = null;
    state.answer = null;
    state.research = null;
    state.evidenceError = state.features.length ? 'Context changed. Load evidence again before evaluating this draft.' : '';
    markDirty();
  }

  async function loadMeta() {
    state.metaError = '';
    const pendingRequest = request('meta', '/api/decision/meta');
    render();
    try {
      state.meta = await pendingRequest;
      state.context.launch_year ??= state.meta.default_launch_year ?? null;
      state.context.markets = state.context.markets.filter(market => market in state.meta.markets);
      state.config.weights = { ...(state.meta.weights || {}) };
      state.researchMarket = state.context.markets[0] || '';
    } catch (error) { reportError(error, 'metaError'); }
    render();
    if (state.meta) loadHistory(false);
  }

  function render() {
    if (!root) return;
    if (!state.meta) {
      root.innerHTML = `<div class="dw"><div class="dw-title"><div><div class="dw-eyebrow">Product planning</div><h1>Feature decision workspace</h1><p>Evidence, regional trade-offs and a decision you can explain.</p></div></div>${progress('meta', 'Loading decision metadata')}${errorBox(state.metaError)}${state.metaError ? '<button class="dw-btn" data-dw="retry-meta">Retry connection</button>' : ''}</div>`;
      return;
    }
    root.innerHTML = `<div class="dw">
      <div class="dw-title"><div><div class="dw-eyebrow">Product planning / Feature decision</div><h1>Turn customer evidence into a decision.</h1><p>Compare customer value across markets. Keep uncertainty and delivery constraints visible.</p></div><div class="dw-tags">${tag('AI proposes. You decide.')}<span id="dw-draft-status" class="dw-tag assumption"></span></div></div>
      ${renderContext()}
      <div class="dw-scope-row"><section class="dw-card dw-scope"><div><div class="dw-eyebrow">Active future scenario</div>${tag('Scenario evaluation', 'scenario')}</div><label class="dw-sr" for="dw-active-scenario">Active future scenario</label><select id="dw-active-scenario" data-config="scenario">${list(state.meta.scenarios).map(scenario => option(scenario, scenario, state.config.scenario)).join('')}</select></section><section class="dw-card dw-scope"><div><div class="dw-eyebrow">Selected strategy</div><strong class="dw-small" id="dw-selected-title">${e(currentPortfolio()?.profile || 'No evaluated portfolio selected')}</strong></div>${tag(state.run?.status || 'Evaluation required')}</section></div>
      <div class="dw-layout"><div><div class="dw-tabs" role="tablist" aria-label="Decision workflow">${tabs.map(tab => `<button role="tab" id="dw-tab-${tab.id}" aria-controls="dw-panel" aria-selected="${state.tab === tab.id}" tabindex="${state.tab === tab.id ? '0' : '-1'}" data-dw="tab" data-tab="${tab.id}">${e(tab.label)}</button>`).join('')}</div><section class="dw-panel" id="dw-panel" role="tabpanel" aria-labelledby="dw-tab-${state.tab}" tabindex="0">${renderPanel()}</section></div>${renderAside()}</div>
      <div class="dw-bottom" ${state.active ? '' : 'hidden'}><div><strong class="dw-small">${state.run ? `Saved ${e(state.run.status)} result` : 'PM planning draft'}</strong><p id="dw-run-note"></p></div><div class="dw-bottom-actions"><button class="dw-btn" data-dw="tab" data-tab="review">Review & history</button><button class="dw-btn primary" data-dw="evaluate" ${state.busy.has('evaluate') || !state.candidates.length ? 'disabled' : ''}>${state.busy.has('evaluate') ? 'Evaluating…' : 'Apply & evaluate'} ${icon('right', 14)}</button></div></div>
      <dialog class="dw-dialog" id="dw-dialog" aria-labelledby="dw-dialog-title"></dialog>
    </div>`;
    updateStatus();
    const dialog = root.querySelector('#dw-dialog');
    dialog.addEventListener('close', () => { state.dialog = null; state.dialogOpener?.focus(); });
  }

  function renderContext() {
    return `<section class="dw-card dw-pad dw-context" aria-labelledby="dw-context-title"><div class="dw-head"><h2 id="dw-context-title">Decision context</h2>${tag('PM inputs · assumption', 'assumption')}</div><div class="dw-context-grid">
      <div><label for="dw-vehicle">Vehicle / predecessor</label><select id="dw-vehicle" data-context="vehicle">${option('', 'Select a vehicle', state.context.vehicle)}${Object.entries(state.meta.vehicles || {}).map(([id, vehicle]) => option(id, `${vehicle.name || id} · ${id}`, state.context.vehicle)).join('')}</select></div>
      <div><label for="dw-feature">Feature / customer need</label><input id="dw-feature" list="dw-features" value="${e(state.featureInput)}" placeholder="Choose a feature or enter a specific need" data-state="featureInput"><datalist id="dw-features">${list(state.meta.features).map(feature => `<option value="${e(feature.label)}">${e(feature.key)}</option>`).join('')}</datalist></div>
      ${numericInput('dw-year', 'Launch year', state.context.launch_year, 'data-context="launch_year"', 'Project planning assumption', 9999, 1)}
      <div><label for="dw-powertrain">Powertrain</label><select id="dw-powertrain" data-context="powertrain">${option('', 'All / unspecified', state.context.powertrain || '')}${['ICE', 'BEVE', 'PHEV'].map(value => option(value, value === 'BEVE' ? 'BEV' : value, state.context.powertrain)).join('')}</select></div>
      <fieldset><legend class="dw-field-label">Target markets</legend><div class="dw-markets">${Object.entries(state.meta.markets || {}).map(([id, label]) => `<label class="dw-market-pick"><input type="checkbox" data-market="${e(id)}" ${state.context.markets.includes(id) ? 'checked' : ''}>${e(id === 'CN' ? 'China' : id)}</label>`).join('')}</div></fieldset>
      </div><div class="dw-context-bottom"><p>Direct feature evidence stays separate from broader component context. Source coverage is shown for each market.</p><button class="dw-btn primary" data-dw="load-evidence" ${state.busy.has('evidence') ? 'disabled' : ''}>${state.busy.has('evidence') ? 'Loading evidence…' : 'Load feature evidence'} ${icon('search', 14)}</button></div>
      ${state.features.length ? `<div class="dw-feature-tags" aria-label="Features in this draft">${state.features.map(feature => `<span class="dw-tag observed">${e(featureName(feature))}</span>`).join('')}<button data-dw="clear-features" type="button">Clear draft features</button></div>` : ''}
      ${progress('evidence', 'Reading the scoped source files and resolving direct evidence')}${errorBox(state.evidenceError)}
    </section>`;
  }

  function renderPanel() {
    if (state.tab === 'scenarios') return renderScenarios();
    if (state.tab === 'alternatives') return renderAlternatives();
    if (state.tab === 'review') return renderReview();
    return renderEvidence();
  }

  function renderEvidence() {
    const evidence = state.evidence;
    return `<div class="dw-head"><div><h2>Compare decisions across markets</h2><p>Complaints, requests and praise answer different questions. None receives automatic priority.</p></div>${tag(evidence ? 'Source snapshot loaded' : 'Evidence not loaded', evidence ? 'observed' : '')}</div>
      <div class="dw-summary"><article class="dw-card"><h3>Customer priority</h3><div class="dw-value">${state.run ? 'See evaluations' : 'Unknown'}</div><p>Reviewed benefit, a fixed frequency rubric and common PM weights.</p></article><article class="dw-card"><h3>Evidence readiness</h3><div class="dw-value">${evidence ? 'Inspect by market' : 'Unknown'}</div><p>Direct scope, sample, source mix and unresolved interpretation stay visible.</p></article><article class="dw-card"><h3>Incremental cars sold</h3><div class="dw-value">Unknown</div><p>Source sales volume describes possible exposure, not a feature's causal sales effect.</p></article></div>
      ${!evidence ? empty('Start with a specific customer need', 'Choose a vehicle, feature and target markets, then load the available evidence. Missing observations remain unknown.') : list(evidence.features).map(feature => renderFeature(feature)).join('')}
      <section class="dw-section"><div class="dw-head"><div><h2>Propose customer-facing actions</h2><p>One action per feature and market. Competing actions are evaluated as alternatives.</p></div>${tag('PM assumptions', 'assumption')}</div>
      ${renderAddAction()}
      <div class="dw-candidates dw-section">${state.candidates.length ? state.candidates.map(renderCandidate).join('') : empty('No actions proposed', 'Add an improvement, an unmet capability, a retention choice or an omission proposal. Enter the customer outcome and review its assumptions before evaluation.')}</div>
      ${errorBox(state.runError)}${progress('evaluate', 'Validating inputs, evaluating constraints and saving a frozen run')}
      </section>`;
  }

  function renderFeature(feature) {
    return `<section class="dw-section"><div class="dw-head"><div><h3>${e(feature.label || feature.id)}</h3><p>${e(typeof feature.resolution === 'string' ? feature.resolution : feature.resolution?.note || feature.resolution?.status || 'Exact and contextual matches are separated in the evidence inspector.')}</p></div><button class="dw-btn small" data-dw="evidence" data-feature="${e(feature.id)}">Inspect all sources ${icon('right', 12)}</button></div><div class="dw-table-wrap" tabindex="0" role="region" aria-label="${e(feature.label)} market evidence"><table class="dw-table dw-evidence-table"><thead><tr><th>Market / sample<br>Observed</th><th>Direct feedback<br>Observed sample records</th><th>Study / volume<br>Source context</th><th>Priority / evidence<br>Separate evaluations</th><th>Inspect / propose</th></tr></thead><tbody>${state.context.markets.map(market => {
      const data = feature.markets?.[market];
      const sample = data?.sample;
      const counts = data?.counts;
      const scoreEntries = state.candidates.filter(candidate => candidate.feature === feature.id && candidate.market === market).map(candidate => state.run?.candidate_scores?.[candidate.id]).filter(Boolean);
      return `<tr><td><div class="dw-cell-title">${e(marketName(market))}</div><span class="dw-help">Eligible sample: ${n(sample?.n)} records</span><span class="dw-help">Countries: ${e(mixText(sample?.country_mix))}</span><span class="dw-help">Source families: ${e(mixText(sample?.source_mix))}</span><span class="dw-help">Powertrain: ${e(mixText(sample?.powertrain_mix))}</span></td>
      <td><div class="dw-lines"><span>Complaints <strong>${n(counts?.complaints)}</strong></span><span>Requests <strong>${n(counts?.requests)}</strong></span><span>Praise <strong>${n(counts?.praise)}</strong></span></div><span class="dw-help">Direct matches: ${n(counts?.mentions)}<br>Unique feedback records, not verified buyers</span></td>
      <td><span class="dw-small">Study: ${list(data?.survey).length ? 'Available for inspection' : 'Unknown / no linked study'}</span><span class="dw-help">Volume: ${n(data?.sales?.volume)} ${data?.sales?.year ? `(${e(data.sales.year)})` : ''}<br>${e(data?.sales?.label || 'Source unavailable')}<br>Incremental sales: unknown</span></td>
      <td><span class="dw-small">Priority: ${scoreEntries.length ? scoreEntries.map(score => score.score == null ? `${n(score.lower_bound, 1)}–${n(score.upper_bound, 1)} provisional` : n(score.score, 1)).join(' / ') : 'not evaluated'}</span><span class="dw-help">Direct evidence: ${n(data?.direct_evidence_ids?.length)} excerpts<br>Unreviewed: ${n(data?.unreviewed_evidence_ids?.length)}<br>Delivery eligibility is assessed per action.</span></td>
      <td><button class="dw-btn small" data-dw="evidence" data-feature="${e(feature.id)}" data-region="${e(market)}">Evidence</button><br><button class="dw-btn text small" data-dw="prefill-action" data-feature="${e(feature.id)}" data-region="${e(market)}">Propose an action →</button></td></tr>`;
    }).join('')}</tbody></table></div><div class="dw-note">Related component context does not contribute to direct feature counts. A missing market sample does not establish low customer need.</div></section>`;
  }

  function mixText(mix) {
    if (!mix || !Object.keys(mix).length) return 'Unknown';
    if (Array.isArray(mix)) return mix.map(item => typeof item === 'object' ? `${item.name || item.label || item.country || item.source}: ${item.n ?? item.count ?? 'Unknown'}` : item).join(', ');
    return Object.entries(mix).map(([key, value]) => `${key}: ${plain(value)}`).join(', ');
  }

  function renderAddAction() {
    const features = list(state.evidence?.features);
    return `<div class="dw-card dw-add"><div><label for="dw-add-feature">Feature with loaded evidence</label><select id="dw-add-feature" ${features.length ? '' : 'disabled'}>${features.length ? features.map(feature => option(feature.id, feature.label || feature.id, '')).join('') : '<option>Load a feature first</option>'}</select></div><div><label for="dw-add-market">Market</label><select id="dw-add-market">${state.context.markets.map(market => option(market, marketName(market), '')).join('')}</select></div><div><label for="dw-add-action">Proposed action</label><select id="dw-add-action">${option('', 'Choose an action', '')}${Object.entries(actionLabels).map(([id, label]) => option(id, label, '')).join('')}</select></div><button class="dw-btn" data-dw="add-candidate" ${!features.length || state.candidates.length >= 16 ? 'disabled' : ''}>${icon('plus', 14)} Add action</button></div><p class="dw-help">Up to 16 reviewed candidates per run. Investigate missing evidence before making a definitive selection.</p>`;
  }

  function candidateField(candidate, key) { return `data-candidate="${e(candidate.id)}" data-field="${e(key)}"`; }
  function renderCandidate(candidate) {
    const score = state.run?.candidate_scores?.[candidate.id];
    const attr = key => candidateField(candidate, key);
    const values = candidate.values || {};
    const scenarioValues = candidate.scenario_values || {};
    return `<article class="dw-card dw-candidate" id="dw-candidate-${e(candidate.id)}"><div class="dw-candidate-head"><div><div class="dw-tags">${tag(candidate.id)}${tag(marketName(candidate.market))}${tag(actionLabels[candidate.action], 'assumption')}${candidate.mandatory ? tag('Mandatory', 'assumption') : ''}</div><h3>${e(candidate.title)}</h3><span class="dw-help">Priority: ${score ? score.score == null ? `${n(score.lower_bound, 1)}–${n(score.upper_bound, 1)} provisional bounds` : n(score.score, 1) : 'not evaluated'} · Feasibility: ${e(candidate.feasibility)} · Development cost: ${n(candidate.development_cost)} ${e(state.config.currency)}</span></div><button class="dw-btn text danger" data-dw="remove-candidate" data-id="${e(candidate.id)}" aria-label="Remove ${e(candidate.title)} from draft">Remove</button></div>
      <details ${score ? '' : 'open'}><summary>Review benefit, criteria, cost and constraints</summary><div class="dw-editor"><div class="dw-grid">
      <div class="dw-span"><label for="dw-title-${e(candidate.id)}">Customer-facing requirement / intended outcome</label><input id="dw-title-${e(candidate.id)}" value="${e(candidate.title)}" ${attr('title')}></div>
      ${numericInput(`dw-impact-${candidate.id}`, 'Customer benefit / impact (0–100)', candidate.impact, attr('impact'), 'PM rubric: 25 minor · 50 meaningful · 75 important · 100 essential')}
      ${numericInput(`dw-saturation-${candidate.id}`, 'Frequency saturation (share 0–1)', candidate.saturation, attr('saturation'), 'Fixed across comparable actions; a PM planning assumption', 1, .000001)}
      ${numericInput(`dw-cost-${candidate.id}`, 'Development cost', candidate.development_cost, attr('development_cost'), 'PM input only · blank stays unknown', null)}
      ${numericInput(`dw-delivery-${candidate.id}`, 'Delivery maturity (0–100)', values.delivery, attr('values.delivery'), 'Reviewed maturity/risk; separate from hard blockers')}
      ${numericInput(`dw-region-${candidate.id}`, 'Regional fit (0–100)', values.regional, attr('values.regional'), 'Reviewed applicability; do not reuse mention frequency')}
      ${numericInput(`dw-experience-${candidate.id}`, 'BMW experience (0–100)', values.experience, attr('values.experience'), 'PM / expert planning assessment')}
      </div><div class="dw-divider"></div><h3>Future relevance by scenario</h3><p class="dw-help">Planning assumptions on a fixed 0–100 rubric. These values are not forecast probabilities.</p><div class="dw-grid" style="margin-top:12px">${list(state.meta.scenarios).map(scenario => numericInput(`dw-future-${scenario}-${candidate.id}`, `${scenario} · future relevance`, scenarioValues[scenario], attr(`scenario_values.${scenario}`), 'Scenario evaluation')).join('')}</div>
      <div class="dw-divider"></div><div class="dw-grid">
      <div><label for="dw-feasibility-${e(candidate.id)}">Feasibility review</label><select id="dw-feasibility-${e(candidate.id)}" ${attr('feasibility')}>${[['unknown', 'Unknown'], ['reviewed', 'Reviewed feasible'], ['assumption', 'Accepted planning assumption'], ['blocked', 'Known blocker']].map(([value, label]) => option(value, label, candidate.feasibility)).join('')}</select><span class="dw-help">A blocker prevents selection. Unknown is not feasible.</span></div>
      <div><label for="dw-dependencies-${e(candidate.id)}">Dependencies · action IDs</label><input id="dw-dependencies-${e(candidate.id)}" value="${e(candidate.dependencies.join(', '))}" ${attr('dependencies')} placeholder="Comma-separated IDs"><span class="dw-help">Shared enabling work should be an explicit dependency.</span></div>
      <div><label for="dw-exclusions-${e(candidate.id)}">Exclusions · action IDs</label><input id="dw-exclusions-${e(candidate.id)}" value="${e(candidate.exclusions.join(', '))}" ${attr('exclusions')} placeholder="Comma-separated IDs"><span class="dw-help">Same feature / market actions are already mutually exclusive.</span></div>
      <div class="dw-span"><label class="dw-checkbox"><input type="checkbox" ${candidate.mandatory ? 'checked' : ''} ${attr('mandatory')}> Mandatory requirement · PM planning constraint</label></div>
      <div class="dw-span"><label for="dw-assumption-${e(candidate.id)}">Evidence basis, assumption rationale and validation needed</label><textarea id="dw-assumption-${e(candidate.id)}" ${attr('assumption_rationale')} placeholder="Explain the intended benefit, review basis and unresolved engineering questions.">${e(candidate.assumption_rationale)}</textarea></div>
      </div>${score ? `<div class="dw-note">${e(list(score.eligibility_reasons).join(' · ') || (score.eligible ? 'Eligible in the saved evaluation.' : 'Not eligible in the saved evaluation.'))}${list(score.missing || score.unknown_criteria).length ? `<br>Unknown criteria: ${e((score.missing || score.unknown_criteria).join(', '))}` : ''}</div><button class="dw-btn text" data-dw="score-detail" data-id="${e(candidate.id)}">Inspect saved score contributions →</button>` : ''}</div></details></article>`;
  }

  function renderScenarios() {
    return `<div class="dw-head"><div><h2>Make the planning assumptions explicit</h2><p>Generation profiles can differ. These common weights make all portfolio comparisons consistent.</p></div>${tag('PM review required', 'assumption')}</div><section class="dw-card dw-pad"><h3>Common comparison weights</h3><p class="dw-help">Weights must be nonnegative and sum to 1. Suggested values are planning assumptions, accepted only when you apply a named run.</p><div class="dw-grid five" style="margin-top:16px">${list(state.meta.criteria).map(criterion => numericInput(`dw-weight-${criterion}`, criteriaLabels[criterion] || criterion, state.config.weights[criterion], `data-weight="${e(criterion)}"`, 'PM comparison preference', 1)).join('')}</div><div class="dw-divider"></div><h3>Market weights</h3><p class="dw-help">Blank weights use equal market weights, a disclosed PM assumption. To override, enter every selected market and make the weights sum to 1. Sample size never sets market priority.</p><div class="dw-grid" style="margin-top:16px">${state.context.markets.map(market => numericInput(`dw-market-weight-${market}`, marketName(market), state.config.market_weights[market], `data-market-weight="${e(market)}"`, 'Blank = proposed equal market weighting', 1)).join('')}</div></section>
      <section class="dw-card dw-pad dw-section"><div class="dw-head"><div><h2>Budget & review basis</h2><p>All costs are PM planning assumptions. Unknown costs are never zero.</p></div>${tag('Assumption', 'assumption')}</div><div class="dw-grid">
      ${numericInput('dw-budget', 'Development budget', state.config.budget, 'data-config="budget"', 'One consistent investment basis', null)}
      ${textInput('dw-currency', 'Currency', state.config.currency, 'data-config="currency" placeholder="Specify currency"', 'Use the same currency for every action')}
      ${textInput('dw-cost-basis', 'Cost basis', state.config.cost_basis, 'data-config="cost_basis"', 'For example, incremental development investment')}
      ${numericInput('dw-floor', 'Cost-disciplined value floor', state.config.value_floor, 'data-config="value_floor"', 'Share of best common utility · PM assumption', 1)}
      ${textInput('dw-reviewer', 'Reviewer / PM name', state.config.reviewer, 'data-config="reviewer" autocomplete="off"', 'Required when applying a run')}
      <div class="dw-span"><label for="dw-rationale">Why are these assumptions appropriate?</label><textarea id="dw-rationale" data-config="rationale" placeholder="Record the customer outcome, evidence limitations, rationale and review basis.">${e(state.config.rationale)}</textarea></div></div></section>
      <section class="dw-card dw-pad dw-section"><h3>Future scenarios change the ranking</h3><p class="dw-help">Each action has a separate future-relevance value under ${e(list(state.meta.scenarios).join(', '))}. Edit them in the action cards. The selected scenario changes which values enter generation; every resulting portfolio is evaluated under all configured scenarios.</p><div class="dw-note">A future scenario is a planning assumption about a possible future. A strategy is a chosen set of customer requirements. They remain separate throughout the decision.</div><button class="dw-btn" data-dw="tab" data-tab="evidence">Review action assumptions</button></section>${errorBox(state.runError)}${progress('evaluate', 'Evaluating and saving the new run')}`;
  }

  function renderAlternatives() {
    const run = state.run;
    if (!run) return `${progress('evaluate', 'Evaluating constraints and generating alternatives')}${errorBox(state.runError)}${empty('No evaluated alternatives yet', 'Review evidence, enter the customer-benefit rubric and planning assumptions, then apply the draft. Only distinct feasible portfolios will be shown.')}`;
    return `<div class="dw-head"><div><h2>${run.status === 'infeasible' ? 'No feasible portfolio' : run.status === 'unresolved' ? 'Some planning inputs need review' : 'Compare feasible alternatives'}</h2><p>Run ${e(run.id || run.run_id)} · ${e(run.algorithm_version || '')} · common comparison weights</p></div>${tag(run.status, run.status === 'ready' ? 'good' : run.status === 'infeasible' ? 'error' : 'assumption')}</div>
      ${state.dirty ? '<div class="dw-note">These are the saved run results. Your current edits have not been evaluated; apply them to create a new run.</div>' : ''}
      ${list(run.conflicts).length ? `<div class="dw-error"><strong>Constraint conflicts</strong><ul>${run.conflicts.map(conflict => `<li>${e(plain(conflict))}</li>`).join('')}</ul></div>` : ''}
      ${list(run.investigation_queue).length ? `<section class="dw-card dw-pad" style="margin-bottom:18px"><h3>Investigation queue</h3><p class="dw-help">Unresolved candidates remain visible. Definitive alternatives only compare the reviewed candidate set.</p><ul class="dw-small">${run.investigation_queue.map(item => `<li><strong>${e(item.id)}</strong> · ${e(list(item.reasons).join(' · '))}</li>`).join('')}</ul></section>` : ''}
      <div class="dw-portfolio-grid">${list(run.portfolios).map(portfolio => renderPortfolio(portfolio, run)).join('')}</div>
      ${!list(run.portfolios).length ? empty('No portfolio available', 'Resolve the conflicts or missing inputs listed above. Constraints are not relaxed to produce an alternative.') : ''}
      <div class="dw-note">${e(run.alternatives_note || 'Only distinct, non-dominated feasible alternatives are shown. The system does not manufacture a fixed number of options.')}</div>
      ${list(run.portfolios).length ? renderScenarioComparison(run) : ''}
      <section class="dw-section"><div class="dw-head"><h2>Action evaluations</h2><span class="dw-help">Scenario evaluation · possible bounds are not confidence intervals</span></div><div class="dw-table-wrap"><table class="dw-table"><thead><tr><th>Action</th><th>Priority</th><th>Customer value</th><th>Delivery eligibility</th><th>Inspect</th></tr></thead><tbody>${list(run.candidates).map(candidate => { const score = run.candidate_scores?.[candidate.id] || {}; return `<tr><td><strong>${e(candidate.id)}</strong> ${e(candidate.title)}<span class="dw-help">${e(marketName(candidate.market))}</span></td><td>${score.score == null ? `${n(score.lower_bound, 1)}–${n(score.upper_bound, 1)}<span class="dw-help">Unresolved score bounds</span>` : n(score.score, 1)}</td><td>${n(score.customer_value, 1)}</td><td>${e(score.eligible ? 'Eligible' : 'Not eligible')}<span class="dw-help">${e(list(score.eligibility_reasons).join(' · '))}</span></td><td><button class="dw-btn small" data-dw="score-detail" data-id="${e(candidate.id)}">Contributions</button></td></tr>`; }).join('')}</tbody></table></div></section>
      ${run.changes ? `<section class="dw-section dw-card dw-pad"><h3>Changes from previous run</h3><p class="dw-help">Added: ${e(list(run.changes.added).join(', ') || 'None')} · Removed: ${e(list(run.changes.removed).join(', ') || 'None')}</p><button class="dw-btn text" data-dw="changes">Inspect recorded changes →</button></section>` : ''}${errorBox(state.runError)}`;
  }

  function renderPortfolio(portfolio, run) {
    const selected = portfolio.id === state.selectedPortfolio;
    const titles = list(portfolio.selected_ids).map(id => list(run.candidates).find(candidate => candidate.id === id)?.title || id);
    return `<article class="dw-card dw-portfolio ${selected ? 'selected' : ''}"><div class="dw-tags">${tag(portfolio.feasible ? 'Feasible under reviewed inputs' : 'Unresolved', portfolio.feasible ? 'good' : 'assumption')}${tag('Scenario evaluation', 'scenario')}</div><h3>${e(portfolio.profile || portfolio.id)}</h3><p class="dw-help">${e(portfolio.id)} · ${selected ? 'Selected for review' : 'Available alternative'}</p><ul>${titles.map(title => `<li>${e(title)}</li>`).join('') || '<li>No optional actions selected</li>'}</ul><dl class="dw-portfolio-metrics"><div><dt>Common utility · evaluation</dt><dd>${n(portfolio.comparison_utility, 1)}</dd></div><div><dt>Development cost · assumption</dt><dd>${n(portfolio.cost)} <small>${e(run.config?.currency || '')}</small></dd></div><div><dt>Worst scenario utility</dt><dd>${n(portfolio.worst_case_utility, 1)}</dd></div><div><dt>Hard constraints</dt><dd style="font-size:13px">${portfolio.feasible ? 'Satisfied' : 'Unresolved'}</dd></div></dl><button class="dw-btn ${selected ? 'primary' : ''}" data-dw="select-portfolio" data-id="${e(portfolio.id)}">${selected ? 'Selected for review' : 'Select for review'}</button></article>`;
  }

  function renderScenarioComparison(run) {
    const scenarios = list(state.meta.scenarios);
    return `<section class="dw-section"><div class="dw-head"><div><h2>Performance across future scenarios</h2><p>Common weights in every cell. Utilities, regret and feasibility are scenario evaluations.</p></div></div><div class="dw-table-wrap"><table class="dw-table"><thead><tr><th>Strategy</th>${scenarios.map(scenario => `<th>${e(scenario)}</th>`).join('')}</tr></thead><tbody>${run.portfolios.map(portfolio => `<tr><td><strong>${e(portfolio.profile)}</strong></td>${scenarios.map(scenario => { const evaluation = portfolio.scenario_evaluations?.[scenario]; return `<td>${evaluation ? n(evaluation.utility, 1) : 'Unknown'}<span class="dw-help">${evaluation ? evaluation.feasible ? 'Feasible' : 'Not feasible' : 'Not evaluated'} · regret ${n(evaluation?.regret, 1)}<br>${e(list(evaluation?.reasons).join(' · '))}</span></td>`; }).join('')}</tr>`).join('')}</tbody></table></div></section>`;
  }

  function renderReview() {
    const run = state.run;
    const portfolio = currentPortfolio();
    return `<div class="dw-head"><div><h2>Review the exact decision version</h2><p>Every decision references a frozen run and portfolio. Later edits create a new draft.</p></div><button class="dw-btn small" data-dw="refresh-history">Refresh history</button></div>
      ${run ? `<section class="dw-card dw-pad"><div class="dw-head"><div><h3>Run ${e(run.id || run.run_id)}</h3><p>${e(run.context?.vehicle || '')} · launch ${e(run.context?.launch_year || '')} · ${e(list(run.context?.markets).join(', '))}</p></div>${tag(run.status)}</div><div class="dw-grid two"><div><label for="dw-review-portfolio">Portfolio to review</label><select id="dw-review-portfolio" data-state="selectedPortfolio">${option('', 'Select an evaluated portfolio', state.selectedPortfolio)}${list(run.portfolios).map(item => option(item.id, item.profile || item.id, state.selectedPortfolio)).join('')}</select><span class="dw-help">Approval is only available for a feasible saved portfolio.</span></div><div><label for="dw-decision-status">Decision</label><select id="dw-decision-status" data-state="decisionStatus">${['Approved', 'Rejected', 'Changes requested'].map(value => option(value, value, state.decisionStatus)).join('')}</select></div>${textInput('dw-reviewer-decision', 'Reviewer name', state.config.reviewer, 'data-config="reviewer"', 'Recorded with the decision')}<div><label for="dw-decision-rationale">Decision rationale</label><textarea id="dw-decision-rationale" data-state="decisionRationale" placeholder="Why this choice? Record trade-offs, rejected alternatives and revisit conditions.">${e(state.decisionRationale)}</textarea></div><div class="dw-span"><label class="dw-checkbox"><input type="checkbox" data-state="acknowledge" ${state.acknowledge ? 'checked' : ''}> I acknowledge the planning assumptions in this saved run.</label><p class="dw-help">${e(list(run.assumptions).map(plain).join(' · ') || 'Inspect every cost, criterion input and scenario assumption in the saved run before deciding.')}</p></div></div><div class="dw-actions-row" style="margin-top:18px"><button class="dw-btn" data-dw="revise">Create a draft revision</button><button class="dw-btn primary" data-dw="record-decision" ${state.busy.has('decision') || !portfolio ? 'disabled' : ''}>${state.busy.has('decision') ? 'Recording decision…' : 'Record decision'}</button></div>${errorBox(state.decisionError)}${progress('decision', 'Recording an append-only human decision')}
      ${list(run.decisions).length ? `<div class="dw-divider"></div><h3>Decision events</h3><div class="dw-timeline">${run.decisions.map(event => `<article class="dw-event"><strong>${e(event.action || event.status)} · ${e(event.reviewer || event.actor)}</strong><p>${e(event.rationale)}</p><small>${e(event.timestamp || event.created_at)} · ${e(event.portfolio_id)}</small>${(event.action || event.status) === 'Approved' ? `<br><a class="dw-btn text small" href="/api/decision/decisions/${encodeURIComponent(event.id || event.event_id)}/export" download>Export approved snapshot ${icon('download', 12)}</a>` : ''}</article>`).join('')}</div>` : ''}</section>` : empty('No saved run to review', 'Apply a reviewed draft first. Approval and rejection require a reviewer, rationale and an evaluated portfolio.')}
      <section class="dw-section"><div class="dw-head"><h2>Run history</h2>${tag('Saved versions')}</div>${progress('history', 'Loading saved decision runs')}${errorBox(state.historyError)}<div class="dw-history-list">${state.history.length ? state.history.map(item => `<article class="dw-card dw-history-item"><div><h3>${e(item.id || item.run_id)} ${tag(item.status || 'Saved')}</h3><span class="dw-help">${e(item.context?.vehicle || item.vehicle || '')} · ${e(item.created_at || '')}</span></div><button class="dw-btn small" data-dw="open-run" data-id="${e(item.id || item.run_id)}">Open saved run</button></article>`).join('') : !state.busy.has('history') ? empty('No saved runs', 'Your applied drafts and later decision events will appear here.') : ''}</div></section>${errorBox(state.runError)}`;
  }

  function renderAside() {
    const status = state.meta.agent_status || {};
    const readerStatus = typeof status === 'string' ? status : status.reader || status.evidence_reader || status.status || 'Availability checked on request';
    const explainerStatus = typeof status === 'string' ? status : status.explainer || status.decision_explainer || status.status || 'Availability checked on request';
    return `<aside class="dw-card dw-pad dw-aside" aria-labelledby="dw-copilot-title"><div class="dw-head"><h2 id="dw-copilot-title">Decision copilot</h2>${tag('Human review')}</div><p class="dw-small dw-muted">Source interpretation and decision explanation, grounded in the same saved evidence.</p><ol class="dw-pipeline"><li><span class="dw-step">1</span><h3>Evidence reader</h3><p>Proposes direct claims, context and counterevidence. Source identifiers are validated.</p>${tag(plain(readerStatus))}</li><li><span class="dw-step">2</span><h3>Deterministic evaluator</h3><p>Python counts, scores and checks hard constraints. Every applied run is frozen.</p>${tag(state.run ? `Run ${state.run.status}` : 'Awaiting reviewed inputs')}</li><li><span class="dw-step">3</span><h3>Decision explainer</h3><p>Explains the stored result. Proposed changes need your explicit review.</p>${tag(plain(explainerStatus))}</li></ol>
      <button class="dw-btn" data-dw="read-evidence" ${!state.evidence || state.busy.has('reader') ? 'disabled' : ''}>${state.busy.has('reader') ? 'Reading sources…' : 'Ask reader to inspect evidence'}</button>${errorBox(state.readerError)}${state.reader ? renderAgentResult(state.reader, 'reader') : ''}
      <section class="dw-questions"><h3>Ask about the saved decision</h3><label class="dw-sr" for="dw-question">Decision question</label><textarea id="dw-question" data-state="question" placeholder="What supports this action in each market, and what remains uncertain?">${e(state.question)}</textarea><button class="dw-btn primary" data-dw="ask-question" ${!state.run || state.busy.has('question') ? 'disabled' : ''}>${state.busy.has('question') ? 'Preparing grounded answer…' : 'Ask decision explainer'}</button><p class="dw-help">${state.run ? `Answers reference saved run ${e(state.run.id || state.run.run_id)}.` : 'Create a saved run before asking about its evaluation.'}</p>${errorBox(state.questionError)}${state.answer ? renderAgentResult(state.answer, 'answer') : ''}</section>
      <section class="dw-questions"><h3>Public competitor research</h3><p class="dw-help">Explicit research uses public vehicle and feature context. Local customer excerpts are not sent to search.</p><label for="dw-research-market" style="margin-top:12px">Market</label><select id="dw-research-market" data-state="researchMarket">${state.context.markets.map(market => option(market, marketName(market), state.researchMarket)).join('')}</select><button class="dw-btn" style="margin-top:10px" data-dw="research" ${!state.context.vehicle || !state.features.length || state.busy.has('research') ? 'disabled' : ''}>${state.busy.has('research') ? 'Researching public sources…' : 'Research public sources'}</button>${errorBox(state.researchError)}${state.research ? renderAgentResult(state.research, 'research') : ''}</section>
      <p class="dw-help" style="border-top:1px solid #e3e8ef;padding-top:15px;margin-top:20px">Missing information stays unknown. Language agents do not calculate, estimate development costs or approve decisions.</p></aside>`;
  }

  function renderAgentResult(result, kind) {
    const unavailable = result.status !== 'available';
    return `<div class="dw-answer" role="status">${tag(unavailable ? 'Unavailable' : kind === 'reader' ? 'Interpretation · review required' : kind === 'research' ? 'Public observations · review required' : 'Grounded explanation', unavailable ? '' : kind === 'research' ? 'observed' : 'assumption')}<p style="margin-top:9px">${e(result.answer || result.reason || (unavailable ? 'This service is unavailable. Evidence and deterministic evaluation remain usable.' : 'Review the following claims against their sources.'))}</p>${list(result.claims).length ? `<ul>${result.claims.map(claim => `<li>${e(claim.text)}${list(claim.evidence_ids).map(id => citationButton(id)).join('')}${claim.url && safeHttpUrl(claim.url) ? `<br><a href="${e(claim.url)}" target="_blank" rel="noopener noreferrer">Public source ↗</a><span class="dw-help">${e(claim.market || '')} · ${e(claim.model || '')} · ${e(claim.source_date || 'Source date unknown')}</span>` : ''}${list(claim.metric_ids).length ? `<span class="dw-help">Stored metrics: ${e(claim.metric_ids.join(', '))}</span>` : ''}</li>`).join('')}</ul>` : ''}${list(result.unknowns || result.assumptions).length ? `<p class="dw-help">${e((result.unknowns || result.assumptions).map(plain).join(' · '))}</p>` : ''}${result.proposed_change ? `<div class="dw-note">Proposed change: ${e(plain(result.proposed_change))}<br>Not applied.</div><button class="dw-btn small" data-dw="review-proposal">Review proposed change</button>` : ''}</div>`;
  }

  function safeHttpUrl(url) { try { const parsed = new URL(url); return ['https:', 'http:'].includes(parsed.protocol); } catch { return false; } }
  function citationButton(id) { return `<button class="dw-source-link" data-dw="citation" data-id="${e(id)}">Source ${e(id)}</button>`; }
  function contextPayload() { return { ...state.context, markets: [...state.context.markets] }; }
  function validateContext() {
    if (!state.context.vehicle) throw new Error('Select a vehicle before loading evidence.');
    if (!Number.isInteger(state.context.launch_year) || state.context.launch_year < 1) throw new Error('Enter a valid launch year.');
    if (!state.context.markets.length) throw new Error('Select at least one target market.');
  }

  async function loadEvidence() {
    state.evidenceError = '';
    try {
      validateContext();
      const query = state.featureInput.trim();
      const key = state.meta.features.find(feature => feature.label.toLowerCase() === query.toLowerCase() || feature.key === query)?.key || query;
      const features = [...new Set([...state.features, ...(key ? [key] : [])])];
      if (!features.length) throw new Error('Enter a feature or customer need first.');
      const revision = state.revision;
      const pendingRequest = request('evidence', '/api/decision/evidence', post({ context: contextPayload(), features }));
      render();
      const evidence = await pendingRequest;
      if (revision !== state.revision) return;
      state.evidence = evidence;
      state.features = list(evidence.features).map(feature => feature.id);
      state.featureInput = '';
      markDirty();
    } catch (error) { reportError(error, 'evidenceError'); }
    render();
  }

  function addCandidate() {
    const feature = root.querySelector('#dw-add-feature')?.value;
    const market = root.querySelector('#dw-add-market')?.value;
    const action = root.querySelector('#dw-add-action')?.value;
    if (!feature || !market || !action) { state.runError = 'Choose a feature, market and action before adding a proposal.'; render(); return; }
    if (state.candidates.some(candidate => candidate.feature === feature && candidate.market === market && candidate.action === action)) { state.runError = 'This feature, action and market already has a draft candidate.'; render(); return; }
    if (state.candidates.length >= 16) return;
    const id = `C${String(state.nextId++).padStart(3, '0')}`;
    state.candidates.push({ id, title: `${actionLabels[action]} ${featureName(feature)} for ${marketName(market)}`, feature, market, action, impact: null, saturation: null, values: { future: null, delivery: null, regional: null, experience: null }, scenario_values: { slow: null, baseline: null, fast: null }, development_cost: null, feasibility: 'unknown', assumption_rationale: '', mandatory: false, dependencies: [], exclusions: [] });
    state.runError = '';
    markDirty();
    render();
    root.querySelector(`#dw-candidate-${id}`)?.scrollIntoView({ behavior: REDUCED_MOTION ? 'auto' : 'smooth', block: 'nearest' });
  }

  async function evaluate() {
    state.runError = '';
    try {
      validateContext();
      if (!state.evidence) throw new Error('Load evidence for the current context before applying the draft.');
      if (!state.candidates.length) throw new Error('Add at least one candidate action.');
      const actor = state.config.reviewer.trim() || document.querySelector('#actor')?.value.trim();
      if (!actor || state.config.rationale.trim().length < 3) {
        state.tab = 'scenarios';
        throw new Error('Enter a reviewer name and rationale in Scenarios & weights before applying a run.');
      }
      if (!state.config.currency.trim()) { state.tab = 'scenarios'; throw new Error('Specify the currency and development cost basis before evaluating.'); }
      const invalid = root.querySelector('input:invalid');
      if (invalid) { invalid.reportValidity(); return; }
      state.config.reviewer = actor;
      const revision = state.revision;
      const payload = { context: contextPayload(), candidates: structuredClone(state.candidates), config: structuredClone(state.config), parent_run_id: state.run?.id || state.run?.run_id || null };
      const pendingRequest = request('evaluate', '/api/decision/runs', post(payload));
      render();
      const run = await pendingRequest;
      state.run = run;
      state.selectedPortfolio = '';
      state.dirty = revision !== state.revision;
      state.tab = 'alternatives';
      state.lastMessage = `Run ${run.id || run.run_id} saved. Inputs, evidence and evaluation are frozen.`;
      state.answer = null;
      state.decisionRationale = '';
      state.acknowledge = false;
      loadHistory(false);
    } catch (error) { reportError(error, 'runError'); }
    render();
  }

  async function loadHistory(repaint = true) {
    state.historyError = '';
    const pendingRequest = request('history', `/api/decision/runs?project_id=${encodeURIComponent(state.context.project_id)}`);
    if (repaint) render();
    try { const response = await pendingRequest; state.history = Array.isArray(response) ? response : list(response.runs); }
    catch (error) { reportError(error, 'historyError'); }
    if (repaint || state.tab === 'review') render();
  }

  async function openRun(id) {
    state.runError = '';
    try {
      const run = await request('open-run', `/api/decision/runs/${encodeURIComponent(id)}`);
      ['evidence', 'reader', 'question', 'research'].forEach(cancel);
      state.run = run;
      state.context = structuredClone(run.context);
      state.config = { ...state.config, ...structuredClone(run.config) };
      state.candidates = structuredClone(list(run.candidates));
      state.nextId = Math.max(0, ...state.candidates.map(candidate => Number(candidate.id.replace(/^C/, '')) || 0)) + 1;
      state.evidence = run.evidence;
      state.features = list(run.evidence?.features).map(feature => feature.id);
      state.selectedPortfolio = '';
      state.dirty = false;
      state.tab = 'alternatives';
      state.answer = null;
      state.reader = null;
      state.research = null;
      state.lastMessage = 'Viewing a frozen saved run. Editing its inputs creates a new draft.';
    } catch (error) { reportError(error, 'runError'); }
    render();
  }

  async function recordDecision() {
    state.decisionError = '';
    const portfolio = currentPortfolio();
    const actor = state.config.reviewer.trim() || document.querySelector('#actor')?.value.trim();
    try {
      if (!portfolio) throw new Error('Select the saved portfolio you want to review.');
      if (!actor || state.decisionRationale.trim().length < 3) throw new Error('A reviewer name and a decision rationale are required.');
      if (state.decisionStatus === 'Approved' && !portfolio.feasible) throw new Error('Approval requires a feasible saved portfolio.');
      const payload = { portfolio_id: portfolio.id, status: state.decisionStatus, actor, rationale: state.decisionRationale.trim(), acknowledge_assumptions: state.acknowledge };
      const runId = state.run.id || state.run.run_id;
      const pendingRequest = request('decision', `/api/decision/runs/${encodeURIComponent(runId)}/decisions`, post(payload));
      render();
      const event = await pendingRequest;
      state.run.decisions = [...list(state.run.decisions), event];
      state.lastMessage = `${state.decisionStatus} recorded for saved run ${runId}.`;
      state.decisionRationale = '';
      state.acknowledge = false;
      loadHistory(false);
    } catch (error) { reportError(error, 'decisionError'); }
    render();
  }

  async function agentAction(kind) {
    const errorField = kind === 'reader' ? 'readerError' : kind === 'question' ? 'questionError' : 'researchError';
    state[errorField] = '';
    try {
      let path; let payload;
      if (kind === 'reader') { path = '/api/decision/read'; payload = { context: contextPayload(), features: [...state.features], question: state.question || undefined }; }
      else if (kind === 'question') { if (!state.question.trim()) throw new Error('Enter a question about the saved decision.'); path = `/api/decision/runs/${encodeURIComponent(state.run.id || state.run.run_id)}/questions`; payload = { question: state.question.trim() }; }
      else { path = '/api/decision/research'; payload = { vehicle: state.context.vehicle, feature: state.features[0], market: state.researchMarket || state.context.markets[0] }; }
      const pendingRequest = request(kind, path, { ...post(payload), timeout: 120000 });
      render();
      const result = await pendingRequest;
      state[kind === 'question' ? 'answer' : kind] = result;
    } catch (error) { reportError(error, errorField); }
    render();
  }

  function openDialog(title, subtitle, body, opener) {
    const dialog = root.querySelector('#dw-dialog');
    state.dialogOpener = opener || document.activeElement;
    dialog.innerHTML = `<div class="dw-dialog-head"><div><div class="dw-eyebrow">Decision inspector</div><h2 id="dw-dialog-title">${e(title)}</h2><p class="dw-small dw-muted">${e(subtitle)}</p></div><button class="dw-btn small" data-dw="close-dialog" aria-label="Close inspector">Close ×</button></div><div class="dw-dialog-body">${body}</div>`;
    if (!dialog.open) dialog.showModal();
  }

  function citationRecord(id) { return state.evidence?.citations?.[id] || state.run?.evidence?.citations?.[id]; }
  function renderCitation(id) {
    const citation = citationRecord(id);
    if (!citation) return `<div class="dw-error">Source ${e(id)} cannot be resolved in this snapshot.</div>`;
    return `<article class="dw-quote"><div class="dw-tags">${tag(citation.label || 'Observed excerpt', 'observed')}${tag(id)}</div><blockquote>${e(citation.text || 'Excerpt text unavailable')}</blockquote><div class="dw-locator"><span><strong>File:</strong> ${e(citation.file || 'Unknown')}</span><span><strong>Sheet:</strong> ${e(citation.sheet || 'Not applicable')}</span><span><strong>Row / record:</strong> ${e(citation.row ?? citation.raw_record_id ?? 'Not applicable')}</span><span><strong>Page / cell:</strong> ${e(citation.page ?? citation.cell ?? 'Not applicable')}</span></div></article>`;
  }

  function showEvidence(featureId, market, relationship = 'direct', opener) {
    const pack = state.evidence || state.run?.evidence;
    const feature = list(pack?.features).find(item => item.id === featureId);
    if (!feature) return;
    state.dialog = { featureId, market, relationship };
    const regions = market ? [market] : Object.keys(feature.markets || {});
    const relationKeys = { direct: 'direct_evidence_ids', context: 'contextual_evidence_ids', unreviewed: 'unreviewed_evidence_ids' };
    const ids = [...new Set(regions.flatMap(region => list(feature.markets?.[region]?.[relationKeys[relationship]])))];
    const notes = { direct: 'Exact feature evidence. Positive and negative signals remain visible; statements support only their applicable scope.', context: 'Broader component and analogous context do not contribute to direct feature counts.', unreviewed: 'Interpretations awaiting review do not establish observed feature demand.' };
    const tabsHtml = `<div class="dw-tabs" role="tablist" aria-label="Evidence relationship">${[['direct', 'Direct evidence'], ['context', 'Parent context'], ['unreviewed', 'Review / counterevidence']].map(([key, label]) => `<button role="tab" aria-selected="${key === relationship}" data-dw="evidence-tab" data-relation="${key}">${e(label)}</button>`).join('')}</div>`;
    const contextual = regions.map(region => {
      const data = feature.markets?.[region] || {};
      return `<section class="dw-section"><h3>${e(marketName(region))} · source context</h3><dl class="dw-readout"><dt>Eligible sample / countries</dt><dd>${n(data.sample?.n)} feedback records · ${e(mixText(data.sample?.country_mix))}</dd><dt>Source families / powertrain</dt><dd>${e(mixText(data.sample?.source_mix))} · ${e(mixText(data.sample?.powertrain_mix))}</dd><dt>Sales baseline</dt><dd>${n(data.sales?.volume)} · ${e(data.sales?.year || 'Unknown period')} · ${e(data.sales?.label || 'Unavailable')}${list(data.sales?.source_ids).map(citationButton).join('')}</dd></dl>${['survey', 'equipment', 'materials', 'competitors'].map(key => list(data[key]).length ? `<details style="margin-top:10px"><summary>${e(key)} · source observations</summary>${data[key].map(item => `<div class="dw-quote"><p class="dw-small">${e(item.text || item.label || item.attribute || item.name || plain(item))}</p>${list(item.source_ids || item.evidence_ids).map(citationButton).join('')}<details><summary class="dw-help">View source fields</summary><pre class="dw-pre">${e(JSON.stringify(item, null, 2))}</pre></details></div>`).join('')}</details>` : `<p class="dw-help">${e(key)}: no applicable source loaded.</p>`).join('')}</section>`;
    }).join('');
    openDialog(feature.label || feature.id, `${market ? marketName(market) : 'Selected markets'} · frozen source locators`, `${tabsHtml}<p class="dw-small dw-muted">${e(notes[relationship])}</p>${ids.length ? ids.map(renderCitation).join('') : empty('No excerpts in this relationship', 'Missing evidence is not evidence of no customer need. Inspect context, applicability and unresolved classifications.')}<div class="dw-note">Counterevidence is a stance, not a separate relevance class. Inspect praise and contradicting statements in direct and contextual evidence; the reader may propose interpretations for review.</div>${contextual}`, opener);
  }

  function showScore(id, opener) {
    const score = state.run?.candidate_scores?.[id];
    const candidate = list(state.run?.candidates).find(item => item.id === id);
    if (!score) return;
    const body = `<div class="dw-tags">${tag('Scenario evaluation', 'scenario')}${tag(state.run.algorithm_version || 'Versioned evaluator')}</div><dl class="dw-readout"><dt>Score / unresolved bounds</dt><dd>${score.score == null ? `${n(score.lower_bound, 2)}–${n(score.upper_bound, 2)}` : n(score.score, 2)}</dd><dt>Customer value / frequency component</dt><dd>${n(score.customer_value, 2)} / ${n(score.frequency, 2)}</dd><dt>Eligibility</dt><dd>${e(score.eligible ? 'Eligible' : 'Not eligible')} · ${e(list(score.eligibility_reasons).join(' · '))}</dd></dl><h3>Stored criterion contributions</h3><pre class="dw-pre">${e(JSON.stringify({ criteria: score.criteria, contributions: score.contributions, unknown_criteria: score.unknown_criteria || score.missing }, null, 2))}</pre><p class="dw-help">Computed in Python from the saved evidence and PM assumptions. Missing positive-weight criteria are not replaced with zero or a default estimate.</p>`;
    openDialog(candidate?.title || id, `Saved run ${state.run.id || state.run.run_id} · ${id}`, body, opener);
  }

  function showProposal(opener) {
    const proposal = state.answer?.proposed_change;
    if (!proposal) return;
    openDialog('Review the proposed change', 'The explainer cannot apply it. Your explicit action changes the draft only.', `<pre class="dw-pre">${e(JSON.stringify(proposal, null, 2))}</pre><p class="dw-help">Review the target action and value. Applying the draft later creates a new evaluated run.</p><button class="dw-btn primary" data-dw="accept-proposal">Accept into draft</button>`, opener);
  }

  function acceptProposal() {
    const proposal = state.answer?.proposed_change;
    const candidate = state.candidates.find(item => item.id === proposal?.candidate_id);
    const fields = ['impact', 'saturation', 'development_cost', 'values.delivery', 'values.regional', 'values.experience', 'scenario_values.slow', 'scenario_values.baseline', 'scenario_values.fast'];
    if (!candidate || !fields.includes(proposal.field) || (proposal.value !== null && typeof proposal.value !== 'number')) { state.questionError = 'This proposal cannot be applied automatically. Review it and edit the draft fields directly.'; root.querySelector('#dw-dialog').close(); render(); return; }
    const [key, nested] = proposal.field.split('.');
    if (nested) candidate[key][nested] = proposal.value;
    else candidate[key] = proposal.value;
    markDirty();
    root.querySelector('#dw-dialog').close();
    state.lastMessage = 'Proposed value accepted into the draft. Review the assumptions, then Apply & evaluate.';
    state.tab = 'evidence';
    render();
  }

  function onInput(event) {
    const target = event.target;
    if (target.dataset.state) { state[target.dataset.state] = target.type === 'checkbox' ? target.checked : target.value; return; }
    if (target.dataset.context) {
      state.context[target.dataset.context] = target.type === 'number' ? target.value === '' ? null : Number(target.value) : target.value || null;
      invalidateEvidence();
      return;
    }
    if (target.dataset.config) {
      state.config[target.dataset.config] = target.type === 'number' ? target.value === '' ? null : Number(target.value) : target.value;
      markDirty();
      return;
    }
    if (target.dataset.weight) { state.config.weights[target.dataset.weight] = target.value === '' ? null : Number(target.value); markDirty(); return; }
    if (target.dataset.marketWeight) {
      if (target.value === '') delete state.config.market_weights[target.dataset.marketWeight];
      else state.config.market_weights[target.dataset.marketWeight] = Number(target.value);
      markDirty(); return;
    }
    if (target.dataset.candidate) {
      const candidate = state.candidates.find(item => item.id === target.dataset.candidate);
      if (!candidate) return;
      let value = target.type === 'checkbox' ? target.checked : target.type === 'number' ? target.value === '' ? null : Number(target.value) : target.value;
      const [field, nested] = target.dataset.field.split('.');
      if (['dependencies', 'exclusions'].includes(field)) value = target.value.split(',').map(item => item.trim()).filter(Boolean);
      if (nested) candidate[field][nested] = value;
      else candidate[field] = value;
      markDirty();
    }
  }

  async function onClick(event) {
    const button = event.target.closest('[data-dw]');
    if (!button) return;
    const action = button.dataset.dw;
    if (action === 'retry-meta') return loadMeta();
    if (action === 'tab') { state.tab = button.dataset.tab; render(); root.querySelector(`#dw-tab-${state.tab}`)?.focus({ preventScroll: true }); return; }
    if (action === 'load-evidence') return loadEvidence();
    if (action === 'add-candidate') return addCandidate();
    if (action === 'remove-candidate') { state.candidates = state.candidates.filter(candidate => candidate.id !== button.dataset.id); markDirty(); render(); return; }
    if (action === 'clear-features') { state.features = []; state.candidates = []; invalidateEvidence(); render(); return; }
    if (action === 'prefill-action') { root.querySelector('#dw-add-feature').value = button.dataset.feature; root.querySelector('#dw-add-market').value = button.dataset.region; root.querySelector('#dw-add-action').focus(); root.querySelector('#dw-add-action').scrollIntoView({ behavior: REDUCED_MOTION ? 'auto' : 'smooth', block: 'center' }); return; }
    if (action === 'evaluate') return evaluate();
    if (action === 'select-portfolio') { state.selectedPortfolio = button.dataset.id; render(); return; }
    if (action === 'refresh-history') return loadHistory();
    if (action === 'open-run') return openRun(button.dataset.id);
    if (action === 'record-decision') return recordDecision();
    if (action === 'revise') { markDirty(); state.tab = 'evidence'; state.lastMessage = 'Revision draft opened. The saved run and prior decisions remain unchanged.'; render(); return; }
    if (action === 'read-evidence') return agentAction('reader');
    if (action === 'ask-question') return agentAction('question');
    if (action === 'research') return agentAction('research');
    if (action === 'evidence') return showEvidence(button.dataset.feature, button.dataset.region, 'direct', button);
    if (action === 'evidence-tab') return showEvidence(state.dialog.featureId, state.dialog.market, button.dataset.relation, state.dialogOpener);
    if (action === 'citation') return openDialog('Source excerpt', 'Resolvable locator from the active source snapshot', renderCitation(button.dataset.id), button);
    if (action === 'score-detail') return showScore(button.dataset.id, button);
    if (action === 'close-dialog') return root.querySelector('#dw-dialog').close();
    if (action === 'changes') return openDialog('Changes from the preceding run', 'Recorded by the deterministic evaluator', `<pre class="dw-pre">${e(JSON.stringify(state.run.changes, null, 2))}</pre>`, button);
    if (action === 'review-proposal') return showProposal(button);
    if (action === 'accept-proposal') return acceptProposal();
  }

  function init() {
    root = document.querySelector('#view-decision');
    root.addEventListener('click', onClick);
    root.addEventListener('input', onInput);
    root.addEventListener('change', event => {
      if (event.target.dataset.market) {
        const market = event.target.dataset.market;
        state.context.markets = event.target.checked ? [...new Set([...state.context.markets, market])] : state.context.markets.filter(item => item !== market);
        delete state.config.market_weights[market];
        invalidateEvidence();
        render();
      } else if (event.target.matches('select')) {
        if (event.target.dataset.state === 'selectedPortfolio') render();
        if (event.target.dataset.context) render();
      }
    });
    root.addEventListener('keydown', event => {
      if (event.target.id === 'dw-feature' && event.key === 'Enter') { event.preventDefault(); loadEvidence(); }
      const tab = event.target.closest('[role="tab"][data-tab]');
      if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const index = tabs.findIndex(item => item.id === state.tab);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      state.tab = tabs[next].id;
      render();
      root.querySelector(`#dw-tab-${state.tab}`)?.focus();
    });
    loadMeta();
  }

  function setActive(active) {
    state.active = active;
    const bottom = root?.querySelector('.dw-bottom');
    if (bottom) bottom.hidden = !active;
    if (!active) {
      ['evidence', 'reader', 'question', 'research'].forEach(cancel);
      root?.querySelector('#dw-dialog')?.close();
    }
  }
  return { init, setActive };
})();
