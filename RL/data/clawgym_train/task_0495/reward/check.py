import csv
import json
import re
import sys
import subprocess
from io import StringIO
from pathlib import Path


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _read_csv_safe(path: Path):
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None, None
    try:
        reader = csv.reader(StringIO(content))
        rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


def _run_normalize_script(workspace: Path):
    script = workspace / "scripts" / "normalize_and_flag.py"
    posts = workspace / "input" / "posts.csv"
    flagged = workspace / "input" / "flagged_domains.json"
    if not script.exists() or not posts.exists() or not flagged.exists():
        return None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--posts", str(posts), "--flagged", str(flagged)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workspace),
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None, None
        return proc.stdout, proc.stderr
    except Exception:
        return None, None


def _emulate_normalize(workspace: Path):
    posts_path = workspace / "input" / "posts.csv"
    flagged_path = workspace / "input" / "flagged_domains.json"
    if not posts_path.exists() or not flagged_path.exists():
        return None, None
    try:
        with open(flagged_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            flagged_set = set([str(d).lower() for d in data.get("flagged_domains", [])])
    except Exception:
        return None, None

    out_csv_io = StringIO()
    writer = csv.writer(out_csv_io)
    writer.writerow(["post_id", "timestamp", "user_id", "domain", "flagged"])
    stderr_lines = []
    seen = set()
    try:
        with open(posts_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = str(row.get("post_id", "")).strip()
                if pid == "":
                    stderr_lines.append("malformed_row:missing_post_id")
                    continue
                if pid in seen:
                    stderr_lines.append(f"duplicate_post_id:{pid}")
                    continue
                seen.add(pid)
                url = (row.get("url") or "").strip()
                if "://" not in url or url == "":
                    stderr_lines.append(f"malformed_url:{pid}")
                    domain = ""
                    flagged = 0
                else:
                    from urllib.parse import urlparse

                    parsed = urlparse(url)
                    domain = parsed.netloc.lower()
                    if domain.startswith("www."):
                        domain = domain[4:]
                    flagged = 1 if domain in flagged_set else 0
                writer.writerow(
                    [
                        pid,
                        (row.get("timestamp") or "").strip(),
                        (row.get("user_id") or "").strip(),
                        domain,
                        flagged,
                    ]
                )
    except Exception:
        return None, None
    csv_out = out_csv_io.getvalue()
    stderr_out = "\n".join(stderr_lines) + ("\n" if stderr_lines else "")
    return csv_out, stderr_out


def _get_expected_normalization(workspace: Path):
    stdout, stderr = _run_normalize_script(workspace)
    if stdout is not None and stderr is not None:
        return stdout, stderr
    # Fallback to emulation
    return _emulate_normalize(workspace)


def _parse_normalized_csv_str(content: str):
    try:
        reader = csv.DictReader(StringIO(content))
        rows = []
        for row in reader:
            rows.append(
                {
                    "post_id": row.get("post_id", ""),
                    "timestamp": row.get("timestamp", ""),
                    "user_id": row.get("user_id", ""),
                    "domain": row.get("domain", ""),
                    "flagged": int(row.get("flagged", "0")),
                }
            )
        return rows
    except Exception:
        return None


def _compute_daily_aggregates(rows):
    by_date = {}
    for r in rows:
        date = r.get("timestamp", "")
        if date not in by_date:
            by_date[date] = {"total_posts": 0, "flagged_posts": 0}
        by_date[date]["total_posts"] += 1
        try:
            f = int(r.get("flagged", 0))
        except Exception:
            f = 0
        by_date[date]["flagged_posts"] += f
    result = {}
    for d, agg in by_date.items():
        total = agg["total_posts"]
        flagged = agg["flagged_posts"]
        share = (flagged / total) if total > 0 else 0.0
        result[d] = {"total_posts": total, "flagged_posts": flagged, "flagged_share": share}
    return result


def _approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _count_warnings_in_log_content(content: str):
    if content is None:
        return None
    lines = _normalize_newlines(content).split("\n")
    malformed_url = 0
    duplicate_post_id = 0
    for line in lines:
        if not line:
            continue
        if line.startswith("malformed_url:"):
            malformed_url += 1
        if line.startswith("duplicate_post_id:"):
            duplicate_post_id += 1
    return {"malformed_url": malformed_url, "duplicate_post_id": duplicate_post_id}


def _extract_ints_floats_from_line(line: str):
    # Return tuple (ints, floats)
    # Remove commas in numbers if any (unlikely)
    cleaned = line
    # Extract floats (with decimal). To avoid double counting, extract floats first, then strip them to avoid matching ints inside floats
    float_pattern = re.compile(r'[-+]?(?:\d+\.\d+|\d+\.\d*|\.\d+)')
    floats = [float(m.group(0)) for m in float_pattern.finditer(cleaned)]
    # Remove float substrings by replacing digits with spaces to preserve positions
    cleaned_for_ints = float_pattern.sub(" ", cleaned)
    int_pattern = re.compile(r'(?<![\d.])[-+]?\d+(?![\d.])')
    ints = [int(m.group(0)) for m in int_pattern.finditer(cleaned_for_ints)]
    return ints, floats


def _find_lines_with_date(report_text: str, date: str):
    report_text = _normalize_newlines(report_text)
    lines = report_text.split("\n")
    matched = []
    for i, line in enumerate(lines):
        if date in line:
            matched.append((i, line))
    return matched


def _parse_report_top_domains(report_text: str, expected_domains_counts: dict) -> bool:
    # For each expected domain, find a line containing it (case-insensitive) and extract the last integer on that line
    text = _normalize_newlines(report_text)
    lines = text.split("\n")
    found = {}
    for dom in expected_domains_counts.keys():
        pattern = re.compile(re.escape(dom), re.IGNORECASE)
        candidates = []
        for line in lines:
            if pattern.search(line):
                ints, _ = _extract_ints_floats_from_line(line)
                if ints:
                    candidates.append(ints[-1])  # prefer the last integer on the line
        if candidates:
            found[dom] = candidates[0]
    # Verify counts
    for dom, cnt in expected_domains_counts.items():
        if dom not in found:
            return False
        if found[dom] != cnt:
            return False
    return True


def _parse_report_warning_counts(report_text: str):
    text = _normalize_newlines(report_text)
    lines = text.split("\n")
    result = {}
    for key in ["malformed_url", "duplicate_post_id"]:
        key_re = re.compile(re.escape(key), re.IGNORECASE)
        value = None
        for line in lines:
            if key_re.search(line):
                ints, _ = _extract_ints_floats_from_line(line)
                if ints:
                    # Prefer the last integer on the line to avoid numbers like "top 3"
                    value = ints[-1]
                    break
        if value is not None:
            result[key] = value
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "deliverables_present": 0.0,
        "normalized_csv_exact_match": 0.0,
        "normalize_stderr_exact_match": 0.0,
        "summary_csv_header_and_schema": 0.0,
        "summary_csv_values_correct": 0.0,
        "report_daily_summaries_correct": 0.0,
        "report_top3_flagged_domains_correct": 0.0,
        "report_warning_counts_correct": 0.0,
    }

    out_dir = workspace / "out"
    normalized_csv_path = out_dir / "normalized_posts.csv"
    normalize_stderr_path = out_dir / "normalize_stderr.log"
    summary_csv_path = out_dir / "flagged_summary_by_day.csv"
    report_path = out_dir / "report.txt"

    # Check deliverables exist
    if all(p.exists() for p in [normalized_csv_path, normalize_stderr_path, summary_csv_path, report_path]):
        scores["deliverables_present"] = 1.0

    # Compute expected normalization using provided script (or emulate)
    expected_stdout, expected_stderr = _get_expected_normalization(workspace)
    expected_stdout_norm = _normalize_newlines(expected_stdout) if expected_stdout is not None else None
    expected_stderr_norm = _normalize_newlines(expected_stderr) if expected_stderr is not None else None

    # Check normalized CSV exact match
    if normalized_csv_path.exists() and expected_stdout_norm is not None:
        actual = _read_text_safe(normalized_csv_path)
        if actual is not None:
            actual_norm = _normalize_newlines(actual)
            if actual_norm == expected_stdout_norm:
                scores["normalized_csv_exact_match"] = 1.0

    # Check normalize stderr exact match
    if normalize_stderr_path.exists() and expected_stderr_norm is not None:
        actual = _read_text_safe(normalize_stderr_path)
        if actual is not None:
            actual_norm = _normalize_newlines(actual)
            if actual_norm == expected_stderr_norm:
                scores["normalize_stderr_exact_match"] = 1.0

    # Check summary CSV header and schema
    if summary_csv_path.exists():
        header, data = _read_csv_safe(summary_csv_path)
        if header is not None and data is not None:
            expected_header = ["date", "total_posts", "flagged_posts", "flagged_share"]
            header_ok = header == expected_header
            schema_ok = True
            date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
            for row in data:
                if len(row) != 4:
                    schema_ok = False
                    break
                date_s, total_s, flagged_s, share_s = row
                if not date_re.match(date_s):
                    schema_ok = False
                    break
                try:
                    int(total_s)
                    int(flagged_s)
                except Exception:
                    schema_ok = False
                    break
                try:
                    float(share_s)
                except Exception:
                    schema_ok = False
                    break
            if header_ok and schema_ok:
                scores["summary_csv_header_and_schema"] = 1.0

    # Check summary values correctness against expected normalization
    if summary_csv_path.exists() and expected_stdout is not None:
        header, data = _read_csv_safe(summary_csv_path)
        if header is not None and data is not None and header == ["date", "total_posts", "flagged_posts", "flagged_share"]:
            # Expected aggregates
            expected_rows = _parse_normalized_csv_str(expected_stdout)
            if expected_rows is not None:
                expected_aggs = _compute_daily_aggregates(expected_rows)
                # Parse student's summary
                student_aggs = {}
                try:
                    for row in data:
                        date_s, total_s, flagged_s, share_s = row
                        student_aggs[date_s] = {
                            "total_posts": int(total_s),
                            "flagged_posts": int(flagged_s),
                            "flagged_share": float(share_s),
                        }
                except Exception:
                    student_aggs = None
                if student_aggs is not None:
                    # Compare sets of dates
                    if set(student_aggs.keys()) == set(expected_aggs.keys()):
                        correct = True
                        for d, exp in expected_aggs.items():
                            stu = student_aggs.get(d)
                            if stu is None:
                                correct = False
                                break
                            if not (stu["total_posts"] == exp["total_posts"] and stu["flagged_posts"] == exp["flagged_posts"]):
                                correct = False
                                break
                            if not _approx_equal(stu["flagged_share"], exp["flagged_share"], tol=1e-6):
                                correct = False
                                break
                        if correct:
                            scores["summary_csv_values_correct"] = 1.0

    # Report checks
    report_text = _read_text_safe(report_path) if report_path.exists() else None
    if report_text is not None and expected_stdout is not None:
        # Compute expected aggregates for dates
        expected_rows = _parse_normalized_csv_str(expected_stdout)
        expected_aggs = _compute_daily_aggregates(expected_rows) if expected_rows is not None else None

        # Daily summaries (one line per date with correct metrics)
        daily_ok = False
        if expected_aggs is not None:
            all_ok = True
            for date, exp in expected_aggs.items():
                matches = _find_lines_with_date(report_text, date)
                # Require exactly one line per date
                if len(matches) != 1:
                    all_ok = False
                    break
                _, line = matches[0]
                # Remove date from line to avoid picking date numbers
                line_wo_date = line.replace(date, " ")
                ints, floats = _extract_ints_floats_from_line(line_wo_date)
                # Check presence of expected ints
                if exp["total_posts"] not in ints or exp["flagged_posts"] not in ints:
                    all_ok = False
                    break
                # Check flagged_share present as float
                # If no float present, allow exact integer 0 or 1 for edge cases
                found_share = False
                for f in floats:
                    if _approx_equal(f, exp["flagged_share"], tol=1e-6):
                        found_share = True
                        break
                if not found_share:
                    # Sometimes share might be formatted as int-like 0 or 1; allow if exactly equal and floats list empty
                    if len(floats) == 0 and (exp["flagged_share"] in (0.0, 1.0)) and (int(exp["flagged_share"]) in ints):
                        found_share = True
                if not found_share:
                    all_ok = False
                    break
            daily_ok = all_ok
        if daily_ok:
            scores["report_daily_summaries_correct"] = 1.0

        # Top 3 flagged domains with counts
        top_ok = False
        if expected_rows is not None:
            counts = {}
            for r in expected_rows:
                if int(r.get("flagged", 0)) == 1:
                    dom = r.get("domain", "")
                    counts[dom] = counts.get(dom, 0) + 1
            # Sort and take top 3
            top_items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            expected_top = dict(top_items)
            if expected_top:
                if _parse_report_top_domains(report_text, expected_top):
                    top_ok = True
        if top_ok:
            scores["report_top3_flagged_domains_correct"] = 1.0

        # Warning counts from log vs report
        log_content = _read_text_safe(normalize_stderr_path) if normalize_stderr_path.exists() else None
        log_counts = _count_warnings_in_log_content(log_content) if log_content is not None else None
        if log_counts is not None:
            rep_counts = _parse_report_warning_counts(report_text)
            if rep_counts is not None:
                if (
                    rep_counts.get("malformed_url") == log_counts.get("malformed_url")
                    and rep_counts.get("duplicate_post_id") == log_counts.get("duplicate_post_id")
                ):
                    scores["report_warning_counts_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()