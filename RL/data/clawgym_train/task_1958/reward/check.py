import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def parse_report(report_text):
    # Returns a tuple: (sections_data, file_order, meta)
    # sections_data: { "input/skill_risky.md": {"risk": str or None, "counts": {"EXFIL":int,"FILES":int,"SHELL":int}, "mitigations_bullets": int}, ... }
    # file_order: list of file paths in the order they appear
    # meta: {"file_lines_count": int}
    lines = report_text.splitlines()
    # Normalize line endings and keep raw for processing
    file_line_indices = []
    file_paths_at_indices = []
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("File: "):
            path = stripped[len("File: "):].strip()
            file_line_indices.append(idx)
            file_paths_at_indices.append(path)

    sections = {}
    file_order = []
    for i, start_idx in enumerate(file_line_indices):
        end_idx = file_line_indices[i+1] if i+1 < len(file_line_indices) else len(lines)
        section_lines = lines[start_idx+1:end_idx]
        # Extract risk
        risk = None
        for sl in section_lines:
            s = sl.strip()
            if s.startswith("RISK: "):
                risk = s[len("RISK: "):].strip()
                break
        # Count findings
        counts = {"EXFIL": 0, "FILES": 0, "SHELL": 0}
        finding_re = re.compile(r'^- \[(EXFIL|FILES|SHELL)\] line (\d+):')
        for sl in section_lines:
            s = sl.strip()
            m = finding_re.match(s)
            if m:
                kind = m.group(1)
                # Ensure integer line number
                try:
                    int(m.group(2))
                    counts[kind] += 1
                except ValueError:
                    pass  # ignore malformed line numbers

        # Mitigations block detection
        mitigations_bullets = 0
        mit_idx = None
        for j, sl in enumerate(section_lines):
            if sl.strip() == "Mitigations:":
                mit_idx = j
                break
        if mit_idx is not None:
            # Count bullets after "Mitigations:" within this section
            for sl in section_lines[mit_idx+1:]:
                if sl.strip().startswith("- "):
                    mitigations_bullets += 1

        filepath = file_paths_at_indices[i] if i < len(file_paths_at_indices) else None
        if filepath is not None:
            sections[filepath] = {
                "risk": risk,
                "counts": counts,
                "mitigations_bullets": mitigations_bullets,
            }
            file_order.append(filepath)

    meta = {"file_lines_count": len(file_line_indices)}
    return sections, file_order, meta

def parse_csv(csv_text):
    # Returns (header_ok, rows_map, rows_count)
    # rows_map: {file: {"risk_level": str, "exfil": int, "files": int, "shell": int, "total": int}}
    lines = [l.strip() for l in csv_text.splitlines() if l.strip() != ""]
    if not lines:
        return False, {}, 0
    header = lines[0]
    header_ok = header == "file,risk_level,exfil_count,files_count,shell_count,total_findings"
    rows_map = {}
    for data_line in lines[1:]:
        parts = data_line.split(",")
        if len(parts) != 6:
            continue
        filev = parts[0].strip()
        risk_level = parts[1].strip()
        try:
            exfil = int(parts[2].strip())
            files = int(parts[3].strip())
            shell = int(parts[4].strip())
            total = int(parts[5].strip())
        except ValueError:
            # skip malformed row
            continue
        rows_map[filev] = {
            "risk_level": risk_level,
            "exfil": exfil,
            "files": files,
            "shell": shell,
            "total": total,
        }
    return header_ok, rows_map, len(lines) - 1

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "report_exists": False,
        "csv_exists": False,
        "report_two_sections_exact": False,
        "report_has_expected_files": False,
        "report_risky_risk_high": False,
        "report_safe_risk_low": False,
        "report_risky_has_exfil": False,
        "report_risky_has_files": False,
        "report_risky_has_shell": False,
        "report_safe_zero_findings": False,
        "report_risky_has_mitigations_2plus": False,
        "report_safe_has_mitigations_2plus": False,
        "csv_header_ok": False,
        "csv_two_rows_exact": False,
        "csv_risk_levels_match_report": False,
        "csv_counts_match_report": False,
    }

    expected_files = {"input/skill_risky.md", "input/skill_safe.md"}

    # Paths
    report_path = os.path.join(output_dir, "security_audit_report.md")
    csv_path = os.path.join(output_dir, "security_audit_summary.csv")

    # Read and parse report
    sections = {}
    file_order = []
    meta = {"file_lines_count": 0}

    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report_text = read_text(report_path)
        if report_text is not None:
            sections, file_order, meta = parse_report(report_text)

            # Exactly two top-level sections
            if meta.get("file_lines_count", 0) == 2:
                checks["report_two_sections_exact"] = True

            # Verify expected file paths present (both and only)
            present_files = set(file_order)
            if present_files == expected_files:
                checks["report_has_expected_files"] = True

            # Evaluate risky/safe specifics only if sections contain both expected files
            if expected_files.issubset(sections.keys()):
                risky = sections.get("input/skill_risky.md")
                safe = sections.get("input/skill_safe.md")

                # Risk level checks
                if risky and (risky.get("risk") == "HIGH"):
                    checks["report_risky_risk_high"] = True
                if safe and (safe.get("risk") == "LOW"):
                    checks["report_safe_risk_low"] = True

                # Findings checks
                if risky:
                    counts = risky.get("counts", {})
                    if counts.get("EXFIL", 0) >= 1:
                        checks["report_risky_has_exfil"] = True
                    if counts.get("FILES", 0) >= 1:
                        checks["report_risky_has_files"] = True
                    if counts.get("SHELL", 0) >= 1:
                        checks["report_risky_has_shell"] = True

                if safe:
                    scounts = safe.get("counts", {})
                    total_safe = (scounts.get("EXFIL", 0) + scounts.get("FILES", 0) + scounts.get("SHELL", 0))
                    if total_safe == 0:
                        checks["report_safe_zero_findings"] = True

                # Mitigations bullets
                if risky and isinstance(risky.get("mitigations_bullets"), int) and risky.get("mitigations_bullets") >= 2:
                    checks["report_risky_has_mitigations_2plus"] = True
                if safe and isinstance(safe.get("mitigations_bullets"), int) and safe.get("mitigations_bullets") >= 2:
                    checks["report_safe_has_mitigations_2plus"] = True

    # Read and parse CSV
    rows_map = {}
    rows_count = 0
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        csv_text = read_text(csv_path)
        if csv_text is not None:
            header_ok, rows_map, rows_count = parse_csv(csv_text)
            if header_ok:
                checks["csv_header_ok"] = True
            # Exactly two rows and they correspond to expected files
            if rows_count == 2 and set(rows_map.keys()) == expected_files:
                checks["csv_two_rows_exact"] = True

            # Compare CSV risk levels to report
            if checks["report_has_expected_files"]:
                risk_match = True
                for fp in expected_files:
                    report_risk = sections[fp].get("risk")
                    csv_risk = rows_map.get(fp, {}).get("risk_level")
                    if not (report_risk and csv_risk and report_risk == csv_risk):
                        risk_match = False
                        break
                if risk_match:
                    checks["csv_risk_levels_match_report"] = True

            # Compare CSV counts to report counts (and total equals sum)
            if checks["report_has_expected_files"] and set(rows_map.keys()) == expected_files:
                counts_match = True
                for fp in expected_files:
                    rc = sections[fp]["counts"]
                    exf = rows_map[fp]["exfil"]
                    fil = rows_map[fp]["files"]
                    sh = rows_map[fp]["shell"]
                    tot = rows_map[fp]["total"]
                    if not (exf == rc.get("EXFIL", 0) and fil == rc.get("FILES", 0) and sh == rc.get("SHELL", 0)):
                        counts_match = False
                        break
                    if tot != (exf + fil + sh):
                        counts_match = False
                        break
                if counts_match:
                    checks["csv_counts_match_report"] = True

    # Compute reward
    # No-op baseline: if output dir missing or both files missing, reward is 0.0
    if not checks["report_exists"] and not checks["csv_exists"]:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()