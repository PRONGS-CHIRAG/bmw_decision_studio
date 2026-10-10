"""Pure, reproducible decision calculations. No I/O, model calls or invented inputs.

The caller supplies frozen evidence measurements and explicitly reviewed PM inputs.
All customer counts remain descriptive; none is converted into customers or sales.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

ALGORITHM_VERSION = "feature-decision-1.0"
MAX_CANDIDATES = 16
CRITERIA = ("customer", "future", "delivery", "regional", "experience")
PROFILE_WEIGHTS = {
    "customer-led": dict(zip(CRITERIA, (0.40, 0.20, 0.15, 0.15, 0.10))),
    "future-led": dict(zip(CRITERIA, (0.20, 0.40, 0.15, 0.10, 0.15))),
    "experience-led": dict(zip(CRITERIA, (0.20, 0.15, 0.15, 0.10, 0.40))),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _number(value: Any, name: str, lower: float = 0, upper: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < lower or (upper is not None and result > upper):
        raise ValueError(f"{name} must be finite and within {lower}..{upper if upper is not None else 'infinity'}")
    return result


def validate_weights(weights: dict, keys=CRITERIA) -> dict[str, float]:
    if set(weights) != set(keys):
        raise ValueError(f"Weights must contain exactly: {', '.join(keys)}")
    result = {key: _number(weights[key], f"weight {key}", upper=1) for key in keys}
    if not math.isclose(math.fsum(result.values()), 1, abs_tol=1e-9, rel_tol=0):
        raise ValueError("Weights must sum to 1; they are never silently normalized")
    return result


def frequency_score(support_rate: float | None, saturation: float | None) -> float | None:
    """Fixed PM planning rubric, never a population-demand estimate."""
    if support_rate is not None:
        _number(support_rate, "support rate", upper=1)
    if saturation is not None:
        _number(saturation, "saturation", upper=1)
        if saturation == 0:
            raise ValueError("Saturation must be positive")
    if support_rate is None or saturation is None:
        return None
    return 100 * min(1, support_rate / saturation)


def customer_value(impact: float | None, frequency: float | None) -> float | None:
    if impact is not None:
        _number(impact, "impact", upper=100)
    if frequency is not None:
        _number(frequency, "frequency", upper=100)
    if impact is None or frequency is None:
        return None
    return impact * (0.6 + 0.4 * frequency / 100)


def score_criteria(values: dict, weights: dict) -> dict:
    weights = validate_weights(weights)
    unknown = []
    contributions = {}
    for key in CRITERIA:
        value = values.get(key)
        if value is None:
            unknown.append(key)
            contributions[key] = None if weights[key] else 0.0
        else:
            contributions[key] = weights[key] * _number(value, key, upper=100)
    missing = [key for key in unknown if weights[key] > 0]
    lower = math.fsum(value for value in contributions.values() if value is not None)
    upper = lower + 100 * math.fsum(weights[key] for key in missing)
    return {
        "score": None if missing else round(lower, 10),
        "lower_bound": round(lower, 10),
        "upper_bound": round(upper, 10),
        "contributions": {key: None if value is None else round(value, 10) for key, value in contributions.items()},
        "missing": missing,
        "unknown_criteria": unknown,
        "complete": not missing,
    }


def _descriptors(candidate: dict) -> dict:
    support = candidate.get("support_count")
    base = candidate.get("sample_size")
    for name, count in (("support_count", support), ("sample_size", base)):
        if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
            raise ValueError(f"{candidate['id']} {name} must be a nonnegative integer or unknown")
    if support is not None and base is not None and support > base:
        raise ValueError(f"{candidate['id']} support_count exceeds its matching sample_size")
    rate = support / base if support is not None and base else None
    frequency = frequency_score(rate, candidate.get("saturation"))
    return {
        "support_rate": rate,
        "frequency": frequency,
        "customer_value": customer_value(candidate.get("impact"), frequency),
    }


def _criteria(candidate: dict, scenario: str, scenario_config: dict) -> dict:
    descriptors = _descriptors(candidate)
    values = {"customer": descriptors["customer_value"], **candidate.get("values", {}), **candidate.get("criteria", {})}
    scenario_values = candidate.get("scenario_values", {})
    if scenario in scenario_values:
        supplied = scenario_values[scenario]
        values.update(supplied if isinstance(supplied, dict) else {"future": supplied})
    values.update(scenario_config.get("criteria", {}).get(candidate["id"], {}))
    for key, value in values.items():
        if key not in CRITERIA:
            raise ValueError(f"Unknown criterion {key}")
        if value is not None:
            _number(value, f"{candidate['id']} {key}", upper=100)
    return {key: values.get(key) for key in CRITERIA}


def _candidate_reasons(candidate: dict, score: dict) -> list[str]:
    reasons = []
    feasibility = candidate.get("feasibility", "unknown")
    if feasibility not in {"reviewed", "reviewed_feasible", "assumption", "assumed_feasible", "blocked", "unknown"}:
        raise ValueError(f"Unknown feasibility state for {candidate['id']}")
    if candidate.get("blocked") or feasibility == "blocked":
        reasons.append("Known engineering blocker")
    elif feasibility == "unknown":
        reasons.append("Feasibility is unknown")
    elif feasibility in {"assumption", "assumed_feasible"} and not candidate.get("assumption_rationale", "").strip():
        reasons.append("Feasibility assumption requires a rationale")
    if candidate.get("development_cost") is None:
        reasons.append("Development cost is unknown; no zero-cost substitution")
    else:
        _number(candidate["development_cost"], f"{candidate['id']} development cost")
    if score["missing"]:
        reasons.append("Unresolved active criteria: " + ", ".join(score["missing"]))
    return reasons


def _normalize(context: dict, candidates: list[dict], config: dict, source_hashes: dict):
    # JSON round-trip both freezes caller-owned containers and rejects nonfinite inputs.
    context, candidates, config, source_hashes = json.loads(canonical_json([context, candidates, config, source_hashes]))
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError(f"At most {MAX_CANDIDATES} candidates can be enumerated; narrow the reviewed set")
    identifiers = [item.get("id") for item in candidates]
    if any(not isinstance(item, str) or not item.strip() for item in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Candidate IDs must be unique nonempty strings")
    candidates.sort(key=lambda item: item["id"])
    for candidate in candidates:
        for relationship in ("dependencies", "exclusions"):
            targets = candidate.get(relationship, [])
            if not isinstance(targets, list) or any(not isinstance(target, str) for target in targets):
                raise ValueError(f"{relationship} must be a list of candidate IDs")
            for target in targets:
                if target not in identifiers:
                    noun = "dependency" if relationship == "dependencies" else "exclusion"
                    raise ValueError(f"Unknown {noun} {target} for {candidate['id']}")
                if target == candidate["id"]:
                    raise ValueError(f"A candidate cannot declare itself in {relationship}")
            candidate[relationship] = sorted(set(targets))
    return context, candidates, config, source_hashes


def _is_dominated(candidate: dict, other: dict, dimensions: list[str]) -> bool:
    if other["cost_decimal"] > candidate["cost_decimal"]:
        return False
    differences = [other["criterion_totals"][key] - candidate["criterion_totals"][key] for key in dimensions]
    return all(value >= -1e-9 for value in differences) and (
        other["cost_decimal"] < candidate["cost_decimal"] or any(value > 1e-9 for value in differences)
    )


def _aggregate(selected: list[dict], values: dict, market_weights: dict) -> dict:
    totals = {}
    for key in CRITERIA:
        missing = any(values[item["id"]][key] is None and market_weights[item["market"]] > 0 for item in selected)
        totals[key] = None if missing else math.fsum(
            market_weights[item["market"]] * (values[item["id"]][key] or 0) for item in selected
        )
    return totals


def _utility(totals: dict, weights: dict) -> float | None:
    if any(totals[key] is None and weights[key] for key in CRITERIA):
        return None
    return math.fsum(weights[key] * (totals[key] or 0) for key in CRITERIA)


def build_run(context: dict, candidates: list[dict], config: dict, source_hashes: dict) -> dict:
    """Evaluate up to 16 explicit action/market candidates, preserving all unknowns.

    ``criteria`` can contain directly reviewed PM criterion assumptions. Otherwise
    customer value is derived from the scoped support count and PM impact/rubric.
    Context/candidate measurements must be assembled and validated by the server.
    """
    context, candidates, config, source_hashes = _normalize(context, candidates, config, source_hashes)
    weights = validate_weights(config.get("weights", config.get("comparison_weights", dict.fromkeys(CRITERIA, 0.2))))
    markets = context.get("markets") or sorted({item.get("market") for item in candidates})
    if not markets or any(not isinstance(market, str) or not market for market in markets):
        raise ValueError("At least one explicit target market is required")
    if any(item.get("market") not in markets for item in candidates):
        raise ValueError("A candidate market is outside the project context")
    market_weights = config.get("market_weights")
    if market_weights is None and len(markets) == 1:
        market_weights = {markets[0]: 1.0}
    if market_weights is None:
        raise ValueError("Multi-market aggregation requires explicit PM market weights")
    market_weights = validate_weights(market_weights, tuple(sorted(markets)))
    budget = config.get("budget")
    if budget is not None:
        _number(budget, "budget")
    floor = _number(config.get("value_floor", 0.85), "value floor", upper=1)
    active = config.get("scenario", config.get("active_scenario", "baseline"))
    scenarios = config.get("scenarios", {name: {} for name in ("slow", "baseline", "fast")})
    if active not in scenarios or not all(isinstance(value, dict) for value in scenarios.values()):
        raise ValueError("The active scenario must be in the configured scenario set")
    values = {item["id"]: _criteria(item, active, scenarios[active]) for item in candidates}
    scores = {}
    for item in candidates:
        score = score_criteria(values[item["id"]], weights)
        reasons = _candidate_reasons(item, score)
        scores[item["id"]] = {
            **score, **_descriptors(item), "criteria": values[item["id"]],
            "eligible": not reasons, "eligibility_reasons": reasons,
        }
    # A dependency can be unresolved even when the dependent's own inputs are complete.
    while True:
        changed = False
        for item in candidates:
            missing = [target for target in item["dependencies"] if not scores[target]["eligible"]]
            if missing and scores[item["id"]]["eligible"]:
                scores[item["id"]]["eligible"] = False
                scores[item["id"]]["eligibility_reasons"].append("Dependency is ineligible: " + ", ".join(missing))
                changed = True
        if not changed:
            break
    configuration = {
        **config, "weights": weights, "market_weights": market_weights,
        "scenario": active, "scenarios": scenarios, "value_floor": floor,
    }
    hash_inputs = {"algorithm_version": ALGORITHM_VERSION, "context": context, "candidates": candidates,
                   "config": configuration, "source_hashes": source_hashes}
    result = {
        "algorithm_version": ALGORITHM_VERSION,
        "input_hash": content_hash(hash_inputs), "config_hash": content_hash(configuration),
        "source_hashes": source_hashes, "context": context, "config": configuration,
        "candidates": candidates, "status": "ready", "candidate_scores": scores,
        "investigation_queue": [{"id": key, "reasons": value["eligibility_reasons"]} for key, value in scores.items() if not value["eligible"]],
        "conflicts": [], "portfolios": [], "alternatives_note": "", "assumptions": [], "unavailable_profiles": [],
        "comparison_scope": "Best within the reviewed candidate set; investigation items are excluded",
    }
    for item in candidates:
        if item.get("feasibility") in {"assumption", "assumed_feasible"}:
            result["assumptions"].append({"candidate_id": item["id"], "kind": "feasibility", "rationale": item.get("assumption_rationale", "")})
    by_id = {item["id"]: item for item in candidates}
    mandatory = {item["id"] for item in candidates if item.get("mandatory")}
    required = set(mandatory)
    while True:
        expanded = required | {target for key in required for target in by_id[key]["dependencies"]}
        if expanded == required:
            break
        required = expanded
    blocked_required = [key for key in sorted(required) if by_id[key].get("blocked") or by_id[key].get("feasibility") == "blocked"]
    if blocked_required:
        result.update(status="infeasible", conflicts=["Mandatory selection has a known blocker: " + ", ".join(blocked_required)])
        return result
    for key in sorted(required):
        conflicts = required.intersection(by_id[key]["exclusions"])
        if conflicts:
            result.update(status="infeasible", conflicts=[f"Mandatory selection exclusion: {key} conflicts with {', '.join(sorted(conflicts))}"])
            return result
    known_required_cost = sum((Decimal(str(by_id[key]["development_cost"])) for key in required if by_id[key].get("development_cost") is not None), Decimal(0))
    if budget is not None and known_required_cost > Decimal(str(budget)):
        result.update(status="infeasible", conflicts=["Known mandatory requirements and dependencies already exceed the PM budget"])
        return result
    unresolved_required = [key for key in sorted(required) if not scores[key]["eligible"]]
    if unresolved_required:
        result.update(status="unresolved", conflicts=["Mandatory input unresolved: " + ", ".join(unresolved_required)])
        return result
    if budget is None:
        result.update(status="unresolved", conflicts=["PM development budget is unknown"])
        return result
    eligible = [item for item in candidates if scores[item["id"]]["eligible"]]
    if not candidates or (not eligible and any(not item.get("blocked") and item.get("feasibility") != "blocked" for item in candidates)):
        result.update(status="unresolved", conflicts=["No reviewed candidates are eligible; resolve the investigation queue"])
        return result
    required_cost = sum((Decimal(str(by_id[key]["development_cost"])) for key in required), Decimal(0))
    if required_cost > Decimal(str(budget)):
        result.update(status="infeasible", conflicts=["Mandatory requirements and dependencies exceed the PM budget"])
        return result
    feasible = _enumerate(eligible, mandatory, budget, values, market_weights, weights, scenarios[active])
    if not feasible:
        result.update(status="infeasible", conflicts=["No feasible portfolio satisfies budget, mandatory requirements, dependencies, exclusions and scenario blockers"])
        return result
    profiles = {**PROFILE_WEIGHTS, **config.get("profiles", {})}
    profiles = {name: validate_weights(profile) for name, profile in profiles.items()}
    for name, profile in profiles.items():
        incomplete = [item["id"] for item in eligible if score_criteria(values[item["id"]], profile)["missing"]]
        if incomplete:
            result["unavailable_profiles"].append({"profile": name, "reason": "Additional positive-weight criteria are unresolved", "candidate_ids": incomplete})
    unavailable = {item["profile"] for item in result["unavailable_profiles"]}
    profiles = {name: profile for name, profile in profiles.items() if name not in unavailable}
    if not profiles:
        profiles = {"comparison-led": weights}
    dimensions = [key for key in CRITERIA if weights[key] > 0]
    selected = _alternatives(feasible, profiles, weights, floor, dimensions)
    scenario_values = {name: {item["id"]: _criteria(item, name, settings) for item in candidates} for name, settings in sorted(scenarios.items())}
    # Re-enumeration per scenario gives regret against the reviewed feasible universe,
    # not merely against the handful of displayed alternatives.
    scenario_best = {}
    evaluation_cache = {
        content_hash({"values": values, "constraints": scenarios[active]}): max(option["comparison_utility"] for option in feasible)
    }
    for name, settings in sorted(scenarios.items()):
        key = content_hash({"values": scenario_values[name], "constraints": settings})
        if key not in evaluation_cache:
            scenario_eligible = [item for item in candidates if not _candidate_reasons(item, score_criteria(scenario_values[name][item["id"]], weights))]
            options = _enumerate(scenario_eligible, mandatory, budget, scenario_values[name], market_weights, weights, settings)
            evaluation_cache[key] = max((option["comparison_utility"] for option in options), default=None)
        scenario_best[name] = evaluation_cache[key]
    for portfolio in selected:
        chosen = [by_id[key] for key in portfolio["selected_ids"]]
        evaluations = {}
        for name, settings in sorted(scenarios.items()):
            reasons = _selection_reasons(chosen, mandatory, budget, settings)
            incomplete = [item["id"] for item in chosen if score_criteria(scenario_values[name][item["id"]], weights)["missing"]]
            utility = _utility(_aggregate(chosen, scenario_values[name], market_weights), weights)
            valid = not reasons
            best = scenario_best[name]
            evaluations[name] = {
                "feasible": valid, "complete": not incomplete, "utility": None if not valid else utility,
                "regret": max(0, best - utility) if valid and utility is not None and best is not None else None,
                "reasons": reasons + (["Unresolved criteria: " + ", ".join(incomplete)] if incomplete else []),
                "label": "scenario evaluation",
            }
        public = {key: value for key, value in portfolio.items() if key != "cost_decimal"}
        known_utilities = [item["utility"] for item in evaluations.values() if item["feasible"] and item["utility"] is not None]
        public.update(
            id="portfolio-" + content_hash(portfolio["selected_ids"])[:16], feasible=True,
            scenario_evaluations=evaluations, feasible_scenarios=sum(item["feasible"] for item in evaluations.values()),
            worst_case_utility=min(known_utilities) if known_utilities and all(item["complete"] for item in evaluations.values() if item["feasible"]) else None,
            requires_assumption_acknowledgement=any(item.get("feasibility") in {"assumption", "assumed_feasible"} for item in chosen),
        )
        result["portfolios"].append(public)
    result["portfolios"].sort(key=lambda item: (-item["comparison_utility"], item["cost"], item["selected_ids"]))
    if len(result["portfolios"]) < 4:
        result["alternatives_note"] = f"{len(result['portfolios'])} distinct non-dominated portfolios are available under the reviewed inputs and common comparison criteria; no extra alternatives were manufactured."
    if result["investigation_queue"]:
        result["alternatives_note"] += " Unresolved candidates remain visible in the investigation queue and were excluded."
    if result["unavailable_profiles"]:
        result["alternatives_note"] += " Generation profiles needing additional unresolved criteria are unavailable; common comparison inputs were retained."
    return result


def _selection_reasons(selected: list[dict], mandatory: set[str], budget: float, scenario: dict) -> list[str]:
    identifiers = {item["id"] for item in selected}
    reasons = []
    if not mandatory.issubset(identifiers):
        reasons.append("Missing mandatory requirement")
    blocked = set(scenario.get("blocked_ids", []))
    for item in selected:
        if item["id"] in blocked:
            reasons.append(f"Scenario blocker: {item['id']}")
        if not set(item["dependencies"]).issubset(identifiers):
            reasons.append(f"Missing dependency for {item['id']}")
        if identifiers.intersection(item["exclusions"]):
            reasons.append(f"Exclusion conflict for {item['id']}")
    if sum((Decimal(str(item["development_cost"])) for item in selected), Decimal(0)) > Decimal(str(budget)):
        reasons.append("PM budget exceeded")
    return reasons


def _enumerate(candidates: list[dict], mandatory: set[str], budget: float, values: dict, market_weights: dict, weights: dict, scenario: dict) -> list[dict]:
    identifiers = {item["id"] for item in candidates}
    if not mandatory.issubset(identifiers):
        return []
    positions = {item["id"]: index for index, item in enumerate(candidates)}
    required_mask = sum(1 << positions[key] for key in mandatory)
    blocked_mask = sum(1 << positions[key] for key in set(scenario.get("blocked_ids", [])) if key in positions)
    dependency_masks = [sum(1 << positions[key] for key in item["dependencies"]) if set(item["dependencies"]).issubset(identifiers) else -1 for item in candidates]
    exclusion_masks = [sum(1 << positions[key] for key in item["exclusions"] if key in positions) for item in candidates]
    costs = [Decimal(str(item["development_cost"])) for item in candidates]
    budget_decimal = Decimal(str(budget))
    subset_costs = [Decimal(0)] * (1 << len(candidates))
    portfolios = []
    for mask in range(1 << len(candidates)):
        if mask:
            last_bit = mask & -mask
            subset_costs[mask] = subset_costs[mask ^ last_bit] + costs[last_bit.bit_length() - 1]
        if mask & required_mask != required_mask or mask & blocked_mask or subset_costs[mask] > budget_decimal:
            continue
        indices = [index for index in range(len(candidates)) if mask & (1 << index)]
        if any(dependency_masks[index] == -1 or mask & dependency_masks[index] != dependency_masks[index] or mask & exclusion_masks[index] for index in indices):
            continue
        selected = [candidates[index] for index in indices]
        totals = _aggregate(selected, values, market_weights)
        utility = _utility(totals, weights)
        if utility is None:
            continue
        cost = subset_costs[mask]
        portfolios.append({"selected_ids": [item["id"] for item in selected], "cost": float(cost), "cost_decimal": cost,
                           "criterion_totals": totals, "comparison_utility": utility})
    return portfolios


def _alternatives(feasible: list[dict], profiles: dict, common_weights: dict, floor: float, dimensions: list[str]) -> list[dict]:
    selected = []
    selected_ids = set()
    witnesses = []
    dominance_cache = {}

    def non_dominated(option):
        key = tuple(option["selected_ids"])
        if key not in dominance_cache:
            dominator = next((other for other in witnesses if _is_dominated(option, other, dimensions)), None)
            if dominator is None:
                dominator = next((other for other in feasible if _is_dominated(option, other, dimensions)), None)
            dominance_cache[key] = dominator is None
            if dominator is not None and all(other is not dominator for other in witnesses):
                witnesses.append(dominator)
        return dominance_cache[key]

    rankings = []
    for name, weights in profiles.items():
        ranked = [option for option in feasible if _utility(option["criterion_totals"], weights) is not None]
        ranked.sort(key=lambda option: (-_utility(option["criterion_totals"], weights), option["cost_decimal"], option["selected_ids"]))
        rankings.append((name, ranked))
    best_common = max(option["comparison_utility"] for option in feasible)
    economical = [option for option in feasible if option["comparison_utility"] >= floor * best_common]
    economical.sort(key=lambda option: (option["cost_decimal"], -option["comparison_utility"], option["selected_ids"]))
    rankings.append(("cost-disciplined", economical))
    # First retain each objective's actual optimum; shared optima retain all profile names.
    for name, ranked in rankings:
        optimum = next((option for option in ranked if non_dominated(option)), None)
        if optimum is None:
            continue
        key = tuple(optimum["selected_ids"])
        if key in selected_ids:
            next(item for item in selected if tuple(item["selected_ids"]) == key)["profiles"].append(name)
        else:
            selected.append({**optimum, "profile": name, "profiles": [name]})
            selected_ids.add(key)
    # Search next-best non-dominated choices when objectives coincide. No dominated filler.
    for name, ranked in rankings:
        if len(selected) >= 4:
            break
        for option in ranked:
            key = tuple(option["selected_ids"])
            if key not in selected_ids and non_dominated(option):
                selected.append({**option, "profile": name + " alternative", "profiles": [name], "next_best": True})
                selected_ids.add(key)
                break
    return selected[:4]
