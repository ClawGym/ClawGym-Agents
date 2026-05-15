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

def read_lines(path):
    txt = read_text(path)
    if txt is None:
        return None
    return txt.splitlines()

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def has_exact_header(lines, header_text):
    # Accept either a raw line equal to header_text or a Markdown header with any number of leading '#'
    if not lines:
        return False
    target = header_text.strip()
    for line in lines:
        s = line.strip()
        if s == target:
            return True
        # If markdown header like "## Core Finding"
        if s.startswith("#"):
            s2 = s.lstrip("#").strip()
            if s2 == target:
                return True
    return False

def section_range(lines, header_text, all_headers):
    """
    Return start and end indices (start inclusive, end exclusive) for the section whose header matches header_text.
    all_headers is a list of all header names to detect the next section boundary.
    """
    if not lines:
        return (None, None)
    # Find start
    start = None
    for i, line in enumerate(lines):
        s = line.strip()
        s_norm = s.lstrip("#").strip() if s.startswith("#") else s
        if s_norm == header_text:
            start = i + 1  # content starts after header
            break
    if start is None:
        return (None, None)
    # Find end: next line that matches any other header in all_headers (excluding the target one)
    end = len(lines)
    for j in range(start, len(lines)):
        s = lines[j].strip()
        s_norm = s.lstrip("#").strip() if s.startswith("#") else s
        if s_norm in all_headers and s_norm != header_text:
            end = j
            break
    return (start, end)

def count_subheading_claims(lines):
    if not lines:
        return 0
    cnt = 0
    for line in lines:
        if line.startswith("## ") and ":" in line:
            cnt += 1
    return cnt

def contains_any(text, items):
    tl = text.lower()
    for it in items:
        if it.lower() in tl:
            return True
    return False

def find_line_prefix(lines, prefix):
    """Return (index, line) of first line starting with prefix, else (None, None)."""
    if not lines:
        return (None, None)
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            return (idx, line)
    return (None, None)

def words_english_count(phrase):
    # Count tokens that look like English words (letters, digits, hyphen), separated by whitespace
    tokens = [t for t in phrase.strip().split() if t]
    if len(tokens) == 0:
        return 0
    valid = 0
    for t in tokens:
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9\-]*", t) is not None:
            valid += 1
        else:
            # non-english-ish token still counts as a token, but not valid english
            pass
    # Return total tokens for word count constraint, but we can also check "english-ness"
    return len(tokens)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths for expected outputs
    diagnosis_path = os.path.join(output_dir, "diagnosis.json")
    framework_path = os.path.join(output_dir, "framework_upgrade.md")
    contribution_path = os.path.join(output_dir, "original_contribution.md")
    chapter4_path = os.path.join(output_dir, "chapter4_rewrite.md")
    conclusion_path = os.path.join(output_dir, "conclusion_rewrite.md")
    checklist_path = os.path.join(output_dir, "quality_checklist.json")
    datasources_path = os.path.join(output_dir, "data_sources.md")

    # Initialize all checks to False
    checks.update({
        # diagnosis.json checks
        "diagnosis_exists": False,
        "diagnosis_schema_keys": False,
        "diagnosis_scores_valid": False,
        "diagnosis_insider_angle_len": False,
        "diagnosis_chapter_findings_len": False,

        # framework_upgrade.md checks
        "framework_exists": False,
        "framework_has_selection_header": False,
        "framework_has_theory_name": False,
        "framework_no_swot": False,
        "framework_has_diagram_header": False,
        "framework_has_two_arrows": False,

        # original_contribution.md checks
        "contribution_exists": False,
        "contribution_named_concept_format": False,
        "contribution_mechanism_contains_when_then_because": False,
        "contribution_boundary_conditions_with_bullets": False,

        # chapter4_rewrite.md checks
        "chapter4_exists": False,
        "chapter4_has_three_claim_subheadings": False,
        "chapter4_has_percentage": False,
        "chapter4_links_to_theory": False,
        "chapter4_has_counterintuitive_or_surprising": False,

        # conclusion_rewrite.md checks
        "conclusion_exists": False,
        "conclusion_has_all_headers": False,
        "conclusion_theoretical_contribution_has_1_2_3": False,

        # quality_checklist.json checks
        "checklist_exists": False,
        "checklist_schema_valid": False,
        "checklist_style_b_markers_true": False,
        "checklist_figures_plan_len": False,

        # data_sources.md checks
        "datasources_exists": False,
        "datasources_at_least_three_bullets": False,
    })

    # Approved theory names (case-insensitive match)
    approved_theories = [
        "Dynamic Capabilities",
        "Institutional Isomorphism",
        "Principal-Agent",
        "Absorptive Capacity",
        "Resource-Based View",
        "Team Topologies",
        "Conway's Law",
        "Scenario Planning",
        "VUCA",
    ]

    # 1) diagnosis.json
    diag = load_json(diagnosis_path)
    if diag is not None:
        checks["diagnosis_exists"] = True
        # schema keys
        if isinstance(diag, dict) and \
           "scores" in diag and "insider_angle" in diag and "chapter_findings" in diag:
            checks["diagnosis_schema_keys"] = True
            # scores validation
            scores = diag.get("scores", {})
            expected_score_keys = ["contribution", "insider_access", "theory_fit", "data_quality", "conclusion_rigor"]
            scores_valid = True
            if not isinstance(scores, dict):
                scores_valid = False
            else:
                for k in expected_score_keys:
                    v = scores.get(k)
                    if not isinstance(v, int) or not (1 <= v <= 5):
                        scores_valid = False
                        break
            checks["diagnosis_scores_valid"] = scores_valid

            # insider_angle length >= 30
            insider_angle = diag.get("insider_angle")
            if isinstance(insider_angle, str) and len(insider_angle.strip()) >= 30:
                checks["diagnosis_insider_angle_len"] = True

            # chapter_findings keys and lengths
            cf = diag.get("chapter_findings", {})
            chapter_keys = ["chap01", "chap02", "chap03", "chap04", "chap05"]
            cf_valid = True
            if not isinstance(cf, dict):
                cf_valid = False
            else:
                for ck in chapter_keys:
                    v = cf.get(ck)
                    if not isinstance(v, str) or len(v.strip()) < 50:
                        cf_valid = False
                        break
            checks["diagnosis_chapter_findings_len"] = cf_valid

    # 2) framework_upgrade.md
    ftxt = read_text(framework_path)
    flines = read_lines(framework_path)
    if ftxt is not None and flines is not None:
        checks["framework_exists"] = True
        # header "Framework Selection"
        if has_exact_header(flines, "Framework Selection"):
            checks["framework_has_selection_header"] = True
        # contains approved theory
        if contains_any(ftxt, approved_theories):
            checks["framework_has_theory_name"] = True
        # no "SWOT" substring
        if "swot" not in ftxt.lower():
            checks["framework_no_swot"] = True
        # header "Framework Diagram Description"
        if has_exact_header(flines, "Framework Diagram Description"):
            checks["framework_has_diagram_header"] = True
        # at least two "→"
        if ftxt.count("→") >= 2:
            checks["framework_has_two_arrows"] = True

    # 3) original_contribution.md
    ctxt = read_text(contribution_path)
    clines = read_lines(contribution_path)
    if ctxt is not None and clines is not None:
        checks["contribution_exists"] = True
        # Named Concept line
        idx_nc, line_nc = find_line_prefix(clines, "Named Concept:")
        if idx_nc is not None:
            phrase = line_nc[len("Named Concept:"):].strip()
            wc = words_english_count(phrase)
            if 2 <= wc <= 6:
                checks["contribution_named_concept_format"] = True
        # Mechanism Statement line with when, then, because
        idx_ms, line_ms = find_line_prefix(clines, "Mechanism Statement:")
        if idx_ms is not None:
            rest = line_ms[len("Mechanism Statement:"):].strip().lower()
            if ("when" in rest) and ("then" in rest) and ("because" in rest):
                checks["contribution_mechanism_contains_when_then_because"] = True
        # Boundary Conditions header and at least one bullet after it
        if has_exact_header(clines, "Boundary Conditions:"):
            # find section range from Boundary Conditions:
            start, end = section_range(clines, "Boundary Conditions:", ["Boundary Conditions:"])
            bullets = 0
            if start is None:
                # fallback: count any bullets after header line position
                # find header line index
                header_idx = None
                for i, line in enumerate(clines):
                    s = line.strip()
                    s_norm = s.lstrip("#").strip() if s.startswith("#") else s
                    if s_norm == "Boundary Conditions:":
                        header_idx = i
                        break
                rng = range(header_idx + 1, len(clines)) if header_idx is not None else range(0)
            else:
                rng = range(start, end)
            for i in rng:
                if clines[i].lstrip().startswith("- "):
                    bullets += 1
            if bullets >= 1:
                checks["contribution_boundary_conditions_with_bullets"] = True

    # 4) chapter4_rewrite.md
    ch4txt = read_text(chapter4_path)
    ch4lines = read_lines(chapter4_path)
    if ch4txt is not None and ch4lines is not None:
        checks["chapter4_exists"] = True
        # At least three subheadings "## " containing ":"
        if count_subheading_claims(ch4lines) >= 3:
            checks["chapter4_has_three_claim_subheadings"] = True
        # Percentage pattern
        if re.search(r"\b\d+(\.\d+)?%\b", ch4txt) is not None:
            checks["chapter4_has_percentage"] = True
        # Mention at least one approved theory
        if contains_any(ch4txt, approved_theories):
            checks["chapter4_links_to_theory"] = True
        # contains 'counterintuitive' or 'surprising'
        low = ch4txt.lower()
        if ("counterintuitive" in low) or ("surprising" in low):
            checks["chapter4_has_counterintuitive_or_surprising"] = True

    # 5) conclusion_rewrite.md
    contxt = read_text(conclusion_path)
    conlines = read_lines(conclusion_path)
    required_con_headers = [
        "Core Finding",
        "Theoretical Contribution",
        "Managerial Implications",
        "Boundary Conditions",
        "Limitations and Future Research",
    ]
    if contxt is not None and conlines is not None:
        checks["conclusion_exists"] = True
        # all headers present
        if all(has_exact_header(conlines, h) for h in required_con_headers):
            checks["conclusion_has_all_headers"] = True
        # under "Theoretical Contribution", at least lines starting with "1.", "2.", "3."
        start, end = section_range(conlines, "Theoretical Contribution", required_con_headers)
        nums_present = {"1": False, "2": False, "3": False}
        if start is not None:
            for i in range(start, end):
                s = conlines[i].lstrip()
                for n in ["1", "2", "3"]:
                    if s.startswith(n + "."):
                        nums_present[n] = True
            if nums_present["1"] and nums_present["2"] and nums_present["3"]:
                checks["conclusion_theoretical_contribution_has_1_2_3"] = True

    # 6) quality_checklist.json
    qj = load_json(checklist_path)
    if qj is not None:
        checks["checklist_exists"] = True
        schema_ok = True
        # academic_rigor boolean
        if not isinstance(qj.get("academic_rigor", None), bool):
            schema_ok = False
        # style_b_markers object with booleans
        sb = qj.get("style_b_markers", None)
        sb_ok = False
        if isinstance(sb, dict):
            cf = sb.get("counterintuitive_finding", None)
            mi = sb.get("mechanism_identified", None)
            bcs = sb.get("boundary_conditions_stated", None)
            if isinstance(cf, bool) and isinstance(mi, bool) and isinstance(bcs, bool):
                sb_ok = True
                if cf and mi and bcs:
                    checks["checklist_style_b_markers_true"] = True
        # figures_and_tables_plan array length >= 3
        ftp = qj.get("figures_and_tables_plan", None)
        ftp_ok = isinstance(ftp, list) and len(ftp) >= 3
        if not ftp_ok:
            schema_ok = False
        checks["checklist_figures_plan_len"] = ftp_ok
        checks["checklist_schema_valid"] = schema_ok and sb_ok

    # 7) data_sources.md
    dstxt = read_text(datasources_path)
    dslines = read_lines(datasources_path)
    if dstxt is not None and dslines is not None:
        checks["datasources_exists"] = True
        bullets = sum(1 for ln in dslines if ln.lstrip().startswith("- "))
        if bullets >= 3:
            checks["datasources_at_least_three_bullets"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure exactly 0.0 if output dir missing or empty/no required artifacts produced (baseline no-op)
    # This is naturally satisfied by ratio if no checks passed. Keep as-is.

    result = {"reward": reward}
    # Append checks ensuring boolean values
    for k in checks:
        result[k] = bool(checks[k])

    # Print exactly one JSON object on the last non-empty stdout line
    print(json.dumps(result))

if __name__ == "__main__":
    main()