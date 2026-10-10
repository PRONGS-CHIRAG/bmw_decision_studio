/* Parametric side-view car sketches + clickable zone hotspots. Shared by app and report. */
'use strict';

const CAR_GEOMETRY = {
  F70: { type: 'hatch', tail: 120, nose: 905, rw: 265, fw: 745, r: 56, roofY: 128, roofRear: 300, roofFront: 600, ws: 725, hoodY: 212, belt: 208 },
  G60: { type: 'sedan', tail: 90, nose: 950, rw: 250, fw: 775, r: 58, roofY: 134, roofRear: 440, roofFront: 640, ws: 760, hoodY: 212, belt: 210, deckY: 214, deckEnd: 300 },
  G70: { type: 'sedan', tail: 65, nose: 965, rw: 235, fw: 805, r: 61, roofY: 122, roofRear: 420, roofFront: 665, ws: 785, hoodY: 206, belt: 206, deckY: 206, deckEnd: 285 },
};
const CAR_VIEWBOX = '0 70 1030 330';
const WHEEL_Y = 318;
const SILL_Y = 326;

function carGeometry(code) { return CAR_GEOMETRY[code] || CAR_GEOMETRY.G60; }

function bodyPath(g) {
  const { tail: t, nose: n, rw, fw, roofY, roofRear, roofFront, ws, hoodY } = g;
  const R = g.r + 5;
  const dx = Math.sqrt(R * R - (SILL_Y - WHEEL_Y) ** 2).toFixed(1);
  let p = `M ${t + 6} 300 C ${t} 272 ${t + 2} 248 ${t + 18} 234 `;
  if (g.type === 'sedan') {
    p += `C ${t + 50} ${g.deckY + 6} ${g.deckEnd - 60} ${g.deckY} ${g.deckEnd} ${g.deckY} `;
    p += `C ${g.deckEnd + 45} ${g.deckY - 30} ${roofRear - 70} ${roofY + 14} ${roofRear} ${roofY} `;
  } else {
    p += `C ${t + 24} 205 ${t + 38} 172 ${t + 66} 152 `;
    p += `C ${t + 100} ${roofY + 8} ${roofRear - 70} ${roofY + 2} ${roofRear} ${roofY} `;
  }
  p += `C ${roofRear + 90} ${roofY - 7} ${roofFront - 90} ${roofY - 7} ${roofFront} ${roofY + 3} `;
  p += `C ${roofFront + 55} ${roofY + 18} ${ws - 45} ${hoodY - 28} ${ws} ${hoodY - 6} `;
  p += `C ${ws + 70} ${hoodY} ${n - 70} ${hoodY + 10} ${n - 28} ${hoodY + 24} `;
  p += `C ${n - 8} ${hoodY + 33} ${n} 256 ${n} 282 L ${n - 2} 304 C ${n - 5} 318 ${n - 15} ${SILL_Y} ${n - 30} ${SILL_Y} `;
  p += `L ${fw + +dx} ${SILL_Y} A ${R} ${R} 0 1 0 ${fw - dx} ${SILL_Y} `;
  p += `L ${rw + +dx} ${SILL_Y} A ${R} ${R} 0 1 0 ${rw - dx} ${SILL_Y} `;
  p += `L ${t + 30} ${SILL_Y} C ${t + 16} ${SILL_Y - 2} ${t + 8} 316 ${t + 6} 300 Z`;
  return p;
}

function bPillar(g) { return Math.round(g.rw + (g.fw - g.rw) * 0.56); }

function glassPath(g) {
  const { tail: t, roofY, roofRear, roofFront, ws, belt } = g;
  const top = roofY + 12;
  let p;
  if (g.type === 'sedan') {
    const s = g.deckEnd + 40;
    p = `M ${s} ${belt} C ${s + 30} ${belt - 32} ${roofRear - 50} ${top + 6} ${roofRear + 10} ${top} `;
  } else {
    const s = t + 62;
    p = `M ${s} ${belt - 4} C ${s + 2} ${top + 40} ${t + 90} ${top + 8} ${t + 130} ${top} `;
  }
  return `${p}L ${roofFront - 12} ${top + 2} C ${roofFront + 30} ${top + 16} ${ws - 70} ${belt - 30} ${ws - 38} ${belt} Z`;
}

function wheel(cx, r) {
  const spokes = Array.from({ length: 5 }, (_, i) => {
    const a = (i * 72 - 90) * Math.PI / 180;
    return `<line x1="${(cx + Math.cos(a) * r * 0.2).toFixed(1)}" y1="${(WHEEL_Y + Math.sin(a) * r * 0.2).toFixed(1)}" x2="${(cx + Math.cos(a) * r * 0.6).toFixed(1)}" y2="${(WHEEL_Y + Math.sin(a) * r * 0.6).toFixed(1)}"/>`;
  }).join('');
  return `<g class="car-wheel"><circle class="tyre car-line" pathLength="1" cx="${cx}" cy="${WHEEL_Y}" r="${r}"/>
    <circle class="car-line" pathLength="1" cx="${cx}" cy="${WHEEL_Y}" r="${(r * 0.66).toFixed(1)}"/>
    <circle cx="${cx}" cy="${WHEEL_Y}" r="6" class="hub"/>${spokes}</g>`;
}

/* Zone anchor points on the sketch (x, y). */
function zoneAnchors(code) {
  const g = carGeometry(code);
  const bp = bPillar(g);
  const top = g.roofY + 12;
  const R = g.r + 5;
  return {
    exterior: [bp - 100, 278], lights: [g.nose - 40, g.hoodY + 30], wheels: [g.fw, WHEEL_Y], dynamics: [g.rw, WHEEL_Y],
    powertrain: [Math.round((g.ws + g.nose) / 2) - 10, g.hoodY + 22], charging: [g.rw + R + 32, g.belt + 26],
    assist: [g.roofFront + 5, top + 14], screens: [g.ws - 70, g.belt - 14], connect: [g.roofRear + 25, g.roofY - 8],
    seats: [bp + 34, g.belt - 46], climate: [bp - 30, top + 24], interior: [bp - 110, g.belt - 26],
    roof: [Math.round((g.roofRear + g.roofFront) / 2) + 20, g.roofY - 4], access: [bp + 40, g.belt + 22],
    space: g.type === 'sedan' ? [g.tail + 55, g.deckY + 22] : [g.tail + 40, 200], ownership: [g.tail + 10, 388],
  };
}

/* Car line art. opts: {code, animate, hotspots: [{key,label,tier,size,tip,active}], highlight: [zones], compact} */
function carSVG(opts) {
  const code = opts.code || 'G60';
  const g = carGeometry(code);
  const bp = bPillar(g);
  const top = g.roofY + 12;
  const R = g.r + 5;
  const anim = opts.animate ? 'animate' : '';
  const handleY = g.belt + 16;
  const interior = `<g class="car-ghost">
      <path d="M ${g.ws - 72} ${g.belt - 6} q -10 -24 2 -40"/>
      <path d="M ${bp + 58} ${g.belt + 4} L ${bp + 46} ${top + 30} q -2 -12 10 -12 l 6 0"/>
      <path d="M ${bp - 70} ${g.belt + 4} L ${bp - 84} ${top + 34} q -2 -12 10 -12 l 6 0"/>
    </g>`;
  const fin = `<path class="car-fill car-line" pathLength="1" d="M ${g.roofRear + 12} ${g.roofY - 1} q 12 -10 26 -3 l 2 4 z"/>`;
  const lines = `
    <path class="car-line detail" pathLength="1" d="M ${g.tail + 28} 250 C ${(g.tail + g.nose) / 2} 240 ${(g.tail + g.nose) / 2 + 100} 240 ${g.nose - 30} 248"/>
    <path class="car-line detail" pathLength="1" d="M ${bp} ${g.belt + 4} L ${bp - 2} 306"/>
    <path class="car-line detail" pathLength="1" d="M ${g.fw - R - 6} ${g.belt + 8} L ${g.fw - R - 6} 300"/>
    <path class="car-line detail" pathLength="1" d="M ${g.rw + R + 8} ${g.belt + 8} L ${g.rw + R + 8} 300"/>
    <path class="car-line detail" pathLength="1" d="M ${bp} ${top} L ${bp - 4} ${g.belt}" stroke-width="7"/>
    <rect class="car-handle" x="${bp + 24}" y="${handleY}" width="34" height="6" rx="3"/>
    <rect class="car-handle" x="${g.rw + R + 24}" y="${handleY}" width="34" height="6" rx="3"/>
    <path class="car-light front" d="M ${g.nose - 62} ${g.hoodY + 20} L ${g.nose - 14} ${g.hoodY + 30} L ${g.nose - 20} ${g.hoodY + 42} L ${g.nose - 66} ${g.hoodY + 32} Z"/>
    <path class="car-light rear" d="M ${g.tail + 8} 238 L ${g.tail + 56} 232 L ${g.tail + 54} 246 L ${g.tail + 10} 250 Z"/>
    <path class="car-fill car-line" pathLength="1" d="M ${g.ws - 52} ${g.belt - 4} q 18 -16 32 -4 l -4 12 z"/>
    <path class="car-kidney" d="M ${g.nose - 4} 262 q 6 12 0 26"/>`;
  const spots = (opts.hotspots || []).map((h, i) => hotspotSVG(code, h, i)).join('');
  const glow = (opts.highlight || []).map((z) => {
    const a = zoneAnchors(code)[z];
    return a ? `<circle class="zone-glow" cx="${a[0]}" cy="${a[1]}" r="34"/><circle class="zone-dot" cx="${a[0]}" cy="${a[1]}" r="8"/>` : '';
  }).join('');
  return `<svg class="car ${anim} ${opts.compact ? 'compact' : ''}" viewBox="${CAR_VIEWBOX}" role="img" aria-label="${esc(opts.label || `Side view of the ${code}`)}">
    <defs><linearGradient id="glass-${code}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--glass-1)"/><stop offset="1" stop-color="var(--glass-2)"/></linearGradient></defs>
    <ellipse class="car-shadow" cx="${(g.tail + g.nose) / 2}" cy="340" rx="${(g.nose - g.tail) / 2 + 10}" ry="9"/>
    <path class="car-body car-line" pathLength="1" d="${bodyPath(g)}"/>
    <path class="car-glass car-line" pathLength="1" d="${glassPath(g)}" fill="url(#glass-${code})"/>
    ${opts.compact ? '' : interior}${fin}${lines}
    ${wheel(g.rw, g.r)}${wheel(g.fw, g.r)}
    ${glow}<g class="hotspots">${spots}</g>
  </svg>`;
}

function hotspotSVG(code, h, i) {
  const a = zoneAnchors(code)[h.key];
  if (!a) return '';
  const r = h.size || 12;
  const tier = h.tier || 'none';
  return `<g class="hotspot tier-${tier} ${h.active ? 'active' : ''} ${h.dim ? 'dim' : ''}" data-zone="${esc(h.key)}" tabindex="0" role="button"
      aria-label="${esc(`${h.label}${h.tier ? `, top priority ${h.tier}` : ''}`)}" data-tip="${esc(h.tip || h.label)}"
      transform="translate(${a[0]} ${a[1]})" style="--d:${(i * 45) + 500}ms">
    <g class="hs-inner">
      ${tier === 'P1' ? `<circle class="hs-pulse" r="${r}"/>` : ''}
      <circle class="hs-ring" r="${r + 5}"/>
      <circle class="hs-dot" r="${r}"/>
      <text class="hs-text" text-anchor="middle" dy="0.35em">${esc(h.text ?? (h.tier || ''))}</text>
    </g>
    ${h.key === 'ownership' ? `<text class="hs-label" x="${r + 8}" dy="0.35em">Manual &amp; ownership</text>` : ''}
  </g>`;
}
