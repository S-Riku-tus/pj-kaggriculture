"""Build reproducible B1-based Round11 market-policy variants."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
B1 = (
    ROOT
    / "experiments"
    / "Kaggriculture_Round11_Research_Revision_20260924"
    / "inputs"
    / "agents"
    / "B1.py"
)


FORECAST_OLD = """    scored.sort(key=lambda x: -x[0])
    return [ev for _, ev in scored[:_V92_P_TOP]]
"""
FORECAST_NEW = """    scored.sort(key=lambda x: -x[0])
    # Keep up to three positively supported near-best rival trajectories.
    if not scored or scored[0][0] < 0:
        return [ev for _, ev in scored[:_V92_P_TOP]]
    return [ev for score, ev in scored[:3] if score >= scored[0][0] - 1.0]
"""
VOTE_OLD = """        if votes < 1:
            continue
        ours = 0
"""
VOTE_NEW = """        if votes < 1:
            continue
        alternate = not (
            best[0].get((step + 1, i), 0) + best[0].get((step + 2, i), 0) >= _V92_P_K
        )
        ours = 0
"""
REPORT_OLD = """            _V92_P_REPORT["pred_units"] += qty
            _V92_P_REPORT["pred_fires"] += 1
            changed = True
"""
REPORT_NEW = """            _V92_P_REPORT["pred_units"] += qty
            _V92_P_REPORT["pred_fires"] += 1
            if alternate:
                _V92_P_REPORT["frontier_fires"] = _V92_P_REPORT.get("frontier_fires", 0) + 1
                _V92_P_REPORT["frontier_units"] = _V92_P_REPORT.get("frontier_units", 0) + qty
            changed = True
"""
RESCUE_OLD = """    _R2_REPORT.update(rescue=dict(_UPGRADE_STATS), fertilizer=dict(_E410_REPORT), seed_budget=dict(globals().get('_E402_REPORT', {})))
"""
RESCUE_NEW = """    _R2_REPORT.update(rescue=dict(_UPGRADE_STATS), fertilizer=dict(_E410_REPORT), seed_budget=dict(globals().get('_E402_REPORT', {})), forecast=dict(_V92_P_REPORT))
"""


M11_TEMPLATE = r'''

# Round11 M11: one response after the complete B1 chain. The stateful host is
# invoked exactly once. Fixed-price orders can be delayed but never advanced.
_M11_HOST = [v for v in list(globals().values()) if callable(v)][-1]
_M11_MODE = "{mode}"
_M11_REPORT = dict(calls=0, eligible=0, changes=0, errors=0,
                   evaluations=0, predicted_gain=0.0, mode=_M11_MODE)


def _m11_response(obs, baseline):
    orders = baseline.get("market") or []
    if len(orders) < 2:
        return baseline
    bought = {{o[1] for o in orders if o and len(o) > 1 and o[0] == "BUY_PRODUCT"}}
    slots, sells, fixed = [], [], []
    for index, order in enumerate(orders):
        if not order:
            continue
        if order[0] in _CXD_FIXED:
            slots.append(index)
            fixed.append(order)
        elif order[0] == "SELL" and len(order) >= 3 and order[1] not in bought:
            slots.append(index)
            sells.append(order)
    if not sells or len(slots) < 2:
        return baseline
    _M11_REPORT["eligible"] += 1
    params = _v44y_params(obs)
    stock = {{k: max(0, int(v)) for k, v in projected_shed(baseline, FarmView(obs)).items()}}
    inventory = {{k: int(v) for k, v in obs["market"]["inventory"].items()}}
    models = [orders]
    parent_orders = [list(o) for o in globals().get("_CXD_PARENT_ORDERS", []) if o]
    if _M11_MODE == "robust" and parent_orders and parent_orders != orders:
        models.append(parent_orders)
    scorers = [_v44y_factor_margin(model, inventory, stock, params) for model in models]
    references = [score(orders) for score in scorers]
    fixed_positions = [i for i, o in enumerate(orders) if o and o[0] in _CXD_FIXED]
    best_gain, chosen = 0.5, None
    for count, candidate in enumerate(_cxd_candidates(orders, slots, sells, fixed)):
        if count >= _CXD_BUDGET:
            break
        if candidate == orders:
            continue
        new_fixed = [i for i, o in enumerate(candidate) if o and o[0] in _CXD_FIXED]
        if any(new < old for new, old in zip(new_fixed, fixed_positions)):
            continue
        gain = min(score(candidate) - ref for score, ref in zip(scorers, references))
        _M11_REPORT["evaluations"] += 1
        if gain > best_gain:
            best_gain, chosen = gain, candidate
    if chosen is None:
        return baseline
    _M11_REPORT["changes"] += 1
    _M11_REPORT["predicted_gain"] += best_gain
    return dict(baseline, market=chosen)


def m11_response_agent(observation, configuration=None):
    action = _M11_HOST(observation, configuration)
    if int(observation.get("step", 0)) == 0:
        _M11_REPORT.update(calls=0, eligible=0, changes=0, errors=0,
                           evaluations=0, predicted_gain=0.0, mode=_M11_MODE)
    _M11_REPORT["calls"] += 1
    try:
        return _m11_response(observation, action)
    except Exception:
        _M11_REPORT["errors"] += 1
        return action


m11_response_agent.telemetry = _M11_REPORT
'''


ALWAYS_OPEN_WOOL_TEMPLATE = r'''

# Round11 diagnostic control: reproduce the package's unconditional WOOL gate
# opening while keeping the complete B1 callable chain.
V9_RACEGATE_BASE["WOOL"] = 0
_R11_WOOL_OPEN_HOST = [v for v in list(globals().values()) if callable(v)][-1]
_R11_WOOL_OPEN_REPORT = dict(calls=0, errors=0, mode="unconditional")


def wool_gate_open_agent(observation, configuration=None):
    if int(observation.get("step", 0)) == 0:
        _R11_WOOL_OPEN_REPORT.update(calls=0, errors=0, mode="unconditional")
    _R11_WOOL_OPEN_REPORT["calls"] += 1
    try:
        return _R11_WOOL_OPEN_HOST(observation, configuration)
    except Exception:
        _R11_WOOL_OPEN_REPORT["errors"] += 1
        return {"farmer": ["PASS"], "hands": [], "market": []}


wool_gate_open_agent.telemetry = _R11_WOOL_OPEN_REPORT
'''


CONDITIONAL_WOOL_TEMPLATE = r'''

# Round11 CW1: open only the WOOL reservation gate when multiple public-history
# trajectories predict an imminent rival lot and that lot is expected to push the
# quote down. The original reservation implementation remains responsible for
# stock, purchase, pickup, order-cap, horizon and sell-debt contracts.
_CW1_ENTRY_HOST = [v for v in list(globals().values()) if callable(v)][-1]
_CW1_RESERVE_HOST = _RACE_ORIG_RESERVE
_CW1_REPORT = dict(calls=0, eligible=0, open_attempts=0, changes=0,
                   reserved_units=0, errors=0, mode="conditional_wool_v1")


def _cw1_forecast(observation):
    player = int(observation["player"])
    step = int(observation["step"])
    state = _V92_P.get(player) or {}
    if step < 192 or step >= 672 or not state.get("obs"):
        return 0, 0, 0
    global _V92_P_TOP
    previous_top = _V92_P_TOP
    try:
        _V92_P_TOP = 3
        forecasts = _v92_p_forecast(observation, state)
    finally:
        _V92_P_TOP = previous_top
    if len(forecasts) < 2:
        return 0, 0, len(forecasts)
    index = _V92_P_ITEMS.index("WOOL")
    quantities = [
        int(events.get((step + 1, index), 0)) + int(events.get((step + 2, index), 0))
        for events in forecasts
    ]
    votes = sum(quantity >= 4 for quantity in quantities)
    conservative_quantity = sorted(quantities, reverse=True)[1] if votes >= 2 else 0
    return votes, conservative_quantity, len(forecasts)


def _cw1_should_open(observation, action):
    price = int(observation["market"]["prices"].get("WOOL", 0))
    if price < 150 or price > 200:
        return False
    orders = action.get("market") or []
    if any(order and len(order) > 1 and order[1] == "WOOL"
           and order[0] in ("SELL", "BUY_PRODUCT") for order in orders):
        return False
    stock = projected_shed(action, FarmView(observation))
    if int(stock.get("WOOL", 0)) <= 0:
        return False
    votes, rival_quantity, models = _cw1_forecast(observation)
    if models < 2 or votes < 2 or rival_quantity < 8:
        return False
    step = int(observation["step"])
    shops = list(observation["town"].get("unlocked_shops") or [])
    consumption = sum(_v9_town_draw(shops, turn).get("WOOL", 0) for turn in (step, step + 1))
    net_rival = max(0, rival_quantity - consumption)
    if net_rival < 8:
        return False
    inventory = int(observation["market"]["inventory"]["WOOL"])
    future_quote = int(_v44y_price("WOOL", inventory + net_rival, _v44y_params(observation)))
    return price - future_quote >= 5


def _cw1_reserve(observation, action):
    _CW1_REPORT["eligible"] += 1
    if not _cw1_should_open(observation, action):
        return _CW1_RESERVE_HOST(observation, action)
    _CW1_REPORT["open_attempts"] += 1
    before = sum(int(order[2]) for order in action.get("market") or []
                 if order and len(order) >= 3 and order[:2] == ["SELL", "WOOL"])
    previous = V9_RACEGATE_BASE["WOOL"]
    try:
        V9_RACEGATE_BASE["WOOL"] = 0
        result = _CW1_RESERVE_HOST(observation, action)
    finally:
        V9_RACEGATE_BASE["WOOL"] = previous
    after = sum(int(order[2]) for order in result.get("market") or []
                if order and len(order) >= 3 and order[:2] == ["SELL", "WOOL"])
    if after > before:
        _CW1_REPORT["changes"] += 1
        _CW1_REPORT["reserved_units"] += after - before
    return result


_RACE_ORIG_RESERVE = _cw1_reserve


def conditional_wool_agent(observation, configuration=None):
    if int(observation.get("step", 0)) == 0:
        _CW1_REPORT.update(calls=0, eligible=0, open_attempts=0, changes=0,
                           reserved_units=0, errors=0, mode="conditional_wool_v1")
    _CW1_REPORT["calls"] += 1
    try:
        return _CW1_ENTRY_HOST(observation, configuration)
    except Exception:
        _CW1_REPORT["errors"] += 1
        return {"farmer": ["PASS"], "hands": [], "market": []}


conditional_wool_agent.telemetry = _CW1_REPORT
'''


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one occurrence, found {count}")
    return source.replace(old, new, 1)


def build_m20(source: str) -> str:
    source = replace_once(source, FORECAST_OLD, FORECAST_NEW, "forecast")
    source = replace_once(source, VOTE_OLD, VOTE_NEW, "vote")
    source = replace_once(source, REPORT_OLD, REPORT_NEW, "report")
    return replace_once(source, RESCUE_OLD, RESCUE_NEW, "rescue telemetry")


def write_variant(output_root: Path, name: str, source: str, changes: list[str]) -> dict:
    path = output_root / name / "main.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = source.encode("utf-8")
    ast.parse(source)
    path.write_bytes(data)
    functions = [
        node.name
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return {
        "arm": name,
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(data),
        "bytes": len(data),
        "last_top_level_function": functions[-1],
        "changes": changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "experiments/round11_execution_20260924/arms",
    )
    args = parser.parse_args()
    output_root = args.output_root if args.output_root.is_absolute() else ROOT / args.output_root
    baseline_bytes = B1.read_bytes()
    baseline = baseline_bytes.decode("utf-8").replace("\r\n", "\n")
    m20 = build_m20(baseline)
    variants = [
        write_variant(
            output_root,
            "m20_multi_hypothesis",
            m20,
            ["B1 forecast keeps up to three near-best trajectories; B1 opening retained"],
        ),
        write_variant(
            output_root,
            "m11_final_response",
            baseline + M11_TEMPLATE.format(mode="final"),
            ["one response to final B1 orders; fixed-price orders never advanced"],
        ),
        write_variant(
            output_root,
            "m11_robust_response",
            baseline + M11_TEMPLATE.format(mode="robust"),
            ["one response robust to final and pre-CXD B1 order hypotheses"],
        ),
        write_variant(
            output_root,
            "m20_m11_final",
            m20 + M11_TEMPLATE.format(mode="final"),
            ["M20 multi-hypothesis forecast", "M11 final-order response"],
        ),
        write_variant(
            output_root,
            "wool_gate_open_control",
            baseline + ALWAYS_OPEN_WOOL_TEMPLATE,
            ["diagnostic control: V9_RACEGATE_BASE[WOOL]=0 on every decision"],
        ),
        write_variant(
            output_root,
            "cw1_conditional_wool",
            baseline + CONDITIONAL_WOOL_TEMPLATE,
            [
                "open WOOL reservation only with >=2 public-history trajectory votes",
                "require conservative imminent lot >=8 after town demand and predicted quote loss >=5",
                "preserve B1 reservation debt, stock, pickup, purchase, horizon and order-cap logic",
            ],
        ),
    ]
    result = {
        "schema": "round11-generated-arm-manifest-v1",
        "baseline_path": B1.relative_to(ROOT).as_posix(),
        "baseline_sha256": sha256(baseline_bytes),
        "variants": variants,
    }
    manifest = output_root / "generated_manifest.json"
    manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
