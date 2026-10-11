"""Command line entry point.

  python -m pm_copilot build                 ingest raw data + derive/score requirements
  python -m pm_copilot serve [--port 8000]   start the PM cockpit (API + frontend)
  python -m pm_copilot brief "seat ventilation" --derivative G60
  python -m pm_copilot top --derivative G70 [--n 15]
  python -m pm_copilot export [--derivative G60] [--format csv]
  python -m pm_copilot research --derivative G60 --region CN --feature "seat ventilation"
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import DEFAULT_HORIZON, DERIVATIVES, HORIZONS, REGIONS


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="pm_copilot", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="ingest data and (re)build requirement candidates")
    b.add_argument("--horizon", choices=HORIZONS, default=DEFAULT_HORIZON)
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    f = sub.add_parser("brief", help="feature brief in the terminal")
    f.add_argument("query")
    f.add_argument("--derivative", choices=list(DERIVATIVES))
    f.add_argument("--horizon", choices=HORIZONS, default=DEFAULT_HORIZON)
    f.add_argument("--json", action="store_true")
    t = sub.add_parser("top", help="top requirements")
    t.add_argument("--derivative", choices=list(DERIVATIVES))
    t.add_argument("--n", type=int, default=15)
    e = sub.add_parser("export", help="export requirements (deliverable list)")
    e.add_argument("--derivative", choices=list(DERIVATIVES))
    e.add_argument("--format", choices=["json", "csv"], default="json")
    r = sub.add_parser("research", help="competitor web research with Claude (needs API credentials)")
    r.add_argument("--derivative", choices=list(DERIVATIVES), required=True)
    r.add_argument("--region", choices=REGIONS, required=True)
    r.add_argument("--feature", required=True)
    args = p.parse_args(argv)

    if args.cmd == "build":
        from . import requirements
        from .ingest import build
        from .store import reload
        manifest = build()
        print(f"Ingested {manifest['rows']}")
        result = requirements.sync(reload(), args.horizon)
        print(f"Requirements: {result}")
    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("pm_copilot.api:app", host=args.host, port=args.port)
    elif args.cmd == "brief":
        from .brief import feature_brief
        from .store import load
        out = feature_brief(load(), args.query, args.derivative, args.horizon)
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
        else:
            _print_brief(out)
    elif args.cmd == "top":
        from .requirements import list_requirements
        for req in list_requirements(args.derivative)[:args.n]:
            pr = req["priority"]
            print(f"{pr['tier']} {pr['score']:5.1f}  {req['evidence']['level']:<6} {req['status']:<10} {req['id']}\n"
                  f"      {req['title']}")
    elif args.cmd == "export":
        from .requirements import export
        print(export(args.derivative, args.format)[0])
    elif args.cmd == "research":
        from . import db, research
        from .brief import feature_brief, resolve
        from .store import load
        data = load()
        res = resolve(args.feature, data)
        b = feature_brief(data, args.feature, args.derivative)
        context = f"- {b['demand']['headline']}\n- Availability (DE list): {b['equipment'][args.derivative]['status']}"
        try:
            rec = research.run_web_research(args.derivative, args.region, res.label, res.key, context)
        except research.AIUnavailable as exc:
            print(f"Research unavailable: {exc}")
            return 1
        with db.connect() as con:
            db.log(con, "claude", "ai", "web_research", None, "competitor_benchmark", None,
                   {"derivative": args.derivative, "region": args.region, "feature": res.label},
                   rec["result"]["summary"][:400])
        print(json.dumps(rec["result"], indent=2, ensure_ascii=False))
    return 0


def _print_brief(b: dict) -> None:
    print(f"\n{b['resolution']['label']} - {b['scope']['vehicle']} (horizon {b['scope']['horizon']})")
    print(f"  {b['resolution']['note']}")
    print(f"\n1. Demand: {b['demand']['headline']}")
    print(f"2. Kano-style class: {b['kano']['class']} - {b['kano']['why']}")
    print(f"   Have it: {b['have_vs_not']['have']}\n   Don't:   {b['have_vs_not']['not_have']}")
    print("3. Markets:")
    for r, v in b["regions"].items():
        print(f"   {r:<4} {v['mentions']:>4} / {v['verbatim_base']:<5} vol {v['volume']:>7,}  "
              f"{v['recommendation']['label']} - {v['recommendation']['why']}")
    mats = b["materials"]["feature"] or b["materials"]["vehicle"]
    print("4. Materials: " + (", ".join(f"{m['material']} (+{m['positive']}/-{m['negative']})" for m in mats[:5])
                              or "no material mentions"))
    ma = b["markets_affected"]
    print(f"5. Markets affected: implemented -> {ma['if_implemented']['regions']} "
          f"({ma['if_implemented']['volume']:,} units); not implemented -> {ma['if_not_implemented']['regions']}")
    sa = b["sales"]
    print(f"6. Sales: exposure {sa['exposure']:,} units, ~{sa['customers_who_care']:,} customers care, "
          f"~{sa['units_at_stake']:,} units at stake (sensitivity {sa['sensitivity']:.0%})")
    print("7. Top issues: " + "; ".join(f"{i['issue']} ({i['verbatims']})" for i in b["issues"][:5]))
    print("8. Competitors mentioned: " + (", ".join(f"{c['brand']} ({c['verbatims']})"
                                                  for c in b["competitors"]["mentions"][:5]) or "none"))
    print(f"   Evidence: {b['evidence']['level']} ({', '.join(b['evidence']['reasons'])})")
    if b["coverage_warning"]:
        print(f"   ! {b['coverage_warning']}")


if __name__ == "__main__":
    raise SystemExit(main())
