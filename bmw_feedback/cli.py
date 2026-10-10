"""Command line entry point: python -m bmw_feedback <command>

    build     raw Excel/PDF -> data/processed/*.csv, reports/data_quality.json, scorecards
    train     evaluate + fit text classifiers -> reports/classifier_metrics.json, models/
    figures   regenerate reports/figures/*.png
    export    JSON row files for the interactive dashboard -> data/processed/dashboard/
    graph     knowledge graph of the processed data and model outputs -> data/processed/knowledge_graph.json
    agent     run the three-agent idea evaluation in the terminal (needs OPENAI_API_KEY for agents 2 and 3)
    verdict   PM verdict for a feature (--feature) or a new comment (--text)
    serve     API + web app (Product Decision Studio) on http://127.0.0.1:8000
    all       build + train + graph + figures
"""

import argparse
import json
import sys

import pandas as pd

from . import clean, config, load, scoring, taxonomy


def _save_list_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["feedback_types", "sentiments", "domains", "features"]:
        out[col] = out[col].apply("|".join)
    return out


def cmd_build(_args=None) -> None:
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading raw feedback ...")
    raw = load.load_feedback()
    labels, comments, quality = clean.build_tables(raw)
    labels.to_csv(config.PROCESSED_DIR / "labels.csv", index=False)
    _save_list_columns(comments).to_csv(config.PROCESSED_DIR / "comments.csv", index=False)
    print(f"  {len(labels):,} label rows, {len(comments):,} comments "
          f"({quality['comments_by_label_status']})")

    print("Loading survey, sales ...")
    sales = load.load_sales()
    sales.to_csv(config.PROCESSED_DIR / "sales.csv", index=False)
    weights = clean.market_weights(labels, sales)
    weights.to_csv(config.REPORTS_DIR / "market_representativeness.csv", index=False)
    load.load_survey_cn_eu().to_csv(config.PROCESSED_DIR / "survey_cn_eu.csv", index=False)
    survey_us = load.load_survey_us()
    survey_us.to_csv(config.PROCESSED_DIR / "survey_us.csv", index=False)
    load.summarise_survey_us(survey_us).to_csv(config.PROCESSED_DIR / "survey_us_summary.csv", index=False)

    print("Parsing option-list PDFs ...")
    from . import option_catalog
    cat = option_catalog.build_catalog()
    quality["option_catalog"] = option_catalog.validate(cat)
    links = option_catalog.match_features(cat)
    fitment = option_catalog.feature_fitment(links, cat)
    tables = {**cat, "feature_option_links": links, "feature_fitment": fitment,
              "feature_fitment_summary": option_catalog.fitment_summary(fitment),
              "feature_fitment_by_engine": option_catalog.fitment_summary(fitment, ("feature", "model", "engine")),
              "feature_specs": option_catalog.spec_context(cat)}
    for name, frame in tables.items():
        frame.to_csv(config.PROCESSED_DIR / f"catalog_{name}.csv", index=False)
    q = quality["option_catalog"]
    print(f"  {len(cat['variants'])} variants, {len(cat['option_items'])} items, {len(cat['fitment'])} fitment cells, "
          f"{len(cat['technical'])} technical values; {links['feature'].nunique()} feedback features linked")
    print(f"  checks passed: {q['glyphs_assigned']} glyphs assigned, {q['option_price_pairs_checked']} price pairs, "
          f"{q['base_prices_checked']} base prices; {len(q['source_price_anomalies'])} source anomaly")

    print("Scoring features ...")
    feats = scoring.score(labels)
    feats.to_csv(config.REPORTS_DIR / "feature_scorecard.csv", index=False)
    scoring.score(labels, group_keys=("domain",), prior_keys=()).to_csv(
        config.REPORTS_DIR / "domain_scorecard.csv", index=False)
    scoring.score(labels, group_keys=("domain", "model"), prior_keys=()).to_csv(
        config.REPORTS_DIR / "domain_by_model_scorecard.csv", index=False)
    scoring.score(labels, group_keys=("feature", "model")).to_csv(
        config.PROCESSED_DIR / "feature_by_model_scorecard.csv", index=False)
    units = scoring.feature_units(labels)
    specific = units[~units["feature"].isin(taxonomy.UMBRELLA_FEATURES)]
    quality["source_baselines_all_features"] = scoring.source_baselines(units).round(3).to_dict("index")
    quality["source_baselines_specific_features"] = scoring.source_baselines(specific).round(3).to_dict("index")
    quality["verdicts_specific_features"] = feats.loc[~feats["is_umbrella"], "verdict"].value_counts().to_dict()
    (config.REPORTS_DIR / "data_quality.json").write_text(json.dumps(quality, indent=2, default=str))
    print(f"  verdicts (specific features): {quality['verdicts_specific_features']}")


def cmd_train(_args=None) -> None:
    from . import classifier
    from .verdict import load_context
    ctx = load_context()
    print("Cross-validating classifiers ...")
    metrics = classifier.evaluate_all(ctx.comments)
    print("Fitting final models ...")
    classifier.fit_and_save(ctx.comments)
    pool = ctx.comments[ctx.comments["label_status"] != "labeled"]
    preds = classifier.predict(pool["text"].tolist())
    out = pool[["comment_id", "source", "model", "label_status", "text"]].copy()
    out["pred_feedback_types"] = ["|".join(f for f, _ in p["feedback_type"]) for p in preds]
    out["pred_domains"] = ["|".join(d for d, _ in p["domain"]) for p in preds]
    out["pred_top_feature"] = [p["feature"][0][0] for p in preds]
    out["pred_top_feature_p"] = [p["feature"][0][1] for p in preds]
    out.to_csv(config.PROCESSED_DIR / "unlabeled_predictions.csv", index=False)
    metrics["unlabeled_pool"] = {
        "n": int(len(out)),
        "pred_feedback_type_counts": out["pred_feedback_types"].str.split("|").explode().value_counts().to_dict(),
        "pred_domain_counts": out["pred_domains"].str.split("|").explode().value_counts().to_dict(),
    }
    classifier.save_metrics(metrics, config.REPORTS_DIR / "classifier_metrics.json")
    print(f"  saved models to {config.MODELS_DIR.relative_to(config.ROOT)}/ and metrics to reports/")

    print("Option-list ablations ...")
    from . import risk_model
    p = config.PROCESSED_DIR
    fit_by_engine = pd.read_csv(p / "catalog_feature_fitment_by_engine.csv")
    variants = pd.read_csv(p / "catalog_variants.csv")
    fitment = pd.read_csv(p / "catalog_fitment.csv")
    covered = set(map(tuple, fitment[["model", "variant"]].drop_duplicates()
                      .merge(variants[["model", "variant", "engine"]])[["model", "engine"]].drop_duplicates().values))
    units = risk_model.unit_frame(ctx.labels, fit_by_engine, variants, fitment)
    ablation = {
        "complaint_risk_ebm": risk_model.evaluate(units),
        "poor_value_check": risk_model.value_check(units, ctx.labels),
        "feature_classifier_fitment": classifier.fitment_ablation(ctx.comments, fit_by_engine, covered),
    }
    risk_model.fit_and_save(units)
    classifier.save_reranker(ablation["feature_classifier_fitment"], ctx.comments)
    ablation["complaint_risk_ebm"]["production_inputs"] = risk_model.CONTEXT
    ablation["complaint_risk_ebm"]["audit_only_inputs"] = risk_model.CONTEXT + risk_model.PDF
    ablation["complaint_risk_ebm"]["global_production"] = risk_model.global_explanation(risk_model.load())
    ablation["complaint_risk_ebm"]["global_audit_with_pdf"] = risk_model.global_explanation(risk_model.load(audit=True))
    (config.REPORTS_DIR / "model_ablation.json").write_text(json.dumps(ablation, indent=2, default=str))
    e = ablation["complaint_risk_ebm"]
    for k in ("all_features", "linked_features_only"):
        v = e[k]["variants"]
        print(f"  complaint EBM ({k}): AUC context {v['context_only']['auc_mean']:.3f} -> +PDF "
              f"{v['context_plus_pdf']['auc_mean']:.3f} (gain {e[k]['pdf_auc_gain_mean']:+.4f})")
    f = ablation["feature_classifier_fitment"]
    print(f"  feature classifier top-1 (linked): car prior {f['variants']['text_plus_car_prior']['top1_hit_linked']:.4f}"
          f" -> +fitment {f['variants']['text_plus_car_prior_plus_fitment']['top1_hit_linked']:.4f}"
          f" (McNemar p={f['mcnemar_linked']['p_value']})")


def cmd_figures(_args=None) -> None:
    from . import figures
    figures.make_all()


def cmd_export(_args=None) -> None:
    from .export import export_dashboard
    export_dashboard()


def cmd_verdict(args) -> None:
    from .verdict import load_context, render_markdown, text_card
    ctx = load_context()
    if args.list:
        cols = ["feature", "domain", "verdict", "confidence", "n_comments", "index_negative", "requested"]
        table = ctx.features.reset_index()[cols]
        table = table[table["verdict"] != "Not enough data"].round(2)
        print(table.to_string(index=False))
        return
    if args.text:
        result = text_card(ctx, args.text)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
            return
        p = result["prediction"]
        print(f"Comment classified as: {', '.join(f'{t} ({s:.0%})' for t, s in p['feedback_type'])}")
        print(f"Domain(s): {', '.join(f'{d} ({s:.0%})' for d, s in p['domain'])}")
        print(f"Top features: {', '.join(f'{f} ({s:.0%})' for f, s in p['feature'])}\n")
        for card in result["cards"]:
            print(render_markdown(card), "\n")
        return
    feature = ctx.resolve(args.feature or "")
    if feature is None:
        print(f"No feature matches {args.feature!r}. Try `--list` to see all features.")
        sys.exit(1)
    card = ctx.feature_card(feature)
    print(json.dumps(card, indent=2, default=str) if args.json else render_markdown(card))


def cmd_graph(_args=None) -> None:
    from .graph.build import GRAPH_FILE, build_and_save
    print("Building the knowledge graph ...")
    meta = build_and_save()
    for c in meta["checks"]:
        print(f"  {'ok ' if c['ok'] else 'FAIL'} {c['check']}: {c['graph']:,} (source {c['source']:,})")
    print(f"  {meta['n_nodes']:,} nodes, {meta['n_edges']:,} edges -> {GRAPH_FILE.relative_to(config.ROOT)}")


def cmd_agent(args) -> None:
    from .agents.llm import LLMError
    from .agents.pipeline import Pipeline
    from .decision import DecisionEngine
    pipe = Pipeline(DecisionEngine())
    if args.check:
        print(json.dumps(pipe.status(check=True), indent=2, default=str))
        return
    if not args.idea:
        print("Give an idea: python -m bmw_feedback agent \"make seat massage standard on the 5 Series\"")
        sys.exit(1)
    r = pipe.interpret(args.idea)
    s = r["spec"]
    print(f"Agent 1 ({r['method']}): features {[f['feature'] for f in s['features']]}, series {s['series'] or 'all'}, "
          f"markets {s['markets'] or 'all'}, move {s['move']}, price {s['proposed_price_eur']}")
    e = pipe.evaluate(s)
    print(f"Decision engine: {len(e['facts'])} facts, evaluation {e['evaluation_id']}")
    for f in e["result"]["features"]:
        print(f"  {f['headline']}")
    try:
        out = pipe.explain(e["evaluation_id"])
    except LLMError as err:
        print(f"Agents 2 + 3 not run: {err}")
        return
    v = out["verification"]
    print(f"Agent 2 + 3: {v['n_verified']} claims verified, {v['n_removed']} removed, "
          f"{len(v['rewritten'])} rewritten ({out['seconds']} s)")
    for section, claims in out["explanation"]["sections"].items():
        for c in claims:
            print(f"  [{section}] {c['text']}  ({', '.join(c['fact_ids'])})")
    for c in v["claims"]:
        if c["status"] == "removed":
            print(f"  REMOVED [{c['section']}] {c['text']}: "
                  + "; ".join(ch["detail"] for ch in c["checks"] if not ch["passed"]))


def cmd_serve(args) -> None:
    import uvicorn
    uvicorn.run("bmw_feedback.api:app", host=args.host, port=args.port, reload=False)


def cmd_all(args) -> None:
    cmd_build(args)
    cmd_train(args)
    cmd_graph(args)
    cmd_figures(args)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m bmw_feedback", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build").set_defaults(func=cmd_build)
    sub.add_parser("train").set_defaults(func=cmd_train)
    sub.add_parser("figures").set_defaults(func=cmd_figures)
    sub.add_parser("export").set_defaults(func=cmd_export)
    sub.add_parser("all").set_defaults(func=cmd_all)
    sub.add_parser("graph").set_defaults(func=cmd_graph)
    ag = sub.add_parser("agent", help="evaluate an idea with the three agents in the terminal")
    ag.add_argument("idea", nargs="?", help="the feature idea, in quotes")
    ag.add_argument("--check", action="store_true", help="check the API key and model availability")
    ag.set_defaults(func=cmd_agent)
    sv = sub.add_parser("serve", help="run the API + web app (frontend/dist) on http://HOST:PORT")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)
    v = sub.add_parser("verdict", help="verdict for a feature or a new comment")
    v.add_argument("--feature", "-f", help="feature name or alias, e.g. 'head-up display', 'carplay'")
    v.add_argument("--text", "-t", help="a new customer comment to classify")
    v.add_argument("--list", action="store_true", help="list all features with a verdict")
    v.add_argument("--json", action="store_true", help="machine-readable output")
    v.set_defaults(func=cmd_verdict)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
