import json
import os
import sys
import re
from datetime import datetime, date, timezone

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def safe_float(x):
    try:
        if isinstance(x, bool):
            return float(int(x))
        return float(x)
    except (TypeError, ValueError):
        return 0.0

def safe_int(x):
    try:
        if isinstance(x, bool):
            return int(x)
        # If float string like "1.0", cast to float first then int
        if isinstance(x, str) and x.strip() != "":
            if "." in x or "e" in x.lower():
                return int(float(x))
        return int(x)
    except (TypeError, ValueError):
        return 0

def parse_iso_or_epoch(ts_val):
    """
    Parse timestamp from various formats to datetime (UTC naive).
    Accepts ISO strings with or without Z/offset and epoch seconds or ms.
    Returns datetime or None.
    """
    if ts_val is None:
        return None
    try:
        if isinstance(ts_val, (int, float)):
            val = float(ts_val)
            # Treat > 1e11 as milliseconds
            if val > 1e11:
                val = val / 1000.0
            dt = datetime.utcfromtimestamp(val)
            return dt
        if isinstance(ts_val, str):
            s = ts_val.strip()
            if not s:
                return None
            # Replace trailing Z with +00:00 for fromisoformat
            s2 = s.replace("Z", "+00:00")
            # Try datetime ISO
            try:
                dt = datetime.fromisoformat(s2)
                # If timezone-aware, convert to UTC naive
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
            except ValueError:
                pass
            # Try date-only ISO
            try:
                d = date.fromisoformat(s[:10])
                return datetime(d.year, d.month, d.day)
            except ValueError:
                pass
            # Try numeric string epoch
            if re.fullmatch(r"-?\d+(\.\d+)?", s):
                val = float(s)
                if val > 1e11:
                    val = val / 1000.0
                return datetime.utcfromtimestamp(val)
    except Exception:
        return None
    return None

def process_jsonl_file(filepath):
    """
    Process a single JSONL conversation session file.
    Returns a dict with session metrics.
    """
    tokens_in = 0
    tokens_out = 0
    cost_total = 0.0
    human_turns = 0
    assistant_turns = 0
    earliest = None
    models_in_session = set()
    model_costs_session = {}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Timestamps
                ts = msg.get("timestamp")
                if ts is None:
                    ts = msg.get("createdAt")
                if ts is None:
                    ts = msg.get("ts")
                dt = parse_iso_or_epoch(ts)
                if dt is not None:
                    if earliest is None or dt < earliest:
                        earliest = dt

                # Turns
                role = str(msg.get("role", "")).lower()
                if role in ("user", "human"):
                    human_turns += 1
                elif role == "assistant":
                    assistant_turns += 1

                # Tokens usage with fallback by presence (not falsy value)
                usage = msg.get("usage", {})
                in_tok = 0
                out_tok = 0
                if isinstance(usage, dict):
                    if "input_tokens" in usage and usage.get("input_tokens") is not None:
                        in_tok = safe_int(usage.get("input_tokens"))
                    elif "prompt_tokens" in usage and usage.get("prompt_tokens") is not None:
                        in_tok = safe_int(usage.get("prompt_tokens"))
                    if "output_tokens" in usage and usage.get("output_tokens") is not None:
                        out_tok = safe_int(usage.get("output_tokens"))
                    elif "completion_tokens" in usage and usage.get("completion_tokens") is not None:
                        out_tok = safe_int(usage.get("completion_tokens"))
                tokens_in += in_tok
                tokens_out += out_tok

                # Cost (prefer costUSD)
                msg_cost = 0.0
                if "costUSD" in msg and msg.get("costUSD") is not None:
                    msg_cost = safe_float(msg.get("costUSD"))
                elif "cost" in msg and msg.get("cost") is not None:
                    msg_cost = safe_float(msg.get("cost"))
                cost_total += msg_cost

                # Model attribution for model breakdowns
                model_name = msg.get("model")
                if isinstance(model_name, str) and model_name.strip() != "":
                    models_in_session.add(model_name)
                    model_costs_session[model_name] = model_costs_session.get(model_name, 0.0) + msg_cost

    except FileNotFoundError:
        pass
    except UnicodeDecodeError:
        pass

    date_str = earliest.date().isoformat() if earliest is not None else None
    return {
        "date": date_str,
        "turns": human_turns + assistant_turns,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": cost_total,
        "models_seen": models_in_session,
        "model_costs": model_costs_session,
    }

def aggregate_from_input(input_projects_dir):
    """
    Walk input/projects and aggregate ground-truth metrics.
    """
    sessions = []
    projects = {}
    model_costs = {}
    model_sessions = {}
    date_set = set()
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0
    total_turns = 0
    total_sessions = 0

    if not os.path.isdir(input_projects_dir):
        return {
            "sessions": sessions,
            "projects": {},
            "models_cost": {},
            "models_sessions": {},
            "dates": set(),
            "totals": {
                "sessions": 0,
                "turns": 0,
                "cost": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
            }
        }

    for root, _, files in os.walk(input_projects_dir):
        for fn in files:
            if not fn.lower().endswith(".jsonl"):
                continue
            fpath = os.path.join(root, fn)
            # Determine project name (first path segment under input/projects)
            rel = os.path.relpath(fpath, input_projects_dir)
            parts = rel.split(os.sep)
            project_name = parts[0] if len(parts) >= 2 else (os.path.dirname(rel) or "unknown")
            if project_name == "." or project_name == "":
                project_name = "unknown"

            s = process_jsonl_file(fpath)
            sessions.append((fpath, project_name, s))
            total_sessions += 1
            total_turns += s["turns"]
            total_tokens_in += s["tokens_in"]
            total_tokens_out += s["tokens_out"]
            total_cost += s["cost"]
            if s["date"]:
                date_set.add(s["date"])

            # Projects aggregation
            p = projects.get(project_name)
            if p is None:
                p = {"sessions": 0, "cost": 0.0, "turns": 0}
                projects[project_name] = p
            p["sessions"] += 1
            p["cost"] += s["cost"]
            p["turns"] += s["turns"]

            # Models aggregation
            for m in s["models_seen"]:
                model_sessions[m] = model_sessions.get(m, 0) + 1
            for m, c in s["model_costs"].items():
                model_costs[m] = model_costs.get(m, 0.0) + c

    return {
        "sessions": sessions,
        "projects": projects,
        "models_cost": model_costs,
        "models_sessions": model_sessions,
        "dates": date_set,
        "totals": {
            "sessions": total_sessions,
            "turns": total_turns,
            "cost": total_cost,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
        }
    }

def nearly_equal(a, b, tol=1e-6):
    return abs(float(a) - float(b)) <= tol

def sorted_desc_by_cost(projects_list):
    for i in range(len(projects_list) - 1):
        if projects_list[i].get("cost", 0) < projects_list[i + 1].get("cost", 0) - 1e-9:
            return False
    return True

def extract_headings_lines(lines):
    return [ln.strip() for ln in lines]

def find_section_indices(lines, header_keywords):
    """
    Find indices of lines that contain specified header keywords (case-insensitive).
    Returns dict keyword_lower -> index, if found.
    """
    idxs = {}
    for i, ln in enumerate(lines):
        s = ln.strip()
        s_no_hash = s.lstrip("#").strip()
        for kw in header_keywords:
            if s_no_hash.lower() == kw.lower():
                idxs[kw.lower()] = i
            # Also allow lines that start with header markdown and keyword
            elif s_no_hash.lower().startswith(kw.lower()):
                idxs.setdefault(kw.lower(), i)
    return idxs

def check_report_recommendations(lines, rec_start_idx, next_section_idx=None):
    """
    Count bullet lines starting with "- " in Recommendations section.
    """
    if rec_start_idx is None:
        return 0
    start = rec_start_idx + 1
    end = next_section_idx if next_section_idx is not None else len(lines)
    count = 0
    for ln in lines[start:end]:
        if ln.startswith("- "):
            count += 1
    return count

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used but reserved

    checks = {
        "has_stats_json": False,
        "stats_json_parsed": False,
        "stats_summary_fields_present": False,
        "stats_totals_match": False,
        "stats_active_days_and_date_range_and_daily_avg_match": False,
        "stats_projects_present_sorted": False,
        "stats_projects_top_two_expected": False,
        "stats_projects_values_match": False,
        "stats_models_presence": False,
        "stats_models_values_match": False,
        "has_report_md": False,
        "report_sections_present": False,
        "report_data_window_line": False,
        "report_recommendations_bullets": False,
        "report_mentions_top_project": False,
    }

    # Aggregate expected ground-truth
    input_projects_dir = os.path.join(input_dir, "projects")
    agg = aggregate_from_input(input_projects_dir)
    gt_total_sessions = agg["totals"]["sessions"]
    gt_total_turns = agg["totals"]["turns"]
    gt_total_cost = agg["totals"]["cost"]
    gt_tokens_in = agg["totals"]["tokens_in"]
    gt_tokens_out = agg["totals"]["tokens_out"]
    gt_dates = sorted(agg["dates"])
    gt_active_days = len(set(gt_dates))
    gt_date_min = gt_dates[0] if gt_dates else None
    gt_date_max = gt_dates[-1] if gt_dates else None
    gt_daily_avg = (gt_total_sessions / gt_active_days) if gt_active_days > 0 else 0.0

    # Projects ground truth
    gt_projects = {}
    for name, p in agg["projects"].items():
        sessions = p["sessions"]
        cost = p["cost"]
        turns = p["turns"]
        avg_cost = cost / sessions if sessions else 0.0
        gt_projects[name] = {
            "name": name,
            "sessions": sessions,
            "cost": cost,
            "turns": turns,
            "avg_cost": avg_cost,
        }
    # Expected top two project names by cost (descending)
    gt_projects_sorted = sorted(gt_projects.values(), key=lambda x: (-x["cost"], x["name"]))
    gt_top1_name = gt_projects_sorted[0]["name"] if gt_projects_sorted else None
    gt_top2_name = gt_projects_sorted[1]["name"] if len(gt_projects_sorted) > 1 else None

    # Models ground truth (costs from messages with model; sessions count per model by session presence)
    gt_models_cost = agg["models_cost"]
    gt_models_sessions = agg["models_sessions"]

    # Read outputs
    stats_path = os.path.join(output_dir, "stats.json")
    report_path = os.path.join(output_dir, "report.md")

    stats_obj = None
    if os.path.isfile(stats_path):
        checks["has_stats_json"] = True
        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                stats_obj = json.load(f)
            checks["stats_json_parsed"] = True
        except Exception:
            stats_obj = None

    if stats_obj is not None and isinstance(stats_obj, dict):
        # Check summary fields presence
        summary = stats_obj.get("summary")
        projects_list = stats_obj.get("projects")
        models_list = stats_obj.get("models")
        if isinstance(summary, dict) and isinstance(projects_list, list) and isinstance(models_list, list):
            required_summary_keys = [
                "total_sessions",
                "total_turns",
                "total_cost",
                "total_tokens_in",
                "total_tokens_out",
                "active_days",
                "daily_avg_sessions",
                "date_range",
            ]
            if all(k in summary for k in required_summary_keys):
                checks["stats_summary_fields_present"] = True

                # Totals match (with rounding rule for costs)
                try:
                    rep_sessions = safe_int(summary.get("total_sessions"))
                    rep_turns = safe_int(summary.get("total_turns"))
                    rep_cost = safe_float(summary.get("total_cost"))
                    rep_tokens_in = safe_int(summary.get("total_tokens_in"))
                    rep_tokens_out = safe_int(summary.get("total_tokens_out"))
                    # Costs expected rounded to 4 decimals in stats.json
                    gt_total_cost_rounded = round(gt_total_cost, 4)
                    totals_ok = (
                        rep_sessions == gt_total_sessions and
                        rep_turns == gt_total_turns and
                        rep_tokens_in == gt_tokens_in and
                        rep_tokens_out == gt_tokens_out and
                        nearly_equal(rep_cost, gt_total_cost_rounded, tol=1e-6)
                    )
                    if totals_ok:
                        checks["stats_totals_match"] = True
                except Exception:
                    pass

                # Active days, date range include min and max, and daily avg within tolerance
                try:
                    rep_active_days = safe_int(summary.get("active_days"))
                    rep_daily_avg = safe_float(summary.get("daily_avg_sessions"))
                    rep_date_range = str(summary.get("date_range", ""))

                    # Date window check: ensure both min and max dates appear in the string
                    date_ok = False
                    if gt_date_min and gt_date_max:
                        if (gt_date_min in rep_date_range) and (gt_date_max in rep_date_range):
                            date_ok = True
                    else:
                        # If no dates, accept empty or N/A
                        if rep_date_range.strip() == "" or rep_date_range.lower().startswith("n/a"):
                            date_ok = True

                    avg_ok = True
                    if gt_active_days > 0:
                        avg_ok = abs(rep_daily_avg - (gt_total_sessions / gt_active_days)) <= 0.1
                    else:
                        avg_ok = rep_daily_avg == 0 or abs(rep_daily_avg) <= 1e-6

                    if (rep_active_days == gt_active_days) and date_ok and avg_ok:
                        checks["stats_active_days_and_date_range_and_daily_avg_match"] = True
                except Exception:
                    pass

            # Projects present and sorted by cost descending
            try:
                if isinstance(projects_list, list) and len(projects_list) >= 1:
                    # Check sorted descending by cost
                    if sorted_desc_by_cost(projects_list):
                        checks["stats_projects_present_sorted"] = True

                    # Top two expected names
                    # According to task, highest cost is "acme-client" and second "internal-research"
                    top_names_ok = False
                    if len(projects_list) >= 2:
                        first_name = str(projects_list[0].get("name", ""))
                        second_name = str(projects_list[1].get("name", ""))
                        if first_name == "acme-client" and second_name == "internal-research":
                            top_names_ok = True
                    if top_names_ok:
                        checks["stats_projects_top_two_expected"] = True

                    # Values match for each project reported (allow rounding for costs and avg_cost)
                    values_ok = True
                    for p in projects_list:
                        name = p.get("name")
                        if name not in gt_projects:
                            values_ok = False
                            break
                        gt = gt_projects[name]
                        rep_sessions = safe_int(p.get("sessions"))
                        rep_turns = safe_int(p.get("turns"))
                        rep_cost = safe_float(p.get("cost"))
                        rep_avg_cost = safe_float(p.get("avg_cost"))
                        gt_cost_rounded = round(gt["cost"], 4)
                        gt_avg_cost_rounded = round((gt["cost"] / gt["sessions"]) if gt["sessions"] else 0.0, 4)
                        if not (rep_sessions == gt["sessions"] and rep_turns == gt["turns"] and nearly_equal(rep_cost, gt_cost_rounded, 1e-6) and nearly_equal(rep_avg_cost, gt_avg_cost_rounded, 1e-6)):
                            values_ok = False
                            break
                    if values_ok:
                        checks["stats_projects_values_match"] = True
            except Exception:
                pass

            # Models presence and values match (for specific expected models)
            try:
                # Build lookup from reported models
                rep_models = {}
                for m in models_list:
                    key = m.get("model")
                    if isinstance(key, str):
                        rep_models[key] = {
                            "sessions": safe_int(m.get("sessions")),
                            "cost": safe_float(m.get("cost")),
                        }

                expected_models = ["claude-3.5-sonnet", "gpt-4o-mini", "gpt-3.5-turbo"]
                presence_ok = all(em in rep_models for em in expected_models)
                if presence_ok:
                    checks["stats_models_presence"] = True

                    # Values match for expected models (cost rounded to 4 decimals)
                    values_ok = True
                    for em in expected_models:
                        gt_cost = gt_models_cost.get(em, 0.0)
                        gt_sessions = gt_models_sessions.get(em, 0)
                        rep = rep_models.get(em, {})
                        rep_cost = rep.get("cost", None)
                        rep_sessions = rep.get("sessions", None)
                        gt_cost_rounded = round(gt_cost, 4)
                        if not (rep_sessions == gt_sessions and nearly_equal(rep_cost, gt_cost_rounded, 1e-6)):
                            values_ok = False
                            break
                    if values_ok:
                        checks["stats_models_values_match"] = True
            except Exception:
                pass

    # Report checks
    if os.path.isfile(report_path):
        checks["has_report_md"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            report_text = ""

        lines = report_text.splitlines()

        # Sections present: KPI Overview, Top Projects by Cost, Model Usage, Recommendations
        headings_needed = ["KPI Overview", "Top Projects by Cost", "Model Usage", "Recommendations"]
        found = {k: False for k in headings_needed}
        for ln in lines:
            s = ln.strip()
            s_no_hash = s.lstrip("#").strip()
            for k in headings_needed:
                if s_no_hash.lower() == k.lower():
                    found[k] = True
                elif s_no_hash.lower().startswith(k.lower()):
                    found[k] = True
        if all(found.values()):
            checks["report_sections_present"] = True

        # Data window line contains min and max dates, and either "Data window" or "Date range"
        data_window_ok = False
        if gt_date_min and gt_date_max:
            for ln in lines:
                s = ln.strip()
                if (("data window" in s.lower()) or ("date range" in s.lower())) and (gt_date_min in s) and (gt_date_max in s):
                    data_window_ok = True
                    break
        else:
            # If no dates, allow line mentioning "Data window" or "Date range" without dates
            for ln in lines:
                s = ln.strip().lower()
                if "data window" in s or "date range" in s:
                    data_window_ok = True
                    break
        if data_window_ok:
            checks["report_data_window_line"] = True

        # Recommendations bullets: at least 3 lines starting with "- " within the Recommendations section
        # Find section indices
        idx_map = find_section_indices(lines, headings_needed)
        rec_idx = idx_map.get("recommendations")
        # Find next section after Recommendations (if any)
        next_idx = None
        if rec_idx is not None:
            later_idxs = [idx for key, idx in idx_map.items() if idx is not None and idx > rec_idx]
            next_idx = min(later_idxs) if later_idxs else None
            bullets_count = check_report_recommendations(lines, rec_idx, next_idx)
            if bullets_count >= 3:
                checks["report_recommendations_bullets"] = True

        # Report mentions top project name "acme-client"
        if "acme-client" in report_text:
            checks["report_mentions_top_project"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if checks["has_stats_json"] or checks["has_report_md"] else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()