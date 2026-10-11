// Shapes returned by bmw_feedback/api.py (only the fields the UI reads).
// Engine shapes first, then the agent contracts (bmw_feedback/agents/contracts.py).

export interface Match {
  feature: string;
  score: number;
  how: string;
  domain: string;
  n_comments: number;
  verdict: string;
  umbrella: boolean;
}

export interface Resolution {
  idea: string;
  status: "direct" | "related" | "none";
  matches: Match[];
  suggested: string[];
  predicted_domains: { domain: string; score: number }[];
}

export interface Signal {
  score: number | null;
  status: string;
  weight: number;
  effective_weight: number;
  contribution: number | null;
  level?: string;
  n_comments?: number;
  n_comments_market?: number;
  verdict?: string;
  complaint_index?: number;
  request_index?: number;
  ci_low?: number;
  ci_high?: number;
  observed?: number;
  expected?: number;
  requested?: boolean;
  model_comments?: number;
  share?: number;
  rank_among_features?: number;
  n_features?: number;
  sheet?: string;
  survey_model?: string;
  note?: string | null;
  attributes?: {
    attribute: string;
    rank: number;
    of: number;
    weakness: number;
    mean?: number;
    model_mean?: number;
    top2_box?: number;
    bottom3_box?: number;
    model_mean_top2?: number;
  }[];
}

export interface FitItem {
  name: string;
  sa_code: string | null;
  page: number;
  matched_keyword: string;
  matched_in: string;
}

export interface Fitment {
  model?: string;
  tier: string;
  listed_on?: string[];
  n_variants?: number;
  n_standard?: number;
  n_optional?: number;
  price_min_eur?: number | null;
  price_max_eur?: number | null;
  price_pct_of_base?: number | null;
  price_item?: string | null;
  price_via_package?: boolean | null;
  items: FitItem[];
}

export interface Quote {
  comment_id: number;
  sentiment: string;
  feedback_type: string;
  source: string;
  country: string;
  reason: string;
  text: string;
}

export interface Cell {
  model: string;
  model_name: string;
  market: string;
  market_name: string;
  sales: Record<string, number>;
  volume: number;
  sales_note: string | null;
  recommendation: string;
  score: number | null;
  coverage: number;
  market_weight?: number;
  signals: Record<string, Signal>;
  action: { type: string; tier: string; basis: string } | null;
  reasons: string[];
  evidence: { comment_ids?: number[]; n_comment_ids?: number; quotes?: Quote[] };
}

export interface FeatureResult {
  feature: string;
  domain: string;
  umbrella: boolean;
  overall: {
    verdict: string;
    confidence: string;
    n_comments: number;
    complaint_index: number;
    ci_low: number;
    ci_high: number;
    request_index: number;
    praise_index: number;
  };
  cells: Cell[];
  rollup: { score: number | null; evidence_volume_share: number; by_model: Record<string, { score: number | null; markets: string[] }> };
  price_ladder: Fitment[];
  specs: { model: string; variant: string; attribute: string; value: string; page: number }[];
  headline: string;
}

export interface Policy {
  version: string;
  weights: Record<string, number>;
  market_multipliers: Record<string, number>;
  volume_year: number;
  thresholds: Record<string, number>;
  borrowing: { enabled: boolean; discount: number; into_cn: boolean };
  scoring: {
    complaint_points: Record<string, number>;
    request_points: { requested: number; index_at_least: number; elevated: number; otherwise: number };
    min_comments_for_signal: number;
    survey_weakness: string;
    breadth: string;
  };
  rationale: Record<string, string>;
}

export interface EvaluateResult {
  idea: string;
  status: string;
  headline?: string;
  resolution: Resolution | null;
  features: FeatureResult[];
  policy: Policy;
  policy_hash: string;
  data_hash: string;
  models: string[];
  markets: string[];
}

export interface Decision {
  id: string;
  recorded_at: string;
  pm: string;
  idea: string;
  feature: string;
  decision: "accept" | "override";
  rationale: string;
  system_recommendation?: Record<string, unknown> | null;
  policy_hash: string;
  data_hash: string;
}

// ---------------------------------------------------------------------- agents
export type Move = "fix_existing" | "make_standard" | "new_option" | "price_change" | "introduce_on_series" | "unspecified";
export type Novelty = "matches_existing" | "related_only" | "new_to_data";

export interface Candidate {
  feature: string;
  node_id: string;
  domain: string;
  verdict: string;
  n_comments: number;
  complaint_index: number | null;   // complaints vs. what is typical for the channels (1.0 = typical)
  umbrella: boolean;
  methods: Record<string, number>;
  how: string[];
}

export interface FeaturePick {
  feature: string;
  node_id: string;
  reason: string;
  methods: Record<string, number>;
}

export interface IdeaSpec {
  idea: string;
  summary: string;
  features: FeaturePick[];
  series: string[];
  markets: string[];
  move: Move;
  proposed_price_eur: number | null;
  novelty: Novelty;
  ambiguities: string[];
  method: string;
}

export interface InterpretResult {
  spec: IdeaSpec;
  candidates: Candidate[];
  semantic_method: string;
  semantic_error: string | null;
  method: string;
  attempts: { attempt: number; ok: boolean; errors: string[] }[];
}

export interface Provenance {
  node_id: string | null;
  kind: string;
  ref: string;
  key: string | null;
  page: number | null;
}

export interface Fact {
  id: string;
  group: string;
  statement: string;
  value: number | string | boolean | null;
  unit: string | null;
  feature: string | null;
  series: string | null;
  market: string | null;
  source: Provenance;
}

export interface GraphNode {
  id: string;
  type: string;
  group: string;
  label: string;
  cited: boolean;
  chosen?: boolean;
  virtual?: boolean;
  recommendation?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  rel: string;
}

export interface AgentEvaluation {
  evaluation_id: string;
  spec: IdeaSpec;
  result: EvaluateResult;
  facts: Fact[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[]; n_cited: number };
  candidates: Candidate[];
}

export interface Check {
  name: string;
  passed: boolean;
  detail: string;
}

export interface Claim {
  id: string;
  section: string;
  text: string;
  fact_ids: string[];
  status: "verified" | "removed";
  attempt: number;
  checks: Check[];
}

export interface Explained {
  explanation: { evaluation_id: string; model: string; sections: Record<string, Claim[]>; attempts: number };
  verification: {
    evaluation_id: string;
    rules: string[];
    semantic_model: string | null;
    claims: Claim[];
    rewritten: Claim[];
    n_verified: number;
    n_removed: number;
  };
  seconds: number;
}

export interface AgentStatus {
  llm_configured: boolean;
  provider: string;
  models: Record<string, string>;
  graph: { nodes: number; edges: number; built_at: string; checks_passed: boolean; n_checks: number };
  message: string | null;
}

export interface GraphSchema {
  n_nodes: number;
  n_edges: number;
  built_at: string;
  node_types: { type: string; group: string; count: number }[];
  edge_types: { source: string; rel: string; target: string; count: number }[];
  checks: { check: string; graph: number; source: number; ok: boolean }[];
  not_in_graph: { source: string; why: string }[] | null;
}

export interface NodeView {
  id: string;
  type: string;
  group: string;
  label: string;
  prov: { kind: string; ref: string; key: string | null; page: number | null };
  attributes: Record<string, unknown>;
  neighbours: { rel: string; direction: "in" | "out"; total: number; items: { id: string; type: string; label: string }[] }[];
}

/** /api/graph/full: every node with a precomputed position; edges as index pairs into `nodes`. */
export interface FullGraph {
  built_at: string;
  n_nodes: number;
  n_edges: number;
  nodes: [id: string, type: string, group: string, label: string, x: number, y: number][];
  edges: [source: number, target: number, rel: string][];
}

// ---------------------------------------------------------------------- competitors (bmw_feedback/competitors, agents/competition.py)
export interface WebSource {
  source_id: string;
  publisher: string | null;
  url: string | null;
  title: string | null;
  retrieved_at: string | null;
}

export interface CompPrice {
  model_id: string;
  variant: string;
  powertrain: string;
  group: "combustion" | "plug-in hybrid" | "electric";
  amount: number;
  currency: string;
  basis: string;
  tax_basis: string | null;
  power_kw: number | null;
  model_year?: string | null;
  row_id: string | null;
  source: { kind: string; publisher?: string | null; url?: string | null; ref?: string; page?: number; retrieved_at?: string | null };
}

export interface Gap {
  abs: number;
  pct: number;
  direction: "above" | "below" | "equal";
}

export interface CompSpec {
  label: string;
  unit: string;
  min: number;
  max: number;
  n: number;
  variants: string[];
  sources: string[];
}

export interface CompEquipment {
  status: "standard" | "standard_some" | "optional" | "package" | "not_available" | "unknown" | "not_listed";
  price_eur?: number | null;
  price_item?: string | null;
  price_status?: string | null;
  variant_scope?: string | null;
  rows?: { status: string; price_eur: number | null; item_name: string; variant_scope: string | null; note?: string | null; source: WebSource | null }[];
  publisher?: string | null;
  list_date?: string | null;
  // BMW side (DE price list)
  n_variants?: number | null;
  n_standard?: number | null;
  n_optional?: number | null;
  via_package?: boolean | null;
  items?: string | null;
  pages?: string | null;
}

export interface CompSales {
  units: number;
  year: number;
  region: string;
  basis: string;
  tier: string;
  segment_label: string | null;
  segment_text?: string | null;
  same_source: boolean;
  source: WebSource | null;
}

export interface CompRating {
  publisher: string | null;
  kind: string;
  score: number;
  scale_max: number;
  n_reviews: number | null;
  source: WebSource | null;
  bmw?: CompRating | null;
}

export interface CompReviews {
  n: number;
  positive?: number;
  negative?: number;
  request?: number;
  unassigned?: number;
  top_praise?: [string, number][];
  top_criticism?: [string, number][];
  publishers?: string[];
  in_domain?: Record<string, { positive: number; negative: number }>;
  quotes?: { text: string; kind: string; sentiment: string; source: WebSource | null }[];
}

export interface Competitor {
  rank: number;
  model_id: string;
  name: string;
  brand?: string | null;
  model?: string | null;
  segment: string | null;
  generation: string | null;
  basis: "sales" | "sales_other_segment" | "sales_other_source" | "rival_mentions";
  selection: { units: number | null; year: number | null; region: string | null; segment_label: string | null; segment_text: string | null; segment_english: string | null; n_rival_mentions: number | null; source: WebSource | null; note: string | null };
  prices: CompPrice[];
  entry: CompPrice | null;
  bmw_ref: CompPrice | null;          // the BMW price on the same basis the gap is measured against
  gap: Gap | null;
  by_powertrain: { group: string; competitor: CompPrice | null; bmw: CompPrice | null; gap: Gap | null }[];
  sales: CompSales | null;
  bmw_sales: CompSales | null;
  sales_vs_bmw: { abs: number; pct: number; same_source: boolean } | null;
  specs: Record<string, CompSpec>;
  equipment: Record<string, CompEquipment>;
  ratings: CompRating[];
  reviews: CompReviews;
}

export interface CompTuple {
  series: string;
  series_name: string;
  market: string;
  market_name: string;
  reference: { country: string; country_name: string; currency: string };
  status: "ok" | "not_sold" | "no_data";
  note?: string | null;
  selection_rule?: string;
  set_notes?: string[];
  old_equipment_lists?: string[];
  bmw?: {
    model_id: string;
    name: string;
    prices: CompPrice[];
    entry: CompPrice | null;
    specs: Record<string, CompSpec>;
    equipment: Record<string, CompEquipment>;
    ratings: CompRating[];
    reviews: CompReviews;
  };
  competitors: Competitor[];
  summary?: {
    price?: { bmw_rank_from_cheapest: number; n_models: number; n_competitors_priced: number; median_competitor: number; bmw_vs_median_abs: number; bmw_vs_median_pct: number; currency: string; basis: string; bmw_variant: string; bmw_amount: number; tax_basis: string | null };
    equipment?: Record<string, Record<string, number>>;
  };
}

export interface Comparison {
  available: boolean;
  message?: string;
  data_hash?: string;
  retrieved_from?: string | null;
  retrieved_to?: string | null;
  features?: string[];
  items?: { key: string; label: string; feature: string }[];
  features_without_items?: string[];
  tuples: CompTuple[];
  sources?: WebSource[];
  caveats?: { id: string; text: string }[];
}

export interface CompareResult {
  competition_id: string | null;
  available: boolean;
  comparison: Comparison;
  facts: Fact[];
  graph_missing_nodes?: number;
}

export interface Finding extends Claim {
  series: string;
  market: string;
}

export interface PresentedClaim extends Claim {
  finding_ids: string[];
  origin: "presenter" | "analyst_fallback";
}

export interface CompetitorAnalysis {
  competition_id: string;
  analysis: { model: string | null; attempts: number; findings: Finding[]; removed: Finding[]; rewritten: Finding[] };
  brief: { model: string | null; sections: Record<string, PresentedClaim[]> } | null;
  verification: {
    rules: string[];
    semantic_model: string | null;
    presented: PresentedClaim[];
    n_presented_verified: number;
    n_presented_replaced: number;
    n_findings_verified: number;
    n_findings_removed: number;
  } | null;
  seconds: number;
  message: string | null;
}
