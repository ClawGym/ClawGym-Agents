import json
import os
import sys
import csv
import re

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

checks = {
    "learning_brief_ok": False,
    "sub_skill_map_ok": False,
    "resources_csv_ok": False,
    "learning_protocol_ok": False,
    "spaced_repetition_ok": False,
    "project_plan_ok": False,
    "deliberate_practice_ok": False,
    "knowledge_notes_ok": False,
    "weekly_review_template_ok": False,
    "quality_score_ok": False,
}

def load_yaml(path):
    try:
        import yaml  # type: ignore
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None

def is_int(n):
    try:
        int(n)
        return True
    except Exception:
        return False

def to_float(x):
    try:
        return float(x)
    except Exception:
        return None

# 1) learning_brief.yaml
try:
    lb_path = os.path.join(output_dir, "learning_brief.yaml")
    if os.path.isfile(lb_path):
        data = load_yaml(lb_path)
        if isinstance(data, dict) and "learning_project" in data and isinstance(data["learning_project"], dict):
            lp = data["learning_project"]
            required_keys = [
                "skill",
                "why",
                "target_level",
                "success_looks_like",
                "deadline",
                "hours_per_week",
                "total_estimated_hours",
                "current_level",
                "related_skills",
                "blockers",
                "accountability",
            ]
            presence = all(k in lp for k in required_keys)
            list_types_ok = isinstance(lp.get("related_skills"), (list, tuple)) and isinstance(lp.get("blockers"), (list, tuple))
            if presence and list_types_ok:
                checks["learning_brief_ok"] = True
except Exception:
    pass

# 2) sub_skill_map.yaml
try:
    ssm_path = os.path.join(output_dir, "sub_skill_map.yaml")
    if os.path.isfile(ssm_path):
        data = load_yaml(ssm_path)
        ok = True
        if not (isinstance(data, dict) and "sub_skill_map" in data):
            ok = False
        else:
            sm = data["sub_skill_map"]
            if not (isinstance(sm, dict) and "skill" in sm and "sub_skills" in sm):
                ok = False
            else:
                subs = sm["sub_skills"]
                if not (isinstance(subs, list) and len(subs) >= 10):
                    ok = False
                else:
                    names = set()
                    for item in subs:
                        if not isinstance(item, dict):
                            ok = False
                            break
                        req_fields = ["name", "importance", "frequency", "score", "depends_on", "status"]
                        if not all(k in item for k in req_fields):
                            ok = False
                            break
                        name = item.get("name")
                        importance = item.get("importance")
                        frequency = item.get("frequency")
                        score = item.get("score")
                        depends_on = item.get("depends_on")
                        status = item.get("status")
                        # Type checks
                        if not isinstance(name, str) or not isinstance(status, str) or not isinstance(depends_on, list):
                            ok = False
                            break
                        # Importance and frequency range 1..5
                        try:
                            imp_i = int(importance)
                            freq_i = int(frequency)
                        except Exception:
                            ok = False
                            break
                        if not (1 <= imp_i <= 5 and 1 <= freq_i <= 5):
                            ok = False
                            break
                        # score correctness
                        try:
                            sc = float(score)
                        except Exception:
                            ok = False
                            break
                        if abs(sc - (imp_i * freq_i)) > 1e-6:
                            ok = False
                            break
                        names.add(name)
                    # critical_path check
                    cp = sm.get("critical_path")
                    if not (isinstance(cp, list) and 3 <= len(cp) <= 5):
                        ok = False
                    else:
                        for cp_name in cp:
                            if cp_name not in names:
                                ok = False
                                break
        if ok:
            checks["sub_skill_map_ok"] = True
except Exception:
    pass

# 3) resources.csv
try:
    res_path = os.path.join(output_dir, "resources.csv")
    if os.path.isfile(res_path):
        with open(res_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        header = ["type","title","author","year","practice_ratio_pct","credibility_score","recency_score","practice_ratio_score","progression_score","community_score","weighted_total"]
        ok = True
        if not rows:
            ok = False
        else:
            if rows[0] != header:
                ok = False
            else:
                body = rows[1:]
                if len(body) != 3:
                    ok = False
                else:
                    types = set()
                    for r in body:
                        if len(r) != len(header):
                            ok = False
                            break
                        rdict = dict(zip(header, r))
                        t = rdict["type"]
                        types.add(t)
                        # year numeric
                        if not is_int(rdict["year"]):
                            ok = False
                            break
                        # scores numeric 0..10
                        score_fields = ["credibility_score","recency_score","practice_ratio_score","progression_score","community_score"]
                        vals = []
                        for sf in score_fields:
                            v = to_float(rdict[sf])
                            if v is None or v < 0 or v > 10:
                                ok = False
                                break
                            vals.append(v)
                        if not ok:
                            break
                        # recompute weighted_total
                        computed = vals[0]*2 + vals[1]*1.5 + vals[2]*2 + vals[3]*1.5 + vals[4]*1.0
                        wt = to_float(rdict["weighted_total"])
                        if wt is None or wt > 80 + 1e-6 or abs(computed - wt) > 0.5:
                            ok = False
                            break
                    if ok and types != {"primary","alternative","practice"}:
                        ok = False
        if ok:
            checks["resources_csv_ok"] = True
except Exception:
    pass

# 4) learning_protocol.md
try:
    lp_path = os.path.join(output_dir, "learning_protocol.md")
    if os.path.isfile(lp_path):
        with open(lp_path, "r", encoding="utf-8") as f:
            txt = f.read()
        ok = True
        # Check sessions
        if not all(s in txt for s in ["Session 1", "Session 2", "Session 3"]):
            ok = False
        # Headings count
        headings = ["ABSORB","RETRIEVE","PRACTICE","DEBRIEF"]
        for h in headings:
            if len(re.findall(r"\b" + re.escape(h) + r"\b", txt)) < 3:
                ok = False
                break
        if ok:
            checks["learning_protocol_ok"] = True
except Exception:
    pass

# 5) spaced_repetition.json
try:
    sr_path = os.path.join(output_dir, "spaced_repetition.json")
    if os.path.isfile(sr_path):
        with open(sr_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ok = True
        if not isinstance(data, dict):
            ok = False
        else:
            ss = data.get("spacing_schedule")
            fr = data.get("flashcard_design_rules")
            if not (isinstance(ss, list) and len(ss) == 6):
                ok = False
            else:
                expected_days = {1:1, 2:3, 3:7, 4:14, 5:30, 6:90}
                # Build mapping
                mapping = {}
                for item in ss:
                    if not isinstance(item, dict):
                        ok = False
                        break
                    rn = item.get("review_number")
                    ad = item.get("after_days")
                    if not (isinstance(rn, int) and isinstance(ad, int)):
                        ok = False
                        break
                    mapping[rn] = ad
                if ok:
                    if set(mapping.keys()) != set(expected_days.keys()):
                        ok = False
                    else:
                        for k, v in expected_days.items():
                            if mapping.get(k) != v:
                                ok = False
                                break
            if ok:
                if not (isinstance(fr, list) and len(fr) >= 6):
                    ok = False
        if ok:
            checks["spaced_repetition_ok"] = True
except Exception:
    pass

# 6) project_plan.yaml
try:
    pp_path = os.path.join(output_dir, "project_plan.yaml")
    if os.path.isfile(pp_path):
        data = load_yaml(pp_path)
        ok = True
        if not (isinstance(data, dict) and "learning_project" in data and isinstance(data["learning_project"], dict)):
            ok = False
        else:
            lp = data["learning_project"]
            req = ["name","target_skill","secondary_skills","scope","stretch_goals","deadline","public","milestones"]
            if not all(k in lp for k in req):
                ok = False
            else:
                if not (isinstance(lp.get("secondary_skills"), list) and isinstance(lp.get("stretch_goals"), list)):
                    ok = False
                if not isinstance(lp.get("milestones"), dict):
                    ok = False
                else:
                    ms = lp["milestones"]
                    if not all(k in ms for k in ["week_1","week_2","week_3","week_4"]):
                        ok = False
        # check "30%" mention in file text
        with open(pp_path, "r", encoding="utf-8") as f:
            txt = f.read()
        if "30%" not in txt:
            ok = False
        if ok:
            checks["project_plan_ok"] = True
except Exception:
    pass

# 7) deliberate_practice.md
try:
    dp_path = os.path.join(output_dir, "deliberate_practice.md")
    if os.path.isfile(dp_path):
        with open(dp_path, "r", encoding="utf-8") as f:
            txt = f.read()
        up = txt.upper()
        needed = ["IDENTIFY", "DESIGN", "EXECUTE", "GET FEEDBACK", "ADJUST"]
        ok = all(s in up for s in needed)
        if ok:
            checks["deliberate_practice_ok"] = True
except Exception:
    pass

# 8) knowledge_notes.jsonl
try:
    kn_path = os.path.join(output_dir, "knowledge_notes.jsonl")
    if os.path.isfile(kn_path):
        with open(kn_path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
        non_empty = [ln for ln in lines if ln.strip() != ""]
        ok = True
        if len(non_empty) < 3:
            ok = False
        else:
            for ln in non_empty:
                try:
                    obj = json.loads(ln)
                except Exception:
                    ok = False
                    break
                fields = ["id","title","source","explanation","example","connections","application","questions"]
                if not all(k in obj for k in fields):
                    ok = False
                    break
                if not isinstance(obj.get("connections"), list) or len(obj.get("connections")) < 2:
                    ok = False
                    break
                # Basic non-empty checks for string fields
                str_fields = ["id","title","source","explanation","example","application","questions"]
                for sf in str_fields:
                    if not isinstance(obj.get(sf), str) or obj.get(sf).strip() == "":
                        ok = False
                        break
                if not ok:
                    break
        if ok:
            checks["knowledge_notes_ok"] = True
except Exception:
    pass

# 9) weekly_review_template.yaml
try:
    wr_path = os.path.join(output_dir, "weekly_review_template.yaml")
    if os.path.isfile(wr_path):
        data = load_yaml(wr_path)
        ok = True
        if not (isinstance(data, dict) and "weekly_review" in data and isinstance(data["weekly_review"], dict)):
            ok = False
        else:
            wr = data["weekly_review"]
            req = ["week_of","hours_logged","sessions_completed","sub_skills_progressed","biggest_win","biggest_struggle","next_week_focus","difficulty_rating","enjoyment_rating","confidence_delta"]
            if not all(k in wr for k in req):
                ok = False
        if ok:
            checks["weekly_review_template_ok"] = True
except Exception:
    pass

# 10) quality_score.yaml
try:
    qs_path = os.path.join(output_dir, "quality_score.yaml")
    if os.path.isfile(qs_path):
        data = load_yaml(qs_path)
        ok = True
        dims = ["clarity","decomposition","active_methods","spaced_practice","feedback_loop","progress_tracking","sustainability"]
        if not isinstance(data, dict):
            ok = False
        else:
            # Each dimension has weight and score
            weighted_sum = 0.0
            for d in dims:
                if d not in data or not isinstance(data[d], dict):
                    ok = False
                    break
                item = data[d]
                if "weight" not in item or "score" not in item:
                    ok = False
                    break
                try:
                    w = float(item["weight"])
                    s = float(item["score"])
                except Exception:
                    ok = False
                    break
                weighted_sum += w * s
            if ok:
                wt = data.get("weighted_total")
                nt = data.get("normalized_total")
                try:
                    wt_val = float(wt)
                    nt_val = float(nt)
                except Exception:
                    ok = False
                else:
                    if abs(wt_val - weighted_sum) > 0.5:
                        ok = False
                    expected_nt = (wt_val / 115.0) * 100.0
                    if abs(nt_val - expected_nt) > 0.5:
                        ok = False
                    if not (0.0 <= nt_val <= 100.0):
                        ok = False
        if ok:
            checks["quality_score_ok"] = True
except Exception:
    pass

# Compute reward as fraction of passed checks (no-op baseline yields 0.0)
passed = sum(1 for v in checks.values() if v)
total = len(checks)
reward = (passed / total) if total > 0 else 0.0
# Clamp between 0 and 1
if reward < 0:
    reward = 0.0
if reward > 1:
    reward = 1.0

result = {"reward": reward}
result.update(checks)
print(json.dumps(result))