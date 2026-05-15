import json
import os
import sys
import re
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_jsonl(path):
    objs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    objs.append(json.loads(s))
                except Exception:
                    return None
        return objs
    except Exception:
        return None

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None

def is_boolean_true(val):
    if isinstance(val, bool):
        return val is True
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() == "true"
    return False

def count_bullet_items(lines):
    # Count bullet/numbered list items
    count = 0
    bullet_re = re.compile(r'^\s*([-*]|\d+\.)\s+')
    for ln in lines:
        if bullet_re.match(ln):
            count += 1
    return count

def find_heading_indices(lines, targets):
    # For each target title, find the first line index where it appears as a heading-like line
    indices = []
    for title in targets:
        idx_found = -1
        pattern = re.compile(r'^\s*#{0,6}\s*' + re.escape(title) + r'\s*:?\s*$', re.IGNORECASE)
        for i, ln in enumerate(lines):
            if pattern.match(ln):
                idx_found = i
                break
        indices.append(idx_found)
    return indices

def check_table_sections_with_scores(text, sections):
    # For each section name, ensure there is a line containing the name and a score like X/10 in the same line
    lines = text.splitlines()
    ok = True
    for sec in sections:
        found = False
        for ln in lines:
            if sec in ln and re.search(r'(\b\d{1,2}\s*/\s*10\b)|(/10\b)', ln):
                found = True
                break
        if not found:
            ok = False
            break
    return ok

def get_last_nonempty_line(lines):
    for ln in reversed(lines):
        if ln.strip():
            return ln
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # 1) fit_assessment.json
        "fit_json_exists": False,
        "fit_json_valid_schema": False,
        "fit_json_reasons_len_ge_3": False,
        "fit_json_risks_len_ge_2": False,

        # 2) executive_summary.md
        "exec_summary_exists": False,
        "exec_summary_sections_order": False,

        # 3) narrative_short.txt
        "narrative_short_exists": False,
        "narrative_short_name_and_len": False,

        # 4) ranked_investors.csv
        "ranked_csv_exists": False,
        "ranked_csv_header_exact": False,
        "ranked_csv_min_rows": False,
        "ranked_csv_sorted_desc": False,
        "ranked_csv_ai_and_devtools": False,
        "ranked_csv_initial_batch_count": False,
        "ranked_csv_will_wang_rule": False,

        # 5) investor_emails.jsonl
        "emails_exists": False,
        "emails_min_5": False,
        "emails_valid_schema_and_content": False,

        # 6) outreach_plan.md
        "outreach_plan_exists": False,
        "outreach_plan_steps_verbatim": False,
        "outreach_plan_metrics_3_to_5": False,

        # 7) deck_review.md
        "deck_review_exists": False,
        "deck_review_title_and_scoreline": False,
        "deck_review_table_10_sections": False,
        "deck_review_required_sections": False,
        "deck_review_questions_ge_4": False,
    }

    # 1) fit_assessment.json
    fit_path = os.path.join(output_dir, "fit_assessment.json")
    if os.path.isfile(fit_path):
        checks["fit_json_exists"] = True
        fit = read_json(fit_path)
        if isinstance(fit, dict):
            required_keys = ["startup_name", "venture_scale_fit", "reasons", "risks", "recommendation"]
            has_keys = all(k in fit for k in required_keys)
            types_ok = (
                isinstance(fit.get("startup_name"), str) and
                isinstance(fit.get("venture_scale_fit"), bool) and
                isinstance(fit.get("reasons"), list) and
                isinstance(fit.get("risks"), list) and
                isinstance(fit.get("recommendation"), str)
            )
            if has_keys and types_ok:
                checks["fit_json_valid_schema"] = True
                # lengths
                if isinstance(fit.get("reasons"), list) and len(fit.get("reasons")) >= 3:
                    checks["fit_json_reasons_len_ge_3"] = True
                if isinstance(fit.get("risks"), list) and len(fit.get("risks")) >= 2:
                    checks["fit_json_risks_len_ge_2"] = True

    # 2) executive_summary.md
    exec_path = os.path.join(output_dir, "executive_summary.md")
    if os.path.isfile(exec_path):
        checks["exec_summary_exists"] = True
        exec_txt = read_text(exec_path) or ""
        lines = exec_txt.splitlines()
        titles = [
            "Problem",
            "Solution",
            "Technology Advantage",
            "Market Opportunity",
            "Traction",
            "Long-Term Vision",
        ]
        idxs = find_heading_indices(lines, titles)
        if all(i >= 0 for i in idxs):
            # ensure strictly increasing order
            ordered = all(idxs[i] < idxs[i+1] for i in range(len(idxs)-1))
            if ordered:
                checks["exec_summary_sections_order"] = True

    # 3) narrative_short.txt
    ns_path = os.path.join(output_dir, "narrative_short.txt")
    if os.path.isfile(ns_path):
        checks["narrative_short_exists"] = True
        ns_txt = read_text(ns_path) or ""
        words = re.findall(r'\S+', ns_txt)
        has_name = "foundryflow" in ns_txt.lower()
        if has_name and len(words) <= 200:
            checks["narrative_short_name_and_len"] = True

    # 4) ranked_investors.csv
    ranked_path = os.path.join(output_dir, "ranked_investors.csv")
    if os.path.isfile(ranked_path):
        checks["ranked_csv_exists"] = True
        header, rows = read_csv_rows(ranked_path)
        expected_header = ["investor_name","firm","sector_focus","stage_focus","relevance_score","early_stage_frequency","founder_reputation","network_amplification","initial_batch"]
        if header == expected_header:
            checks["ranked_csv_header_exact"] = True
        if isinstance(rows, list) and len(rows) >= 10:
            checks["ranked_csv_min_rows"] = True

        # Only proceed with further checks if we have rows
        if isinstance(rows, list) and rows:
            # sorted descending by relevance_score
            scores = []
            sortable = True
            for r in rows:
                try:
                    scores.append(float(r.get("relevance_score", "")))
                except Exception:
                    sortable = False
                    break
            if sortable:
                is_desc = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
                if is_desc:
                    checks["ranked_csv_sorted_desc"] = True

            # sector occurrences
            ai_count = 0
            devtools_count = 0
            for r in rows:
                sec = (r.get("sector_focus") or "")
                s = sec.lower()
                if "ai" in s:
                    ai_count += 1
                if "developer tools" in s:
                    devtools_count += 1
            if ai_count >= 2 and devtools_count >= 1:
                checks["ranked_csv_ai_and_devtools"] = True

            # initial batch count exactly 3-5 set to true
            true_count = 0
            for r in rows:
                if is_boolean_true(r.get("initial_batch")):
                    true_count += 1
            if 3 <= true_count <= 5:
                checks["ranked_csv_initial_batch_count"] = True

            # Will Wang rule if present
            will_rows = [r for r in rows if (r.get("investor_name") or "").strip() == "Will Wang" and (r.get("firm") or "").strip() == "BAI Capital"]
            if will_rows:
                # If present, must have initial_batch true
                if any(is_boolean_true(r.get("initial_batch")) for r in will_rows):
                    checks["ranked_csv_will_wang_rule"] = True
            else:
                # If not present, the condition is vacuously satisfied as per spec "If present ... must ..."
                checks["ranked_csv_will_wang_rule"] = True

    # 5) investor_emails.jsonl
    emails_path = os.path.join(output_dir, "investor_emails.jsonl")
    if os.path.isfile(emails_path):
        checks["emails_exists"] = True
        objs = read_jsonl(emails_path)
        if isinstance(objs, list) and len(objs) >= 5:
            checks["emails_min_5"] = True
        # Validate schema and content
        if isinstance(objs, list) and objs:
            all_ok = True
            subj_required = "[FoundryFlow] — Category-Defining Opportunity"
            for obj in objs:
                if not isinstance(obj, dict):
                    all_ok = False
                    break
                required_keys = ["investor_name","investor_firm","to_email","subject","body"]
                if not all(k in obj for k in required_keys):
                    all_ok = False
                    break
                if obj.get("subject") != subj_required:
                    all_ok = False
                    break
                body = (obj.get("body") or "")
                if "Key highlights:" not in body:
                    all_ok = False
                    break
                low = body.lower()
                for kw in ["traction", "technology", "market"]:
                    if kw not in low:
                        all_ok = False
                        break
                if not all_ok:
                    break
            if all_ok:
                checks["emails_valid_schema_and_content"] = True

    # 6) outreach_plan.md
    outreach_path = os.path.join(output_dir, "outreach_plan.md")
    if os.path.isfile(outreach_path):
        checks["outreach_plan_exists"] = True
        otxt = read_text(outreach_path) or ""
        olines = otxt.splitlines()
        steps = [
            "Step 1 — Send pitch deck to a small group of high-signal investors",
            "Step 2 — Collect feedback",
            "Step 3 — Improve narrative",
            "Step 4 — Expand investor outreach",
        ]
        present = [any(line.strip() == s for line in olines) for s in steps]
        if all(present):
            checks["outreach_plan_steps_verbatim"] = True
            # Count metrics listed after the last step line
            last_step_idx = max(i for i, line in enumerate(olines) if line.strip() in steps)
            after_lines = olines[last_step_idx+1:]
            metrics_count = count_bullet_items(after_lines)
            if 3 <= metrics_count <= 5:
                checks["outreach_plan_metrics_3_to_5"] = True

    # 7) deck_review.md
    review_path = os.path.join(output_dir, "deck_review.md")
    if os.path.isfile(review_path):
        checks["deck_review_exists"] = True
        rtxt = read_text(review_path) or ""
        rlines = rtxt.splitlines()
        # Title line starting with "## Pitch Deck Review: " and containing the startup name
        title_ok = False
        for ln in rlines:
            if ln.startswith("## Pitch Deck Review: ") and ("FoundryFlow" in ln):
                title_ok = True
                break
        # Overall Score line pattern
        score_ok = False
        score_re = re.compile(r'^Overall Score:\s*\d+\s*/100\s*$', re.IGNORECASE)
        for ln in rlines:
            if score_re.match(ln.strip()):
                score_ok = True
                break
        if title_ok and score_ok:
            checks["deck_review_title_and_scoreline"] = True

        # Table with 10 sections each with score out of 10
        sections_10 = ["Problem","Solution","Market Size","Business Model","Traction","Team","Competition","Financials","Ask","Story/Design"]
        if check_table_sections_with_scores(rtxt, sections_10):
            checks["deck_review_table_10_sections"] = True

        # Required sections: Strengths, Critical Fixes (Do Before Sending), Nice to Have, Investor Questions You'll Get
        req_heads = ["Strengths","Critical Fixes (Do Before Sending)","Nice to Have","Investor Questions You'll Get"]
        have_all = True
        head_indices = {}
        for h in req_heads:
            idx = -1
            for i, ln in enumerate(rlines):
                if re.match(r'^\s*#{0,6}\s*' + re.escape(h) + r'\s*$', ln):
                    idx = i
                    break
            if idx == -1:
                have_all = False
                break
            head_indices[h] = idx
        if have_all:
            checks["deck_review_required_sections"] = True
            # Count >= 4 questions in the "Investor Questions You'll Get" section
            q_idx = head_indices["Investor Questions You'll Get"]
            # Find next heading index after q_idx
            next_idx = len(rlines)
            for i in range(q_idx+1, len(rlines)):
                if re.match(r'^\s*#{1,6}\s+\S+', rlines[i]):
                    next_idx = i
                    break
            q_lines = rlines[q_idx+1:next_idx]
            # Questions: lines ending with '?' or bullet lines containing '?'
            q_count = 0
            for ln in q_lines:
                if ln.strip().endswith("?"):
                    q_count += 1
                else:
                    if re.match(r'^\s*([-*]|\d+\.)\s+.*\?\s*$', ln):
                        q_count += 1
            if q_count >= 4:
                checks["deck_review_questions_ge_4"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline yields 0.0: if no outputs directory or empty, reward should be 0.0
    # This is naturally achieved since all checks remain False.

    result = {"reward": float(round(reward, 6))}
    result.update(checks)

    # Print exactly one JSON object on the last non-empty stdout line
    print(json.dumps(result))

if __name__ == "__main__":
    main()