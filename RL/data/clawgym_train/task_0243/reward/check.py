import json
import sys
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None, "missing"
        return json.loads(txt), None
    except Exception as e:
        return None, str(e)


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None, None, "missing"
        lines = txt.splitlines()
        if not lines:
            return None, None, "empty"
        reader = csv.DictReader(lines)
        header = reader.fieldnames
        if header is None:
            return None, None, "no_header"
        rows = [dict(row) for row in reader]
        return header, rows, None
    except Exception as e:
        return None, None, str(e)


def _get_topics(workspace: Path) -> Tuple[List[str], bool]:
    topics_path = workspace / "input" / "topics.csv"
    header, rows, err = _safe_read_csv_dicts(topics_path)
    if err is not None or header is None or rows is None:
        return [], False
    if "topic" not in header:
        return [], False
    topics: List[str] = []
    for r in rows:
        t = (r.get("topic") or "").strip()
        if t:
            topics.append(t)
    return topics, len(topics) > 0


def _scan_for_http_urls(obj: Any) -> bool:
    if isinstance(obj, dict):
        for v in obj.values():
            if _scan_for_http_urls(v):
                return True
        return False
    if isinstance(obj, list):
        for v in obj:
            if _scan_for_http_urls(v):
                return True
        return False
    if isinstance(obj, str):
        s = obj.lower()
        if "http://" in s or "https://" in s:
            return True
        return False
    return False


def _is_domain_like(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not s:
        return False
    if "://" in s:
        return False
    if "/" in s:
        return False
    if " " in s:
        return False
    if "." not in s:
        return False
    return True


def _is_allowed_domain(domain: str) -> bool:
    d = (domain or "").strip().lower()
    allowed_exact = {"loc.gov", "archives.gov", "si.edu", "nps.gov"}
    if d in allowed_exact:
        return True
    if d.endswith(".edu"):
        return True
    return False


def _parse_date_yyyy_mm_dd(s: str) -> bool:
    try:
        datetime.strptime(s.strip(), "%Y-%m-%d")
        return True
    except Exception:
        return False


def _round_int(x: float) -> int:
    try:
        return int(round(x))
    except Exception:
        return int(x)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "quiz_json_parseable": 0.0,
        "quiz_coverage": 0.0,
        "quiz_structure_valid": 0.0,
        "quiz_ids_unique": 0.0,
        "quiz_no_urls": 0.0,
        "organizations_official_and_diverse": 0.0,
        "sources_csv_structure_and_header": 0.0,
        "sources_rows_count_and_topics_align": 0.0,
        "sources_organization_domain_allowed": 0.0,
        "sources_no_urls_and_dates_valid": 0.0,
        "sources_align_with_quiz": 0.0,
        "search_log_structure_valid": 0.0,
        "search_log_entries_per_topic": 0.0,
        "search_log_no_urls": 0.0,
        "validation_report_matches_recomputed": 0.0,
        "email_polished_meets_requirements": 0.0,
    }

    # Load topics
    topics, topics_ok = _get_topics(workspace)
    topic_set = set(topics)
    topic_count = len(topics)

    # Load quiz.json
    quiz_path = workspace / "workspace" / "quiz.json"
    quiz_data, quiz_err = _safe_load_json(quiz_path)
    quiz_list: List[Dict[str, Any]] = []
    if quiz_err is None and isinstance(quiz_data, list):
        quiz_list = quiz_data
        scores["quiz_json_parseable"] = 1.0

    # Analyze quiz
    ids_seen = set()
    ids_unique = True
    coverage_ok = False
    no_urls_ok = False
    orgs_set = set()
    questions_per_topic: Dict[str, int] = {}
    all_have_required_fields = True
    all_have_four_choices_and_valid_index = True

    if quiz_list:
        for q in quiz_list:
            if not isinstance(q, dict):
                all_have_required_fields = False
                continue
            qid = (q.get("id") or "").strip()
            topic_val = (q.get("topic") or "").strip()
            question = q.get("question")
            options = q.get("options")
            correct_index = q.get("correct_index")
            source_org = (q.get("source_organization") or "").strip()
            source_dom = (q.get("source_domain") or "").strip()
            citation_title = (q.get("citation_title") or "").strip()

            required_present = (
                bool(qid)
                and bool(topic_val)
                and isinstance(question, str) and bool(question.strip())
                and isinstance(options, list)
                and ("correct_index" in q)
                and bool(source_org)
                and bool(source_dom)
                and bool(citation_title)
            )
            if not required_present:
                all_have_required_fields = False

            options_valid = isinstance(options, list) and len(options) == 4 and all(isinstance(o, str) and o.strip() for o in (options or []))
            correct_index_valid = isinstance(correct_index, int) and 0 <= correct_index <= 3
            if not (options_valid and correct_index_valid):
                all_have_four_choices_and_valid_index = False

            if qid in ids_seen:
                ids_unique = False
            ids_seen.add(qid)

            if topic_val:
                questions_per_topic[topic_val] = questions_per_topic.get(topic_val, 0) + 1

            if source_org:
                orgs_set.add(source_org)

        if topics_ok:
            if len(quiz_list) == topic_count and all(questions_per_topic.get(t, 0) == 1 for t in topics) and set(questions_per_topic.keys()) == topic_set:
                coverage_ok = True

        no_urls_ok = not _scan_for_http_urls(quiz_list)

    if coverage_ok:
        scores["quiz_coverage"] = 1.0
    # Only award structure if there is a non-empty quiz list and it passes strict checks
    if quiz_list and all_have_required_fields and all_have_four_choices_and_valid_index:
        scores["quiz_structure_valid"] = 1.0
    if ids_unique and ids_seen:
        scores["quiz_ids_unique"] = 1.0
    if no_urls_ok and quiz_list:
        scores["quiz_no_urls"] = 1.0

    # Organizations official and diverse (at least two). Validate source_domain allowed for each question.
    orgs_diverse_ok = False
    if quiz_list:
        per_q_domains_ok = True
        for q in quiz_list:
            d = (q.get("source_domain") or "").strip()
            if not (_is_domain_like(d) and _is_allowed_domain(d)):
                per_q_domains_ok = False
                break
        if per_q_domains_ok and len(orgs_set) >= 2:
            orgs_diverse_ok = True
    if orgs_diverse_ok:
        scores["organizations_official_and_diverse"] = 1.0

    # Load sources.csv
    sources_path = workspace / "workspace" / "sources.csv"
    src_header, src_rows, src_err = _safe_read_csv_dicts(sources_path)

    sources_header_ok = False
    sources_rows_ok = False
    sources_domain_ok = False
    sources_no_urls_dates_ok = False
    sources_align_ok = False

    expected_header = ["topic", "citation_title", "organization", "domain", "publication_year", "access_date", "query_used"]

    if src_err is None and src_header is not None and src_rows is not None:
        if src_header == expected_header:
            sources_header_ok = True

        if quiz_list and topics_ok:
            if len(src_rows) == len(quiz_list) == topic_count:
                sources_rows_ok = True
        elif quiz_list:
            if len(src_rows) == len(quiz_list):
                sources_rows_ok = True
        elif topics_ok:
            if len(src_rows) == topic_count:
                sources_rows_ok = True

        per_row_domains_ok = True
        per_row_no_urls_and_dates_ok = True
        topic_to_src = {}
        topics_in_sources: List[str] = []

        for r in src_rows:
            topic_val = (r.get("topic") or "").strip()
            citation_title = (r.get("citation_title") or "").strip()
            organization = (r.get("organization") or "").strip()
            domain = (r.get("domain") or "").strip()
            publication_year = (r.get("publication_year") or "").strip()
            access_date = (r.get("access_date") or "").strip()
            query_used = (r.get("query_used") or "").strip()

            topics_in_sources.append(topic_val)

            if not (_is_domain_like(domain) and _is_allowed_domain(domain)):
                per_row_domains_ok = False

            row_fields = [topic_val, citation_title, organization, domain, publication_year, access_date, query_used]
            if any(("http://" in (f or "").lower() or "https://" in (f or "").lower()) for f in row_fields):
                per_row_no_urls_and_dates_ok = False

            if access_date:
                if not _parse_date_yyyy_mm_dd(access_date):
                    per_row_no_urls_and_dates_ok = False
            else:
                per_row_no_urls_and_dates_ok = False

            if publication_year:
                if not re.fullmatch(r"\d{4}", publication_year):
                    per_row_no_urls_and_dates_ok = False

            if not citation_title or not organization or not query_used:
                per_row_no_urls_and_dates_ok = False

            topic_to_src[topic_val] = {
                "citation_title": citation_title,
                "organization": organization,
                "domain": domain,
            }

        sources_domain_ok = per_row_domains_ok
        sources_no_urls_dates_ok = per_row_no_urls_and_dates_ok

        if topics_ok and quiz_list:
            align_ok = True
            if set(topics_in_sources) != topic_set:
                align_ok = False
            else:
                quiz_topic_map = {
                    (q.get("topic") or "").strip(): {
                        "citation_title": (q.get("citation_title") or "").strip(),
                        "organization": (q.get("source_organization") or "").strip(),
                        "domain": (q.get("source_domain") or "").strip(),
                    }
                    for q in quiz_list
                }
                for t in topics:
                    if t not in quiz_topic_map or t not in topic_to_src:
                        align_ok = False
                        break
                    qvals = quiz_topic_map[t]
                    svals = topic_to_src[t]
                    if qvals["citation_title"] != svals["citation_title"]:
                        align_ok = False
                        break
                    if qvals["organization"] != svals["organization"]:
                        align_ok = False
                        break
                    if qvals["domain"].strip().lower() != svals["domain"].strip().lower():
                        align_ok = False
                        break
            if align_ok:
                sources_align_ok = True

    if sources_header_ok:
        scores["sources_csv_structure_and_header"] = 1.0
    if sources_rows_ok:
        scores["sources_rows_count_and_topics_align"] = 1.0
    if sources_domain_ok:
        scores["sources_organization_domain_allowed"] = 1.0
    if sources_no_urls_dates_ok:
        scores["sources_no_urls_and_dates_valid"] = 1.0
    if sources_align_ok:
        scores["sources_align_with_quiz"] = 1.0

    # Search log
    search_log_path = workspace / "workspace" / "search_log.json"
    search_data, search_err = _safe_load_json(search_log_path)
    search_structure_ok = False
    search_entries_per_topic_ok = False
    search_no_urls_ok = False

    if search_err is None and isinstance(search_data, list):
        per_entry_ok = True
        topic_entries: List[str] = []
        no_urls = True
        for entry in search_data:
            if not isinstance(entry, dict):
                per_entry_ok = False
                break
            topic_val = (entry.get("topic") or "").strip()
            queries = entry.get("queries")
            captured = entry.get("captured_results")
            if not topic_val or not isinstance(queries, list) or len(queries) < 1 or not isinstance(captured, list) or len(captured) > 3:
                per_entry_ok = False
                break
            if not all(isinstance(q, str) and q.strip() for q in queries):
                per_entry_ok = False
                break
            for r in captured:
                if not isinstance(r, dict):
                    per_entry_ok = False
                    break
                title = (r.get("title") or "").strip()
                domain = (r.get("domain") or "").strip()
                if not title or not domain or not _is_domain_like(domain):
                    per_entry_ok = False
                    break
                if "http://" in domain.lower() or "https://" in domain.lower():
                    per_entry_ok = False
                    break
            if not per_entry_ok:
                break
            topic_entries.append(topic_val)
            if any(("http://" in (q or "").lower() or "https://" in (q or "").lower()) for q in queries):
                no_urls = False
            for r in captured:
                if "http://" in (r.get("title") or "").lower() or "https://" in (r.get("title") or "").lower():
                    no_urls = False

        search_structure_ok = per_entry_ok and len(search_data) > 0
        if topics_ok and search_structure_ok:
            if set(topic_entries) == topic_set and len(topic_entries) == topic_count:
                search_entries_per_topic_ok = True
        if no_urls:
            search_no_urls_ok = True

    if search_structure_ok:
        scores["search_log_structure_valid"] = 1.0
    if search_entries_per_topic_ok:
        scores["search_log_entries_per_topic"] = 1.0
    if search_no_urls_ok:
        scores["search_log_no_urls"] = 1.0

    # Validation report consistency
    validation_path = workspace / "workspace" / "validation_report.json"
    val_data, val_err = _safe_load_json(validation_path)
    validation_ok = False

    recomputed = None
    if quiz_list and topics_ok:
        qpt: Dict[str, int] = {}
        for q in quiz_list:
            t = (q.get("topic") or "").strip()
            if t:
                qpt[t] = qpt.get(t, 0) + 1

        passes_coverage = len(quiz_list) == topic_count and all(qpt.get(t, 0) == 1 for t in topics) and set(qpt.keys()) == topic_set

        all_q_four_choices = True
        for q in quiz_list:
            options = q.get("options")
            correct_index = q.get("correct_index")
            if not (isinstance(options, list) and len(options) == 4 and all(isinstance(o, str) and o.strip() for o in options)):
                all_q_four_choices = False
                break
            if not (isinstance(correct_index, int) and 0 <= correct_index <= 3):
                all_q_four_choices = False
                break

        required_fields = ["id", "topic", "question", "options", "correct_index", "source_organization", "source_domain", "citation_title"]
        passes_structure = True
        invalid_ids: List[str] = []
        for q in quiz_list:
            qid = (q.get("id") or "").strip()
            present = all(f in q for f in required_fields) and all((q.get(f) is not None) for f in required_fields)
            non_empty = True
            for f in ["id", "topic", "question", "source_organization", "source_domain", "citation_title"]:
                val = q.get(f)
                if not isinstance(val, str) or not val.strip():
                    non_empty = False
                    break
            if not present or not non_empty:
                passes_structure = False
                invalid_ids.append(qid or "(missing_id)")
        if not all_q_four_choices:
            for q in quiz_list:
                qid = (q.get("id") or "").strip() or "(missing_id)"
                options = q.get("options")
                correct_index = q.get("correct_index")
                if not (isinstance(options, list) and len(options) == 4 and all(isinstance(o, str) and o.strip() for o in options)) or not (isinstance(correct_index, int) and 0 <= correct_index <= 3):
                    if qid not in invalid_ids:
                        invalid_ids.append(qid)

        orgs = sorted(list({(q.get("source_organization") or "").strip() for q in quiz_list if (q.get("source_organization") or "").strip()}))
        unique_orgs_count = len(orgs)

        question_lengths = [len((q.get("question") or "")) for q in quiz_list]
        avg_q_len = _round_int(sum(question_lengths) / len(question_lengths)) if question_lengths else 0
        option_lengths: List[int] = []
        for q in quiz_list:
            opts = q.get("options") or []
            for o in opts:
                if isinstance(o, str):
                    option_lengths.append(len(o))
        avg_opt_len = _round_int(sum(option_lengths) / len(option_lengths)) if option_lengths else 0

        recomputed = {
            "topic_count": topic_count,
            "total_questions": len(quiz_list),
            "questions_per_topic": {t: qpt.get(t, 0) for t in topics},
            "passes_coverage": passes_coverage,
            "all_questions_have_four_choices": all_q_four_choices,
            "passes_structure": passes_structure,
            "unique_organizations_count": unique_orgs_count,
            "organizations": orgs,
            "average_question_length_chars": avg_q_len,
            "average_option_length_chars": avg_opt_len,
            "invalid_questions": sorted(invalid_ids),
        }

    if val_err is None and isinstance(val_data, dict) and recomputed is not None:
        try:
            expected = recomputed
            actual = val_data
            keys_required = [
                "topic_count",
                "total_questions",
                "questions_per_topic",
                "passes_coverage",
                "all_questions_have_four_choices",
                "passes_structure",
                "unique_organizations_count",
                "organizations",
                "average_question_length_chars",
                "average_option_length_chars",
                "invalid_questions",
            ]
            all_present = all(k in actual for k in keys_required)
            matches = all_present
            if matches:
                if actual.get("topic_count") != expected["topic_count"]:
                    matches = False
                if actual.get("total_questions") != expected["total_questions"]:
                    matches = False
                if actual.get("questions_per_topic") != expected["questions_per_topic"]:
                    matches = False
                if bool(actual.get("passes_coverage")) != expected["passes_coverage"]:
                    matches = False
                if bool(actual.get("all_questions_have_four_choices")) != expected["all_questions_have_four_choices"]:
                    matches = False
                if bool(actual.get("passes_structure")) != expected["passes_structure"]:
                    matches = False
                if actual.get("unique_organizations_count") != expected["unique_organizations_count"]:
                    matches = False
                try:
                    actual_orgs = list(actual.get("organizations"))
                    if sorted(actual_orgs) != expected["organizations"]:
                        matches = False
                except Exception:
                    matches = False
                if actual.get("average_question_length_chars") != expected["average_question_length_chars"]:
                    matches = False
                if actual.get("average_option_length_chars") != expected["average_option_length_chars"]:
                    matches = False
                try:
                    actual_invalid = sorted(list(actual.get("invalid_questions")))
                    if actual_invalid != expected["invalid_questions"]:
                        matches = False
                except Exception:
                    matches = False
            validation_ok = matches
        except Exception:
            validation_ok = False

    if validation_ok:
        scores["validation_report_matches_recomputed"] = 1.0

    # Email polished check
    email_path = workspace / "workspace" / "email_polished.txt"
    email_txt = _safe_read_text(email_path)
    email_ok = False
    if email_txt is not None:
        words = re.findall(r"\b\S+\b", email_txt.strip())
        under_limit = len(words) <= 120 and len(words) > 0
        mentions_quiz = "quiz.json" in email_txt
        mentions_validation = "validation_report.json" in email_txt
        mentions_review = re.search(r"\breview\b", email_txt, flags=re.IGNORECASE) is not None
        first_line = email_txt.splitlines()[0] if email_txt.splitlines() else email_txt
        greeting_ok = bool(re.search(r"\b(Dear|Hello|Hi)\b", first_line))
        slang_patterns = [r"\bidk\b", r"\bthx\b", r"\bgonna\b", r"\bkinda\b", r"\blol\b", r"\bhey\b", r"\bplz\b", r"\bu\b", r"\bur\b"]
        no_slang = all(re.search(pat, email_txt, flags=re.IGNORECASE) is None for pat in slang_patterns)
        email_ok = under_limit and mentions_quiz and mentions_validation and mentions_review and greeting_ok and no_slang
    if email_ok:
        scores["email_polished_meets_requirements"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()