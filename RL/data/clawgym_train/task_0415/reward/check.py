import json
import sys
import re
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the specific rules.yaml structure.
    Supports:
      - key: value
      - key:
          - item
          - item
    Values can be quoted strings, unquoted strings, integers, and booleans.
    """
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if current_list_key is not None:
            if line.startswith("-"):
                item = line[1:].strip()
                # Strip surrounding quotes if present
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                data[current_list_key].append(item)
                continue
            else:
                current_list_key = None  # end of list
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value == "":
                data[key] = []
                current_list_key = key
            else:
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    sval = value[1:-1]
                elif value.lower() in ("true", "false"):
                    sval = value.lower() == "true"
                else:
                    try:
                        sval = int(value)
                    except ValueError:
                        sval = value
                data[key] = sval
        else:
            return None
    return data


def _parse_quiz_md(path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Parses the input/draft_quiz.md into a list of dicts with keys: id, tags (list), text.
    Expects blocks:
    ID: Q1
    TAGS: FACT_CHECK
    TEXT: ...
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.strip() for ln in text.splitlines()]
    items: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    for ln in lines:
        if ln.startswith("ID:"):
            if "id" in current or "tags" in current or "text" in current:
                if all(k in current for k in ("id", "tags", "text")):
                    items.append(current)
                current = {}
            id_val = ln[len("ID:"):].strip()
            current["id"] = id_val
        elif ln.startswith("TAGS:"):
            tags_str = ln[len("TAGS:"):].strip()
            tags = [t.strip() for t in tags_str.split(",") if t.strip()]
            current["tags"] = tags
        elif ln.startswith("TEXT:"):
            txt = ln[len("TEXT:"):].strip()
            current["text"] = txt
        elif ln == "" or ln.startswith("#"):
            continue
        else:
            continue
    if current and all(k in current for k in ("id", "tags", "text")):
        items.append(current)
    return items


def _load_json_array(path: Path) -> Optional[List[Any]]:
    try:
        data = json.loads(_read_text(path) or "")
        if isinstance(data, list):
            return data
        else:
            return None
    except Exception:
        return None


def _load_queries(path: Path) -> Optional[List[str]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    return lines


def _count_words(s: str) -> int:
    return len([w for w in s.strip().split() if w])


def _is_sorted_unique(items: List[str]) -> bool:
    return items == sorted(set(items)) and len(items) == len(set(items))


def _contains_url(s: str) -> bool:
    s_lower = s.lower()
    return "http://" in s_lower or "https://" in s_lower or "://" in s_lower


def _extract_id_and_question(line: str) -> Optional[Tuple[str, str]]:
    """
    Extracts ID and question from a line that should start with 'ID:'.
    Accepts formats like:
      ID: Q1 Question text...
      ID: Q1: Question text...
      ID: Q1 - Question text...
    """
    if not line.startswith("ID:"):
        return None
    after = line[len("ID:"):].strip()
    if not after:
        return None
    m = re.match(r'^([A-Za-z0-9_\-]+)\s*(?:[:\-])?\s*(.+)$', after)
    if not m:
        return None
    qid = m.group(1).strip()
    qtext = m.group(2).strip()
    if not qid or not qtext:
        return None
    return qid, qtext


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "fact_check_json_exists_and_valid": 0.0,
        "fact_check_count_matches": 0.0,
        "fact_check_ids_and_texts_match_input": 0.0,
        "fact_check_decisions_and_reasons_valid": 0.0,
        "fact_check_sources_fields_and_domains_valid": 0.0,
        "fact_check_sources_minimum_unique_domains_met": 0.0,
        "queries_log_exists_and_matches_json": 0.0,
        "no_urls_in_source_fields_and_queries": 0.0,
        "rewrite_md_ids_and_limits": 0.0,
        "rewrite_csv_structure_and_alignment": 0.0,
        "rewrite_md_csv_consistency": 0.0,
        "email_exists_and_word_limit": 0.0,
        "email_recipient_and_subject": 0.0,
        "email_paths_mentioned": 0.0,
        "email_counts_match_json": 0.0,
    }

    rules_path = workspace / "input" / "rules.yaml"
    rules = _parse_simple_yaml(rules_path)
    if not isinstance(rules, dict):
        return scores

    try:
        sources_per_item_min = int(rules.get("sources_per_item_min", 0))
        max_question_words = int(rules.get("max_question_words", 0))
        email_recipient = str(rules.get("email_recipient", "") or "")
        email_word_limit = int(rules.get("email_word_limit", 0))
        fact_check_output_path = str(rules.get("fact_check_output_path", "out/validation/quiz_fact_check.json"))
        queries_log_path = str(rules.get("queries_log_path", "out/validation/queries.txt"))
        rewrite_output_md_path = str(rules.get("rewrite_output_md_path", "out/quiz_rewritten.md"))
        rewrite_output_csv_path = str(rules.get("rewrite_output_csv_path", "out/quiz_rewritten.csv"))
        email_output_path = str(rules.get("email_output_path", "out/email/email_to_teacher.txt"))
        allowed_domains = rules.get("source_domains_allowed", [])
        required_source_fields = rules.get("source_fields_required", [])
        if not isinstance(allowed_domains, list):
            allowed_domains = []
        if not isinstance(required_source_fields, list):
            required_source_fields = []
    except Exception:
        return scores

    draft_path = workspace / "input" / "draft_quiz.md"
    quiz_items = _parse_quiz_md(draft_path)
    if not isinstance(quiz_items, list):
        return scores
    fact_check_items = [q for q in quiz_items if "FACT_CHECK" in q.get("tags", [])]
    fact_check_ids = [q["id"] for q in fact_check_items]
    id_to_text = {q["id"]: q["text"] for q in fact_check_items}

    fc_json_path = workspace / fact_check_output_path
    fc_records = _load_json_array(fc_json_path)
    if isinstance(fc_records, list):
        valid_schema = True
        for rec in fc_records:
            if not isinstance(rec, dict):
                valid_schema = False
                break
            if "id" not in rec or "original_text" not in rec or "decision" not in rec or "reason" not in rec or "sources" not in rec:
                valid_schema = False
                break
            if not isinstance(rec.get("id"), str) or not isinstance(rec.get("original_text"), str):
                valid_schema = False
                break
            if rec.get("decision") not in ("plausible", "needs_revision"):
                valid_schema = False
                break
            if not isinstance(rec.get("reason"), str) or rec.get("reason").strip() == "":
                valid_schema = False
                break
            if not isinstance(rec.get("sources"), list):
                valid_schema = False
                break
        if valid_schema:
            scores["fact_check_json_exists_and_valid"] = 1.0

    if isinstance(fc_records, list) and len(fc_records) == len(fact_check_items):
        scores["fact_check_count_matches"] = 1.0

    ids_match = False
    texts_match = False
    if isinstance(fc_records, list):
        ids = [rec.get("id") for rec in fc_records if isinstance(rec, dict)]
        ids_match = set(ids) == set(fact_check_ids)
        if ids_match:
            texts_match = True
            for rec in fc_records:
                rid = rec.get("id")
                orig = rec.get("original_text")
                if rid not in id_to_text or id_to_text.get(rid) != orig:
                    texts_match = False
                    break
    if ids_match and texts_match:
        scores["fact_check_ids_and_texts_match_input"] = 1.0

    decisions_valid = False
    if isinstance(fc_records, list):
        decisions_valid = True
        for rec in fc_records:
            dec = rec.get("decision")
            reason = rec.get("reason")
            if dec not in ("plausible", "needs_revision"):
                decisions_valid = False
                break
            if not isinstance(reason, str) or reason.strip() == "":
                decisions_valid = False
                break
    if decisions_valid and scores["fact_check_json_exists_and_valid"] == 1.0:
        scores["fact_check_decisions_and_reasons_valid"] = 1.0

    sources_fields_valid = False
    sources_min_unique_met = False
    no_urls_in_sources_and_queries = False
    if isinstance(fc_records, list):
        sources_fields_valid = True
        sources_min_unique_met = True
        no_urls_in_sources_and_queries = True
        for rec in fc_records:
            sources = rec.get("sources", [])
            if not isinstance(sources, list):
                sources_fields_valid = False
                sources_min_unique_met = False
                break
            if len(sources) < sources_per_item_min:
                sources_min_unique_met = False
            domains_seen: set = set()
            for src in sources:
                if not isinstance(src, dict):
                    sources_fields_valid = False
                    break
                for field in required_source_fields:
                    if field not in src:
                        sources_fields_valid = False
                        break
                    if not isinstance(src[field], str) or src[field].strip() == "":
                        sources_fields_valid = False
                        break
                if not sources_fields_valid:
                    break
                dom = src.get("domain", "")
                if dom not in allowed_domains:
                    sources_fields_valid = False
                    break
                if "/" in dom or _contains_url(dom):
                    sources_fields_valid = False
                    break
                pt = src.get("page_title", "")
                qu = src.get("query_used", "")
                if _contains_url(pt) or _contains_url(qu):
                    no_urls_in_sources_and_queries = False
                domains_seen.add(dom)
            if len(domains_seen) < sources_per_item_min:
                sources_min_unique_met = False
            if not sources_fields_valid:
                break
    if sources_fields_valid:
        scores["fact_check_sources_fields_and_domains_valid"] = 1.0
    if sources_min_unique_met and scores["fact_check_json_exists_and_valid"] == 1.0:
        scores["fact_check_sources_minimum_unique_domains_met"] = 1.0

    queries_path = workspace / queries_log_path
    queries_list = _load_queries(queries_path)
    queries_ok = False
    if isinstance(fc_records, list) and isinstance(queries_list, list):
        json_queries: List[str] = []
        for rec in fc_records:
            for src in rec.get("sources", []):
                q = src.get("query_used")
                if isinstance(q, str):
                    json_queries.append(q)
        json_queries_set = sorted(set(json_queries))
        if queries_list == json_queries_set and _is_sorted_unique(queries_list):
            queries_ok = True
    if queries_ok:
        scores["queries_log_exists_and_matches_json"] = 1.0

    queries_no_urls = True
    if isinstance(queries_list, list):
        for q in queries_list:
            if _contains_url(q):
                queries_no_urls = False
                break
    else:
        queries_no_urls = False
    if no_urls_in_sources_and_queries and queries_no_urls and scores["fact_check_json_exists_and_valid"] == 1.0:
        scores["no_urls_in_source_fields_and_queries"] = 1.0

    rewrite_md_path = workspace / rewrite_output_md_path
    md_text = _read_text(rewrite_md_path)
    md_ok = False
    md_id_to_question: Dict[str, str] = {}
    if isinstance(md_text, str):
        md_lines = [ln for ln in md_text.splitlines() if ln.strip() != ""]
        if len(md_lines) == len(quiz_items):
            all_ok = True
            for ln in md_lines:
                ext = _extract_id_and_question(ln.strip())
                if not ext:
                    all_ok = False
                    break
                rid, rq = ext
                if rid not in [q["id"] for q in quiz_items]:
                    all_ok = False
                    break
                if max_question_words > 0 and _count_words(rq) > max_question_words:
                    all_ok = False
                    break
                md_id_to_question[rid] = rq
            if set(md_id_to_question.keys()) != set([q["id"] for q in quiz_items]):
                all_ok = False
            md_ok = all_ok
    if md_ok:
        scores["rewrite_md_ids_and_limits"] = 1.0

    rewrite_csv_path = workspace / rewrite_output_csv_path
    csv_ok = False
    csv_id_to_row: Dict[str, Dict[str, Any]] = {}
    try:
        with rewrite_csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            if header == ["id", "rewritten_question", "word_count"]:
                rows = list(reader)
                if len(rows) == len(quiz_items):
                    csv_all_ok = True
                    for row in rows:
                        rid = row.get("id", "")
                        rq = row.get("rewritten_question", "")
                        wc_str = row.get("word_count", "")
                        if rid not in [q["id"] for q in quiz_items]:
                            csv_all_ok = False
                            break
                        try:
                            wc = int(wc_str)
                        except Exception:
                            csv_all_ok = False
                            break
                        if wc != _count_words(rq):
                            csv_all_ok = False
                            break
                        csv_id_to_row[rid] = {"rewritten_question": rq, "word_count": wc}
                    if set(csv_id_to_row.keys()) != set([q["id"] for q in quiz_items]):
                        csv_all_ok = False
                    csv_ok = csv_all_ok
    except Exception:
        csv_ok = False
    if csv_ok:
        scores["rewrite_csv_structure_and_alignment"] = 1.0

    md_csv_consistent = False
    if md_ok and csv_ok:
        consistent = True
        for rid, rq in md_id_to_question.items():
            csv_row = csv_id_to_row.get(rid)
            if not csv_row:
                consistent = False
                break
            if csv_row["rewritten_question"] != rq:
                consistent = False
                break
            if csv_row["word_count"] != _count_words(rq):
                consistent = False
                break
        md_csv_consistent = consistent
    if md_csv_consistent:
        scores["rewrite_md_csv_consistency"] = 1.0

    email_path = workspace / email_output_path
    email_text = _read_text(email_path)
    email_exists_and_limit = False
    email_recipient_and_subject = False
    email_paths_ok = False
    email_counts_ok = False
    if isinstance(email_text, str):
        words = [w for w in email_text.split()]
        if email_word_limit > 0:
            if len(words) <= email_word_limit:
                email_exists_and_limit = True
        else:
            email_exists_and_limit = True

        has_recipient = email_recipient in email_text
        subject_found = any(re.match(r'^\s*Subject\s*:', ln, flags=re.IGNORECASE) for ln in email_text.splitlines())
        if has_recipient and subject_found:
            email_recipient_and_subject = True

        required_paths = [
            fact_check_output_path,
            queries_log_path,
            rewrite_output_md_path,
            rewrite_output_csv_path,
        ]
        email_paths_ok = all(p in email_text for p in required_paths)

        if isinstance(fc_records, list):
            expected_total = len(fc_records)
            needs_revision_count = sum(1 for rec in fc_records if rec.get("decision") == "needs_revision")
            nums = [int(n) for n in re.findall(r'\d+', email_text)]
            email_counts_ok = (expected_total in nums) and (needs_revision_count in nums)

    if email_exists_and_limit:
        scores["email_exists_and_word_limit"] = 1.0
    if email_recipient_and_subject:
        scores["email_recipient_and_subject"] = 1.0
    if email_paths_ok:
        scores["email_paths_mentioned"] = 1.0
    if email_counts_ok:
        scores["email_counts_match_json"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()