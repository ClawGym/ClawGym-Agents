import json
import os
import re
import sys
from datetime import datetime, timedelta

def parse_simple_yaml(path):
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f.read().splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                # Strip surrounding quotes if present
                if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                    val_str = val[1:-1]
                else:
                    val_str = val
                # Try to parse as int or float
                if val_str in ("null", "~"):
                    value = None
                else:
                    try:
                        if "." in val_str:
                            value = float(val_str)
                            # If ends with .0 exactly, cast to int for cleanliness
                            if val_str.endswith(".0"):
                                try:
                                    value = int(value)
                                except Exception:
                                    pass
                        else:
                            value = int(val_str)
                    except ValueError:
                        value = val_str
                data[key] = value
    except FileNotFoundError:
        raise
    except Exception:
        # Fallback: attempt very naive parse line by line without types
        with open(path, "r", encoding="utf-8") as f:
            for raw in f.read().splitlines():
                if ":" in raw:
                    k, v = raw.split(":", 1)
                    data[k.strip()] = v.strip()
    return data

def parse_iso8601(s):
    if s is None:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # Try to remove timezone colon in offset if exists like +00:00
        m = re.match(r"^(.*)([+-]\d{2}):?(\d{2})$", s)
        if m:
            base, hh, mm = m.groups()
            try:
                return datetime.fromisoformat(f"{base}{hh}{mm}")
            except Exception:
                pass
        # Last resort: remove timezone
        try:
            return datetime.fromisoformat(s.split("+")[0].split("-")[0])
        except Exception:
            raise

def nearly_equal(a, b, tol=1e-6):
    return abs(float(a) - float(b)) <= tol

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def round2(x):
    return round(x + 0.0, 2)

def round4(x):
    return round(x + 0.0, 4)

def extract_numbers(line):
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", line)
    out = []
    for n in nums:
        try:
            out.append(float(n))
        except Exception:
            pass
    return out

def contains_int(line, target_int):
    # Matches integer presence exactly (allow decimal .0 as well)
    # Check both direct int and float equal to int
    nums = extract_numbers(line)
    for n in nums:
        if int(round(n)) == int(target_int) and abs(n - int(target_int)) < 1e-6 or (abs(n - int(target_int)) < 1e-6):
            return True
    return False

def contains_float_approx(line, target_float, tol=1e-4):
    nums = extract_numbers(line)
    for n in nums:
        if abs(n - float(target_float)) <= tol:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "metrics_exists": False,
        "metrics_valid_json": False,
        "metrics_markets_observed": False,
        "metrics_selected_set": False,
        "metrics_positions_set_and_stake": False,
        "metrics_pnl": False,
        "metrics_llm": False,
        "metrics_budget": False,
        "metrics_complexity": False,
        "metrics_mini_summary_two_lines": False,
        "report_exists": False,
        "report_labels_present": False,
        "report_markets_counts_match": False,
        "report_titles_include_selected": False,
        "report_simulation_line_matches": False,
        "report_llm_costs_match": False,
        "report_net_result_matches": False,
        "report_complexity_note_if_applicable": False,
        "report_mini_summary_two_lines": False,
    }

    # Load inputs
    try:
        markets_path = os.path.join(input_dir, "markets.json")
        llm_costs_path = os.path.join(input_dir, "llm_costs.yaml")
        budget_path = os.path.join(input_dir, "budget.yaml")
        cycle_hist_path = os.path.join(input_dir, "cycle_history.json")

        markets = read_json(markets_path)
        llm_costs = parse_simple_yaml(llm_costs_path)
        budget = parse_simple_yaml(budget_path)
        cycle_hist = read_json(cycle_hist_path)
    except Exception:
        # If inputs cannot be read, no positive reward should be granted.
        result = {"reward": 0.0, **checks}
        print(json.dumps(result))
        return

    # Compute expected values
    markets_observed = len(markets) if isinstance(markets, list) else 0

    # Pre-filter by deterministic rules
    as_of_iso = budget.get("as_of_iso")
    try:
        as_of_dt = parse_iso8601(as_of_iso)
    except Exception:
        as_of_dt = None
    dt_threshold = None
    if as_of_dt is not None:
        dt_threshold = as_of_dt + timedelta(hours=24)

    def market_passes(m):
        try:
            vol = float(m.get("volume_eur", 0))
            delta = float(m.get("delta_prob_24h", 0))
            closes = m.get("closes_at")
            closes_dt = parse_iso8601(closes)
        except Exception:
            return False
        if vol < 2000:
            return False
        if abs(delta) < 0.02:
            return False
        if dt_threshold is None or closes_dt is None:
            return False
        if not (closes_dt > dt_threshold):
            return False
        return True

    filtered = [m for m in markets if isinstance(m, dict) and market_passes(m)]
    # Select up to 5 by descending volume_eur; tie-break by id for determinism
    def sort_key_sel(m):
        vol = float(m.get("volume_eur", 0))
        mid = str(m.get("id", ""))
        return (-vol, mid)
    selected = sorted(filtered, key=sort_key_sel)[:5]
    selected_ids = [str(m.get("id", "")) for m in selected]
    selected_titles = [str(m.get("title", "")) for m in selected]

    # Positions: only positive delta among selected, top-3 by volume desc
    positives = [m for m in selected if float(m.get("delta_prob_24h", 0.0)) > 0.0]
    positions = sorted(positives, key=lambda m: (-float(m.get("volume_eur", 0.0)), str(m.get("id", ""))))[:3]
    positions_ids = [str(m.get("id", "")) for m in positions]
    positions_opened = len(positions)
    capital_eur = 50.0
    if positions_opened > 0:
        stake_per = round2(capital_eur / positions_opened)
    else:
        stake_per = 0.0

    # P&L per position: round(delta * stake, 2), then sum and round(2)
    pos_pnls = []
    for m in positions:
        delta = float(m.get("delta_prob_24h", 0.0))
        pos_pnls.append(round2(delta * stake_per))
    pnl_eur = round2(sum(pos_pnls))
    pnl_pct = round2((pnl_eur / capital_eur) * 100.0 if capital_eur != 0 else 0.0)

    # LLM accounting
    openai_tokens = 50 * markets_observed + 25 * len(selected)
    anthropic_tokens = 200 + 10 * len(selected)
    anthropic_calls = 1

    openai_price = float(llm_costs.get("openai_price_eur_per_1k", 0.0) or 0.0)
    anthropic_price = float(llm_costs.get("anthropic_price_eur_per_1k", 0.0) or 0.0)

    openai_cost_eur = round4((openai_tokens / 1000.0) * openai_price)
    anthropic_cost_eur = round4((anthropic_tokens / 1000.0) * anthropic_price)
    total_cost_eur = round4(openai_cost_eur + anthropic_cost_eur)

    # Budget gate
    weekly_budget_eur = float(budget.get("weekly_budget_eur", 0.0) or 0.0)
    current_week_spend_eur = float(budget.get("current_week_spend_eur", 0.0) or 0.0)
    allowable_run_eur = max(0.0, weekly_budget_eur - current_week_spend_eur)
    shutdown = total_cost_eur > allowable_run_eur

    # Complexity control
    complexity_reduced = False
    last_two = cycle_hist[-2:] if isinstance(cycle_hist, list) else []
    if len(last_two) == 2:
        try:
            c1 = float(last_two[0].get("llm_cost_eur", 0.0)) > float(last_two[0].get("simulated_return_eur", 0.0))
            c2 = float(last_two[1].get("llm_cost_eur", 0.0)) > float(last_two[1].get("simulated_return_eur", 0.0))
            complexity_reduced = bool(c1 and c2)
        except Exception:
            complexity_reduced = False

    # Load outputs
    metrics_path = os.path.join(output_dir, "metrics.json")
    report_path = os.path.join(output_dir, "report.txt")

    metrics = None
    if os.path.isfile(metrics_path):
        checks["metrics_exists"] = True
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            if isinstance(metrics, dict):
                checks["metrics_valid_json"] = True
        except Exception:
            metrics = None

    report_text = ""
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            report_text = ""

    # Validate metrics.json
    if checks["metrics_valid_json"]:
        try:
            if int(metrics.get("markets_observed", -1)) == markets_observed:
                checks["metrics_markets_observed"] = True
        except Exception:
            pass

        # selected markets
        try:
            msel_count = int(metrics.get("markets_selected_count", -1))
            msel_ids = metrics.get("markets_selected_ids", [])
            if isinstance(msel_ids, list):
                msel_ids = [str(x) for x in msel_ids]
            if (msel_count == len(selected_ids)) and (set(msel_ids) == set(selected_ids)):
                checks["metrics_selected_set"] = True
        except Exception:
            pass

        # positions and stake
        try:
            mpos_opened = int(metrics.get("positions_opened", -1))
            mpos_ids = metrics.get("positions_ids", [])
            if isinstance(mpos_ids, list):
                mpos_ids = [str(x) for x in mpos_ids]
            stake_reported = float(metrics.get("stake_per_position_eur", -999))
            stake_ok = (positions_opened == 0 and nearly_equal(stake_reported, 0.0, tol=0.01)) or (positions_opened > 0 and nearly_equal(stake_reported, stake_per, tol=0.01))
            if (mpos_opened == positions_opened) and (set(mpos_ids) == set(positions_ids)) and stake_ok:
                checks["metrics_positions_set_and_stake"] = True
        except Exception:
            pass

        # pnl
        try:
            mpnl_eur = float(metrics.get("pnl_eur", 999999))
            mpnl_pct = float(metrics.get("pnl_pct", 999999))
            if nearly_equal(mpnl_eur, pnl_eur, tol=0.01) and nearly_equal(mpnl_pct, pnl_pct, tol=0.01):
                checks["metrics_pnl"] = True
        except Exception:
            pass

        # llm metrics
        try:
            llm = metrics.get("llm", {})
            m_openai_tokens = int(llm.get("openai_tokens", -1))
            m_anthropic_tokens = int(llm.get("anthropic_tokens", -1))
            m_openai_cost = float(llm.get("openai_cost_eur", 999999))
            m_anthropic_cost = float(llm.get("anthropic_cost_eur", 999999))
            m_total_cost = float(llm.get("total_cost_eur", 999999))
            m_calls = int(llm.get("anthropic_calls", -1))
            if (
                m_openai_tokens == openai_tokens and
                m_anthropic_tokens == anthropic_tokens and
                nearly_equal(m_openai_cost, openai_cost_eur, tol=1e-4) and
                nearly_equal(m_anthropic_cost, anthropic_cost_eur, tol=1e-4) and
                nearly_equal(m_total_cost, total_cost_eur, tol=1e-4) and
                m_calls == anthropic_calls
            ):
                checks["metrics_llm"] = True
        except Exception:
            pass

        # budget
        try:
            budget_m = metrics.get("budget", {})
            m_weekly = float(budget_m.get("weekly_budget_eur", -999999))
            m_spend = float(budget_m.get("current_week_spend_eur", -999999))
            m_allowable = float(budget_m.get("allowable_run_eur", -999999))
            m_shutdown = bool(budget_m.get("shutdown", None))
            if (
                nearly_equal(m_weekly, weekly_budget_eur, tol=1e-6) and
                nearly_equal(m_spend, current_week_spend_eur, tol=1e-6) and
                nearly_equal(m_allowable, allowable_run_eur, tol=1e-6) and
                (m_shutdown == shutdown)
            ):
                checks["metrics_budget"] = True
        except Exception:
            pass

        # complexity
        try:
            m_complexity = bool(metrics.get("complexity_reduced", False))
            if m_complexity == complexity_reduced:
                checks["metrics_complexity"] = True
        except Exception:
            pass

        # mini_summary two lines
        try:
            mini = metrics.get("mini_summary", [])
            ok = isinstance(mini, list) and len(mini) == 2 and all(isinstance(x, str) and x.strip() for x in mini)
            if ok:
                checks["metrics_mini_summary_two_lines"] = True
        except Exception:
            pass

    # Validate report.txt
    if checks["report_exists"]:
        text = report_text or ""
        labels_ok = all(lbl in text for lbl in [
            "Numero di mercati osservati:",
            "Mercati selezionati:",
            "Risultato della simulazione:",
            "Costi LLM dettagliati",
            "Risultato netto simulato",
            "Mini-riassunto",
        ])
        if labels_ok:
            checks["report_labels_present"] = True

        # Counts in labels
        try:
            m1 = re.search(r"Numero di mercati osservati:\s*(\d+)", text)
            m2 = re.search(r"Mercati selezionati:\s*(\d+)", text)
            if m1 and m2:
                num_obs = int(m1.group(1))
                num_sel = int(m2.group(1))
                if num_obs == markets_observed and num_sel == len(selected_ids):
                    checks["report_markets_counts_match"] = True
        except Exception:
            pass

        # Titles include selected market titles
        titles_ok = True
        if len(selected_titles) > 0:
            for t in selected_titles:
                if t and t not in text:
                    titles_ok = False
                    break
        if titles_ok:
            checks["report_titles_include_selected"] = True

        # Simulation result line strict
        try:
            # Find the line with the label and parse numbers
            sim_line_match = re.search(r"Risultato della simulazione:\s*([+-]?\d+(?:\.\d+)?)%\s*e\s*€\s*([+-]?\d+(?:\.\d+)?)", text)
            if sim_line_match:
                pct_str = sim_line_match.group(1)
                eur_str = sim_line_match.group(2)
                pct_val = float(pct_str)
                eur_val = float(eur_str)
                if nearly_equal(pct_val, pnl_pct, tol=0.01) and nearly_equal(eur_val, pnl_eur, tol=0.01):
                    checks["report_simulation_line_matches"] = True
        except Exception:
            pass

        # LLM costs lines: OpenAI, Anthropic, Totale
        try:
            openai_lines = [line for line in text.splitlines() if "OpenAI" in line]
            anthropic_lines = [line for line in text.splitlines() if "Anthropic" in line]
            total_lines = [line for line in text.splitlines() if re.search(r"\bTotale\b", line)]
            openai_ok = False
            for line in openai_lines:
                if contains_int(line, openai_tokens) and contains_float_approx(line, openai_cost_eur, tol=1e-4):
                    openai_ok = True
                    break
            anthropic_ok = False
            for line in anthropic_lines:
                if contains_int(line, anthropic_tokens) and contains_float_approx(line, anthropic_cost_eur, tol=1e-4):
                    anthropic_ok = True
                    break
            total_ok = False
            for line in total_lines:
                if contains_float_approx(line, total_cost_eur, tol=1e-4):
                    total_ok = True
                    break
            if openai_ok and anthropic_ok and total_ok:
                checks["report_llm_costs_match"] = True
        except Exception:
            pass

        # Net result line
        try:
            net_val = round2(pnl_eur - total_cost_eur)
            net_line_match = re.search(r"Risultato netto simulato.*?€\s*([+-]?\d+(?:\.\d+)?)", text)
            if net_line_match:
                val = float(net_line_match.group(1))
                if nearly_equal(val, net_val, tol=0.01):
                    checks["report_net_result_matches"] = True
        except Exception:
            pass

        # Complexity prudent note if applicable
        try:
            if complexity_reduced:
                # Must mention reduction of complexity and prudence
                lower = text.lower()
                # Look for words like "riduc" and "compless"
                checks["report_complexity_note_if_applicable"] = ("compless" in lower and "riduc" in lower)
            else:
                # Not required when not applicable; pass by default if report exists
                checks["report_complexity_note_if_applicable"] = True
        except Exception:
            pass

        # Mini-riassunto with exactly 2 non-empty lines after the label line
        try:
            lines = text.splitlines()
            idxs = [i for i, ln in enumerate(lines) if "Mini-riassunto" in ln]
            ok = False
            if idxs:
                idx = idxs[0]
                # Take subsequent lines until blank segmentation or end
                # We require exactly 2 non-empty lines immediately following
                after = []
                j = idx + 1
                # Collect next lines until we have 2 non-empty lines
                while j < len(lines) and len(after) < 2:
                    if lines[j].strip():
                        after.append(lines[j])
                    else:
                        after.append("")  # include empty then it will fail
                    j += 1
                if len(after) == 2 and all(s.strip() for s in after):
                    ok = True
            if ok:
                checks["report_mini_summary_two_lines"] = True
        except Exception:
            pass

    # Compute reward: zero if outputs missing or invalid baseline
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Enforce no-op baseline: if either metrics or report missing or invalid, reward must be 0.0
    if not (checks["metrics_exists"] and checks["metrics_valid_json"] and checks["report_exists"]):
        reward = 0.0
    else:
        # Score as fraction of passed checks
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Bound reward to [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()