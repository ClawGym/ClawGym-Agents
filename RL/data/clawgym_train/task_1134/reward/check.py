import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_lines(path: Path) -> Optional[List[str]]:
    txt = safe_read_text(path)
    if txt is None:
        return None
    return txt.splitlines()


def safe_load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def parse_float(val: str) -> Optional[float]:
    try:
        return float(val.strip())
    except Exception:
        return None


def parse_project_title_and_design_lead(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    title = None
    design_lead = None
    for line in lines:
        if line.strip().startswith("# Project Brief:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                title = parts[1].strip()
        if line.strip().startswith("Design Lead:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                design_lead = parts[1].strip()
    return title, design_lead


def compute_expected_backlog(header: List[str], rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    required = ["feature_id", "title", "feature_type", "impact_score", "confidence", "effort_estimate"]
    for col in required:
        if col not in header:
            return []
    expected = []
    for idx, r in enumerate(rows):
        fid = r.get("feature_id", "").strip()
        title = r.get("title", "").strip()
        ftype = r.get("feature_type", "").strip()
        impact = parse_float(str(r.get("impact_score", "")).strip())
        conf = parse_float(str(r.get("confidence", "")).strip())
        effort = parse_float(str(r.get("effort_estimate", "")).strip())
        if not fid or title is None or ftype is None or impact is None or conf is None or effort is None or effort == 0:
            return []
        score = (impact * conf) / effort
        score_rounded = round(score + 1e-12, 2)
        if ftype == "UI":
            owner = "Design"
        elif ftype == "Backend":
            owner = "Engineering"
        elif ftype == "Cross-functional":
            owner = "Design+Engineering"
        else:
            owner = ""
        expected.append({
            "feature_id": fid,
            "title": title,
            "feature_type": ftype,
            "impact_score": impact,
            "confidence": conf,
            "effort_estimate": effort,
            "priority_score": score_rounded,
            "owner_function": owner,
            "orig_index": idx
        })
    expected.sort(key=lambda x: (-x["priority_score"], -x["impact_score"], x["effort_estimate"], x["orig_index"]))
    for i, item in enumerate(expected):
        item["rank"] = i + 1
        item["included_in_v1"] = "Yes" if i < 3 else "No"
    return expected


def format_two_decimals(val: float) -> str:
    return f"{val:.2f}"


def find_section_block(lines: List[str], section_header: str) -> Tuple[Optional[int], Optional[int]]:
    start = None
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("## ") and j != start:
            end = j
            break
    return start, end


def extract_subject_line(lines: List[str]) -> Optional[str]:
    for line in lines:
        m = re.match(r"^\s*Subject\s*:\s*(.+)$", line, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def parse_bullet_blocks(lines: List[str]) -> List[str]:
    blocks: List[str] = []
    current: List[str] = []
    in_bullet = False
    for ln in lines:
        stripped = ln.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            current.append(ln)
            in_bullet = True
        else:
            if in_bullet:
                if stripped.startswith("## "):
                    # New section header, end current bullet
                    blocks.append("\n".join(current).strip())
                    current = []
                    in_bullet = False
                else:
                    current.append(ln)
            else:
                # Not in bullet, ignore
                pass
    if current:
        blocks.append("\n".join(current).strip())
    return blocks


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "prioritized_backlog_header_and_order": 0.0,
        "prioritized_backlog_row_count_match_input": 0.0,
        "prioritized_backlog_priority_scores_and_ranking": 0.0,
        "prioritized_backlog_owner_and_included_flags": 0.0,
        "project_brief_updated_replaced_priorities": 0.0,
        "project_brief_bullets_top3_correct": 0.0,
        "project_brief_other_text_unchanged": 0.0,
        "email_subject_contains_required": 0.0,
        "email_mentions_prioritization_approach_and_backlog_path": 0.0,
        "email_bullets_top3_correct": 0.0,
        "email_calls_out_design_support": 0.0,
        "email_requests_kickoff_and_dependencies": 0.0,
        "email_uses_design_lead_name": 0.0,
    }

    analyst_csv_path = workspace / "input" / "analyst_findings.csv"
    brief_md_path = workspace / "input" / "project_brief.md"
    input_header, input_rows = safe_load_csv(analyst_csv_path)
    brief_lines = safe_read_lines(brief_md_path)

    expected_backlog: List[Dict[str, str]] = []
    project_title = None
    design_lead = None
    if input_header is not None and input_rows is not None:
        expected_backlog = compute_expected_backlog(input_header, input_rows)
    if brief_lines is not None:
        project_title, design_lead = parse_project_title_and_design_lead(brief_lines)

    output_backlog_path = workspace / "output" / "prioritized_backlog.csv"
    out_header, out_rows = safe_load_csv(output_backlog_path)
    expected_output_header = [
        "feature_id",
        "title",
        "feature_type",
        "impact_score",
        "confidence",
        "effort_estimate",
        "priority_score",
        "rank",
        "owner_function",
        "included_in_v1",
    ]

    if out_header is not None and out_rows is not None and out_header == expected_output_header:
        two_decimals_all = True
        for row in out_rows:
            ps = row.get("priority_score", "")
            if not re.fullmatch(r"\d+\.\d{2}", str(ps).strip()):
                two_decimals_all = False
                break
        if two_decimals_all:
            scores["prioritized_backlog_header_and_order"] = 1.0

    if input_rows is not None and out_rows is not None:
        if len(out_rows) == len(input_rows) and len(expected_backlog) == len(input_rows) and len(expected_backlog) > 0:
            scores["prioritized_backlog_row_count_match_input"] = 1.0

    ranking_ok = False
    values_ok = False
    owner_included_ok = False
    if out_header is not None and out_rows is not None and expected_backlog:
        if len(out_rows) == len(expected_backlog):
            ranking_ok = True
            values_ok = True
            owner_included_ok = True
            for i, (o, exp) in enumerate(zip(out_rows, expected_backlog)):
                if o.get("feature_id", "").strip() != exp["feature_id"]:
                    ranking_ok = False
                try:
                    rank_val = int(str(o.get("rank", "")).strip())
                except Exception:
                    rank_val = None
                if rank_val != exp["rank"]:
                    ranking_ok = False
                if o.get("title", "").strip() != exp["title"]:
                    values_ok = False
                if o.get("feature_type", "").strip() != exp["feature_type"]:
                    values_ok = False
                imp = parse_float(str(o.get("impact_score", "")).strip())
                conf = parse_float(str(o.get("confidence", "")).strip())
                eff = parse_float(str(o.get("effort_estimate", "")).strip())
                if imp is None or conf is None or eff is None:
                    values_ok = False
                else:
                    if abs(imp - exp["impact_score"]) > 1e-9:
                        values_ok = False
                    if abs(conf - exp["confidence"]) > 1e-9:
                        values_ok = False
                    if abs(eff - exp["effort_estimate"]) > 1e-9:
                        values_ok = False
                ps_str = str(o.get("priority_score", "")).strip()
                ps_num = parse_float(ps_str)
                if ps_num is None or abs(ps_num - exp["priority_score"]) > 1e-9:
                    values_ok = False
                if o.get("owner_function", "").strip() != exp["owner_function"]:
                    owner_included_ok = False
                if o.get("included_in_v1", "").strip() != exp["included_in_v1"]:
                    owner_included_ok = False
    if ranking_ok:
        scores["prioritized_backlog_priority_scores_and_ranking"] = 1.0 if values_ok else 0.0
    else:
        scores["prioritized_backlog_priority_scores_and_ranking"] = 0.0
    if owner_included_ok:
        scores["prioritized_backlog_owner_and_included_flags"] = 1.0

    output_brief_path = workspace / "output" / "project_brief_updated.md"
    updated_lines = safe_read_lines(output_brief_path)
    replaced_priorities_ok = False
    bullets_ok = False
    unchanged_ok = False
    if brief_lines is not None and updated_lines is not None and expected_backlog:
        orig_start, orig_end = find_section_block(brief_lines, "## Priorities")
        upd_start, upd_end = find_section_block(updated_lines, "## Priorities")
        if orig_start is not None and orig_end is not None and upd_start is not None and upd_end is not None:
            orig_block = brief_lines[orig_start + 1:orig_end]
            if len(orig_block) == 1 and orig_block[0].strip() == "TBD":
                upd_block = updated_lines[upd_start + 1:upd_end]
                bullet_blocks = parse_bullet_blocks(upd_block)
                if len(bullet_blocks) == 3:
                    replaced_priorities_ok = True
                top3 = expected_backlog[:3]
                bullets_match = True
                if len(bullet_blocks) >= 3:
                    for block, exp in zip(bullet_blocks[:3], top3):
                        # Match header pattern somewhere in the block
                        m = re.search(
                            r"\[(F-\d+)\]\s*(.+?)\s+[—-]\s+([A-Za-z\+]+)\s*\(priority_score:\s*([0-9]+\.[0-9]{2})\)",
                            block
                        )
                        if not m:
                            bullets_match = False
                            break
                        fid, title, owner, pscore = m.groups()
                        if fid != exp["feature_id"]:
                            bullets_match = False
                            break
                        if title.strip() != exp["title"]:
                            bullets_match = False
                            break
                        if owner.strip() != exp["owner_function"]:
                            bullets_match = False
                            break
                        if pscore.strip() != format_two_decimals(exp["priority_score"]):
                            bullets_match = False
                            break
                        # Rationale numbers may be on following lines in the block
                        nums_ok = True
                        # Build patterns for impact, confidence, effort numbers
                        imp_val = str(int(exp["impact_score"])) if float(exp["impact_score"]).is_integer() else str(exp["impact_score"])
                        eff_val = str(int(exp["effort_estimate"])) if float(exp["effort_estimate"]).is_integer() else str(exp["effort_estimate"])
                        conf_val = str(exp["confidence"])
                        if re.search(r"\b" + re.escape(imp_val) + r"\b", block) is None:
                            nums_ok = False
                        if re.search(r"\b" + re.escape(conf_val) + r"\b", block) is None:
                            nums_ok = False
                        if re.search(r"\b" + re.escape(eff_val) + r"\b", block) is None:
                            nums_ok = False
                        if not nums_ok:
                            bullets_match = False
                            break
                else:
                    bullets_match = False
                bullets_ok = bullets_match
                rebuilt = updated_lines[:]
                rebuilt = rebuilt[:upd_start + 1] + ["TBD"] + rebuilt[upd_end:]
                if rebuilt == brief_lines:
                    unchanged_ok = True

    if replaced_priorities_ok:
        scores["project_brief_updated_replaced_priorities"] = 1.0
    if bullets_ok:
        scores["project_brief_bullets_top3_correct"] = 1.0
    if unchanged_ok:
        scores["project_brief_other_text_unchanged"] = 1.0

    email_path = workspace / "output" / "email_to_design_lead.txt"
    email_lines = safe_read_lines(email_path)
    if email_lines is not None:
        subj = extract_subject_line(email_lines)
        subj_ok = False
        if subj is not None and project_title is not None:
            if re.search(r"design support request", subj, flags=re.IGNORECASE) and (project_title in subj):
                subj_ok = True
        if subj_ok:
            scores["email_subject_contains_required"] = 1.0

        body_text = "\n".join(email_lines)
        approach_ok = False
        if ("output/prioritized_backlog.csv" in body_text
            and re.search(r"\bimpact\b", body_text, flags=re.IGNORECASE)
            and re.search(r"\bconfidence\b", body_text, flags=re.IGNORECASE)
            and re.search(r"\beffort\b", body_text, flags=re.IGNORECASE)):
            approach_ok = True
        if approach_ok:
            scores["email_mentions_prioritization_approach_and_backlog_path"] = 1.0

        bullets = [ln for ln in email_lines if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
        bullet_map: Dict[str, str] = {}
        for b in bullets:
            fid_match = re.search(r"\b(F-\d+)\b", b)
            if fid_match:
                bullet_map[fid_match.group(1)] = b
        email_bullets_ok = False
        if expected_backlog:
            top3 = expected_backlog[:3]
            all_present = True
            for exp in top3:
                fid = exp["feature_id"]
                if fid not in bullet_map:
                    all_present = False
                    break
                bline = bullet_map[fid]
                if exp["title"] not in bline:
                    all_present = False
                    break
                if exp["owner_function"] not in bline:
                    all_present = False
                    break
                scores_in_line = re.findall(r"\d+\.\d{2}", bline)
                if format_two_decimals(exp["priority_score"]) not in scores_in_line:
                    all_present = False
                    break
            if all_present:
                email_bullets_ok = True
        if email_bullets_ok:
            scores["email_bullets_top3_correct"] = 1.0

        if re.search(r"design support", body_text, flags=re.IGNORECASE):
            scores["email_calls_out_design_support"] = 1.0

        if (re.search(r"kickoff", body_text, flags=re.IGNORECASE)
            and re.search(r"next week", body_text, flags=re.IGNORECASE)
            and re.search(r"dependenc", body_text, flags=re.IGNORECASE)):
            scores["email_requests_kickoff_and_dependencies"] = 1.0

        if design_lead is not None and (design_lead in body_text or (design_lead.split()[0] in body_text)):
            scores["email_uses_design_lead_name"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()