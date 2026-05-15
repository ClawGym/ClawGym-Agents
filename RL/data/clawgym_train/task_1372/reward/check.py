import csv
import json
import os
import re
import sys
from datetime import datetime

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    csv_path = os.path.join(output_dir, "commitments.csv")
    report_path = os.path.join(output_dir, "report.md")

    # Allowed source paths
    allowed_sources = {
        "input/MEMORY.md",
        "input/memory/2026-03-30.md",
        "input/memory/2026-04-15.md",
        "input/memory/2026-06-10.md",
    }

    # Initialize checks (all False by default)
    checks = {
        "file_exists_csv": False,
        "file_exists_report": False,

        "csv_header_correct": False,
        "csv_rows_at_least_5": False,
        "csv_all_rows_have_5_fields": False,
        "csv_dates_in_range": False,
        "csv_source_paths_valid": False,
        "csv_line_ranges_valid": False,

        "report_top5_section_present": False,
        "report_top5_exactly_five_bullets": False,
        "report_top5_citations_valid": False,

        "report_risks_section_present": False,
        "report_risks_at_least_two_bullets": False,

        "report_missing_owners_section_present": False,
        "report_missing_owners_listed": False,

        "report_7week_section_present": False,
        "report_7week_at_least_seven_bullets": False,
        "report_7week_bullets_ref_week": False,

        "report_contains_two_csv_items": False,
    }

    # Helpers
    def read_text(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def find_section(lines, phrase):
        # Find a line that includes the phrase; treat it as a section header
        # Section ends at the next markdown header line (starting with '#') after the header line
        # or at the next line that includes any known section phrase.
        known_phrases = ["Top 5 Priorities", "Risks & Gaps", "Missing Owners", "7-week"]
        start_idx = None
        for i, line in enumerate(lines):
            if phrase.lower() in line.lower():
                start_idx = i
                break
        if start_idx is None:
            return None, None, []
        end_idx = len(lines)
        for j in range(start_idx + 1, len(lines)):
            l = lines[j]
            if l.lstrip().startswith("#"):
                end_idx = j
                break
            # If another known section phrase appears, break as well
            for p in known_phrases:
                if p.lower() in l.lower():
                    end_idx = j
                    break
            if end_idx != len(lines):
                break
        return start_idx, end_idx, lines[start_idx+1:end_idx]

    def extract_bullets(section_lines):
        bullets = []
        for l in section_lines:
            ls = l.lstrip()
            if ls.startswith("- ") or ls.startswith("* "):
                bullets.append(l)
        return bullets

    # File existence
    if os.path.isfile(csv_path):
        checks["file_exists_csv"] = True
    if os.path.isfile(report_path):
        checks["file_exists_report"] = True

    # Parse CSV if exists
    csv_rows = []
    header_ok = False
    if checks["file_exists_csv"]:
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                # Exact header check
                header_ok = header == ["date", "item", "owner", "source_path", "line_range"]
                if header_ok:
                    checks["csv_header_correct"] = True
                data_rows = rows[1:]
                csv_rows = data_rows
                # At least 5 rows
                if len(data_rows) >= 5:
                    checks["csv_rows_at_least_5"] = True
                # All rows have 5 fields
                all_five = all(len(r) == 5 for r in data_rows) and len(data_rows) > 0
                if all_five:
                    checks["csv_all_rows_have_5_fields"] = True

                # Dates in range and correct format
                dates_ok = True
                date_format = "%Y-%m-%d"
                start_date = datetime.strptime("2026-04-01", date_format)
                end_date = datetime.strptime("2026-06-30", date_format)
                for r in data_rows:
                    if len(r) != 5:
                        dates_ok = False
                        break
                    date_str = r[0].strip()
                    try:
                        dt = datetime.strptime(date_str, date_format)
                        if not (start_date <= dt <= end_date):
                            dates_ok = False
                            break
                    except Exception:
                        dates_ok = False
                        break
                if dates_ok and data_rows:
                    checks["csv_dates_in_range"] = True

                # source_path validation
                sp_ok = True
                for r in data_rows:
                    if len(r) != 5:
                        sp_ok = False
                        break
                    sp = r[3].strip()
                    if sp not in allowed_sources:
                        sp_ok = False
                        break
                if sp_ok and data_rows:
                    checks["csv_source_paths_valid"] = True

                # line_range validation "<start>-<end>"
                lr_ok = True
                lr_re = re.compile(r"^\s*(\d+)-(\d+)\s*$")
                for r in data_rows:
                    if len(r) != 5:
                        lr_ok = False
                        break
                    lr = r[4]
                    m = lr_re.match(lr)
                    if not m:
                        lr_ok = False
                        break
                    # Positive integers already assured by regex; no need to enforce order
                if lr_ok and data_rows:
                    checks["csv_line_ranges_valid"] = True

        except Exception:
            # Leave csv-related checks as False
            pass

    # Parse report if exists
    report_text = None
    report_lines = []
    if checks["file_exists_report"]:
        report_text = read_text(report_path)
        if report_text is None:
            report_text = ""
        report_lines = report_text.splitlines()

        # Top 5 Priorities
        t5_start, t5_end, t5_section = find_section(report_lines, "Top 5 Priorities")
        if t5_section is not None:
            checks["report_top5_section_present"] = True
            t5_bullets = extract_bullets(t5_section)
            if len(t5_bullets) == 5:
                checks["report_top5_exactly_five_bullets"] = True
            # Validate citations in bullets
            citation_re = re.compile(
                r"\[source:\s*(input/MEMORY\.md|input/memory/2026-03-30\.md|input/memory/2026-04-15\.md|input/memory/2026-06-10\.md)\s+L(\d+)-L(\d+)\]"
            )
            if t5_bullets:
                all_cited = True
                for b in t5_bullets:
                    if citation_re.search(b) is None:
                        all_cited = False
                        break
                if all_cited and len(t5_bullets) == 5:
                    checks["report_top5_citations_valid"] = True

        # Risks & Gaps
        rg_start, rg_end, rg_section = find_section(report_lines, "Risks & Gaps")
        if rg_section is not None:
            checks["report_risks_section_present"] = True
            rg_bullets = extract_bullets(rg_section)
            if len(rg_bullets) >= 2:
                checks["report_risks_at_least_two_bullets"] = True

        # Missing Owners
        mo_start, mo_end, mo_section = find_section(report_lines, "Missing Owners")
        if mo_section is not None:
            checks["report_missing_owners_section_present"] = True
            # For each CSV row with owner blank or 'TBD', the item summary must appear in this section
            if csv_rows:
                mo_text = "\n".join(mo_section)
                missing_items = []
                for r in csv_rows:
                    if len(r) != 5:
                        continue
                    owner = (r[2] or "").strip()
                    if owner == "" or owner.lower() == "tbd":
                        missing_items.append(r[1].strip())
                if missing_items:
                    all_listed = True
                    for item in missing_items:
                        if item and item not in mo_text:
                            all_listed = False
                            break
                    if all_listed:
                        checks["report_missing_owners_listed"] = True
                else:
                    # If there are no missing owners in CSV, treat as pass (no items to list)
                    checks["report_missing_owners_listed"] = True

        # 7-week plan section
        sw_start, sw_end, sw_section = find_section(report_lines, "7-week")
        if sw_section is not None:
            # Verify the phrase "7-week" appears in the report
            if any("7-week".lower() in line.lower() for line in report_lines):
                checks["report_7week_section_present"] = True
            sw_bullets = extract_bullets(sw_section)
            if len(sw_bullets) >= 7:
                checks["report_7week_at_least_seven_bullets"] = True
            if sw_bullets:
                ref_week_ok = True
                for b in sw_bullets:
                    if "week" not in b.lower():
                        ref_week_ok = False
                        break
                if ref_week_ok and len(sw_bullets) >= 7:
                    checks["report_7week_bullets_ref_week"] = True

        # Cross-reference: at least two item summaries from CSV appear somewhere in report
        if csv_rows and report_text:
            # Collect items
            items = [r[1].strip() for r in csv_rows if len(r) == 5 and r[1].strip()]
            count_present = 0
            seen = set()
            for item in items:
                if item in report_text and item not in seen:
                    seen.add(item)
                    count_present += 1
                if count_present >= 2:
                    break
            if count_present >= 2:
                checks["report_contains_two_csv_items"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if outputs missing or empty, ensure 0.0
    # If both files missing or output dir missing, reward must be 0.0
    if not checks["file_exists_csv"] and not checks["file_exists_report"]:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()