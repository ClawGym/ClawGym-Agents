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

def count_bullet_lines(lines, start_idx, end_idx):
    count = 0
    for i in range(start_idx, end_idx):
        line = lines[i]
        if re.match(r"^\s*-\s+", line):
            count += 1
    return count

def find_section_range(lines, section_header):
    # Return (start_index_of_content, end_index_exclusive) for content after section_header line until next "## " header or EOF
    start = None
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            start = i + 1
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## ") and lines[j].strip() != section_header:
            end = j
            break
    return start, end

def word_count(text):
    if not text:
        return 0
    # Count words as sequences of alphanumerics separated by whitespace/punctuation
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)

def get_lines_between_markers(lines, start_marker, end_markers):
    # Return list of lines between a line starting with start_marker and next line starting with any of end_markers (exact startswith), or EOF
    start_idx = None
    for i, l in enumerate(lines):
        if l.strip().startswith(start_marker):
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        lj = lines[j].strip()
        for em in end_markers:
            if lj.startswith(em):
                end_idx = j
                return lines[start_idx:end_idx]
    return lines[start_idx:end_idx]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) strategy.md checks
    strategy_path = os.path.join(output_dir, "strategy.md")
    strategy_exists = os.path.isfile(strategy_path)
    checks["strategy_exists"] = False
    checks["strategy_headers_ok"] = False
    checks["strategy_ten_angles"] = False
    checks["strategy_mentions_haro"] = False
    checks["strategy_mentions_two_alternatives"] = False

    expected_headers = [
        "## 1. Story Angle Development",
        "## 2. Media Target List & Prioritization",
        "## 3. Journalist Outreach & Pitch Templates",
        "## 4. Press Release Writing Framework",
        "## 5. HARO & Reactive PR Tactics",
        "## 6. Long-Term Media Relationship Building",
        "## 7. PR Measurement & ROI Plan",
    ]

    if strategy_exists:
        checks["strategy_exists"] = True
        content = read_text(strategy_path) or ""
        lines = content.splitlines()
        # Headers exact matches
        headers_found = {h: False for h in expected_headers}
        for line in lines:
            if line.strip() in headers_found:
                headers_found[line.strip()] = True
        checks["strategy_headers_ok"] = all(headers_found.values())

        # Exactly 10 bullet lines under "## 1. Story Angle Development"
        start, end = find_section_range(lines, "## 1. Story Angle Development")
        if start is not None and end is not None:
            bullet_count = count_bullet_lines(lines, start, end)
            checks["strategy_ten_angles"] = (bullet_count == 10)

        # Mentions HARO and at least two of: Qwoted, SourceBottle, ProfNet
        lower_content = content.lower()
        checks["strategy_mentions_haro"] = ("haro" in lower_content)
        alts = ["qwoted", "sourcebottle", "profnet"]
        alt_count = sum(1 for a in alts if a in lower_content)
        checks["strategy_mentions_two_alternatives"] = (alt_count >= 2)

    # 2) targets.csv
    targets_path = os.path.join(output_dir, "targets.csv")
    checks["targets_exists"] = False
    checks["targets_header_ok"] = False
    checks["targets_min_rows"] = False
    checks["targets_valid_tiers"] = False

    if os.path.isfile(targets_path):
        checks["targets_exists"] = True
        try:
            with open(targets_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                checks["targets_header_ok"] = (header == ["publication", "tier", "audience_focus"])
                data_rows = [r for r in rows[1:] if any(cell.strip() for cell in r)]
                checks["targets_min_rows"] = (len(data_rows) >= 20)
                valid_tiers = True
                for r in data_rows:
                    if len(r) < 2:
                        valid_tiers = False
                        break
                    tier = r[1].strip()
                    if tier not in {"T1", "T2", "T3"}:
                        valid_tiers = False
                        break
                checks["targets_valid_tiers"] = valid_tiers
        except Exception:
            # Leave checks as False if parsing fails
            pass

    # 3) pitch_templates.md
    pt_path = os.path.join(output_dir, "pitch_templates.md")
    checks["pitch_templates_exists"] = False
    checks["pitch_subject_lines_5plus"] = False
    checks["pitch_cold_pitch_leq_150_words"] = False
    checks["pitch_followup_two_numbered"] = False

    if os.path.isfile(pt_path):
        checks["pitch_templates_exists"] = True
        pt_content = read_text(pt_path) or ""
        pt_lines = pt_content.splitlines()

        # Subject line options section: count bullet lines until next labeled section
        subject_section_lines = get_lines_between_markers(
            pt_lines,
            "Subject line options",
            ["Cold pitch (<=150 words):", "Follow-up sequence:"]
        )
        subj_count = 0
        for l in subject_section_lines:
            if re.match(r"^\s*-\s+", l):
                subj_count += 1
        checks["pitch_subject_lines_5plus"] = (subj_count >= 5)

        # Cold pitch section body and word count
        cold_body_lines = get_lines_between_markers(
            pt_lines,
            "Cold pitch (<=150 words):",
            ["Follow-up sequence:", "Subject line options"]
        )
        cold_body_text = " ".join([l.strip() for l in cold_body_lines]).strip()
        wc = word_count(cold_body_text)
        checks["pitch_cold_pitch_leq_150_words"] = (wc > 0 and wc <= 150)

        # Follow-up sequence section: two numbered items "1.", "2."
        followup_lines = get_lines_between_markers(
            pt_lines,
            "Follow-up sequence:",
            ["Cold pitch (<=150 words):", "Subject line options"]
        )
        has_one = any(l.strip().startswith("1.") for l in followup_lines)
        has_two = any(l.strip().startswith("2.") for l in followup_lines)
        checks["pitch_followup_two_numbered"] = (has_one and has_two)

    # 4) press_release.md
    pr_path = os.path.join(output_dir, "press_release.md")
    checks["press_release_exists"] = False
    checks["press_has_headline"] = False
    checks["press_has_boilerplate"] = False
    checks["press_has_distribution"] = False

    if os.path.isfile(pr_path):
        checks["press_release_exists"] = True
        pr_content = read_text(pr_path) or ""
        pr_lines = pr_content.splitlines()
        checks["press_has_headline"] = any(l.strip().startswith("Headline:") for l in pr_lines)
        checks["press_has_boilerplate"] = any(l.strip().startswith("Boilerplate:") for l in pr_lines)
        checks["press_has_distribution"] = any(l.strip().startswith("Distribution Strategy:") for l in pr_lines)

    # 5) measurement.json
    meas_path = os.path.join(output_dir, "measurement.json")
    checks["measurement_exists"] = False
    checks["measurement_structure_ok"] = False
    checks["measurement_metrics_keys_ok"] = False

    if os.path.isfile(meas_path):
        checks["measurement_exists"] = True
        try:
            with open(meas_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Structure: arrays and metrics object
            has_keys = all(k in data for k in ["immediate_actions", "short_term", "long_term", "metrics"])
            types_ok = isinstance(data.get("immediate_actions"), list) and isinstance(data.get("short_term"), list) and isinstance(data.get("long_term"), list) and isinstance(data.get("metrics"), dict)
            checks["measurement_structure_ok"] = has_keys and types_ok
            metrics = data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}
            metrics_keys_ok = all(k in metrics for k in ["backlink_quality", "referral_traffic", "brand_search_lift"])
            checks["measurement_metrics_keys_ok"] = metrics_keys_ok
        except Exception:
            # Leave as False on parsing errors
            pass

    # 6) seo_brief.md
    seo_path = os.path.join(output_dir, "seo_brief.md")
    checks["seo_brief_exists"] = False
    checks["seo_title_line_present"] = False
    checks["seo_meta_description_len_ok"] = False
    checks["seo_primary_keyword_line_present"] = False
    checks["seo_secondary_keywords_5plus"] = False
    checks["seo_structure_h2_4plus"] = False
    checks["seo_word_count_target_has_number"] = False
    checks["seo_competitor_gap_analysis_present"] = False
    checks["seo_angle_keyword_map_5plus"] = False

    if os.path.isfile(seo_path):
        checks["seo_brief_exists"] = True
        seo_content = read_text(seo_path) or ""
        seo_lines = seo_content.splitlines()

        # Title line
        checks["seo_title_line_present"] = any(l.strip().startswith("# Article title (H1):") for l in seo_lines)

        # Meta description single-line and length <= 155 chars after label
        meta_len_ok = False
        for l in seo_lines:
            if l.strip().startswith("Meta description:"):
                after = l.split("Meta description:", 1)[1]
                # Count characters after label (strip leading/trailing spaces)
                if len(after.strip()) <= 155:
                    meta_len_ok = True
                break
        checks["seo_meta_description_len_ok"] = meta_len_ok

        # Primary keyword line
        checks["seo_primary_keyword_line_present"] = any(l.strip().startswith("Primary keyword:") for l in seo_lines)

        # Secondary keywords list with at least 5 items
        sec_idx = None
        for i, l in enumerate(seo_lines):
            if l.strip().startswith("Secondary keywords:"):
                sec_idx = i
                break
        sec_count = 0
        if sec_idx is not None:
            for j in range(sec_idx + 1, len(seo_lines)):
                s = seo_lines[j]
                if re.match(r"^\s*-\s+", s):
                    sec_count += 1
                elif s.strip() == "":
                    # allow blank lines in list; continue
                    continue
                else:
                    # break on non-bullet non-empty
                    break
        checks["seo_secondary_keywords_5plus"] = (sec_count >= 5)

        # Recommended article structure: count H2s (## ) after that label until next label ending with ":" (not a header)
        struct_idx = None
        for i, l in enumerate(seo_lines):
            if l.strip().startswith("Recommended article structure:"):
                struct_idx = i
                break
        h2_count = 0
        if struct_idx is not None:
            for j in range(struct_idx + 1, len(seo_lines)):
                lj = seo_lines[j]
                if lj.strip().endswith(":") and not lj.strip().startswith("##"):
                    break
                if lj.startswith("## "):
                    h2_count += 1
        checks["seo_structure_h2_4plus"] = (h2_count >= 4)

        # Word count target line with a number
        wct_ok = False
        for l in seo_lines:
            if l.strip().startswith("Word count target:"):
                if re.search(r"\d", l):
                    wct_ok = True
                break
        checks["seo_word_count_target_has_number"] = wct_ok

        # Competitor Gap Analysis section presence
        checks["seo_competitor_gap_analysis_present"] = any(l.strip().startswith("Competitor Gap Analysis:") for l in seo_lines)

        # Angle-to-Keyword Map with at least 5 mapping lines (count bullets under section)
        map_idx = None
        for i, l in enumerate(seo_lines):
            if l.strip().startswith("Angle-to-Keyword Map:"):
                map_idx = i
                break
        map_count = 0
        if map_idx is not None:
            for j in range(map_idx + 1, len(seo_lines)):
                s = seo_lines[j]
                if re.match(r"^\s*-\s+", s):
                    map_count += 1
                elif s.strip() == "":
                    continue
                else:
                    break
        checks["seo_angle_keyword_map_5plus"] = (map_count >= 5)

    # Compute reward as proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v is True)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print single JSON object with reward first, then checks
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()