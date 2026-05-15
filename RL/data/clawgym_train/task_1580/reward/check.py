import json
import os
import sys
import csv
from datetime import datetime

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def try_parse_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        # Support both 'Z' and timezone offsets
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
        return True
    except Exception:
        return False

def parse_jsonl(path):
    objs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                objs.append(obj)
            except Exception:
                # invalid json line
                raise
    return objs

def load_json_if_possible(text):
    try:
        return json.loads(text)
    except Exception:
        return None

def count_indent(s: str) -> int:
    count = 0
    for ch in s:
        if ch == ' ':
            count += 1
        elif ch == '\t':
            count += 2
        else:
            break
    return count

def parse_scalar(val: str):
    v = val.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    # try int
    try:
        if v.startswith("0") and v != "0":
            # treat as string to preserve formatting
            return v
        iv = int(v)
        return iv
    except Exception:
        pass
    # try float
    try:
        fv = float(v)
        return fv
    except Exception:
        pass
    return v

def simple_yaml_load(text: str):
    # A minimal YAML parser for simple mappings and lists with indentation
    lines = []
    for raw in text.splitlines():
        # Preserve '#' in values; do not strip comments aggressively
        # Keep raw but ignore pure comment lines
        if raw.strip() == "" or raw.lstrip().startswith("#"):
            continue
        # Normalize tabs to two spaces
        norm = raw.replace("\t", "  ")
        lines.append(norm.rstrip("\n\r"))
    i = 0
    def parse_block(start_idx: int, indent: int):
        nonlocal lines
        i = start_idx
        obj = None
        while i < len(lines):
            line = lines[i]
            curr_indent = count_indent(line)
            if curr_indent < indent:
                break
            stripped = line[curr_indent:]
            if stripped.startswith("- "):
                # List item
                if obj is None:
                    obj = []
                elif not isinstance(obj, list):
                    break
                item_str = stripped[2:]
                # If inline mapping: key: value on same line
                if ":" in item_str:
                    # Could be scalar with colon, but in our rules we expect mapping; try split first occurrence
                    key, after = item_str.split(":", 1)
                    key = key.strip()
                    val = after.strip()
                    d = {}
                    if val != "":
                        d[key] = parse_scalar(val)
                        # parse nested block if any with greater indent
                        j = i + 1
                        if j < len(lines) and count_indent(lines[j]) > curr_indent:
                            nested, j2 = parse_block(j, curr_indent + 2)
                            if isinstance(nested, dict):
                                d.update(nested)
                            i = j2
                        else:
                            i = j
                        obj.append(d)
                        continue
                    else:
                        # key: with nested block for the rest of this item
                        j = i + 1
                        nested, j2 = parse_block(j, curr_indent + 2)
                        d[key] = nested
                        obj.append(d)
                        i = j2
                        continue
                # Scalar list item
                if item_str.strip() == "":
                    # Nested structure directly
                    j = i + 1
                    nested, j2 = parse_block(j, curr_indent + 2)
                    obj.append(nested)
                    i = j2
                else:
                    obj.append(parse_scalar(item_str.strip()))
                    i += 1
            else:
                # Mapping entry
                if obj is None:
                    obj = {}
                elif not isinstance(obj, dict):
                    break
                if ":" not in stripped:
                    # Invalid line, skip
                    i += 1
                    continue
                key, after = stripped.split(":", 1)
                key = key.strip()
                val = after.strip()
                if val == "":
                    # nested block
                    j = i + 1
                    nested, j2 = parse_block(j, curr_indent + 2)
                    obj[key] = nested
                    i = j2
                else:
                    obj[key] = parse_scalar(val)
                    i += 1
        return obj, i
    parsed, _ = parse_block(0, 0)
    return parsed

def load_rules_yaml(path):
    text = read_text(path)
    js = load_json_if_possible(text)
    if js is not None:
        return js
    return simple_yaml_load(text)

def get_phase_order(rules, first_tool):
    # rules["phase_order_by_priority"] may map tool -> list of 3 phase titles
    mapping = rules.get("phase_order_by_priority", {})
    if not isinstance(mapping, dict):
        return None
    order = mapping.get(first_tool)
    if isinstance(order, dict):
        # expect keys phase1, phase2, phase3
        seq = [order.get("phase1"), order.get("phase2"), order.get("phase3")]
        if all(isinstance(x, str) for x in seq):
            return seq
    if isinstance(order, list):
        return order
    # try default
    order = mapping.get("default")
    if isinstance(order, list) and len(order) == 3:
        return order
    return None

def get_phase_def(rules, title):
    defs = rules.get("phase_definitions", {})
    if not isinstance(defs, dict):
        return None
    return defs.get(title)

def get_base_weeks(rules, idx, title):
    dur = rules.get("duration", {})
    base = dur.get("base_weeks")
    if isinstance(base, int):
        return base
    if isinstance(base, dict):
        # Try phase index keys
        key = f"phase{idx+1}"
        if key in base:
            b = base[key]
            if isinstance(b, int):
                return b
        # Try by title
        if title in base and isinstance(base[title], int):
            return base[title]
    # Fallback: sample default
    defaults = {0: 8, 1: 10, 2: 6}
    return defaults.get(idx, 6)

def compute_years_adjust(rules, years):
    dur = rules.get("duration", {})
    reductions = dur.get("reductions", {})
    y = reductions.get("yearsInTesting", {})
    thresholds = y.get("thresholds", [])
    best_adjust = 0
    best_min = None
    if isinstance(thresholds, list):
        for t in thresholds:
            if isinstance(t, dict):
                min_y = t.get("minYears")
                adj = t.get("adjust") if "adjust" in t else t.get("delta")
                if isinstance(min_y, (int, float)) and isinstance(adj, (int, float)):
                    if years >= min_y and (best_min is None or min_y > best_min):
                        best_min = min_y
                        best_adjust = int(adj)
    return int(best_adjust)

def compute_prevexp_adjust(rules, prev_exp):
    dur = rules.get("duration", {})
    reductions = dur.get("reductions", {})
    p = reductions.get("previousPerformanceExperience", {})
    if isinstance(prev_exp, bool):
        # support both 'true' and True keys
        for k in ("true", True):
            if k in p and prev_exp is True:
                try:
                    return int(p[k])
                except Exception:
                    pass
        for k in ("false", False):
            if k in p and prev_exp is False:
                try:
                    return int(p[k])
                except Exception:
                    pass
        # try string keys explicitly
        if "true" in p and prev_exp:
            try:
                return int(p["true"])
            except Exception:
                pass
        if "false" in p and not prev_exp:
            try:
                return int(p["false"])
            except Exception:
                pass
    # If p has numeric fields 'yes'/'no'
    if isinstance(prev_exp, bool):
        key = "true" if prev_exp else "false"
        if key in p:
            try:
                return int(p[key])
            except Exception:
                pass
    return 0

def get_min_weeks(rules):
    dur = rules.get("duration", {})
    for k in ("min_weeks", "min_weeks_per_phase", "min"):
        v = dur.get(k)
        if isinstance(v, int):
            return v
    # default minimum bound
    return 1

def build_expected_for_assessment(assess, rules):
    # Extract data
    ad = assess.get("assessmentData", {})
    exp = ad.get("experience", {}) if isinstance(ad, dict) else {}
    years = exp.get("yearsInTesting", 0)
    prev_perf = exp.get("previousPerformanceExperience", False)
    goals = ad.get("goals", {}) if isinstance(ad, dict) else {}
    priorities = goals.get("priorities", [])
    if not isinstance(priorities, list) or len(priorities) == 0:
        # If no priorities, try default order
        priorities = ["JMeter", "LoadRunner"]
    session_id = ad.get("sessionId") or assess.get("sessionId")
    user_id = assess.get("userId", None)
    # Phase titles based on first priority
    first_tool = priorities[0]
    titles = get_phase_order(rules, first_tool) or []
    # Compute per-phase details
    phases = []
    total_hours = 0
    min_w = get_min_weeks(rules)
    for idx, title in enumerate(titles):
        phase_def = get_phase_def(rules, title) or {}
        topics = phase_def.get("topics", [])
        success = phase_def.get("successCriteria")
        base = get_base_weeks(rules, idx, title)
        years_adj = compute_years_adjust(rules, years if isinstance(years, (int, float)) else 0)
        prev_adj = compute_prevexp_adjust(rules, bool(prev_perf))
        weeks = int(base + years_adj + prev_adj)
        if weeks < min_w:
            weeks = min_w
        est_hours = int(weeks * 5)
        total_hours += est_hours
        phases.append({
            "title": title,
            "duration": f"{weeks} weeks",
            "topics": topics,
            "estimatedHours": est_hours,
            "successCriteria": success
        })
    # Certifications based on priorities
    cert_map = rules.get("certifications_by_tool", {})
    certifications = []
    if isinstance(cert_map, dict):
        seen = set()
        for tool in priorities:
            items = cert_map.get(tool, [])
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    name = it.get("name")
                    vendor = it.get("vendor")
                    recommendedTiming = it.get("recommendedTiming")
                    difficulty = it.get("difficulty")
                    key = (name, vendor, recommendedTiming, difficulty)
                    if key in seen:
                        continue
                    seen.add(key)
                    certifications.append({
                        "name": name,
                        "vendor": vendor,
                        "recommendedTiming": recommendedTiming,
                        "difficulty": difficulty
                    })
    # Resources constants per task requirements
    resources = {
        "courses": 8,
        "tools": 3,
        "practiceProjects": 5,
        "estimatedTotalHours": total_hours
    }
    # Next steps based on phase 1 tool
    next_map = rules.get("next_steps_by_phase1_tool", {})
    next_steps = next_map.get(first_tool, [])
    if not isinstance(next_steps, list):
        next_steps = []
    # Build expected lightweight structure for comparison
    expected = {
        "roadmapId": f"roadmap_{session_id}" if session_id else None,
        "sessionId": session_id,
        "userId": user_id if (user_id is not None) else None,
        "phases": phases,
        "certifications": certifications,
        "resources": resources,
        "nextSteps": next_steps
    }
    return expected

def normalize_cert_list(lst):
    out = []
    for it in lst:
        if not isinstance(it, dict):
            continue
        out.append({
            "name": it.get("name"),
            "vendor": it.get("vendor"),
            "recommendedTiming": it.get("recommendedTiming"),
            "difficulty": it.get("difficulty")
        })
    return out

def load_csv_summary(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        for r in reader:
            rows.append(r)
    return header, rows

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_roadmaps_jsonl": False,
        "has_summary_csv": False,
        "parsed_outputs": False,
        "rules_loaded": False,
        "line_count_matches_inputs": False,
        "roadmap_ids_correct": False,
        "phases_count_and_titles_correct": False,
        "topics_match_rules": False,
        "durations_and_hours_correct": False,
        "success_criteria_correct": False,
        "certifications_correct": False,
        "resources_and_total_hours_correct": False,
        "next_steps_correct": False,
        "jsonl_generatedAt_and_ids_valid": False,
        "csv_header_and_rows_valid": False,
        "csv_consistency_with_json": False
    }

    # Paths
    assessments_path = os.path.join(input_dir, "assessments.jsonl")
    rules_path = os.path.join(input_dir, "rules.yaml")
    roadmaps_path = os.path.join(output_dir, "roadmaps.jsonl")
    summary_path = os.path.join(output_dir, "summary.csv")

    # Existence checks on outputs
    if os.path.isfile(roadmaps_path):
        checks["has_roadmaps_jsonl"] = True
    if os.path.isfile(summary_path):
        checks["has_summary_csv"] = True

    # If outputs missing, baseline reward 0.0
    if not (checks["has_roadmaps_jsonl"] and checks["has_summary_csv"]):
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Load inputs
    try:
        with open(assessments_path, "r", encoding="utf-8") as f:
            input_lines = [ln.strip() for ln in f if ln.strip()]
        input_assessments = [json.loads(ln) for ln in input_lines]
    except Exception:
        # Cannot compute expectations without inputs
        # But do not award positive for just existing outputs
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    try:
        rules = load_rules_yaml(rules_path)
        if isinstance(rules, dict):
            checks["rules_loaded"] = True
    except Exception:
        rules = None

    # Parse outputs
    try:
        output_roadmaps = parse_jsonl(roadmaps_path)
        header, csv_rows = load_csv_summary(summary_path)
        checks["parsed_outputs"] = True
    except Exception:
        # If outputs cannot be parsed, reward 0.0
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Validate line count matches inputs
    if len(output_roadmaps) == len(input_assessments):
        checks["line_count_matches_inputs"] = True

    # Build expected per assessment
    expected_by_session = {}
    if checks["rules_loaded"]:
        for assess in input_assessments:
            ad = assess.get("assessmentData", {})
            session_id = ad.get("sessionId") or assess.get("sessionId")
            expected = build_expected_for_assessment(assess, rules)
            expected_by_session[session_id] = expected

    # Map outputs by sessionId
    outputs_by_session = {}
    all_have_generatedAt = True
    all_ids_ok = True
    all_userid_policy_ok = True
    for obj in output_roadmaps:
        sid = obj.get("sessionId")
        if sid is not None:
            outputs_by_session[sid] = obj
        # generatedAt check
        ga = obj.get("generatedAt")
        if not try_parse_iso8601(ga):
            all_have_generatedAt = False

        # userId policy: must include only if provided in input
        # We'll validate later against input map; for now collect

    # Now validate checks across all assessments
    roadmap_ids_ok = True
    phases_titles_ok = True
    topics_ok = True
    durations_hours_ok = True
    success_ok = True
    certs_ok = True
    resources_ok = True
    next_steps_ok = True
    ids_ok = True
    userid_policy_ok = True

    for assess in input_assessments:
        ad = assess.get("assessmentData", {})
        sid = ad.get("sessionId") or assess.get("sessionId")
        out = outputs_by_session.get(sid)
        exp = expected_by_session.get(sid)
        if out is None or exp is None:
            roadmap_ids_ok = False
            phases_titles_ok = False
            topics_ok = False
            durations_hours_ok = False
            success_ok = False
            certs_ok = False
            resources_ok = False
            next_steps_ok = False
            ids_ok = False
            userid_policy_ok = False
            continue
        # roadmapId
        rid = out.get("roadmapId")
        if rid != exp.get("roadmapId"):
            roadmap_ids_ok = False
        # sessionId
        if out.get("sessionId") != exp.get("sessionId"):
            ids_ok = False
        # userId policy
        input_user_id = assess.get("userId", None)
        if input_user_id is not None:
            # must be present and equal
            if "userId" not in out or out.get("userId") != input_user_id:
                userid_policy_ok = False
        else:
            # should not be present
            if "userId" in out and out.get("userId") is not None:
                userid_policy_ok = False

        # phases
        out_phases = out.get("phases")
        if not isinstance(out_phases, list) or len(out_phases) != 3:
            phases_titles_ok = False
            topics_ok = False
            durations_hours_ok = False
            success_ok = False
        else:
            for idx in range(3):
                op = out_phases[idx]
                ep = exp["phases"][idx] if idx < len(exp["phases"]) else None
                if not isinstance(op, dict) or ep is None:
                    phases_titles_ok = False
                    topics_ok = False
                    durations_hours_ok = False
                    success_ok = False
                    continue
                # title
                if op.get("title") != ep.get("title"):
                    phases_titles_ok = False
                # topics
                if op.get("topics") != ep.get("topics"):
                    topics_ok = False
                # duration string
                if isinstance(op.get("duration"), str):
                    if op.get("duration") != ep.get("duration"):
                        durations_hours_ok = False
                else:
                    durations_hours_ok = False
                # estimatedHours
                if op.get("estimatedHours") != ep.get("estimatedHours"):
                    durations_hours_ok = False
                # successCriteria
                if op.get("successCriteria") != ep.get("successCriteria"):
                    success_ok = False

        # certifications
        out_certs = out.get("certifications", [])
        exp_certs = normalize_cert_list(exp.get("certifications", []))
        out_certs_norm = normalize_cert_list(out_certs)
        if out_certs_norm != exp_certs:
            certs_ok = False

        # resources
        out_resources = out.get("resources", {})
        if not isinstance(out_resources, dict):
            resources_ok = False
        else:
            # constants
            if out_resources.get("courses") != 8 or out_resources.get("tools") != 3 or out_resources.get("practiceProjects") != 5:
                resources_ok = False
            # total hours equals sum
            sum_hours = 0
            if isinstance(out.get("phases"), list):
                for p in out.get("phases"):
                    try:
                        sum_hours += int(p.get("estimatedHours", 0))
                    except Exception:
                        sum_hours += 0
            if out_resources.get("estimatedTotalHours") != sum_hours:
                resources_ok = False

        # next steps
        if out.get("nextSteps") != exp.get("nextSteps"):
            next_steps_ok = False

    # Apply JSONL meta checks
    if not all_have_generatedAt:
        checks["jsonl_generatedAt_and_ids_valid"] = False
    else:
        # also ensure sessionId present for all and matches inputs (already checked ids_ok)
        if ids_ok and userid_policy_ok:
            checks["jsonl_generatedAt_and_ids_valid"] = True

    checks["roadmap_ids_correct"] = roadmap_ids_ok
    checks["phases_count_and_titles_correct"] = phases_titles_ok
    checks["topics_match_rules"] = topics_ok
    checks["durations_and_hours_correct"] = durations_hours_ok
    checks["success_criteria_correct"] = success_ok
    checks["certifications_correct"] = certs_ok
    checks["resources_and_total_hours_correct"] = resources_ok
    checks["next_steps_correct"] = next_steps_ok

    # CSV validations
    header_ok = False
    rows_ok = True
    csv_consistency_ok = True

    expected_header = ["sessionId", "totalEstimatedHours", "phase1Title", "phase2Title", "phase3Title", "certificationsCount"]
    if header == expected_header:
        header_ok = True

    # Build map from JSON roadmaps for consistency checks
    json_info = {}
    for sid, obj in outputs_by_session.items():
        # totalEstimatedHours, titles, cert count
        total_hours = 0
        titles = []
        for p in obj.get("phases", []):
            titles.append(p.get("title"))
            try:
                total_hours += int(p.get("estimatedHours", 0))
            except Exception:
                pass
        cert_count = len(obj.get("certifications", []))
        json_info[sid] = {
            "totalEstimatedHours": total_hours,
            "titles": titles,
            "certificationsCount": cert_count
        }

    # Validate row count equals input assessments
    if len(csv_rows) != len(input_assessments):
        rows_ok = False

    for row in csv_rows:
        # Check required columns present
        for col in expected_header:
            if col not in row:
                rows_ok = False
        sid = row.get("sessionId")
        if sid not in json_info:
            csv_consistency_ok = False
            continue
        # Compare totals and titles and cert count
        try:
            total_est = int(row.get("totalEstimatedHours", "0"))
        except Exception:
            total_est = None
        if total_est != json_info[sid]["totalEstimatedHours"]:
            csv_consistency_ok = False
        # Titles
        titles = json_info[sid]["titles"]
        if len(titles) >= 3:
            if row.get("phase1Title") != titles[0] or row.get("phase2Title") != titles[1] or row.get("phase3Title") != titles[2]:
                csv_consistency_ok = False
        else:
            csv_consistency_ok = False
        # Cert count
        try:
            cc = int(row.get("certificationsCount", ""))
        except Exception:
            cc = None
        if cc != json_info[sid]["certificationsCount"]:
            csv_consistency_ok = False

    checks["csv_header_and_rows_valid"] = header_ok and rows_ok
    checks["csv_consistency_with_json"] = csv_consistency_ok

    # Compute reward as fraction of passed checks that depend on output content
    scored_keys = [
        "has_roadmaps_jsonl",
        "has_summary_csv",
        "parsed_outputs",
        "line_count_matches_inputs",
        "roadmap_ids_correct",
        "phases_count_and_titles_correct",
        "topics_match_rules",
        "durations_and_hours_correct",
        "success_criteria_correct",
        "certifications_correct",
        "resources_and_total_hours_correct",
        "next_steps_correct",
        "jsonl_generatedAt_and_ids_valid",
        "csv_header_and_rows_valid",
        "csv_consistency_with_json"
    ]
    # Do not award for rules_loaded directly (depends on input), and not for reading inputs alone.
    total = len(scored_keys)
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    reward = 0.0
    if checks["has_roadmaps_jsonl"] and checks["has_summary_csv"]:
        reward = passed / total
    else:
        reward = 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()