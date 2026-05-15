import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, Tuple, Optional, List, Any


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_json_load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def simple_yaml_load(path: Path) -> Optional[Dict[str, Any]]:
    text = read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    current_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith("  ") and line.endswith(":"):
            key = line[:-1].strip()
            current_key = key
            data[current_key] = None
            continue
        if line.startswith("  - "):
            if current_key is None:
                return None
            if data.get(current_key) is None:
                data[current_key] = []
            if not isinstance(data[current_key], list):
                return None
            val = line[4:].strip()
            data[current_key].append(val)
            continue
        if line.startswith("  ") and ":" in line:
            if current_key is None:
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                try:
                    data[k] = int(v)
                except Exception:
                    data[k] = v
                continue
            if data.get(current_key) is None:
                data[current_key] = {}
            if not isinstance(data[current_key], dict):
                return None
            k, v = line.strip().split(":", 1)
            k = k.strip()
            v = v.strip()
            try:
                v_val: Any = int(v)
            except Exception:
                v_val = v
            data[current_key][k] = v_val
            continue
        if ":" in line and not line.startswith("  "):
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            try:
                data[k] = int(v)
            except Exception:
                data[k] = v
            continue
        return None
    return data


def sanitize_doi(doi: str) -> str:
    return doi.replace("/", "_")


def extract_title_abstract(meta: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    def get_title(m: Dict[str, Any]) -> Optional[str]:
        t = m.get("title")
        if isinstance(t, list) and t:
            return str(t[0])
        if isinstance(t, str):
            return t
        msg = m.get("message")
        if isinstance(msg, dict):
            return get_title(msg)
        return None

    def get_abstract(m: Dict[str, Any]) -> Optional[str]:
        a = m.get("abstract")
        if isinstance(a, str):
            a_clean = re.sub(r"<[^>]+>", " ", a)
            return a_clean
        msg = m.get("message")
        if isinstance(msg, dict):
            return get_abstract(msg)
        return None

    title = get_title(meta) if isinstance(meta, dict) else None
    abstract = get_abstract(meta) if isinstance(meta, dict) else None
    return title, abstract


def word_count(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def split_sentences(text: str) -> List[str]:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]


def compute_keyword_matches(text: str, keywords: Dict[str, int], stopwords: List[str]) -> Tuple[int, List[str]]:
    if text is None:
        return 0, []
    text_l = text
    matched_set = set()
    score = 0
    stop_set = {s.lower() for s in stopwords} if isinstance(stopwords, list) else set()
    for kw, w in keywords.items():
        if kw.lower() in stop_set:
            continue
        pattern = r"\b" + re.escape(kw) + r"\b"
        matches = re.findall(pattern, text_l, flags=re.IGNORECASE)
        if matches:
            matched_set.add(kw.lower())
            score += w * len(matches)
    return score, sorted(matched_set)


def is_sorted_by_score_then_title(rows: List[Dict[str, Any]]) -> bool:
    for i in range(len(rows) - 1):
        s1 = rows[i].get("score")
        s2 = rows[i + 1].get("score")
        t1 = (rows[i].get("title") or "").lower()
        t2 = (rows[i + 1].get("title") or "").lower()
        try:
            f1 = float(s1)
            f2 = float(s2)
        except Exception:
            return False
        if f1 < f2:
            return False
        if f1 == f2 and t1 > t2:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metadata_json_count_correct": 0.0,
        "metadata_json_fields_valid": 0.0,
        "ranked_csv_exists_and_columns": 0.0,
        "ranked_csv_sorted_and_rank_values": 0.0,
        "ranked_csv_filter_compliance": 0.0,
        "ranked_csv_scores_match_expected": 0.0,
        "ranked_csv_retrieval_status_consistency": 0.0,
        "matched_keywords_list_correct": 0.0,
        "email_word_count_ok": 0.0,
        "email_mentions_ranking_keywords_config": 0.0,
        "email_lists_top_n_items": 0.0,
        "slack_word_count_ok": 0.0,
        "slack_rewritten_not_copied": 0.0,
        "slack_includes_only_top_n_items": 0.0,
        "logs_with_timestamps_present": 0.0,
        "validator_report_present_and_consistent": 0.0,
        "validate_script_exists": 0.0,
    }

    config_path = workspace / "config" / "keywords.yaml"
    config = simple_yaml_load(config_path)
    if not isinstance(config, dict):
        keywords = {}
        stopwords = []
        min_score = None
        digest_top_n = None
        slack_top_n = None
    else:
        keywords = config.get("keywords") or {}
        stopwords = config.get("stopwords") or []
        min_score = config.get("min_score_to_include_in_digest")
        digest_top_n = config.get("digest_top_n")
        slack_top_n = config.get("slack_top_n")

    input_csv_path = workspace / "input" / "inbox" / "reading_list_2024q4.csv"
    input_rows = load_csv_dicts(input_csv_path) or []
    dois_input: List[str] = [row.get("doi", "").strip() for row in input_rows if row.get("doi")]
    notes_by_doi: Dict[str, str] = {row.get("doi", "").strip(): row.get("notes", "") for row in input_rows if row.get("doi")}
    expected_count = len(dois_input)

    metadata_dir = workspace / "downloads" / "metadata"
    if metadata_dir.exists():
        _ = list(metadata_dir.glob("*.json"))
    meta_by_doi: Dict[str, Dict[str, Any]] = {}
    present_count = 0
    valid_meta_count = 0
    for doi in dois_input:
        sanitized = sanitize_doi(doi)
        fpath = metadata_dir / f"{sanitized}.json"
        if fpath.exists():
            present_count += 1
            data = safe_json_load(fpath)
            if isinstance(data, dict):
                meta_by_doi[doi] = data
                rs = data.get("retrieval_status")
                has_doi = data.get("doi") == doi
                if rs in ("ok", "error") and has_doi and (rs != "error" or isinstance(data.get("error"), str)):
                    valid_meta_count += 1
            else:
                meta_by_doi[doi] = {}
        else:
            meta_by_doi[doi] = {}

    if expected_count > 0:
        scores["metadata_json_count_correct"] = max(0.0, min(1.0, present_count / expected_count))
        scores["metadata_json_fields_valid"] = max(0.0, min(1.0, valid_meta_count / expected_count))
    else:
        scores["metadata_json_count_correct"] = 0.0
        scores["metadata_json_fields_valid"] = 0.0

    expected_scores: Dict[str, int] = {}
    expected_matched: Dict[str, List[str]] = {}
    expected_retrieval_status: Dict[str, str] = {}
    for doi in dois_input:
        meta = meta_by_doi.get(doi) or {}
        rs = meta.get("retrieval_status")
        expected_retrieval_status[doi] = rs if isinstance(rs, str) else ""
        title, abstract = extract_title_abstract(meta)
        if (not title and not abstract) and doi in notes_by_doi:
            txt = notes_by_doi.get(doi) or ""
        else:
            parts = []
            if title:
                parts.append(title)
            if abstract:
                parts.append(abstract)
            txt = " ".join(parts)
        score, matched = compute_keyword_matches(txt, keywords if isinstance(keywords, dict) else {}, stopwords if isinstance(stopwords, list) else [])
        expected_scores[doi] = score
        expected_matched[doi] = matched

    ranked_path = workspace / "outputs" / "reading_list_2024q4_ranked.csv"
    ranked_rows = load_csv_dicts(ranked_path)
    required_cols = ["doi", "title", "score", "rank", "retrieval_status", "matched_keywords"]
    if isinstance(ranked_rows, list) and ranked_rows:
        header_ok = all(col in ranked_rows[0] for col in required_cols) and len(ranked_rows[0].keys()) >= len(required_cols)
        scores["ranked_csv_exists_and_columns"] = 1.0 if header_ok else 0.0
    elif isinstance(ranked_rows, list) and ranked_rows == []:
        scores["ranked_csv_exists_and_columns"] = 0.0
    else:
        scores["ranked_csv_exists_and_columns"] = 0.0

    if isinstance(ranked_rows, list) and ranked_rows:
        sorted_check_rows = []
        rank_seq_ok = True
        try:
            for idx, r in enumerate(ranked_rows, start=1):
                s = float(r.get("score", "nan"))
                t = r.get("title", "")
                sorted_check_rows.append({"score": s, "title": t})
                rnk = int(str(r.get("rank")).strip())
                if rnk != idx:
                    rank_seq_ok = False
        except Exception:
            rank_seq_ok = False
        sorted_ok = is_sorted_by_score_then_title(sorted_check_rows)
        scores["ranked_csv_sorted_and_rank_values"] = 1.0 if (sorted_ok and rank_seq_ok) else 0.0
    else:
        scores["ranked_csv_sorted_and_rank_values"] = 0.0

    if isinstance(ranked_rows, list) and min_score is not None:
        try:
            min_thr = int(min_score)
        except Exception:
            min_thr = None
        if min_thr is not None:
            expected_included = {doi for doi, sc in expected_scores.items() if sc >= min_thr}
            present_dois = {r.get("doi", "").strip() for r in ranked_rows}
            union = expected_included | present_dois
            inter = expected_included & present_dois
            if len(union) > 0:
                jacc = len(inter) / len(union)
                present_below = any(expected_scores.get((r.get("doi") or "").strip(), 0) < min_thr for r in ranked_rows)
                if present_below:
                    jacc = 0.0
                scores["ranked_csv_filter_compliance"] = max(0.0, min(1.0, jacc))
            else:
                scores["ranked_csv_filter_compliance"] = 0.0
        else:
            scores["ranked_csv_filter_compliance"] = 0.0
    else:
        scores["ranked_csv_filter_compliance"] = 0.0

    if isinstance(ranked_rows, list) and ranked_rows:
        total = len(ranked_rows)
        match_scores = 0
        match_status = 0
        match_keywords_count = 0
        for r in ranked_rows:
            doi = r.get("doi", "").strip()
            try:
                s_csv = int(float(str(r.get("score")).strip()))
            except Exception:
                s_csv = None
            s_exp = expected_scores.get(doi)
            if s_csv is not None and s_exp is not None and s_csv == s_exp:
                match_scores += 1
            rs_csv = (r.get("retrieval_status") or "").strip()
            rs_exp = expected_retrieval_status.get(doi, "")
            if rs_exp and rs_csv == rs_exp:
                match_status += 1
            mk_csv = r.get("matched_keywords") or ""
            mk_set_csv = set([m.strip().lower() for m in mk_csv.split(";") if m.strip()])
            mk_set_exp = set(expected_matched.get(doi, []))
            if mk_set_csv == mk_set_exp:
                match_keywords_count += 1
        scores["ranked_csv_scores_match_expected"] = max(0.0, min(1.0, match_scores / total if total else 0.0))
        scores["ranked_csv_retrieval_status_consistency"] = max(0.0, min(1.0, match_status / total if total else 0.0))
        scores["matched_keywords_list_correct"] = max(0.0, min(1.0, match_keywords_count / total if total else 0.0))
    else:
        scores["ranked_csv_scores_match_expected"] = 0.0
        scores["ranked_csv_retrieval_status_consistency"] = 0.0
        scores["matched_keywords_list_correct"] = 0.0

    email_path = workspace / "outputs" / "messages" / "reading_list_2024q4_email.txt"
    slack_path = workspace / "outputs" / "messages" / "reading_list_2024q4_slack.txt"
    email_text = read_text(email_path) or ""
    slack_text = read_text(slack_path) or ""

    email_wc_ok = False
    slack_wc_ok = False
    if email_text:
        wc = word_count(email_text)
        email_wc_ok = 120 <= wc <= 180
    if slack_text:
        wc = word_count(slack_text)
        slack_wc_ok = 40 <= wc <= 60
    scores["email_word_count_ok"] = 1.0 if email_wc_ok else 0.0
    scores["slack_word_count_ok"] = 1.0 if slack_wc_ok else 0.0

    if email_text:
        mentions = (("rank" in email_text.lower()) and ("keyword" in email_text.lower()) and ("config/keywords.yaml" in email_text))
        scores["email_mentions_ranking_keywords_config"] = 1.0 if mentions else 0.0
    else:
        scores["email_mentions_ranking_keywords_config"] = 0.0

    top_dois: List[str] = []
    top_titles: Dict[str, str] = {}
    top_slack_dois: List[str] = []
    if isinstance(ranked_rows, list) and ranked_rows:
        try:
            dn = int(digest_top_n) if digest_top_n is not None else 0
            sn = int(slack_top_n) if slack_top_n is not None else 0
        except Exception:
            dn = 0
            sn = 0
        for idx, r in enumerate(ranked_rows):
            doi = (r.get("doi") or "").strip()
            title = (r.get("title") or "").strip()
            if idx < dn:
                top_dois.append(doi)
                top_titles[doi] = title
            if idx < sn:
                top_slack_dois.append(doi)

    email_lists_ok = False
    if email_text and top_dois:
        all_present = True
        for doi in top_dois:
            if doi not in email_text:
                all_present = False
                break
            title = top_titles.get(doi, "")
            if title and title.lower() not in email_text.lower():
                all_present = False
                break
        email_lists_ok = all_present
    scores["email_lists_top_n_items"] = 1.0 if email_lists_ok else 0.0

    slack_includes_ok = False
    if slack_text and top_slack_dois:
        includes_all = all(doi in slack_text for doi in top_slack_dois)
        includes_any_other = False
        for doi in dois_input:
            if doi in top_slack_dois:
                continue
            if doi and doi in slack_text:
                includes_any_other = True
                break
        slack_includes_ok = includes_all and not includes_any_other
    scores["slack_includes_only_top_n_items"] = 1.0 if slack_includes_ok else 0.0

    slack_rewrite_ok = False
    if email_text and slack_text:
        email_sents = [s.lower() for s in split_sentences(email_text)]
        slack_sents = [s.lower() for s in split_sentences(slack_text)]
        overlap = set(email_sents) & set(slack_sents)
        slack_rewrite_ok = len(overlap) == 0
    scores["slack_rewritten_not_copied"] = 1.0 if slack_rewrite_ok else 0.0

    log_path = workspace / "logs" / "automation.log"
    log_text = read_text(log_path) or ""
    has_timestamp = False
    if log_text:
        for line in log_text.splitlines():
            if re.search(r"\d{4}-\d{2}-\d{2}", line) or re.search(r"\d{2}:\d{2}:\d{2}", line):
                has_timestamp = True
                break
    scores["logs_with_timestamps_present"] = 1.0 if has_timestamp else 0.0

    validate_sh_path = workspace / "scripts" / "validate.sh"
    scores["validate_script_exists"] = 1.0 if validate_sh_path.exists() else 0.0

    report_path = workspace / "outputs" / "validation" / "reading_list_2024q4_report.json"
    report = safe_json_load(report_path)
    if isinstance(report, dict):
        required_fields = ["total_dois_processed", "metadata_json_count", "ranked_sorted", "email_word_count_ok", "slack_word_count_ok"]
        has_fields = all(k in report for k in required_fields)
        consistent = True
        if expected_count:
            if isinstance(report.get("total_dois_processed"), int):
                consistent = consistent and (report["total_dois_processed"] == expected_count)
            else:
                consistent = False
        if isinstance(report.get("metadata_json_count"), int):
            consistent = consistent and (report["metadata_json_count"] == present_count)
        else:
            consistent = False
        ranked_sorted_bool = True if scores["ranked_csv_sorted_and_rank_values"] == 1.0 else False
        if isinstance(report.get("ranked_sorted"), bool):
            consistent = consistent and (report["ranked_sorted"] == ranked_sorted_bool)
        else:
            consistent = False
        if isinstance(report.get("email_word_count_ok"), bool):
            consistent = consistent and (report["email_word_count_ok"] == (scores["email_word_count_ok"] == 1.0))
        else:
            consistent = False
        if isinstance(report.get("slack_word_count_ok"), bool):
            consistent = consistent and (report["slack_word_count_ok"] == (scores["slack_word_count_ok"] == 1.0))
        else:
            consistent = False
        scores["validator_report_present_and_consistent"] = 1.0 if (has_fields and consistent) else 0.0
    else:
        scores["validator_report_present_and_consistent"] = 0.0

    for k, v in list(scores.items()):
        try:
            f = float(v)
        except Exception:
            f = 0.0
        if f < 0.0:
            f = 0.0
        if f > 1.0:
            f = 1.0
        scores[k] = f

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()