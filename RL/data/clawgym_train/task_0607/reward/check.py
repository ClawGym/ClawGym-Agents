import json
import os
import sys
import csv
import re

def parse_simple_yaml(path):
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if ":" not in s:
                    continue
                key, val = s.split(":", 1)
                key = key.strip()
                val = val.strip()
                # remove surrounding quotes
                if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                    val = val[1:-1]
                # try to parse number
                try:
                    if "." in val:
                        num = float(val)
                    else:
                        num = int(val)
                    data[key] = float(num)
                    continue
                except ValueError:
                    pass
                # booleans
                low = val.lower()
                if low in ("true", "false"):
                    data[key] = (low == "true")
                else:
                    data[key] = val
    except Exception:
        return {}
    return data

def read_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None

def safe_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_input_backlog(path):
    by_id = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = row.get("id", "").strip()
                if not rid:
                    continue
                def as_float(k):
                    try:
                        return float(row.get(k, "").strip())
                    except Exception:
                        return None
                by_id[rid] = {
                    "title": row.get("title", "").strip(),
                    "business_value": as_float("business_value"),
                    "user_impact": as_float("user_impact"),
                    "risk": as_float("risk"),
                    "effort": as_float("effort"),
                    "notes": row.get("notes", ""),
                }
        return by_id
    except Exception:
        return None

def compute_score(bv, ui, risk, effort):
    return 0.40 * bv + 0.30 * ui + 0.15 * (10 - risk) + 0.15 * (10 - effort)

def float_eq(a, b, tol):
    return abs(a - b) <= tol

def is_non_increasing(seq, tol=1e-9):
    # Allow ties: each element >= next - tol
    for i in range(len(seq) - 1):
        if seq[i] + tol < seq[i+1]:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # user stories checks
        "stories_file_exists": False,
        "stories_count_between_6_10": False,
        "stories_ids_unique": False,
        "stories_fields_and_types_valid": False,
        "stories_story_format_valid": False,
        "stories_points_values_valid": False,
        "stories_acceptance_criteria_gherkin": False,
        "stories_acceptance_criteria_count_valid": False,

        # backlog checks
        "backlog_file_exists": False,
        "backlog_columns_present": False,
        "backlog_ids_exist_in_input": False,
        "backlog_scores_match_input": False,
        "backlog_sorted_descending": False,
        "backlog_rank_sequence_valid": False,

        # sprint plan checks
        "sprint_file_exists": False,
        "sprint_capacity_matches": False,
        "sprint_ids_reference_valid_stories": False,
        "sprint_ids_no_overlap_duplicates": False,
        "sprint_committed_points_sum_and_limit": False,
        "sprint_stretch_points_sum_and_range": False,
        "sprint_goal_present_string": False,

        # readme
        "readme_exists_nonempty": False,
    }

    # Paths
    stories_path = os.path.join(output_dir, "user_stories.jsonl")
    backlog_input_path = os.path.join(input_dir, "backlog.csv")
    backlog_output_path = os.path.join(output_dir, "backlog_prioritized.csv")
    velocity_yaml_path = os.path.join(input_dir, "velocity.yaml")
    sprint_plan_path = os.path.join(output_dir, "sprint_plan.json")
    readme_path = os.path.join(output_dir, "README.md")

    # Validate user stories
    stories = None
    if os.path.isfile(stories_path):
        checks["stories_file_exists"] = True
        stories = read_jsonl(stories_path)
        if stories is not None and isinstance(stories, list):
            # Count between 6 and 10
            if 6 <= len(stories) <= 10:
                checks["stories_count_between_6_10"] = True

            # Collect IDs and validate uniqueness
            ids = []
            id_re = re.compile(r"^US-\d{3}$")
            fields_valid = True
            story_format_valid_all = True
            points_valid_all = True
            ac_gherkin_all = True
            ac_count_valid_all = True

            allowed_points = {1, 2, 3, 5, 8}

            for item in stories:
                # Required fields
                required_keys = ["id", "title", "persona", "story", "points", "acceptance_criteria", "tags"]
                for k in required_keys:
                    if k not in item:
                        fields_valid = False
                        break
                if not fields_valid:
                    break
                # Types and non-empty basics
                if not isinstance(item["id"], str) or not id_re.match(item["id"]):
                    fields_valid = False
                if not isinstance(item["title"], str) or not item["title"].strip():
                    fields_valid = False
                if not isinstance(item["persona"], str) or not item["persona"].strip():
                    fields_valid = False
                if not isinstance(item["story"], str) or not item["story"].strip():
                    fields_valid = False
                # points must be int in allowed set
                pts = item["points"]
                if isinstance(pts, float) and pts.is_integer():
                    pts = int(pts)
                if not isinstance(pts, int) or pts not in allowed_points:
                    points_valid_all = False
                # acceptance_criteria must be list of non-empty strings
                ac = item["acceptance_criteria"]
                if not isinstance(ac, list) or len(ac) == 0:
                    fields_valid = False
                else:
                    # Each string must contain Given, When, Then (case-insensitive)
                    for s in ac:
                        if not isinstance(s, str) or not s.strip():
                            fields_valid = False
                            break
                        low = s.lower()
                        if ("given" not in low) or ("when" not in low) or ("then" not in low):
                            ac_gherkin_all = False
                    # Count range by points
                    if isinstance(pts, int):
                        n = len(ac)
                        if pts in (1, 2):
                            if not (3 <= n <= 4):
                                ac_count_valid_all = False
                        elif pts in (3, 5):
                            if not (4 <= n <= 6):
                                ac_count_valid_all = False
                        elif pts == 8:
                            if not (5 <= n <= 8):
                                ac_count_valid_all = False
                # tags must be list
                tags = item["tags"]
                if not isinstance(tags, list):
                    fields_valid = False

                # Story format "As a ... I want to ... so that ..."
                story_text = item["story"]
                # Check ordered substrings
                st_low = story_text.lower()
                pos_as = st_low.find("as a ")
                pos_want = st_low.find(" i want to ")
                pos_so = st_low.find(" so that ")
                if not (pos_as != -1 and pos_want != -1 and pos_so != -1 and pos_as < pos_want < pos_so):
                    story_format_valid_all = False

                ids.append(item["id"])

            if fields_valid:
                checks["stories_fields_and_types_valid"] = True
            if story_format_valid_all:
                checks["stories_story_format_valid"] = True
            if points_valid_all:
                checks["stories_points_values_valid"] = True
            if ac_gherkin_all:
                checks["stories_acceptance_criteria_gherkin"] = True
            if ac_count_valid_all:
                checks["stories_acceptance_criteria_count_valid"] = True
            if ids and len(ids) == len(set(ids)):
                checks["stories_ids_unique"] = True

    # Backlog prioritization
    backlog_output_rows = []
    if os.path.isfile(backlog_output_path):
        checks["backlog_file_exists"] = True
        try:
            with open(backlog_output_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                out_fieldnames = [fn.strip() for fn in (reader.fieldnames or [])]
                needed = {"id", "title", "computed_score", "rank"}
                if set(out_fieldnames) >= needed:
                    checks["backlog_columns_present"] = True
                for row in reader:
                    backlog_output_rows.append({
                        "id": row.get("id", "").strip(),
                        "title": row.get("title", "").strip(),
                        "computed_score": row.get("computed_score", "").strip(),
                        "rank": row.get("rank", "").strip(),
                    })
        except Exception:
            backlog_output_rows = []

        # Load input backlog to recompute scores
        input_backlog = load_input_backlog(backlog_input_path)
        if input_backlog is not None and backlog_output_rows:
            # IDs exist in input
            ids_exist = True
            scores_match = True
            scores = []
            # Recompute and compare
            for r in backlog_output_rows:
                rid = r["id"]
                if rid not in input_backlog:
                    ids_exist = False
                    break
                src = input_backlog[rid]
                try:
                    bv = float(src["business_value"])
                    ui = float(src["user_impact"])
                    risk = float(src["risk"])
                    effort = float(src["effort"])
                except Exception:
                    ids_exist = False
                    break
                computed = compute_score(bv, ui, risk, effort)
                try:
                    out_score = float(r["computed_score"])
                except Exception:
                    scores_match = False
                    break
                if not float_eq(out_score, computed, 0.01):
                    scores_match = False
                scores.append(out_score)
            if ids_exist:
                checks["backlog_ids_exist_in_input"] = True
            if scores_match and scores:
                checks["backlog_scores_match_input"] = True
                # sorted strictly descending (ties allowed)
                if is_non_increasing(scores, tol=0.0000001):
                    checks["backlog_sorted_descending"] = True
            # Ranks 1..N in order
            ranks_ok = True
            for idx, r in enumerate(backlog_output_rows, start=1):
                try:
                    rank_val = int(r["rank"])
                    if rank_val != idx:
                        ranks_ok = False
                        break
                except Exception:
                    ranks_ok = False
                    break
            if ranks_ok and backlog_output_rows:
                checks["backlog_rank_sequence_valid"] = True

    # Sprint plan
    sprint_plan = None
    if os.path.isfile(sprint_plan_path):
        checks["sprint_file_exists"] = True
        sprint_plan = safe_read_json(sprint_plan_path)
        if isinstance(sprint_plan, dict):
            # Load velocity.yaml
            vel = parse_simple_yaml(velocity_yaml_path)
            # capacity check
            if "capacity" in sprint_plan and isinstance(sprint_plan["capacity"], (int, float)):
                cap = float(sprint_plan["capacity"])
                if ("average_velocity" in vel and "availability" in vel and
                    isinstance(vel["average_velocity"], (int, float)) and isinstance(vel["availability"], (int, float))):
                    expected_cap = float(vel["average_velocity"]) * float(vel["availability"])
                    if abs(cap - expected_cap) <= 0.5:
                        checks["sprint_capacity_matches"] = True
            # Load stories map for point sums
            stories_map = {}
            if stories is not None:
                for item in stories:
                    pts = item["points"]
                    if isinstance(pts, float) and pts.is_integer():
                        pts = int(pts)
                    stories_map[item["id"]] = int(pts) if isinstance(pts, int) else pts

            # Validate ids reference and uniqueness/no overlap
            ids_ref_valid = False
            no_overlap = False
            committed_sum_ok = False
            stretch_sum_ok = False

            committed_ids = sprint_plan.get("committed_ids")
            stretch_ids = sprint_plan.get("stretch_ids")
            committed_points = sprint_plan.get("committed_points")
            stretch_points = sprint_plan.get("stretch_points")

            if isinstance(committed_ids, list) and isinstance(stretch_ids, list):
                # Check all are strings and exist in stories_map
                def all_valid(arr):
                    return all(isinstance(x, str) and x in stories_map for x in arr)
                if stories_map and all_valid(committed_ids) and all_valid(stretch_ids):
                    ids_ref_valid = True
                # no duplicates and no overlap
                if committed_ids is not None and stretch_ids is not None:
                    set_comm = set(committed_ids)
                    set_str = set(stretch_ids)
                    if len(set_comm) == len(committed_ids) and len(set_str) == len(stretch_ids) and set_comm.isdisjoint(set_str):
                        no_overlap = True

                # Sum points checks if capacity available
                if isinstance(committed_points, (int, float)) and isinstance(stretch_points, (int, float)) and isinstance(sprint_plan.get("capacity"), (int, float)):
                    cap = float(sprint_plan["capacity"])
                    calc_comm = sum(stories_map[i] for i in committed_ids) if ids_ref_valid else None
                    calc_str = sum(stories_map[i] for i in stretch_ids) if ids_ref_valid else None
                    if calc_comm is not None:
                        if float_eq(float(committed_points), float(calc_comm), 0.01) and (float(committed_points) <= 0.85 * cap + 0.5):
                            committed_sum_ok = True
                    if calc_str is not None:
                        if float_eq(float(stretch_points), float(calc_str), 0.01):
                            lower = 0.10 * cap - 0.5
                            upper = 0.15 * cap + 0.5
                            sp = float(stretch_points)
                            if sp >= lower and sp <= upper:
                                stretch_sum_ok = True

            if ids_ref_valid:
                checks["sprint_ids_reference_valid_stories"] = True
            if no_overlap:
                checks["sprint_ids_no_overlap_duplicates"] = True
            if committed_sum_ok:
                checks["sprint_committed_points_sum_and_limit"] = True
            if stretch_sum_ok:
                checks["sprint_stretch_points_sum_and_range"] = True

            # sprint_goal present string
            goal = sprint_plan.get("sprint_goal", None)
            if isinstance(goal, str) and goal.strip():
                checks["sprint_goal_present_string"] = True

    # README
    if os.path.isfile(readme_path):
        try:
            if os.path.getsize(readme_path) > 0:
                checks["readme_exists_nonempty"] = True
        except Exception:
            pass

    # Required output artifacts must exist; otherwise reward must be 0.0
    required_exist = all([
        checks["stories_file_exists"],
        checks["backlog_file_exists"],
        checks["sprint_file_exists"],
        checks["readme_exists_nonempty"],  # also confirms README exists and non-empty
    ])

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    reward = (passed / total_checks) if required_exist else 0.0
    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()