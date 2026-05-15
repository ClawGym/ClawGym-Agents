import csv
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


EXPECTED_HEADER = ['Name', 'Tradition', 'Order', 'Region', 'BirthYear', 'DeathYear']


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = [row for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def write_csv(path: Path, header: List[str], rows: List[Dict[str, str]]) -> bool:
    try:
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return True
    except Exception:
        return False


def clean_year_value(val: str) -> str:
    if val is None:
        return ""
    digits = "".join(ch for ch in str(val) if ch.isdigit())
    return digits if digits != "" else ""


def compute_ages(rows: List[Dict[str, str]]) -> List[int]:
    ages = []
    for r in rows:
        by = (r.get('BirthYear') or '').strip()
        dy = (r.get('DeathYear') or '').strip()
        if by != "" and dy != "":
            try:
                b = int(by)
                d = int(dy)
            except Exception:
                continue
            if d >= b:
                ages.append(d - b)
    return ages


def compute_summary_metrics(rows: List[Dict[str, str]]) -> Dict[str, str]:
    total_records = len(rows)
    missing_birth = 0
    missing_death = 0
    complete = 0
    ages = []
    for r in rows:
        by = (r.get('BirthYear') or '').strip()
        dy = (r.get('DeathYear') or '').strip()
        if by == "":
            missing_birth += 1
        if dy == "":
            missing_death += 1
        if by != "" and dy != "":
            try:
                b = int(by)
                d = int(dy)
            except Exception:
                continue
            if d >= b:
                complete += 1
                ages.append(d - b)
    if ages:
        avg = sum(ages) / len(ages)
        avg_rounded = round(avg * 10) / 10.0
        ages_sorted = sorted(ages)
        n = len(ages_sorted)
        if n % 2 == 1:
            median_val = float(ages_sorted[n // 2])
        else:
            median_val = (ages_sorted[n // 2 - 1] + ages_sorted[n // 2]) / 2.0
        median_rounded = round(median_val * 10) / 10.0
    else:
        avg_rounded = 0.0
        median_rounded = 0.0
    return {
        "total_records": str(total_records),
        "complete_life_records": str(complete),
        "missing_birthyear_count": str(missing_birth),
        "missing_deathyear_count": str(missing_death),
        "average_age_at_death": f"{avg_rounded:.1f}",
        "median_age_at_death": f"{median_rounded:.1f}",
    }


def compute_birth_century_counts(rows: List[Dict[str, str]]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for r in rows:
        by = (r.get('BirthYear') or '').strip()
        if by == "":
            continue
        try:
            b = int(by)
        except Exception:
            continue
        century = 1 + (b - 1) // 100
        counts[century] = counts.get(century, 0) + 1
    return counts


def parse_summary_csv(path: Path) -> Optional[Dict[str, str]]:
    header, rows = load_csv(path)
    if header is None or rows is None:
        return None
    if header != ["Key", "Value"]:
        return None
    out: Dict[str, str] = {}
    for r in rows:
        k = r.get("Key")
        v = r.get("Value")
        if k is None or v is None:
            return None
        if k in out:
            return None
        out[k] = v.strip()
    return out


def parse_birth_century_csv(path: Path) -> Optional[List[Tuple[int, int]]]:
    header, rows = load_csv(path)
    if header is None or rows is None:
        return None
    if header != ["Century", "Count"]:
        return None
    parsed: List[Tuple[int, int]] = []
    for r in rows:
        c = r.get("Century")
        cnt = r.get("Count")
        if c is None or cnt is None:
            return None
        try:
            ci = int(c.strip())
            cni = int(cnt.strip())
        except Exception:
            return None
        parsed.append((ci, cni))
    # check sorting by Century ascending
    if parsed != sorted(parsed, key=lambda x: x[0]):
        return None
    return parsed


def extract_notes_section(text: str) -> Optional[str]:
    lines = text.splitlines()
    idx = None
    # Identify a "Notes" section header line
    for i, line in enumerate(lines):
        if re.match(r'^\s{0,3}#{0,6}\s*Notes\b[:\s]*', line, flags=re.IGNORECASE):
            idx = i
            break
    if idx is None:
        # Try to find a standalone "Notes:" line
        for i, line in enumerate(lines):
            if re.match(r'^\s*Notes\s*:?\s*$', line, flags=re.IGNORECASE):
                idx = i
                break
    if idx is None:
        return None
    # Capture content until next header or EOF
    content_lines: List[str] = []
    for j in range(idx + 1, len(lines)):
        if re.match(r'^\s{0,3}#{1,6}\s+\S', lines[j]):
            break
        content_lines.append(lines[j])
    content = "\n".join(content_lines).strip()
    return content if content else None


def count_sentences(text: str) -> int:
    # Split by sentence terminators . ! ?
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    # Filter out empty fragments
    count = 0
    for p in parts:
        if re.search(r'[A-Za-z0-9]', p):
            count += 1
    return count


def run_validator(validator_path: Path, csv_path: Path) -> Tuple[bool, Optional[str]]:
    if not validator_path.exists() or not csv_path.exists():
        return False, None
    try:
        proc = subprocess.run(
            [sys.executable, str(validator_path), str(csv_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=validator_path.parent.parent  # run from workspace root
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        ok = "PASS: validated" in output and proc.returncode == 0
        return ok, output
    except Exception:
        return False, None


def top_three_centuries(counts: Dict[int, int]) -> List[Tuple[int, int]]:
    # Sort by Count desc, Century asc
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:3]


def sentence_contains_tokens(sentence: str, tokens: List[str]) -> bool:
    s = sentence.lower()
    for t in tokens:
        if re.search(r'\b' + re.escape(t.lower()) + r'\b', s) is None:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "validation_log_exists": 0.0,
        "validation_log_contains_initial_error": 0.0,
        "validation_log_contains_notes_2_4_sentences": 0.0,
        "validation_log_contains_revalidation_pass": 0.0,
        "cleaned_csv_exists_and_header": 0.0,
        "cleaned_rows_preserve_non_year_columns_and_clean_years": 0.0,
        "revalidation_pass_on_cleaned_file": 0.0,
        "summary_metrics_correct": 0.0,
        "birth_century_counts_correct": 0.0,
        "email_exists_and_wordcount": 0.0,
        "email_mentions_attachments": 0.0,
        "email_reports_total_and_median": 0.0,
        "email_lists_top_three_centuries_with_counts": 0.0,
    }

    # Paths
    input_csv = workspace / "input" / "biographies.csv"
    validator_py = workspace / "tools" / "validate_records.py"
    validation_log = workspace / "output" / "validation_log.md"
    cleaned_csv = workspace / "output" / "biographies_clean.csv"
    summary_csv = workspace / "output" / "summary_metrics.csv"
    century_csv = workspace / "output" / "birth_century_counts.csv"
    email_txt = workspace / "output" / "email_to_colleague.txt"

    # 1) Validation log checks
    log_text = read_text_safe(validation_log)
    if log_text is not None:
        scores["validation_log_exists"] = 1.0
        # initial error presence
        if re.search(r'ERROR', log_text):
            scores["validation_log_contains_initial_error"] = 1.0
        # notes section with 2-4 sentences
        notes = extract_notes_section(log_text)
        if notes is not None:
            sent_count = count_sentences(notes)
            if 2 <= sent_count <= 4:
                scores["validation_log_contains_notes_2_4_sentences"] = 1.0
        # PASS appended with validated N rows
        m = re.search(r'PASS:\s*validated\s+(\d+)\s+rows', log_text)
        if m:
            try:
                pass_rows = int(m.group(1))
            except Exception:
                pass_rows = None
            # If cleaned file exists, verify counts match
            header_c, rows_c = load_csv(cleaned_csv)
            if header_c is not None and rows_c is not None and pass_rows == len(rows_c):
                scores["validation_log_contains_revalidation_pass"] = 1.0
            elif header_c is None or rows_c is None:
                # If cleaned file not present, at least PASS is present
                scores["validation_log_contains_revalidation_pass"] = 1.0
    # 2) Cleaned CSV checks vs input
    header_in, rows_in = load_csv(input_csv)
    header_out, rows_out = load_csv(cleaned_csv)

    if header_out == EXPECTED_HEADER and rows_out is not None:
        scores["cleaned_csv_exists_and_header"] = 1.0

    if header_in is not None and rows_in is not None and header_out is not None and rows_out is not None:
        if len(rows_in) == len(rows_out):
            # Check row-by-row, preserving non-year columns and cleaning rules on years
            ok = True
            for rin, rout in zip(rows_in, rows_out):
                for col in EXPECTED_HEADER:
                    if col not in rin or col not in rout:
                        ok = False
                        break
                if not ok:
                    break
                # Non-year columns must match exactly
                for col in ['Name', 'Tradition', 'Order', 'Region']:
                    if (rin.get(col) or "").strip() != (rout.get(col) or "").strip():
                        ok = False
                        break
                if not ok:
                    break
                # Year cleaning rule
                by_in = (rin.get('BirthYear') or '')
                dy_in = (rin.get('DeathYear') or '')
                by_expected = clean_year_value(by_in)
                dy_expected = clean_year_value(dy_in)
                by_out = (rout.get('BirthYear') or '').strip()
                dy_out = (rout.get('DeathYear') or '').strip()
                # Out must be digits-only or blank
                if by_out != "" and not by_out.isdigit():
                    ok = False
                    break
                if dy_out != "" and not dy_out.isdigit():
                    ok = False
                    break
                # Match expected cleaned values
                if by_out != by_expected or dy_out != dy_expected:
                    ok = False
                    break
            if ok:
                scores["cleaned_rows_preserve_non_year_columns_and_clean_years"] = 1.0

    # 2b) Revalidation of cleaned via running validator (deterministic subprocess)
    if validator_py.exists() and cleaned_csv.exists():
        ok_run, output = run_validator(validator_py, cleaned_csv)
        if ok_run:
            # Validate row count in PASS line
            m2 = re.search(r'PASS:\s*validated\s+(\d+)\s+rows', output or "")
            if m2:
                try:
                    n_validated = int(m2.group(1))
                except Exception:
                    n_validated = -1
            else:
                n_validated = -1
            _, rows_out_tmp = load_csv(cleaned_csv)
            if rows_out_tmp is not None and n_validated == len(rows_out_tmp):
                scores["revalidation_pass_on_cleaned_file"] = 1.0

    # 3) Aggregates and statistics checks
    # Compute expected metrics from cleaned CSV
    if header_out is not None and rows_out is not None and header_out == EXPECTED_HEADER:
        expected_metrics = compute_summary_metrics(rows_out)
        parsed_summary = parse_summary_csv(summary_csv)
        if parsed_summary is not None:
            required_keys = {
                "total_records",
                "complete_life_records",
                "missing_birthyear_count",
                "missing_deathyear_count",
                "average_age_at_death",
                "median_age_at_death",
            }
            if set(parsed_summary.keys()) == required_keys:
                # Compare values exactly as deterministic strings (floats have one decimal)
                match = True
                for k, v in expected_metrics.items():
                    if parsed_summary.get(k) != v:
                        match = False
                        break
                if match:
                    scores["summary_metrics_correct"] = 1.0

        # Birth century counts
        expected_counts = compute_birth_century_counts(rows_out)
        parsed_centuries = parse_birth_century_csv(century_csv)
        if parsed_centuries is not None:
            expected_sorted = sorted(expected_counts.items(), key=lambda kv: kv[0])
            parsed_dict = dict(parsed_centuries)
            if len(parsed_dict) == len(expected_counts):
                match_counts = True
                # ensure equality for every century
                for c, cnt in expected_counts.items():
                    if parsed_dict.get(c) != cnt:
                        match_counts = False
                        break
                # also ensure no extra keys
                if match_counts and set(parsed_dict.keys()) == set(expected_counts.keys()):
                    scores["birth_century_counts_correct"] = 1.0

    # 4) Email checks
    email_text = read_text_safe(email_txt)
    if email_text is not None:
        words = re.findall(r'\b\w+\b', email_text)
        wc = len(words)
        if 120 <= wc <= 200:
            scores["email_exists_and_wordcount"] = 1.0
        # Subject line
        # Not a separate score but part of existence check; ensure presence for later checks
        has_subject = any(re.match(r'^\s*Subject\s*:\s*', line, flags=re.IGNORECASE) for line in email_text.splitlines())

        # Attachments mention
        attachments = [
            "output/biographies_clean.csv",
            "output/summary_metrics.csv",
            "output/birth_century_counts.csv",
            "output/validation_log.md",
        ]
        if all(att in email_text for att in attachments) and has_subject:
            scores["email_mentions_attachments"] = 1.0

        # compute numbers for verification from cleaned outputs (if available)
        if header_out is not None and rows_out is not None:
            metrics = compute_summary_metrics(rows_out)
            total_val = metrics["total_records"]
            median_val = metrics["median_age_at_death"]
            # Split into sentences
            sentences = re.split(r'(?<=[.!?])\s+', email_text.strip())
            # Check total mention: sentence with 'total' or 'records' and the number
            total_ok = False
            for s in sentences:
                if re.search(r'\b(total|records?)\b', s, flags=re.IGNORECASE) and re.search(r'\b' + re.escape(total_val) + r'\b', s):
                    total_ok = True
                    break
            # Check median mention: sentence with 'median' and the number
            median_ok = False
            for s in sentences:
                if re.search(r'\bmedian\b', s, flags=re.IGNORECASE) and re.search(r'\b' + re.escape(median_val) + r'\b', s):
                    median_ok = True
                    break
            if total_ok and median_ok:
                scores["email_reports_total_and_median"] = 1.0

            # Check top three centuries with counts listed
            counts = compute_birth_century_counts(rows_out)
            top3 = top_three_centuries(counts)
            # Each pair must appear in at least one sentence containing both numbers
            sentences_lower = sentences
            pair_ok = True
            for (cent, cnt) in top3:
                found = False
                cent_tok = str(cent)
                cnt_tok = str(cnt)
                for s in sentences_lower:
                    if re.search(r'\b' + re.escape(cent_tok) + r'\b', s) and re.search(r'\b' + re.escape(cnt_tok) + r'\b', s):
                        found = True
                        break
                if not found:
                    pair_ok = False
                    break
            if pair_ok:
                scores["email_lists_top_three_centuries_with_counts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()