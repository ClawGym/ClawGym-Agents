import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_feedback_jsonl(path):
    theme_counts = {}
    negative_counts = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                theme = obj.get("theme")
                if theme is None:
                    theme = obj.get("label")
                if theme is None:
                    continue
                theme_l = str(theme).strip().lower()
                theme_counts[theme_l] = theme_counts.get(theme_l, 0) + 1
                sentiment = obj.get("sentiment")
                if sentiment is None:
                    sentiment = obj.get("sentiment_label")
                if sentiment is not None and str(sentiment).strip().lower() == "negative":
                    negative_counts[theme_l] = negative_counts.get(theme_l, 0) + 1
    except Exception:
        pass
    return theme_counts, negative_counts

def parse_competitors(path):
    names = []
    key_gaps = set()
    data = load_json(path)
    if isinstance(data, list):
        for item in data:
            name = item.get("name")
            if isinstance(name, str):
                names.append(name)
            limits = item.get("limitations")
            if isinstance(limits, list):
                for lim in limits:
                    if isinstance(lim, str):
                        key_gaps.add(lim)
    return names, key_gaps

def extract_bullets_under_heading(md_text, heading_name):
    lines = md_text.splitlines()
    bullets = []
    in_section = False
    target = f"## {heading_name}".strip()
    for i, line in enumerate(lines):
        if line.strip() == target:
            in_section = True
            # start collecting from next line
            j = i + 1
            while j < len(lines):
                l = lines[j]
                ls = l.strip()
                if ls.startswith("## ") and not ls.startswith("### "):
                    in_section = False
                    break
                # collect bullets starting with - or *
                m = re.match(r'^\s*[-*]\s+(.*)$', l)
                if m:
                    bullets.append(m.group(1).strip())
                j += 1
            break
    return bullets

def parse_business_goals_yaml(path):
    goals = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r'^\s*-\s+(.*)$', line)
                if m:
                    val = m.group(1).strip()
                    # strip surrounding quotes if present
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    goals.append(val)
    except Exception:
        pass
    return goals

def extract_section(md_text, heading_name):
    # returns content string between "## heading_name" and next "## "
    lines = md_text.splitlines()
    content_lines = []
    in_section = False
    target = f"## {heading_name}".strip()
    for i, line in enumerate(lines):
        if line.strip() == target:
            in_section = True
            # start taking from next line
            for j in range(i+1, len(lines)):
                l2 = lines[j]
                ls2 = l2.strip()
                if ls2.startswith("## ") and not ls2.startswith("### "):
                    in_section = False
                    break
                content_lines.append(l2)
            break
    return "\n".join(content_lines)

def extract_subsection(section_text, subheading_name):
    # within a section text, find "### subheading_name" and return its block until next ### or ## (but section_text should contain no new ##)
    lines = section_text.splitlines()
    content_lines = []
    in_sub = False
    target = f"### {subheading_name}".strip()
    for i, line in enumerate(lines):
        if line.strip() == target:
            in_sub = True
            for j in range(i+1, len(lines)):
                l2 = lines[j]
                ls2 = l2.strip()
                if ls2.startswith("### ") or ls2.startswith("## "):
                    in_sub = False
                    break
                content_lines.append(l2)
            break
    return "\n".join(content_lines)

def count_user_stories(section_text):
    cnt = 0
    for line in section_text.splitlines():
        if line.strip().startswith("- As a "):
            cnt += 1
    return cnt

def has_bullet(section_text):
    for line in section_text.splitlines():
        if re.match(r'^\s*[-*]\s+', line):
            return True
    return False

def headings_present(md_text, headings):
    present = True
    for h in headings:
        if h not in md_text:
            present = False
            break
    return present

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # pm_pack.json checks
        "pm_pack_exists": False,
        "pm_pack_valid_json": False,
        "task_type_ok": False,
        "theme_counts_ok": False,
        "top_negative_themes_ok": False,
        "competitors_list_ok": False,
        "key_gaps_list_ok": False,
        "meeting_decisions_ok": False,
        "open_questions_ok": False,
        "prd_outline_ok": False,
        "success_metrics_ok": False,
        "next_step_ok": False,
        # PRD markdown checks
        "prd_exists": False,
        "headings_ok": False,
        "requirements_subsections_ok": False,
        "must_should_could_bullets_ok": False,
        "user_stories_count_ok": False,
        "prd_competitors_ok": False,
        "timeline_date_ok": False,
        "prd_open_questions_ok": False,
        "success_metrics_targets_ok": False,
    }

    # Load inputs
    feedback_path = os.path.join(input_dir, "feedback.jsonl")
    competitors_path = os.path.join(input_dir, "competitors.json")
    meeting_notes_path = os.path.join(input_dir, "meeting_notes.md")
    business_goals_path = os.path.join(input_dir, "business_goals.yaml")

    theme_counts_expected, negative_counts_expected = parse_feedback_jsonl(feedback_path)
    # Prepare top negative themes expected
    neg_sorted = sorted(negative_counts_expected.items(), key=lambda kv: (-kv[1], kv[0]))
    top2_negative_expected = [k for k, v in neg_sorted[:2]]

    competitor_names_expected, key_gaps_expected = parse_competitors(competitors_path)

    meeting_text = read_text(meeting_notes_path) or ""
    decisions_expected = extract_bullets_under_heading(meeting_text, "Decisions")
    open_questions_expected = extract_bullets_under_heading(meeting_text, "Open Questions")

    business_goals_expected = parse_business_goals_yaml(business_goals_path)

    # Check pm_pack.json
    pm_pack_path = os.path.join(output_dir, "pm_pack.json")
    pm_pack = None
    if os.path.isfile(pm_pack_path):
        checks["pm_pack_exists"] = True
        pm_pack = load_json(pm_pack_path)
        if isinstance(pm_pack, dict):
            checks["pm_pack_valid_json"] = True

    if checks["pm_pack_valid_json"]:
        # task_type
        if pm_pack.get("task_type") == "PRD drafting":
            checks["task_type_ok"] = True

        # feedback_synthesis
        fs = pm_pack.get("feedback_synthesis")
        if isinstance(fs, dict):
            # theme_counts
            tc = fs.get("theme_counts")
            if isinstance(tc, dict):
                # normalize keys to lowercase for comparison
                tc_norm = {str(k).strip().lower(): int(v) for k, v in tc.items() if isinstance(v, int) or (isinstance(v, str) and v.isdigit())}
                if tc_norm == theme_counts_expected:
                    checks["theme_counts_ok"] = True
            # top_negative_themes
            tnt = fs.get("top_negative_themes")
            if isinstance(tnt, list):
                tnt_norm = [str(x).strip().lower() for x in tnt]
                if tnt_norm == top2_negative_expected:
                    checks["top_negative_themes_ok"] = True

        # competitor_insights
        ci = pm_pack.get("competitor_insights")
        if isinstance(ci, dict):
            comp_list = ci.get("competitors")
            gaps_list = ci.get("key_gaps")
            # competitors: must include all expected names (order not enforced)
            if isinstance(comp_list, list):
                rep = set([str(x) for x in comp_list])
                if set(competitor_names_expected).issubset(rep):
                    checks["competitors_list_ok"] = True
            # key_gaps: must include all unique limitations (order not enforced)
            if isinstance(gaps_list, list):
                repg = set([str(x) for x in gaps_list])
                if key_gaps_expected.issubset(repg):
                    checks["key_gaps_list_ok"] = True

        # meeting_decisions
        md_list = pm_pack.get("meeting_decisions")
        if isinstance(md_list, list):
            rep_md = set([str(x).strip() for x in md_list])
            exp_md = set([s.strip() for s in decisions_expected])
            if exp_md and exp_md.issubset(rep_md):
                checks["meeting_decisions_ok"] = True

        # open_questions: exactly equal to expected set and count
        oq_list = pm_pack.get("open_questions")
        if isinstance(oq_list, list):
            rep_oq = [str(x).strip() for x in oq_list]
            exp_oq = [s.strip() for s in open_questions_expected]
            if len(rep_oq) == len(exp_oq) and set(rep_oq) == set(exp_oq):
                checks["open_questions_ok"] = True

        # prd_outline
        prd_outline = pm_pack.get("prd_outline")
        required_sections = ["Problem","Goals","Non-Goals","User Stories","Requirements","Success Metrics","Open Questions","Timeline","Competitor Comparison","Next Steps"]
        if isinstance(prd_outline, dict):
            secs = prd_outline.get("sections")
            if isinstance(secs, list) and secs == required_sections:
                checks["prd_outline_ok"] = True

        # success_metrics includes both business goals
        sm_list = pm_pack.get("success_metrics")
        if isinstance(sm_list, list):
            rep_sm = set([str(x).strip() for x in sm_list])
            exp_sm = set([s.strip() for s in business_goals_expected])
            if exp_sm and exp_sm.issubset(rep_sm):
                checks["success_metrics_ok"] = True

        # recommended_next_step length >= 10
        rns = pm_pack.get("recommended_next_step")
        if isinstance(rns, str) and len(rns.strip()) >= 10:
            checks["next_step_ok"] = True

    # Check offline_mode_prd.md
    prd_path = os.path.join(output_dir, "offline_mode_prd.md")
    prd_text = None
    if os.path.isfile(prd_path):
        prd_text = read_text(prd_path)
        if isinstance(prd_text, str):
            checks["prd_exists"] = True

    if checks["prd_exists"]:
        # Headings presence
        required_headings = [
            "## Problem",
            "## Goals",
            "## Non-Goals",
            "## User Stories",
            "## Requirements",
            "### MUST",
            "### SHOULD",
            "### COULD",
            "## Success Metrics",
            "## Open Questions",
            "## Timeline",
            "## Competitor Comparison",
            "## Next Steps",
        ]
        if headings_present(prd_text, required_headings):
            checks["headings_ok"] = True

        # Requirements subsections present specifically within Requirements section
        req_section = extract_section(prd_text, "Requirements")
        must_sub = extract_subsection(req_section, "MUST")
        should_sub = extract_subsection(req_section, "SHOULD")
        could_sub = extract_subsection(req_section, "COULD")
        if must_sub.strip() != "" and should_sub.strip() != "" and could_sub.strip() != "":
            checks["requirements_subsections_ok"] = True

        # MUST/SHOULD/COULD each has at least one bullet
        if has_bullet(must_sub) and has_bullet(should_sub) and has_bullet(could_sub):
            checks["must_should_could_bullets_ok"] = True

        # User stories count
        us_section = extract_section(prd_text, "User Stories")
        if count_user_stories(us_section) >= 3:
            checks["user_stories_count_ok"] = True

        # Competitor names mentioned anywhere
        all_present = True
        for name in competitor_names_expected:
            if name not in prd_text:
                all_present = False
                break
        if all_present and competitor_names_expected:
            checks["prd_competitors_ok"] = True

        # Timeline: exact date string in Timeline section
        timeline_section = extract_section(prd_text, "Timeline")
        if "2026-06-30" in timeline_section:
            checks["timeline_date_ok"] = True

        # Open Questions present verbatim in Open Questions section
        oq_section = extract_section(prd_text, "Open Questions")
        oq_ok = True
        for q in open_questions_expected:
            if q not in oq_section:
                oq_ok = False
                break
        if oq_ok and open_questions_expected:
            checks["prd_open_questions_ok"] = True

        # Success metrics targets in Success Metrics section
        sm_section = extract_section(prd_text, "Success Metrics")
        if ("90-day retention" in sm_section) and ("8%" in sm_section) and ("12%" in sm_section):
            checks["success_metrics_targets_ok"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure exactly 0.0 if no outputs exist or missing required artifacts
    # This is already enforced as no checks would pass, but keep explicit baseline check
    output_exists = os.path.isfile(pm_pack_path) or os.path.isfile(prd_path)
    if not output_exists:
        reward = 0.0

    # Print JSON with "reward" first
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()