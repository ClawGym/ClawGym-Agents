import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize keys by stripping spaces just in case
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows
    except Exception:
        return None


def _discover_case_files(workspace: Path) -> List[Path]:
    base = workspace / "input" / "case_updates"
    if not base.exists() or not base.is_dir():
        return []
    files = []
    for p in sorted(base.iterdir(), key=lambda x: x.name):
        if p.is_file() and p.name.lower().startswith("case_updates_") and p.suffix.lower() == ".csv":
            files.append(p)
    return files


def _parse_date(s: str) -> Optional[datetime]:
    try:
        # Expecting YYYY-MM-DD
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _to_int(s: str) -> Optional[int]:
    try:
        return int(float(s.strip()))
    except Exception:
        return None


def _compute_expected_filtered(files: List[Path]) -> Tuple[List[Dict[str, str]], int]:
    records: List[Dict[str, str]] = []
    total_count = 0
    for p in files:
        rows = _load_csv_dicts(p)
        if rows is None:
            # Malformed file -> treat as zero contribution and mark later checks via comparisons
            return ([], 0)
        for r in rows:
            status = r.get("status", "").strip()
            child_involved = r.get("child_involved", "").strip()
            immigration_pathway = r.get("immigration_pathway", "").strip()
            if status == "open" and child_involved == "TRUE" and immigration_pathway in {"asylum", "temporary_protection"}:
                total_count += 1
                records.append(r)
    # Sort by risk_score desc, then last_update desc, then case_id asc
    def sort_key(r: Dict[str, str]):
        rs = _to_int(r.get("risk_score", ""))
        # Higher first -> use negative
        rs_key = -(rs if rs is not None else -10**9)
        dt = _parse_date(r.get("last_update", "") or "")
        # later first -> use timestamp negative
        dt_key = -(dt.timestamp() if dt is not None else -10**12)
        cid = r.get("case_id", "")
        return (rs_key, dt_key, cid)
    records_sorted = sorted(records, key=sort_key)
    return (records_sorted, total_count)


def _expected_top5_rows(records_sorted: List[Dict[str, str]]) -> List[Dict[str, str]]:
    cols = ["case_id", "region", "status", "child_involved", "category", "immigration_pathway", "risk_score", "last_update", "language", "summary"]
    top = records_sorted[:5]
    out = []
    for r in top:
        out.append({c: (r.get(c, "") if r.get(c, "") is not None else "") for c in cols})
    return out


def _load_output_top5(workspace: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    out_path = workspace / "output" / "top5_cases.csv"
    if not out_path.exists():
        return (None, None)
    try:
        with out_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return ([], [])
        header = [h.strip() for h in rows[0]]
        dict_rows: List[Dict[str, str]] = []
        for row in rows[1:]:
            # pad or truncate row to header length
            padded = row + [""] * (len(header) - len(row))
            mapped = {header[i]: (padded[i].strip() if i < len(padded) else "") for i in range(len(header))}
            dict_rows.append(mapped)
        return (header, dict_rows)
    except Exception:
        return (None, None)


def _load_processed_files_list(workspace: Path) -> Optional[List[str]]:
    p = workspace / "output" / "processed_files.txt"
    if not p.exists():
        return None
    content = _read_text_safe(p)
    if content is None:
        return None
    lines = [ln.strip().replace("\\", "/") for ln in content.splitlines() if ln.strip() != ""]
    return lines


def _dominant_region(top5: List[Dict[str, str]]) -> Optional[str]:
    if not top5:
        return None
    freq: Dict[str, int] = {}
    for r in top5:
        region = (r.get("region") or "").strip()
        freq[region] = freq.get(region, 0) + 1
    max_count = max(freq.values())
    candidates = sorted([k for k, v in freq.items() if v == max_count])
    return candidates[0] if candidates else None


def _extract_bullets(body: str) -> List[str]:
    bullets = []
    for ln in body.splitlines():
        s = ln.lstrip()
        for prefix in ["- ", "* ", "• ", "– ", "— "]:
            if s.startswith(prefix):
                bullets.append(s[len(prefix):].strip())
                break
    return bullets


def _first_nonempty_nonbullet_line(body: str) -> Optional[str]:
    for ln in body.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("Data sources:"):
            # This is footer
            continue
        # if bullet, skip
        if any(s.startswith(pref) for pref in ["- ", "* ", "• ", "– ", "— "]):
            continue
        return s
    return None


def _last_nonempty_line(text: str) -> Optional[str]:
    for ln in reversed(text.splitlines()):
        if ln.strip():
            return ln.strip()
    return None


def _normalize_expected_row(r: Dict[str, str]) -> Dict[str, str]:
    out = {}
    for k, v in r.items():
        if v is None:
            out[k] = ""
        else:
            if k == "risk_score":
                # Ensure integer-like string
                iv = _to_int(str(v))
                out[k] = str(iv) if iv is not None else str(v).strip()
            else:
                out[k] = str(v).strip()
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "processed_files_listed_correct": 0.0,
        "top5_cases_header_correct": 0.0,
        "top5_cases_rows_correct_and_sorted": 0.0,
        "email_subject_dominant_region_correct": 0.0,
        "email_body_word_limit": 0.0,
        "email_intro_total_count_correct": 0.0,
        "email_bulleted_top3_correct": 0.0,
        "email_required_phrases_present": 0.0,
        "email_data_sources_line_correct": 0.0,
    }

    # Discover inputs and compute expected outputs
    case_files = _discover_case_files(workspace)
    expected_rel_paths = [str(p.relative_to(workspace)).replace("\\", "/") for p in case_files]
    expected_rel_paths_set = set(expected_rel_paths)
    expected_filenames = [p.name for p in case_files]
    expected_filenames_set = set(expected_filenames)

    expected_records_sorted, total_filtered_count = _compute_expected_filtered(case_files)
    expected_top5 = _expected_top5_rows(expected_records_sorted)
    expected_cols = ["case_id", "region", "status", "child_involved", "category", "immigration_pathway", "risk_score", "last_update", "language", "summary"]

    # Check processed_files.txt
    processed_lines = _load_processed_files_list(workspace)
    if processed_lines is not None:
        # Accept set equality, no extras, and each line relative with input/case_updates/
        processed_set = set(processed_lines)
        if processed_set == expected_rel_paths_set and all(ln.startswith("input/case_updates/") and not ln.startswith("/") for ln in processed_lines):
            scores["processed_files_listed_correct"] = 1.0

    # Check top5_cases.csv
    header, rows = _load_output_top5(workspace)
    if header is not None and rows is not None:
        # Header
        if header == expected_cols:
            scores["top5_cases_header_correct"] = 1.0
        # Rows and sort/order/content
        expected_norm_rows = [_normalize_expected_row(r) for r in expected_top5]
        if header == expected_cols:
            # Normalize student's rows to strings
            student_rows_norm = []
            for r in rows:
                row_norm = {}
                for c in expected_cols:
                    v = r.get(c, "")
                    if c == "risk_score":
                        iv = _to_int(str(v)) if v is not None else None
                        row_norm[c] = str(iv) if iv is not None else (str(v).strip() if v is not None else "")
                    else:
                        row_norm[c] = (str(v).strip() if v is not None else "")
                student_rows_norm.append(row_norm)
            # Student must provide exactly min(5, total_filtered_count) rows
            expected_len = min(5, len(expected_norm_rows))
            if len(student_rows_norm) == expected_len and student_rows_norm == expected_norm_rows[:expected_len]:
                scores["top5_cases_rows_correct_and_sorted"] = 1.0

    # Email checks
    email_path = workspace / "output" / "email_to_taskforce_en.txt"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        lines = email_text.splitlines()
        first_line = lines[0].strip() if lines else ""
        dominant = _dominant_region(expected_top5)
        if dominant:
            expected_subject = f"Subject: Weekly Child Welfare Risk Brief — {dominant}"
            if first_line == expected_subject:
                scores["email_subject_dominant_region_correct"] = 1.0
        # Body under 180 words
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        # Count words in body
        word_count = len([w for w in re.findall(r"\b\w+\b", body)])
        if word_count <= 180 and word_count > 0:
            scores["email_body_word_limit"] = 1.0

        # Intro sentence stating total filtered open cases (first non-empty, non-bullet, non-footer line)
        intro_line = _first_nonempty_nonbullet_line(body)
        if intro_line and total_filtered_count > 0:
            if re.search(rf"\b{total_filtered_count}\b", intro_line) and re.search(r"\bcases?\b", intro_line, flags=re.IGNORECASE) and re.search(r"\bopen\b", intro_line, flags=re.IGNORECASE):
                scores["email_intro_total_count_correct"] = 1.0
        elif intro_line and total_filtered_count == 0:
            # If no expected cases, allow "0" open cases in intro line
            if re.search(r"\b0\b", intro_line) and re.search(r"\bcases?\b", intro_line, flags=re.IGNORECASE) and re.search(r"\bopen\b", intro_line, flags=re.IGNORECASE):
                scores["email_intro_total_count_correct"] = 1.0

        # Bulleted list of exactly top 3 cases by rank (format: case_id | category | risk_score)
        bullets = _extract_bullets(body)
        if len(bullets) == min(3, len(expected_top5)):
            ok = True
            for i in range(min(3, len(expected_top5))):
                exp = expected_top5[i]
                exp_line = f"{exp['case_id']} | {exp['category']} | {str(_to_int(exp['risk_score']) if _to_int(exp['risk_score']) is not None else exp['risk_score']).strip()}"
                if bullets[i] != exp_line:
                    ok = False
                    break
            if ok and len(bullets) == 3:
                scores["email_bulleted_top3_correct"] = 1.0

        # Required phrases
        body_lower = body.lower()
        if all(phrase in body_lower for phrase in ["family separation", "guardianship", "language access"]):
            scores["email_required_phrases_present"] = 1.0

        # Data sources footer as last non-empty line with filenames (not paths)
        last_line = _last_nonempty_line(email_text)
        if last_line and last_line.startswith("Data sources:"):
            after = last_line[len("Data sources:"):].strip()
            # Split by commas
            names = [n.strip() for n in after.split(",") if n.strip() != ""]
            # Ensure no path separators
            if all("/" not in n and "\\" not in n for n in names):
                if set(names) == expected_filenames_set and len(names) == len(expected_filenames_set):
                    scores["email_data_sources_line_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()