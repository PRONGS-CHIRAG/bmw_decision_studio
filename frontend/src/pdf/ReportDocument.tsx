import { Document, Font, Image, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
import { MODEL_NAMES, MOVE_LABELS, fmtEur, fmtInt, fmtNum, fmtPct } from "../api";
import type { AgentEvaluation, AgentStatus, Cell, Claim, CompTuple, CompareResult, CompetitorAnalysis, Explained, Fact, FeatureResult, Fitment } from "../types";
import { BASIS_LABEL, BRIEF_SECTIONS as COMP_SECTIONS, type CompState, VOLUME_WORDS, compCitations, equipText, gapText, money, specRange } from "../components/CompetitorPanel";
import type { ExplainState } from "../components/ProcessFlow";
import { TITLES, citationNumbers } from "../components/claims";
import { tierLabel } from "../components/marks";
import { REC_INFO, REC_ORDER, VERDICT_WORDS, bottomLine, complaintWords, groupCells, marketName, recGroup, seriesName } from "../plain";

// The whole report as an A4 PDF, built from the same objects the app shows. Claim text is printed exactly as
// verified; citations become numbers that point into the Sources appendix.

Font.registerHyphenationCallback((word) => [word]);       // no mid-word hyphens

const C = {
  ink: "#111827", text: "#1f2937", muted: "#6b7280", faint: "#98a2b3", border: "#e4e7ec", soft: "#f2f4f9",
  accent: "#2f6fed", accentSoft: "#eef3fd", success: "#059669", error: "#dc2626",
};
const TONE: Record<string, { line: string; bg: string }> = {
  go: { line: "#059669", bg: "#ecfdf5" },
  maybe: { line: "#2f6fed", bg: "#eef3fd" },
  low: { line: "#98a2b3", bg: "#f2f4f9" },
  unknown: { line: "#d97706", bg: "#fffbeb" },
  na: { line: "#d0d5dd", bg: "#f8f9fb" },
};
const SECTION_ORDER = ["customer_evidence", "market_view", "price_and_equipment", "risks_and_caveats", "next_steps"];
const SECTION_NAMES: Record<string, string> = { headline: "Bottom line", ...TITLES };
const RULE_NAMES: Record<string, string> = {
  citations: "Citations", numbers: "Numbers", labels: "Labels", quotes: "Quotes", scope: "Series / market", semantic: "Entailment",
};
const SHORT_TIER: Record<string, string> = {
  standard_all: "Standard", standard_some: "Partly standard", optional: "Optional", not_listed: "Not listed", no_link: "No link",
};

// Helvetica in a PDF covers Windows-1252 only; anything else is spelled out or replaced.
const SWAP: Record<string, string> = {
  "→": "->", "←": "<-", "↔": "<->", "≥": ">=", "≤": "<=", "≈": "~", "−": "-", "✓": "OK", "✕": "x", "✗": "x", "•": "•",
  " ": " ", " ": " ", " ": " ",
};
const CP1252 = new Set("€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ");
const CJK_RUN = /[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]+(?:[\s\d.,:/()-]*[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]+)*/g;
export function safe(s: unknown): string {
  return [...String(s ?? "").replace(CJK_RUN, "[Chinese text]")]
    .map((ch) => {
      if (SWAP[ch] !== undefined) return SWAP[ch];
      const c = ch.codePointAt(0)!;
      if (c === 10 || (c >= 32 && c <= 126) || (c >= 160 && c <= 255) || CP1252.has(ch)) return ch;
      return "?";
    })
    .join("");
}

const s = StyleSheet.create({
  page: { paddingTop: 54, paddingBottom: 56, paddingHorizontal: 48, fontFamily: "Helvetica", fontSize: 9.5, color: C.text },
  // No inherited line height: react-pdf compounds a relative one on fixed and nested elements. Set it per text style.
  body: {},
  topbar: { position: "absolute", top: 0, left: 0, right: 0, height: 5, backgroundColor: C.accent },
  runhead: { position: "absolute", top: 22, left: 48, right: 48, flexDirection: "row", justifyContent: "space-between", fontSize: 7.5, color: C.faint },
  footer: { position: "absolute", bottom: 24, left: 48, right: 48, flexDirection: "row", justifyContent: "space-between", fontSize: 7.5, color: C.faint, borderTopWidth: 0.5, borderTopColor: C.border, paddingTop: 6 },

  kicker: { fontSize: 8, fontFamily: "Helvetica-Bold", color: C.accent, letterSpacing: 1.2, textTransform: "uppercase" },
  title: { fontSize: 21, fontFamily: "Helvetica-Bold", color: C.ink, lineHeight: 1.25, marginTop: 6, marginBottom: 14 },
  meta: { flexDirection: "row", flexWrap: "wrap", backgroundColor: C.soft, borderRadius: 6, padding: 12, marginBottom: 18 },
  metaItem: { width: "33.33%", paddingRight: 10, paddingVertical: 4 },
  metaLabel: { fontSize: 7, color: C.muted, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 2 },
  metaValue: { fontSize: 9, color: C.ink },

  h1: { fontSize: 15, fontFamily: "Helvetica-Bold", color: C.ink, marginBottom: 2 },
  h1sub: { fontSize: 8.5, color: C.muted, marginBottom: 12, lineHeight: "12pt" },
  h2: { fontSize: 11.5, fontFamily: "Helvetica-Bold", color: C.ink, marginTop: 16, marginBottom: 3 },
  hint: { fontSize: 8, color: C.muted, marginBottom: 8 },
  p: { marginBottom: 6, lineHeight: "13pt" },
  small: { fontSize: 8, color: C.muted },
  bold: { fontFamily: "Helvetica-Bold" },

  answer: { borderLeftWidth: 4, borderRadius: 4, paddingVertical: 10, paddingHorizontal: 14, marginBottom: 6 },
  answerKicker: { fontSize: 7.5, fontFamily: "Helvetica-Bold", color: C.muted, textTransform: "uppercase", letterSpacing: 0.8, marginBottom: 3 },
  answerText: { fontSize: 12, fontFamily: "Helvetica-Bold", color: C.ink, lineHeight: 1.35 },
  answerMove: { fontSize: 8.5, color: C.text, marginTop: 5 },

  groups: { flexDirection: "row", flexWrap: "wrap", marginHorizontal: -4 },
  group: { width: "50%", padding: 4 },
  groupBox: { borderTopWidth: 3, borderWidth: 0.5, borderColor: C.border, borderRadius: 4, padding: 9, minHeight: 64 },
  groupHead: { flexDirection: "row", justifyContent: "space-between", marginBottom: 2 },
  groupLabel: { fontFamily: "Helvetica-Bold", color: C.ink, fontSize: 9.5 },
  groupN: { fontFamily: "Helvetica-Bold", color: C.muted },
  groupMeaning: { fontSize: 7.5, color: C.muted, marginBottom: 4 },

  facts: { borderTopWidth: 0.5, borderTopColor: C.border },
  factRow: { flexDirection: "row", paddingVertical: 6, borderBottomWidth: 0.5, borderBottomColor: C.border },
  factLabel: { width: "28%", color: C.muted, fontSize: 8.5 },
  factValue: { width: "72%", lineHeight: "12.5pt" },

  table: { borderWidth: 0.5, borderColor: C.border, borderRadius: 4 },
  tr: { flexDirection: "row", borderTopWidth: 0.5, borderTopColor: C.border },
  th: { flexDirection: "row", backgroundColor: C.soft },
  thText: { fontSize: 7, fontFamily: "Helvetica-Bold", color: C.muted, textTransform: "uppercase", letterSpacing: 0.4 },
  thCompact: { fontSize: 7, fontFamily: "Helvetica-Bold", color: C.muted, lineHeight: "9pt" },   // wraps: rival names
  td: { paddingVertical: 5, paddingHorizontal: 6, fontSize: 8.5 },
  tdNote: { paddingHorizontal: 6, paddingBottom: 6, fontSize: 7.5, color: C.muted, lineHeight: "10.5pt" },
  num: { textAlign: "right" },

  pill: { borderRadius: 8, paddingVertical: 1.5, paddingHorizontal: 6, fontSize: 7.5, fontFamily: "Helvetica-Bold", alignSelf: "flex-start" },

  briefsec: { marginBottom: 10 },
  briefTitle: { fontSize: 10, fontFamily: "Helvetica-Bold", color: C.ink, marginBottom: 4 },
  claim: { flexDirection: "row", marginBottom: 4 },
  bullet: { width: 10, color: C.accent },
  claimText: { flex: 1, lineHeight: "13pt" },     // absolute: the nested citation would compound a relative one
  cite: { fontSize: 7, color: C.accent, fontFamily: "Helvetica-Bold", lineHeight: "13pt" },
  note: { borderRadius: 4, padding: 10, backgroundColor: "#fffbeb", fontSize: 8.5, marginBottom: 8, lineHeight: "12.5pt" },

  figure: { borderWidth: 0.5, borderColor: C.border, borderRadius: 4, padding: 6, marginBottom: 6 },
  legend: { flexDirection: "row", flexWrap: "wrap", marginTop: 4 },
  legendItem: { flexDirection: "row", alignItems: "center", marginRight: 12, marginBottom: 3 },
  swatch: { width: 7, height: 7, borderRadius: 4, marginRight: 4 },

  stats: { flexDirection: "row", marginBottom: 10 },
  stat: { flex: 1, backgroundColor: C.soft, borderRadius: 4, padding: 8, marginRight: 6 },
  statValue: { fontSize: 14, fontFamily: "Helvetica-Bold", color: C.ink },
  statLabel: { fontSize: 7, color: C.muted, textTransform: "uppercase", letterSpacing: 0.4 },

  src: { flexDirection: "row", paddingVertical: 3.5, borderBottomWidth: 0.5, borderBottomColor: C.border },
  srcN: { width: 20, fontFamily: "Helvetica-Bold", color: C.accent, fontSize: 8 },
  srcBody: { flex: 1, fontSize: 8, lineHeight: "10.5pt" },
  srcId: { fontSize: 7, color: C.faint, fontFamily: "Courier" },
  srcProv: { fontSize: 7, color: C.muted, marginTop: 1 },
  toc: { marginTop: 4 },
  tocRow: { flexDirection: "row", paddingVertical: 2.5 },
  tocN: { width: 18, color: C.accent, fontFamily: "Helvetica-Bold" },
});

export interface GraphPictures {
  evaluation: string | null;
  schema: string | null;
  legend: { label: string; color: string }[];
}

export interface CompetitorsInput {
  compare: CompareResult | null;
  analysis: CompetitorAnalysis | null;
  state: CompState;
  error: string | null;
}

export interface ReportInput {
  competitors?: CompetitorsInput;
  evaluation: AgentEvaluation;
  explained: Explained | null;
  explainState: ExplainState;
  explainError: string | null;
  status: AgentStatus | null;
  pictures: GraphPictures;
  generatedAt: Date;
}

export default function ReportDocument({ evaluation, explained, explainState, explainError, status, pictures, generatedAt, competitors }: ReportInput) {
  const spec = evaluation.spec;
  const result = evaluation.result;
  const features = result.features;
  const numbers = citationNumbers(explained);
  const brief = explainState === "done" && explained ? explained : null;
  const date = generatedAt.toLocaleString("en-GB", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
  const shortIdea = safe(spec.idea.length > 70 ? `${spec.idea.slice(0, 69)}…` : spec.idea);
  const toc = [
    ...features.map((f) => `Evidence for ${f.feature}`),
    ...(features.length === 0 ? ["Closest features in the data"] : []),
    ...(competitors?.compare?.available ? ["Competitors"] : []),
    "The written brief", "Knowledge graph", "Verification", "Appendix: sources and facts",
    ...(competitors?.compare?.available ? ["Appendix: competitor sources"] : []), "Technical details",
  ];

  return (
    <Document title={`Idea evaluation: ${safe(spec.idea)}`} author="Product Idea Evaluation" subject="Product idea evaluation report"
      creator="Product Idea Evaluation" producer="Product Idea Evaluation">
      <Page size="A4" style={s.page} wrap>
        <View style={s.topbar} fixed />
        <View style={s.runhead} fixed render={({ pageNumber }) => (pageNumber > 1 ? (
          <>
            <Text>Product idea evaluation</Text>
            <Text>{shortIdea}</Text>
          </>
        ) : null)} />
        <View style={s.footer} fixed>
          <Text>Evaluation {evaluation.evaluation_id} · generated {date}</Text>
          <Text render={({ pageNumber, totalPages }) => `Page ${pageNumber} of ${totalPages}`} />
        </View>

        <View style={s.body}>
          {/* ---- opening */}
          <Text style={s.kicker}>Product idea evaluation</Text>
          <Text style={s.title}>{safe(spec.idea)}</Text>
          <View style={s.meta}>
            <Meta label="Matched feature" value={spec.features.map((f) => f.feature).join(", ") || "None in the data"} />
            <Meta label="Series in scope" value={(spec.series.length ? spec.series : result.models).map((m) => seriesName(m)).join(", ")} />
            <Meta label="Markets in scope" value={(spec.markets.length ? spec.markets : result.markets).map((m) => marketName(m)).join(", ")} />
            <Meta label="Proposed move" value={MOVE_LABELS[spec.move] ?? spec.move} />
            <Meta label="Proposed price" value={spec.proposed_price_eur ? fmtEur(spec.proposed_price_eur) : "None given"} />
            <Meta label="Generated" value={date} />
          </View>

          {spec.summary && norm(spec.summary) !== norm(spec.idea) ? <Text style={[s.p, { color: C.muted }]}>{safe(spec.summary)}</Text> : null}

          {features.length ? features.map((f) => <ShortAnswer key={f.feature} feature={f} move={spec.move} price={spec.proposed_price_eur} title={features.length > 1} />) : (
            <View style={[s.answer, { borderLeftColor: TONE.unknown.line, backgroundColor: TONE.unknown.bg }]}>
              <Text style={s.answerKicker}>The short answer</Text>
              <Text style={s.answerText}>The customer data has nothing on this idea directly, so it cannot tell you whether customers want it.</Text>
            </View>
          )}
          {brief && (brief.explanation.sections.headline ?? []).length > 0 && (
            <View style={{ marginTop: 6 }}>
              <Text style={s.answerKicker}>The brief in one sentence (verified)</Text>
              {brief.explanation.sections.headline.map((c) => <ClaimLine key={c.id} claim={c} numbers={numbers} bullet={false} />)}
            </View>
          )}

          <Text style={s.h2}>Contents</Text>
          <View style={s.toc}>
            {toc.map((t, i) => (
              <View key={t} style={s.tocRow}>
                <Text style={s.tocN}>{i + 1}</Text>
                <Text>{safe(t)}</Text>
              </View>
            ))}
          </View>

          {/* ---- evidence per feature */}
          {features.map((f) => <FeatureSection key={f.feature} feature={f} evaluation={evaluation} />)}
          {features.length === 0 && (
            <View break>
              <Text style={s.h1}>Closest features in the data</Text>
              <Text style={s.h1sub}>No customer comments, survey questions or price-list items match the idea directly. Pick one of these in the scope step to see its evidence.</Text>
              <Table cols={[["Feature", 36], ["Domain", 30], ["Verdict", 18], ["Comments", 16, true]]}
                rows={evaluation.candidates.slice(0, 8).map((c) => [c.feature, c.domain, c.verdict, fmtInt(c.n_comments)])} />
            </View>
          )}

          {/* ---- competitors */}
          {competitors?.compare?.available && <CompetitorSection input={competitors} />}
          {competitors && !competitors.compare?.available && competitors.state !== "idle" && (
            <View style={{ marginTop: 18 }} wrap={false}>
              <Text style={s.h2}>Competitors</Text>
              <Text style={s.note}>
                {safe(competitors.state === "loading" ? "The competitor comparison was still loading when this PDF was exported. Export again in a moment to include it."
                  : competitors.state === "error" ? `The competitor comparison could not be loaded${competitors.error ? `: ${competitors.error}` : ""}.`
                  : competitors.compare?.comparison.message ?? "No competitor data is available.")}
              </Text>
            </View>
          )}

          {/* ---- the written brief */}
          <View break>
            <Text style={s.h1}>The written brief</Text>
            <Text style={s.h1sub}>
              Written by the explainer from the computed facts only. Every sentence cites the facts it relies on (numbers in brackets, listed under Sources)
              and passed the verifier's checks.
            </Text>
            <BriefNote state={explainState} error={explainError} />
            {brief && SECTION_ORDER.filter((k) => (brief.explanation.sections[k] ?? []).length).map((k) => (
              <View key={k} style={s.briefsec}>
                <Text style={s.briefTitle} minPresenceAhead={40}>{SECTION_NAMES[k]}</Text>
                {brief.explanation.sections[k].map((c) => <ClaimLine key={c.id} claim={c} numbers={numbers} />)}
              </View>
            ))}
          </View>

          {/* ---- knowledge graph */}
          <View break>
            <Text style={s.h1}>Knowledge graph</Text>
            <Text style={s.h1sub}>
              The part of the knowledge graph this evaluation touches: {evaluation.graph.nodes.length} nodes, {evaluation.graph.n_cited} of them cited by a fact (blue ring).
              The idea is at the centre, then its features, the recommendations per series and market, and the evidence behind them.
            </Text>
            {pictures.evaluation ? (
              <View style={s.figure} wrap={false}>
                <Image src={pictures.evaluation} style={{ width: "100%", objectFit: "contain", maxHeight: 470 }} />
              </View>
            ) : <Text style={s.small}>The graph picture could not be drawn.</Text>}
            <View style={s.legend}>
              {pictures.legend.map((l) => (
                <View key={l.label} style={s.legendItem}>
                  <View style={[s.swatch, { backgroundColor: l.color }]} />
                  <Text style={s.small}>{l.label}</Text>
                </View>
              ))}
              <View style={s.legendItem}>
                <View style={[s.swatch, { borderWidth: 1.5, borderColor: C.accent, backgroundColor: "#fff" }]} />
                <Text style={s.small}>Cited by a fact</Text>
              </View>
            </View>
            {pictures.schema && (
              <View wrap={false}>
                <Text style={s.h2}>How all the data connects</Text>
                <Text style={s.hint}>
                  The whole knowledge graph by node type{status ? `: ${fmtInt(status.graph.nodes)} nodes and ${fmtInt(status.graph.edges)} edges, ${status.graph.checks_passed ? "all" : "not all"} ${status.graph.n_checks} integrity checks against the source tables passed` : ""}.
                </Text>
                <View style={s.figure}>
                  <Image src={pictures.schema} style={{ width: "100%", objectFit: "contain", maxHeight: 300 }} />
                </View>
              </View>
            )}
          </View>

          {/* ---- verification */}
          <View break>
            <Text style={s.h1}>Verification</Text>
            <Text style={s.h1sub}>
              Each claim must cite facts from the decision engine. Rules check citations, numbers, recommendation and verdict labels, quotes and the series
              and markets named; a second model then judges whether the cited facts support the claim. A failing claim is rewritten once, then removed.
            </Text>
            {explained ? <Verification explained={explained} /> : <Text style={s.small}>The verifier has not run for this evaluation, so there is nothing to report.</Text>}
          </View>

          {/* ---- sources */}
          <View break>
            <Text style={s.h1}>Appendix: sources and facts</Text>
            <Text style={s.h1sub}>
              Every fact the decision engine computed for this evaluation, with where it comes from. Numbered facts are cited in the brief.
            </Text>
            <Sources facts={evaluation.facts} numbers={numbers} />
          </View>

          {/* ---- competitor sources */}
          {competitors?.compare?.available && <CompetitorSources input={competitors} />}

          {/* ---- technical */}
          <View break={false} style={{ marginTop: 18 }} wrap={false}>
            <Text style={s.h2}>Technical details</Text>
            <View style={s.facts}>
              <FactRow label="Evaluation" value={evaluation.evaluation_id} />
              <FactRow label="Decision policy" value={`${result.policy.version} (hash ${result.policy_hash}), sales year ${result.policy.volume_year}`} />
              <FactRow label="Data version" value={result.data_hash} />
              <FactRow label="Idea matching" value={`${spec.method}${spec.novelty ? `, ${spec.novelty.replace(/_/g, " ")}` : ""}`} />
              {status && <FactRow label="Agents" value={`Retriever ${status.models.retriever}, explainer ${status.models.explainer}, verifier rules + ${status.models.verifier}`} />}
              {explained && <FactRow label="Brief" value={`Written by ${explained.explanation.model} in ${explained.explanation.attempts} draft(s), ${fmtNum(explained.seconds, 1)} s on the server`} />}
              {status && <FactRow label="Knowledge graph" value={`${fmtInt(status.graph.nodes)} nodes, ${fmtInt(status.graph.edges)} edges, built ${status.graph.built_at}`} />}
            </View>
            <Text style={[s.small, { marginTop: 10 }]}>
              Data: customer feedback exports for the 1, 5 and 7 Series, customer studies 2025 (CN/EU and US), sales volumes 2024-2030 and the German
              price lists of July 2026. Prices are EUR including 19% VAT and exist for Germany only. Complaint index 1.00 means as many complaints as
              expected for the channels the feature is discussed in. Internal prototype on hackathon data.
            </Text>
          </View>
        </View>
      </Page>
    </Document>
  );
}

const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <View style={s.metaItem}>
      <Text style={s.metaLabel}>{label}</Text>
      <Text style={s.metaValue}>{safe(value)}</Text>
    </View>
  );
}

function ShortAnswer({ feature, move, price, title }: { feature: FeatureResult; move: string; price: number | null; title: boolean }) {
  const line = bottomLine(feature);
  const tone = TONE[line.tone] ?? TONE.unknown;
  return (
    <View style={[s.answer, { borderLeftColor: tone.line, backgroundColor: tone.bg }]} wrap={false}>
      <Text style={s.answerKicker}>The short answer{title ? `: ${safe(feature.feature)}` : ""}</Text>
      <Text style={s.answerText}>{safe(line.text)}</Text>
      <Text style={s.answerMove}>Your proposal: {MOVE_LABELS[move] ?? move}{price ? ` at ${fmtEur(price)}` : ""}.</Text>
    </View>
  );
}

function FeatureSection({ feature, evaluation }: { feature: FeatureResult; evaluation: AgentEvaluation }) {
  const groups = groupCells(feature);
  const o = feature.overall;
  const year = evaluation.result.policy.volume_year;
  return (
    <View break>
      <Text style={s.h1}>Evidence for {safe(feature.feature)}</Text>
      <Text style={s.h1sub}>{safe(feature.domain)}{feature.umbrella ? " (umbrella feature)" : ""}. Everything in this section is computed from the data; no language model is involved.</Text>

      <Text style={[s.h2, { marginTop: 4 }]} minPresenceAhead={60}>Where to act</Text>
      <Text style={s.hint}>One recommendation per series and market.</Text>
      <View style={s.groups}>
        {REC_ORDER.filter((k) => groups.get(k)?.length).map((k) => {
          const cells = groups.get(k)!;
          const info = REC_INFO[k];
          return (
            <View key={k} style={s.group} wrap={false}>
              <View style={[s.groupBox, { borderTopColor: TONE[info.tone].line, backgroundColor: k === "notsold" ? TONE.na.bg : "#fff" }]}>
                <View style={s.groupHead}>
                  <Text style={s.groupLabel}>{info.label}</Text>
                  <Text style={s.groupN}>{cells.length}</Text>
                </View>
                <Text style={s.groupMeaning}>{info.meaning}</Text>
                {cells.map((c) => (
                  <Text key={`${c.model}|${c.market}`} style={{ fontSize: 8.5 }}>
                    <Text style={s.bold}>{seriesName(c.model)}</Text> in {marketName(c.market)}
                    {c.score !== null && (k === "prioritise" || k === "consider" || k === "low") ? <Text style={{ color: C.muted }}>  {fmtNum(c.score)}</Text> : null}
                  </Text>
                ))}
              </View>
            </View>
          );
        })}
      </View>

      <Text style={s.h2} minPresenceAhead={80}>The numbers, in plain words</Text>
      <View style={[s.facts, { marginTop: 4 }]}>
        <FactRow label="How customers feel" value={`${VERDICT_WORDS[o.verdict] ?? o.verdict} (${o.verdict}), based on ${fmtInt(o.n_comments)} comments.`} />
        <FactRow label="Complaints" value={complaintWords(o)} />
        <FactRow label="Priority score" value={feature.rollup.score === null ? "Not enough evidence for a score." : `${fmtNum(feature.rollup.score)} on a scale from 0 (no reason to act) to 1 (strong reason), weighted by how many cars are sold.`} />
        <FactRow label="Backed by data" value={`Direct evidence covers ${fmtPct(feature.rollup.evidence_volume_share)} of the cars sold in scope. The rest has too little feedback to judge.`} />
      </View>

      <Text style={s.h2} minPresenceAhead={80}>Series and markets in detail</Text>
      <Text style={s.hint}>Score from 0 to 1; coverage is the share of the score backed by direct evidence; cars sold in {year}.</Text>
      <CellTable cells={feature.cells} />

      <Text style={s.h2} minPresenceAhead={80}>Price and equipment today</Text>
      <Text style={s.hint}>German price lists, July 2026. EUR incl. 19% VAT. Prices for other markets are not in the data.</Text>
      <Ladder ladder={feature.price_ladder} />

      {feature.specs.length > 0 && (
        <>
          <Text style={s.h2} minPresenceAhead={60}>Technical data linked to {safe(feature.feature)}</Text>
          <Table cols={[["Series", 16], ["Variant", 22], ["Attribute (as printed)", 36], ["Value", 16, true], ["Page", 10, true]]}
            rows={feature.specs.slice(0, 40).map((x) => [MODEL_NAMES[x.model] ?? x.model, x.variant, x.attribute, x.value, `p.${x.page}`])} />
          {feature.specs.length > 40 && <Text style={[s.small, { marginTop: 4 }]}>And {feature.specs.length - 40} more values; see the app.</Text>}
        </>
      )}
    </View>
  );
}

function CellTable({ cells }: { cells: Cell[] }) {
  const W = [15, 15, 19, 8, 10, 11, 22];
  const head = ["Series", "Market", "Recommendation", "Score", "Coverage", "Cars sold", "Suggested action"];
  return (
    <View style={s.table}>
      <View style={s.th} fixed={false}>
        {head.map((h, i) => (
          <View key={h} style={[s.td, { width: `${W[i]}%` }]}>
            <Text style={[s.thText, i === 3 || i === 4 || i === 5 ? s.num : {}]}>{h}</Text>
          </View>
        ))}
      </View>
      {cells.map((c) => {
        const tone = TONE[REC_INFO[recGroup(c.recommendation)].tone];
        const scored = c.score !== null && c.recommendation !== "Not sold";
        return (
          <View key={`${c.model}|${c.market}`} style={{ borderTopWidth: 0.5, borderTopColor: C.border }} wrap={false}>
            <View style={{ flexDirection: "row" }}>
              <Text style={[s.td, { width: `${W[0]}%`, fontFamily: "Helvetica-Bold" }]}>{seriesName(c.model)}</Text>
              <Text style={[s.td, { width: `${W[1]}%` }]}>{marketName(c.market)}</Text>
              <View style={[s.td, { width: `${W[2]}%` }]}>
                <Text style={[s.pill, { backgroundColor: tone.bg, color: tone.line === "#d0d5dd" ? C.muted : tone.line }]}>{safe(c.recommendation)}</Text>
              </View>
              <Text style={[s.td, s.num, { width: `${W[3]}%` }]}>{scored ? fmtNum(c.score) : "–"}</Text>
              <Text style={[s.td, s.num, { width: `${W[4]}%` }]}>{c.recommendation === "Not sold" ? "–" : fmtPct(c.coverage)}</Text>
              <Text style={[s.td, s.num, { width: `${W[5]}%` }]}>{c.volume ? fmtInt(c.volume) : "–"}</Text>
              <Text style={[s.td, { width: `${W[6]}%`, fontSize: 7.5 }]}>{c.action ? safe(c.action.type) : "–"}</Text>
            </View>
            {c.reasons.length > 0 && (
              <View style={s.tdNote}>
                {c.reasons.map((r, i) => <Text key={i}>{safe(r)}</Text>)}
                {c.sales_note ? <Text>{safe(c.sales_note)}</Text> : null}
              </View>
            )}
          </View>
        );
      })}
    </View>
  );
}

function Ladder({ ladder }: { ladder: Fitment[] }) {
  if (!ladder.some((l) => l.tier !== "no_link"))
    return <Text style={s.small}>This feature has no curated link to the price lists, so availability and price are not shown.</Text>;
  return (
    <Table cols={[["Series", 15], ["Availability", 25], ["From", 12, true], ["Cheapest listed item", 26], ["Variants", 22]]}
      rows={ladder.map((l) => [
        `${MODEL_NAMES[l.model ?? ""] ?? l.model}`,
        `${SHORT_TIER[l.tier] ?? l.tier}: ${tierLabel(l.tier)}`,
        l.tier === "optional" && l.price_min_eur ? fmtEur(l.price_min_eur) : "–",
        l.price_item ? `${l.price_item}${l.price_via_package ? " (package)" : ""}${l.items[0] ? `, p.${l.items[0].page}` : ""}` : l.items.slice(0, 2).map((i) => `${i.name}, p.${i.page}`).join("; ") || "–",
        l.n_variants !== undefined ? `Standard on ${l.n_standard}, optional on ${l.n_optional} of ${l.n_variants}${l.price_pct_of_base ? `; from ${fmtNum(l.price_pct_of_base, 1)}% of base price` : ""}` : "–",
      ])} />
  );
}

function Table({ cols, rows, compactHead = false }: { cols: [string, number, boolean?][]; rows: string[][]; compactHead?: boolean }) {
  return (
    <View style={s.table}>
      <View style={s.th}>
        {cols.map(([h, w, r], i) => (
          <View key={`${h}|${i}`} style={[s.td, { width: `${w}%` }]}>
            <Text style={[compactHead ? s.thCompact : s.thText, r ? s.num : {}]}>{safe(h)}</Text>
          </View>
        ))}
      </View>
      {rows.map((row, i) => (
        <View key={i} style={s.tr} wrap={false}>
          {row.map((v, j) => (
            <Text key={j} style={[s.td, { width: `${cols[j][1]}%` }, cols[j][2] ? s.num : {}, j === 0 ? s.bold : {}]}>{safe(v)}</Text>
          ))}
        </View>
      ))}
    </View>
  );
}

function FactRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={s.factRow} wrap={false}>
      <Text style={s.factLabel}>{label}</Text>
      <Text style={s.factValue}>{safe(value)}</Text>
    </View>
  );
}

function ClaimLine({ claim, numbers, bullet = true }: { claim: Claim; numbers: Map<string, number>; bullet?: boolean }) {
  const refs = claim.fact_ids.map((id) => numbers.get(id)).filter((n): n is number => n !== undefined);
  return (
    <View style={s.claim} wrap={false}>
      {bullet && <Text style={s.bullet}>•</Text>}
      <Text style={[s.claimText, bullet ? {} : { fontSize: 10.5, fontFamily: "Helvetica-Bold", color: C.ink, lineHeight: "14.5pt" }]}>
        {safe(claim.text)}
        {refs.length > 0 && <Text style={s.cite}>{`  [${refs.join(", ")}]`}</Text>}
      </Text>
    </View>
  );
}

function BriefNote({ state, error }: { state: ExplainState; error: string | null }) {
  const text = {
    running: "The brief was still being written when this PDF was exported. Export again once it is ready to include it. Every other section comes straight from the data.",
    stale: "The decision policy was changed after the brief was written, so the brief is out of date and is left out. Write it again in the app, then export.",
    unavailable: `The writing agents were not available${error ? ` (${error})` : ""}. Every other section comes straight from the data.`,
    error: `The brief could not be written${error ? `: ${error}` : ""}. Nothing unchecked is shown.`,
    idle: "The brief had not been written when this PDF was exported.",
    done: "",
  }[state];
  return text ? <Text style={s.note}>{safe(text)}</Text> : null;
}

function Verification({ explained }: { explained: Explained }) {
  const v = explained.verification;
  return (
    <>
      <View style={s.stats}>
        <Stat label="Verified claims" value={String(v.n_verified)} />
        <Stat label="Removed claims" value={String(v.n_removed)} />
        <Stat label="Failed in first draft" value={String(v.rewritten.length)} />
        <Stat label="Semantic checker" value={v.semantic_model ?? "–"} small />
      </View>
      <View style={s.table}>
        <View style={s.th}>
          {[["Status", 12], ["Section", 16], ["Claim", 50], ["Checks", 22]].map(([h, w]) => (
            <View key={h} style={[s.td, { width: `${w}%` }]}><Text style={s.thText}>{h}</Text></View>
          ))}
        </View>
        {v.claims.map((c) => {
          const removed = c.status === "removed";
          const failed = c.checks.filter((ch) => !ch.passed);
          return (
            <View key={c.id} style={s.tr} wrap={false}>
              <View style={[s.td, { width: "12%" }]}>
                <Text style={[s.pill, { backgroundColor: removed ? "#fef2f2" : "#ecfdf5", color: removed ? C.error : C.success }]}>{removed ? "Removed" : "Verified"}</Text>
              </View>
              <Text style={[s.td, { width: "16%", color: C.muted, fontSize: 8 }]}>{SECTION_NAMES[c.section] ?? c.section}</Text>
              <Text style={[s.td, { width: "50%" }, removed ? { color: C.muted } : {}]}>{safe(c.text)}</Text>
              <Text style={[s.td, { width: "22%", fontSize: 7.5, color: failed.length ? C.error : C.muted }]}>
                {failed.length
                  ? failed.map((ch) => `${RULE_NAMES[ch.name] ?? ch.name}: ${ch.detail}`).join(" ")
                  : `${c.checks.length} of ${v.rules.length} passed: ${c.checks.map((ch) => RULE_NAMES[ch.name] ?? ch.name).join(", ")}`}
              </Text>
            </View>
          );
        })}
      </View>
      {v.rewritten.length > 0 && (
        <View style={{ marginTop: 10 }}>
          <Text style={s.briefTitle}>First-draft claims that failed and were rewritten</Text>
          {v.rewritten.map((c) => (
            <Text key={c.id} style={[s.small, { marginBottom: 3 }]}>
              "{safe(c.text)}" - {safe(c.checks.filter((ch) => !ch.passed).map((ch) => `${RULE_NAMES[ch.name] ?? ch.name}: ${ch.detail}`).join(" "))}
            </Text>
          ))}
        </View>
      )}
    </>
  );
}

function Stat({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <View style={s.stat}>
      <Text style={[s.statValue, small ? { fontSize: 9, marginTop: 4, marginBottom: 2 } : {}]}>{safe(value)}</Text>
      <Text style={s.statLabel}>{label}</Text>
    </View>
  );
}

function Sources({ facts, numbers }: { facts: Fact[]; numbers: Map<string, number> }) {
  const cited = facts.filter((f) => numbers.has(f.id)).sort((a, b) => numbers.get(a.id)! - numbers.get(b.id)!);
  const rest = facts.filter((f) => !numbers.has(f.id));
  const row = (f: Fact, n: string) => (
    <View key={f.id} style={s.src} wrap={false}>
      <Text style={s.srcN}>{n}</Text>
      <View style={s.srcBody}>
        <Text>{safe(f.statement)}</Text>
        <Text style={s.srcProv}>
          {safe(`${f.source.kind}: ${f.source.ref}${f.source.key ? ` · ${f.source.key}` : ""}${f.source.page ? ` · page ${f.source.page}` : ""}`)}
          <Text style={s.srcId}>{`   ${safe(f.id)}`}</Text>
        </Text>
      </View>
    </View>
  );
  return (
    <>
      {cited.length > 0 && (
        <>
          <Text style={[s.briefTitle, { marginTop: 4 }]}>Cited in the brief ({cited.length})</Text>
          {cited.map((f) => row(f, String(numbers.get(f.id))))}
        </>
      )}
      {rest.length > 0 && (
        <>
          <Text style={[s.briefTitle, { marginTop: 12 }]} minPresenceAhead={40}>{cited.length ? `Other facts computed (${rest.length})` : `Facts computed (${rest.length})`}</Text>
          {rest.map((f) => row(f, "–"))}
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------- competitors
/** Helvetica prints WinAnsi only: text that is mostly another script (Chinese names) gets a readable fallback. */
function latin(text: string | null | undefined, fallback = "(name in Chinese; see the app)"): string {
  const t = String(text ?? "");
  const other = [...t].filter((ch) => (ch.codePointAt(0) ?? 0) > 0x24f).length;
  return other > 0 && other / Math.max(t.length, 1) > 0.2 ? fallback : t;
}
const COMP_STATE_TEXT: Record<string, string> = {
  running: "The competitor agents were still working when this PDF was exported; the tables come straight from the data. Export again to include the written comparison.",
  unavailable: "The competitor agents were not available, so there is no written comparison. The tables come straight from the data.",
  error: "The written comparison could not be produced. Nothing unchecked is shown; the tables come straight from the data.",
  loading: "The competitor comparison was still loading when this PDF was exported.",
  idle: "", done: "", nodata: "",
};

function CompetitorSection({ input }: { input: CompetitorsInput }) {
  const c = input.compare!.comparison;
  const a = input.state === "done" ? input.analysis : null;
  const numbers = compCitations(a);
  const sections = a?.brief?.sections ?? {};
  const tuples = c.tuples;
  return (
    <View break>
      <Text style={s.h1}>Competitors</Text>
      <Text style={s.h1sub}>
        {safe(`BMW against its top five competitors per series and market: rivals ranked by sales in the same segment, with prices, German-market equipment, product data and reviews from public web sources${c.retrieved_to ? ` retrieved ${String(c.retrieved_from ?? "").slice(0, 10)} to ${c.retrieved_to.slice(0, 10)}` : ""}. Prices are compared within one market and currency, never converted. Citations [C1], [C2] ... point to the competitor sources appendix.`)}
      </Text>
      {COMP_STATE_TEXT[input.state] ? <Text style={s.note}>{safe(COMP_STATE_TEXT[input.state])}</Text> : null}
      {a && !a.brief && <Text style={s.note}>{safe(a.message ?? "No finding passed verification.")}</Text>}
      {a?.brief && (
        <View>
          {(sections.headline ?? []).map((cl) => <CompClaimLine key={cl.id} claim={cl} numbers={numbers} bullet={false} />)}
          {COMP_SECTIONS.filter((x) => (sections[x.key] ?? []).length).map((x) => (
            <View key={x.key} style={s.briefsec}>
              <Text style={s.briefTitle} minPresenceAhead={40}>{x.title}</Text>
              {sections[x.key].map((cl) => <CompClaimLine key={cl.id} claim={cl} numbers={numbers} />)}
            </View>
          ))}
          <Text style={[s.small, { marginBottom: 6 }]}>
            {safe(`Written by ${a.brief.model} from ${a.analysis.findings.length} verified findings of ${a.analysis.model} (${a.analysis.removed.length} removed); ${a.verification?.n_presented_verified ?? 0} sentences verified, ${a.verification?.n_presented_replaced ?? 0} replaced by the analyst's finding.`)}
          </Text>
        </View>
      )}
      {tuples.map((t) => <CompTupleBlock key={`${t.series}|${t.market}`} t={t} items={c.items ?? []} />)}
      {(c.caveats ?? []).length > 0 && (
        <View style={{ marginTop: 8 }} wrap={false}>
          <Text style={s.briefTitle}>Limits of this comparison</Text>
          {c.caveats!.map((cv) => <Text key={cv.id} style={[s.small, { marginBottom: 2 }]}>{safe(`- ${cv.text}`)}</Text>)}
        </View>
      )}
    </View>
  );
}

function latinRule(t: CompTuple): string {
  // the rule names the source's segment label; in the PDF a Chinese label is replaced by its English gloss
  let rule = t.selection_rule || "as listed";
  for (const c of t.competitors) {
    const { segment_text: st, segment_english: en } = c.selection;
    if (st && en && st !== en) rule = rule.split(st).join(en);
  }
  return latin(rule, "ranked by sales in the source's segment table");
}

function CompClaimLine({ claim, numbers, bullet = true }: { claim: Claim; numbers: Map<string, number>; bullet?: boolean }) {
  const refs = claim.fact_ids.map((id) => numbers.get(id)).filter((n): n is number => n !== undefined);
  return (
    <View style={s.claim} wrap={false}>
      {bullet && <Text style={s.bullet}>•</Text>}
      <Text style={[s.claimText, bullet ? {} : { fontSize: 10.5, fontFamily: "Helvetica-Bold", color: C.ink, lineHeight: "14.5pt" }]}>
        {safe(claim.text)}
        {refs.length > 0 && <Text style={s.cite}>{`  [${refs.map((n) => `C${n}`).join(", ")}]`}</Text>}
      </Text>
    </View>
  );
}

const BRAND_SHORT: Record<string, string> = {
  "Mercedes-Benz": "Mercedes", "Mercedes-Maybach": "Maybach", "Mercedes-AMG": "AMG", "DS Automobiles": "DS", "IM Motors": "IM",
  Volkswagen: "VW",
};
/** 'Mercedes E-Class' rather than 'Mercedes-Benz E-Class': matrix headers wrap at spaces only. */
function shortName(c: { name: string; brand?: string | null; model?: string | null }): string {
  if (!c.brand || !c.model) return c.name;
  const model = c.model.replace(/\s*\(.*\)$/, "");
  return `${BRAND_SHORT[c.brand] ?? c.brand} ${model}`;
}

function CompTupleBlock({ t, items }: { t: CompTuple; items: { key: string; label: string }[] }) {
  if (t.status !== "ok" || !t.bmw)
    return (
      <View wrap={false} style={{ marginTop: 10 }}>
        <Text style={s.h2}>{safe(`${t.series_name} in ${t.market_name}`)}</Text>
        <Text style={s.small}>{safe(t.note ?? "No competitor set.")}</Text>
      </View>
    );
  const cur = t.reference.currency;
  const bmw = t.bmw;
  const comps = t.competitors;
  const pr = t.summary?.price;
  const w = Math.floor(78 / (comps.length + 1));
  return (
    <View style={{ marginTop: 6 }}>
      <Text style={s.h2} minPresenceAhead={120}>{safe(`${t.series_name} in ${t.market_name}`)}</Text>
      <Text style={s.hint}>
        {safe(`Rivals ${latinRule(t)}. Prices: ${t.reference.country_name}, ${cur}${t.market === "EU" ? " (BMW from its own DE price list)" : ""}.${pr ? ` Entry price rank ${pr.bmw_rank_from_cheapest} of ${pr.n_models} (1 = cheapest; ${latin(pr.bmw_variant, "cheapest version")}, ${money(pr.bmw_amount, cur)}); ${gapText({ abs: pr.bmw_vs_median_abs, pct: pr.bmw_vs_median_pct, direction: pr.bmw_vs_median_abs > 0 ? "above" : pr.bmw_vs_median_abs < 0 ? "below" : "equal" }, cur)} vs the rivals' median${BASIS_LABEL[pr.basis] ? ` (${BASIS_LABEL[pr.basis]})` : ""}.` : ""}`)}
      </Text>
      <Table cols={[["Model", 24], ["Entry version", 22], ["Entry price", 15, true], ["vs BMW", 19, true], ["Sold", 10, true], ["Rating", 10]]}
        rows={[
          [bmw.name, bmw.entry ? `${latin(bmw.entry.variant, "cheapest version")} (${bmw.entry.powertrain})` : "-", money(bmw.entry?.amount, cur), "-",
            comps.find((c) => c.bmw_sales)?.bmw_sales ? fmtInt(comps.find((c) => c.bmw_sales)!.bmw_sales!.units) : "-",
            bmw.ratings.map((r) => `${r.score}/${r.scale_max}`).join("; ") || "-"],
          ...comps.map((c) => [`${c.rank}. ${c.name}`, c.entry ? `${latin(c.entry.variant, "cheapest version")} (${c.entry.powertrain})` : "no price found",
            money(c.entry?.amount, cur),
            `${gapText(c.gap, cur)}${c.gap && c.bmw_ref && bmw.entry && (c.bmw_ref.basis !== bmw.entry.basis || c.bmw_ref.variant !== bmw.entry.variant) ? ` vs ${c.bmw_ref.variant} ${money(c.bmw_ref.amount, cur)}${BASIS_LABEL[c.bmw_ref.basis] ? ` (${BASIS_LABEL[c.bmw_ref.basis]})` : ""}` : ""}`,
            c.sales ? fmtInt(c.sales.units) : "-",
            c.ratings.map((r) => `${r.score}/${r.scale_max}`).join("; ") || "-"]),
        ]} />
      {(t.set_notes ?? []).length > 0 && <Text style={[s.small, { marginTop: 3 }]}>{safe(t.set_notes!.map((n) => n[0].toUpperCase() + n.slice(1)).join(". ") + ".")}</Text>}
      {comps.some((c) => c.sales) && (
        <Text style={[s.small, { marginTop: 3 }]}>
          {safe(`Sold: ${VOLUME_WORDS[comps.find((c) => c.sales)?.sales?.basis ?? ""] ?? "units sold"} in ${comps.find((c) => c.sales)?.sales?.region} in ${comps.find((c) => c.sales)?.sales?.year} (${comps.find((c) => c.sales)?.sales?.source?.publisher ?? ""}).`)}
        </Text>
      )}
      {items.length > 0 && (
        <View style={{ marginTop: 6 }}>
          <Text style={s.briefTitle} minPresenceAhead={60}>Equipment for this idea (German market)</Text>
          <Table compactHead cols={[["Item", 22], [seriesName(t.series), w], ...comps.map((c) => [shortName(c), w] as [string, number])]}
            rows={items.map((it) => [it.label, equipText(bmw.equipment[it.key]), ...comps.map((c) => equipText(c.equipment[it.key]))])} />
        </View>
      )}
      <View style={{ marginTop: 6 }}>
        <Text style={s.briefTitle} minPresenceAhead={60}>Product</Text>
        <Table compactHead cols={[["Attribute", 22], [seriesName(t.series), w], ...comps.map((c) => [shortName(c), w] as [string, number])]}
          rows={["power_kw", "accel_0_100_s", "length_mm", "boot_l", "range_km_wltp"].filter((k) => bmw.specs[k] || comps.some((c) => c.specs[k]))
            .map((k) => [(bmw.specs[k] ?? comps.find((c) => c.specs[k])?.specs[k])?.label ?? k, specRange(bmw.specs[k]), ...comps.map((c) => specRange(c.specs[k]))])} />
      </View>
    </View>
  );
}

function CompetitorSources({ input }: { input: CompetitorsInput }) {
  const cmp = input.compare!;
  const a = input.state === "done" ? input.analysis : null;
  const numbers = compCitations(a);
  const facts = new Map(cmp.facts.map((f) => [f.id, f]));
  const cited = [...numbers.entries()].sort((x, y) => x[1] - y[1]).map(([id, n]) => ({ id, n, f: facts.get(id) }));
  const srcs = cmp.comparison.sources ?? [];
  return (
    <View break>
      <Text style={s.h1}>Appendix: competitor sources</Text>
      <Text style={s.h1sub}>The competitor facts cited in the written comparison, and every web page the comparison above draws on. Each value was quoted from a saved copy of its page.</Text>
      {cited.length > 0 && (
        <>
          <Text style={[s.briefTitle, { marginTop: 4 }]}>Cited in the comparison ({cited.length})</Text>
          {cited.map(({ id, n, f }) => (
            <View key={id} style={s.src} wrap={false}>
              <Text style={s.srcN}>{`C${n}`}</Text>
              <View style={s.srcBody}>
                <Text>{safe(f ? f.statement : "This fact is not in the bundle.")}</Text>
                {f && <Text style={s.srcProv}>{safe(`${f.source.kind}: ${f.source.ref}${f.source.key ? ` · ${f.source.key}` : ""}${f.source.page ? ` · page ${f.source.page}` : ""}`)}<Text style={s.srcId}>{`   ${safe(id)}`}</Text></Text>}
              </View>
            </View>
          ))}
        </>
      )}
      <Text style={[s.briefTitle, { marginTop: 12 }]} minPresenceAhead={40}>{`Web sources (${srcs.length})`}</Text>
      {srcs.map((w) => (
        <View key={w.source_id} style={s.src} wrap={false}>
          <Text style={[s.srcN, { width: 60 }]}>{safe(w.publisher ?? "")}</Text>
          <View style={s.srcBody}>
            <Text>{safe(w.title || w.url || "")}</Text>
            <Text style={s.srcProv}>{safe(`${w.url ?? ""} · retrieved ${(w.retrieved_at ?? "").slice(0, 10)}`)}</Text>
          </View>
        </View>
      ))}
    </View>
  );
}

