import sys
import json
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_recipients(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader]
        mapping = {}
        for r in rows:
            fn = (r.get("file_name") or "").strip()
            if not fn:
                return None
            mapping[fn] = {
                "student_name": (r.get("student_name") or "").strip(),
                "email": (r.get("email") or "").strip(),
            }
        return mapping
    except Exception:
        return None


def parse_rubric_yaml(path: Path) -> Optional[Dict]:
    text = read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    i = 0
    n = len(lines)

    weights: Dict[str, float] = {}
    subject_prefix = None
    thresholds = {
        "minor_revision": None,
        "moderate_revision": None,
        "major_revision": None,
    }

    def clean_line(s: str) -> str:
        return s.rstrip("\n").rstrip("\r")

    # Parse criteria weights
    while i < n:
        line = clean_line(lines[i])
        if re.match(r"^criteria:\s*$", line):
            i += 1
            while i < n:
                line = clean_line(lines[i])
                if re.match(r"^\w", line) and not line.startswith(" "):
                    break
                m = re.match(r"^\s{2}([A-Za-z0-9_]+):\s*$", line)
                if m:
                    crit = m.group(1)
                    i += 1
                    while i < n:
                        sub = clean_line(lines[i])
                        if re.match(r"^\s{2}[A-Za-z0-9_]+:\s*$", sub) or (re.match(r"^\w", sub) and not sub.startswith(" ")):
                            i -= 1
                            break
                        wm = re.match(r"^\s{4}weight:\s*([0-9.]+)\s*$", sub)
                        if wm:
                            try:
                                weights[crit] = float(wm.group(1))
                            except Exception:
                                return None
                        i += 1
                i += 1
            continue
        i += 1

    # Parse decision thresholds nested under scoring: decision_thresholds:
    i = 0
    while i < n:
        line = clean_line(lines[i])
        if re.match(r"^\s*decision_thresholds:\s*$", line):
            i += 1
            while i < n:
                sub = clean_line(lines[i])
                if re.match(r"^\s*[A-Za-z_]+:\s*", sub):
                    if "minor_revision" in sub:
                        nums = re.findall(r"([0-9]+(?:\.[0-9]+)?)", sub)
                        if nums:
                            try:
                                thresholds["minor_revision"] = float(nums[-1])
                            except Exception:
                                return None
                    elif "moderate_revision" in sub:
                        nums = re.findall(r"([0-9]+(?:\.[0-9]+)?)", sub)
                        if len(nums) >= 2:
                            try:
                                thresholds["moderate_revision"] = (float(nums[0]), float(nums[1]))
                            except Exception:
                                return None
                    elif "major_revision" in sub:
                        nums = re.findall(r"([0-9]+(?:\.[0-9]+)?)", sub)
                        if nums:
                            try:
                                thresholds["major_revision"] = float(nums[-1])
                            except Exception:
                                return None
                elif re.match(r"^\w", sub) and not sub.startswith(" "):
                    break
                i += 1
            break
        i += 1

    # Parse subject_prefix
    i = 0
    while i < n:
        line = clean_line(lines[i])
        if re.match(r"^email_requirements:\s*$", line):
            i += 1
            while i < n:
                sub = clean_line(lines[i])
                sp = re.match(r"^\s{2}subject_prefix:\s*\"?(.*?)\"?\s*$", sub)
                if sp:
                    subject_prefix = sp.group(1)
                    break
                if re.match(r"^\w", sub) and not sub.startswith(" "):
                    break
                i += 1
            break
        i += 1

    if not weights:
        return None
    if thresholds["minor_revision"] is None:
        thresholds["minor_revision"] = 4.0
    if thresholds["moderate_revision"] is None:
        thresholds["moderate_revision"] = (3.0, 4.0)
    if thresholds["major_revision"] is None:
        thresholds["major_revision"] = 3.0
    if subject_prefix is None:
        subject_prefix = "Preliminary feedback on your draft:"

    return {
        "weights": weights,
        "thresholds": thresholds,
        "subject_prefix": subject_prefix,
    }


def extract_title_from_md(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().startswith("#"):
            title = line.strip().lstrip("#").strip()
            if title:
                return title
    return None


def extract_title_from_txt(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()
            if title:
                return title
    return None


def extract_titles_for_submissions(submissions_dir: Path, file_names: List[str]) -> Optional[Dict[str, str]]:
    titles: Dict[str, str] = {}
    for file_name in file_names:
        p = submissions_dir / file_name
        content = read_text_safe(p)
        if content is None:
            return None
        if file_name.lower().endswith(".md"):
            title = extract_title_from_md(content)
        elif file_name.lower().endswith(".txt"):
            title = extract_title_from_txt(content)
        else:
            title = None
        if not title:
            return None
        titles[file_name] = title
    return titles


def read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f2:
            reader = csv.reader(f2)
            row = next(reader)
            return row
    except Exception:
        return None


def read_reviews_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader]
        return rows
    except Exception:
        return None


def canonicalize_decision(decision: str) -> str:
    d = (decision or "").strip().lower()
    if "minor" in d:
        return "minor revision"
    if "moderate" in d:
        return "moderate revision"
    if "major" in d:
        return "major revision"
    return d


def expected_decision_from_total(total: float, thresholds: Dict) -> str:
    minor_th = thresholds["minor_revision"]
    moderate_low, moderate_high = thresholds["moderate_revision"]
    major_th = thresholds["major_revision"]
    if total >= minor_th:
        return "minor revision"
    elif total >= moderate_low and total < moderate_high:
        return "moderate revision"
    elif total < major_th:
        return "major revision"
    return "major revision"


def lastname_from_student_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    parts = name.split()
    last = parts[-1]
    last = last.replace(".", "")
    if last:
        return last[0].upper() + last[1:]
    return ""


def parse_semicolon_list(value: str) -> List[str]:
    items = [s.strip() for s in (value or "").split(";")]
    items = [s for s in items if s != ""]
    return items


def map_item_to_criterion(item: str, criteria_keys: List[str]) -> Optional[str]:
    item_low = (item or "").strip().lower()
    item_low = item_low.replace("-", " ").replace("_", " ")
    for key in criteria_keys:
        k1 = key.lower()
        k2 = k1.replace("_", " ")
        if k1 == item_low or k2 == item_low or k1 in item_low or k2 in item_low:
            return key
    return None


def compute_top_bottom_sets(scores_by_criterion: Dict[str, int], top_n: int = 2) -> Tuple[set, set]:
    items = list(scores_by_criterion.items())
    items_sorted_desc = sorted(items, key=lambda x: (-x[1], x[0]))
    items_sorted_asc = sorted(items, key=lambda x: (x[1], x[0]))

    top_scores = []
    for k, v in items_sorted_desc:
        if not top_scores or (len(top_scores) < top_n or v == top_scores[-1][1]):
            top_scores.append((k, v))
        else:
            break
    top_score_values = [v for _, v in top_scores]
    min_top_value = min(top_score_values) if top_score_values else None
    allowed_top = {k for k, v in items if min_top_value is not None and v >= min_top_value}

    bottom_scores = []
    for k, v in items_sorted_asc:
        if not bottom_scores or (len(bottom_scores) < top_n or v == bottom_scores[-1][1]):
            bottom_scores.append((k, v))
        else:
            break
    bottom_score_values = [v for _, v in bottom_scores]
    max_bottom_value = max(bottom_score_values) if bottom_score_values else None
    allowed_bottom = {k for k, v in items if max_bottom_value is not None and v <= max_bottom_value}

    return allowed_top, allowed_bottom


def approx_number_in_text(num: float, text: str) -> bool:
    text = text or ""
    candidates = set()
    candidates.add(f"{num:.0f}")
    candidates.add(f"{num:.1f}")
    candidates.add(f"{num:.2f}")
    candidates.add(f"{num:.3f}")
    candidates.add(f"{num:.2f}".rstrip("0").rstrip("."))
    candidates.add(f"{num:.3f}".rstrip("0").rstrip("."))
    for c in candidates:
        if c and c in text:
            return True
    return False


def count_revision_requests(email_text: str, criteria_keys: List[str]) -> int:
    """
    Count lines that look like concrete revision requests.
    Heuristic: lines starting with "-", "*", or digit+dot, or starting with "Request:",
    that also contain at least one criterion keyword or verbs suggesting action.
    """
    if not email_text:
        return 0
    lines = email_text.splitlines()
    verbs = ["revise", "clarify", "add", "quantify", "state", "specify", "define", "report", "include", "describe", "support", "reduce", "tighten", "explain", "address", "map"]
    count = 0
    for ln in lines:
        stripped = ln.strip()
        starts_like_list = bool(re.match(r"^(\-|\*|\d+\.)\s+", stripped)) or stripped.startswith("Request:")
        if starts_like_list:
            lower_ln = stripped.lower()
            has_action = any(v in lower_ln for v in verbs)
            has_criterion = any(k.replace("_", " ") in lower_ln for k in criteria_keys)
            if has_action or has_criterion:
                count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "reviews_csv_exists_and_header": 0.0,
        "reviews_row_count_and_student_match": 0.0,
        "titles_match_extracted": 0.0,
        "score_fields_integers_0_5": 0.0,
        "weighted_total_correct": 0.0,
        "decision_matches_thresholds": 0.0,
        "strengths_two_mapped_and_top": 0.0,
        "concerns_two_mapped_and_bottom": 0.0,
        "evidence_quotes_valid_and_from_draft": 0.0,
        "emails_exist_and_filenames": 0.0,
        "email_subject_greeting_decision_total": 0.0,
        "email_contains_strengths_concerns_and_quotes": 0.0,
        "email_revision_requests_2_to_3": 0.0,
    }

    # Load rubric and recipients (needed for downstream checks)
    rubric_path = workspace / "input" / "rubric.yaml"
    recipients_path = workspace / "input" / "recipients.csv"
    submissions_dir = workspace / "input" / "submissions"
    reviews_csv_path = workspace / "output" / "evaluations" / "reviews.csv"
    emails_dir = workspace / "output" / "emails"

    rubric = parse_rubric_yaml(rubric_path) if rubric_path.exists() else None
    recipients = load_recipients(recipients_path) if recipients_path.exists() else None

    # Validate CSV header strictly (existence and exact order)
    expected_header = [
        "file_name",
        "student_name",
        "title",
        "hypothesis_score",
        "methods_score",
        "data_specificity_score",
        "uncertainty_score",
        "clarity_conciseness_score",
        "weighted_total",
        "decision",
        "strengths",
        "concerns",
        "evidence_quotes",
    ]
    header = read_csv_header(reviews_csv_path) if reviews_csv_path.exists() else None
    rows = read_reviews_csv(reviews_csv_path) if reviews_csv_path.exists() else None
    if header == expected_header and rows is not None and len(rows) > 0:
        scores["reviews_csv_exists_and_header"] = 1.0

    # Row count and student match
    if rows is not None and recipients is not None and len(rows) == len(recipients):
        try:
            file_names_in_csv = [r.get("file_name", "").strip() for r in rows]
            if sorted(file_names_in_csv) == sorted(list(recipients.keys())):
                mapping_ok = True
                for r in rows:
                    fn = r.get("file_name", "").strip()
                    sn = r.get("student_name", "").strip()
                    if fn not in recipients or recipients[fn]["student_name"] != sn:
                        mapping_ok = False
                        break
                if mapping_ok:
                    scores["reviews_row_count_and_student_match"] = 1.0
        except Exception:
            pass

    # Titles match extracted from submissions
    if rows is not None and submissions_dir.exists():
        try:
            titles = extract_titles_for_submissions(submissions_dir, [r.get("file_name", "").strip() for r in rows])
            if titles is not None:
                titles_ok = True
                for r in rows:
                    fn = r.get("file_name", "").strip()
                    title_csv = (r.get("title") or "").strip()
                    expected_title = titles.get(fn, "")
                    if title_csv != expected_title:
                        titles_ok = False
                        break
                if titles_ok:
                    scores["titles_match_extracted"] = 1.0
        except Exception:
            pass

    # Validate scores are 0-5 integers
    per_row_scores: List[Dict[str, int]] = []
    all_scores_ok = True
    if rows is not None:
        for r in rows:
            row_scores = {}
            for k in ["hypothesis_score", "methods_score", "data_specificity_score", "uncertainty_score", "clarity_conciseness_score"]:
                val = (r.get(k) or "").strip()
                try:
                    iv = int(val)
                    if 0 <= iv <= 5:
                        row_scores[k] = iv
                    else:
                        all_scores_ok = False
                        break
                except Exception:
                    all_scores_ok = False
                    break
            if not all_scores_ok:
                break
            per_row_scores.append(row_scores)
        if all_scores_ok and len(per_row_scores) == len(rows):
            scores["score_fields_integers_0_5"] = 1.0

    # Weighted total correctness
    if rows is not None and rubric is not None and scores["score_fields_integers_0_5"] == 1.0:
        wt_ok = True
        criteria_weights = rubric["weights"]
        for r, row_scores in zip(rows, per_row_scores):
            try:
                wt_csv = float((r.get("weighted_total") or "").strip())
            except Exception:
                wt_ok = False
                break
            crit_to_score = {
                "hypothesis": row_scores["hypothesis_score"],
                "methods": row_scores["methods_score"],
                "data_specificity": row_scores["data_specificity_score"],
                "uncertainty": row_scores["uncertainty_score"],
                "clarity_conciseness": row_scores["clarity_conciseness_score"],
            }
            wt_calc = 0.0
            for crit, w in criteria_weights.items():
                if crit not in crit_to_score:
                    wt_ok = False
                    break
                wt_calc += crit_to_score[crit] * w
            if not wt_ok:
                break
            if abs(wt_calc - wt_csv) > 0.05:
                wt_ok = False
                break
        if wt_ok:
            scores["weighted_total_correct"] = 1.0

    # Decision matches thresholds
    if rows is not None and rubric is not None and scores["weighted_total_correct"] == 1.0:
        thresholds = rubric["thresholds"]
        decision_ok = True
        for r in rows:
            try:
                wt_csv = float((r.get("weighted_total") or "").strip())
            except Exception:
                decision_ok = False
                break
            expected_dec = expected_decision_from_total(wt_csv, thresholds)
            got_dec = canonicalize_decision(r.get("decision", ""))
            if got_dec != expected_dec:
                decision_ok = False
                break
        if decision_ok:
            scores["decision_matches_thresholds"] = 1.0

    # Strengths and concerns tied to rubric and aligned with top/bottom
    if rows is not None and rubric is not None and scores["score_fields_integers_0_5"] == 1.0:
        criteria_keys = list(rubric["weights"].keys())
        strengths_tied_ok = True
        concerns_tied_ok = True
        strengths_align_ok = True
        concerns_align_ok = True
        for r, row_scores in zip(rows, per_row_scores):
            strengths_items = parse_semicolon_list(r.get("strengths", ""))
            concerns_items = parse_semicolon_list(r.get("concerns", ""))
            if len(strengths_items) != 2:
                strengths_tied_ok = False
            if len(concerns_items) != 2:
                concerns_tied_ok = False

            s_mapped = []
            for item in strengths_items:
                mapped = map_item_to_criterion(item, criteria_keys)
                if not mapped:
                    strengths_tied_ok = False
                else:
                    s_mapped.append(mapped)
            c_mapped = []
            for item in concerns_items:
                mapped = map_item_to_criterion(item, criteria_keys)
                if not mapped:
                    concerns_tied_ok = False
                else:
                    c_mapped.append(mapped)
            if len(set(s_mapped)) != 2:
                strengths_tied_ok = False
            if len(set(c_mapped)) != 2:
                concerns_tied_ok = False

            crit_to_score = {
                "hypothesis": row_scores["hypothesis_score"],
                "methods": row_scores["methods_score"],
                "data_specificity": row_scores["data_specificity_score"],
                "uncertainty": row_scores["uncertainty_score"],
                "clarity_conciseness": row_scores["clarity_conciseness_score"],
            }
            allowed_top, allowed_bottom = compute_top_bottom_sets(crit_to_score, top_n=2)
            if not all(x in allowed_top for x in s_mapped):
                strengths_align_ok = False
            if not all(x in allowed_bottom for x in c_mapped):
                concerns_align_ok = False

        if strengths_tied_ok and strengths_align_ok:
            scores["strengths_two_mapped_and_top"] = 1.0
        if concerns_tied_ok and concerns_align_ok:
            scores["concerns_two_mapped_and_bottom"] = 1.0

    # Evidence quotes validity and presence in drafts
    if rows is not None and submissions_dir.exists():
        evidence_ok = True
        for r in rows:
            fn = (r.get("file_name") or "").strip()
            draft_path = submissions_dir / fn
            draft_text = read_text_safe(draft_path)
            if draft_text is None:
                evidence_ok = False
                break
            quotes_field = r.get("evidence_quotes", "")
            quotes = [q.strip() for q in quotes_field.split("|") if q.strip() != ""]
            if len(quotes) < 1 or len(quotes) > 2:
                evidence_ok = False
                break
            for q in quotes:
                if len(q) > 150:
                    evidence_ok = False
                    break
                if q not in draft_text:
                    evidence_ok = False
                    break
            if not evidence_ok:
                break
        if evidence_ok:
            scores["evidence_quotes_valid_and_from_draft"] = 1.0

    # Emails existence and filenames
    emails_exist_ok = True
    if rows is None or recipients is None or not emails_dir.exists():
        emails_exist_ok = False
    else:
        for fn, rec in recipients.items():
            student_name = rec["student_name"]
            last = lastname_from_student_name(student_name)
            email_path = emails_dir / f"{last}_feedback.txt"
            if not email_path.exists():
                emails_exist_ok = False
                break
            if read_text_safe(email_path) is None:
                emails_exist_ok = False
                break
    if emails_exist_ok:
        scores["emails_exist_and_filenames"] = 1.0

    # Email subject, greeting, decision, and total present
    if recipients is not None and rows is not None and rubric is not None and emails_dir.exists():
        rows_by_file = {r.get("file_name", "").strip(): r for r in rows}
        subject_prefix = rubric["subject_prefix"]
        email_subject_ok = True
        for fn, rec in recipients.items():
            student_name = rec["student_name"]
            last = lastname_from_student_name(student_name)
            email_path = emails_dir / f"{last}_feedback.txt"
            email_text = read_text_safe(email_path)
            if email_text is None:
                email_subject_ok = False
                break
            # Subject
            # Need title from draft
            draft_path = submissions_dir / fn
            draft_text = read_text_safe(draft_path) or ""
            if fn.lower().endswith(".md"):
                title = extract_title_from_md(draft_text) or ""
            else:
                title = extract_title_from_txt(draft_text) or ""
            expected_subject = f"{subject_prefix} {title}".strip()
            if expected_subject not in email_text:
                email_subject_ok = False
            # Greeting by name (accept full or last name)
            if student_name not in email_text and last not in email_text:
                email_subject_ok = False
            # Weighted total and decision
            row = rows_by_file.get(fn)
            if row is None:
                email_subject_ok = False
                continue
            try:
                wt_val = float((row.get("weighted_total") or "").strip())
            except Exception:
                email_subject_ok = False
                continue
            dec_val = canonicalize_decision(row.get("decision", ""))
            if not approx_number_in_text(wt_val, email_text):
                email_subject_ok = False
            if dec_val not in email_text.lower():
                email_subject_ok = False
        if email_subject_ok:
            scores["email_subject_greeting_decision_total"] = 1.0

    # Email contains strengths, concerns, and quotes
    if recipients is not None and rows is not None and emails_dir.exists():
        rows_by_file = {r.get("file_name", "").strip(): r for r in rows}
        email_content_ok = True
        for fn, rec in recipients.items():
            row = rows_by_file.get(fn)
            if row is None:
                email_content_ok = False
                break
            last = lastname_from_student_name(rec["student_name"])
            email_path = emails_dir / f"{last}_feedback.txt"
            email_text = read_text_safe(email_path)
            if email_text is None:
                email_content_ok = False
                break
            strengths_items = parse_semicolon_list(row.get("strengths", ""))
            concerns_items = parse_semicolon_list(row.get("concerns", ""))
            lower_email = email_text.lower()
            for item in strengths_items:
                if item.strip() and item.strip().lower() not in lower_email:
                    email_content_ok = False
            for item in concerns_items:
                if item.strip() and item.strip().lower() not in lower_email:
                    email_content_ok = False
            quotes_field = row.get("evidence_quotes", "")
            quotes = [q.strip() for q in quotes_field.split("|") if q.strip() != ""]
            if len(quotes) == 0:
                email_content_ok = False
            for q in quotes:
                if q not in email_text:
                    email_content_ok = False
        if email_content_ok:
            scores["email_contains_strengths_concerns_and_quotes"] = 1.0

    # Email revision requests count 2–3
    if recipients is not None and rows is not None and rubric is not None and emails_dir.exists():
        criteria_keys = list(rubric["weights"].keys())
        requests_ok = True
        for _, rec in recipients.items():
            last = lastname_from_student_name(rec["student_name"])
            email_path = emails_dir / f"{last}_feedback.txt"
            email_text = read_text_safe(email_path)
            if email_text is None:
                requests_ok = False
                break
            count = count_revision_requests(email_text, criteria_keys)
            if count < 2 or count > 3:
                requests_ok = False
                break
        if requests_ok:
            scores["email_revision_requests_2_to_3"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()