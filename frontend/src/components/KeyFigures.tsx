import { fmtInt, fmtNum, fmtPct } from "../api";
import type { Explained, FeatureResult } from "../types";
import { Verdict } from "./marks";

/** Key figures in bmw.de's technical-data style: light label above a light value, a source note below. */
export default function KeyFigures({
  feature,
  explained,
  policyHash,
  dataHash,
}: {
  feature: FeatureResult;
  explained: Explained | null;
  policyHash: string;
  dataHash: string;
}) {
  const cells = feature.cells;
  const sold = cells.filter((c) => c.recommendation !== "Not sold");
  const prio = cells.filter((c) => c.recommendation === "Prioritise").length;
  const consider = cells.filter((c) => c.recommendation === "Consider").length;
  const v = explained?.verification;
  return (
    <div className="stack">
      <div className="keyfigs">
        <div className="facts-row">
          <Fact label="Priority score" value={fmtNum(feature.rollup.score)} note="volume-weighted, 0 to 1" />
          <Fact label="Prioritise / Consider" value={`${prio} / ${consider}`} note={`of ${sold.length} sold series × markets`} />
          <Fact label="Evidence coverage" value={fmtPct(feature.rollup.evidence_volume_share)} note="of sales volume in scope" />
          <div>
            <p className="techfact__label">Customer verdict</p>
            <p className="techfact__value">
              <Verdict verdict={feature.overall.verdict} />
            </p>
            <p className="caption">{fmtInt(feature.overall.n_comments)} comments, complaint index {fmtNum(feature.overall.complaint_index)}</p>
          </div>
          <Fact
            label="Claims verified"
            value={v ? `${v.n_verified} / ${v.n_verified + v.n_removed}` : "–"}
            note={v ? `${v.n_removed} removed by the verifier` : "after the explanation runs"}
          />
        </div>
      </div>
      <p className="lead">{feature.headline}</p>
      <p className="disclaimer">
        Decision engine on the processed BMW hackathon data. Policy {policyHash}, data version {dataHash}. Complaint index 1.00 means as
        many complaints as expected for the channels the feature is discussed in.
      </p>
    </div>
  );
}

function Fact({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div>
      <p className="techfact__label">{label}</p>
      <p className="techfact__value num">{value}</p>
      <p className="caption">{note}</p>
    </div>
  );
}
