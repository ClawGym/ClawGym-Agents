import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[dict]]:
    entries = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        entries.append(obj)
                    else:
                        return None
                except Exception:
                    return None
        return entries
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                if not isinstance(row, dict):
                    return None
                rows.append(row)
            return rows
    except Exception:
        return None


def _load_topics(workspace: Path) -> List[str]:
    topics_path = workspace / "input" / "compliance_topics.json"
    data = _safe_load_json(topics_path)
    topics: List[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "topic" in item and isinstance(item["topic"], str):
                topics.append(item["topic"])
    return topics


def _load_allowed_jurisdictions(workspace: Path) -> List[str]:
    yaml_path = workspace / "input" / "jurisdictions.yaml"
    text = _safe_read_text(yaml_path)
    if text is None:
        return []
    allowed: List[str] = []
    in_key = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("allowed_jurisdictions:"):
            in_key = True
            continue
        if in_key:
            if stripped.startswith("- "):
                val = stripped[2:].strip()
                if val:
                    allowed.append(val)
            elif stripped and not stripped.startswith("#"):
                in_key = False
    return allowed


def _parse_int(value: Any) -> Optional[int]:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            v = value.strip()
            if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
                return int(v)
    except Exception:
        pass
    return None


def _float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_exist": 0.0,
        "sources_raw_structure": 0.0,
        "sources_raw_values_per_topic_count": 0.0,
        "sources_raw_enums_valid": 0.0,
        "sources_ranked_structure": 0.0,
        "sources_ranked_max_three_per_topic": 0.0,
        "sources_ranked_sorted_and_rank_consistent": 0.0,
        "sources_ranked_matches_raw": 0.0,
        "search_log_structure": 0.0,
        "search_log_coverage_per_topic": 0.0,
        "scoring_rules_contents_completeness": 0.0,
        "email_required_fields": 0.0,
        "email_references_top_sources": 0.0,
        "email_mentions_attachments": 0.0,
    }

    out_dir = workspace / "out"
    search_log_path = out_dir / "search_log.jsonl"
    sources_raw_path = out_dir / "sources_raw.json"
    scoring_rules_path = out_dir / "scoring_rules.md"
    sources_ranked_path = out_dir / "sources_ranked.csv"
    email_path = out_dir / "email_to_compliance.md"

    if all(p.exists() for p in [search_log_path, sources_raw_path, scoring_rules_path, sources_ranked_path, email_path]):
        scores["outputs_exist"] = 1.0

    topics = _load_topics(workspace)
    allowed_j = _load_allowed_jurisdictions(workspace)
    allowed_org_types = {"standards_body", "regulator", "industry_association", "official_portal"}
    allowed_doc_types = {"standard", "regulation", "guidance"}
    allowed_jurisdiction_values = {"US", "EU", "International", "Other"}

    raw = _safe_load_json(sources_raw_path) if sources_raw_path.exists() else None
    raw_valid_structure = False
    per_topic_counts_valid = False
    enums_valid = False

    if isinstance(raw, list) and len(raw) >= 1:
        all_items_valid = True
        topic_counts: Dict[str, int] = {t: 0 for t in topics}
        enum_ok = True
        for item in raw:
            if not isinstance(item, dict):
                all_items_valid = False
                break
            required_fields = [
                "topic",
                "title",
                "organization_name",
                "organization_type",
                "doc_type",
                "jurisdiction",
                "publication_year",
                "url",
            ]
            for rf in required_fields:
                if rf not in item:
                    all_items_valid = False
                    break
            if not all_items_valid:
                break
            if not isinstance(item["topic"], str):
                all_items_valid = False
                break
            if item["topic"] not in topics:
                all_items_valid = False
                break
            if not (isinstance(item["title"], str) and item["title"].strip()):
                all_items_valid = False
                break
            if not (isinstance(item["organization_name"], str) and item["organization_name"].strip()):
                all_items_valid = False
                break
            if not (isinstance(item["organization_type"], str) and item["organization_type"] in allowed_org_types):
                enum_ok = False
            if not (isinstance(item["doc_type"], str) and item["doc_type"] in allowed_doc_types):
                enum_ok = False
            if not (isinstance(item["jurisdiction"], str) and item["jurisdiction"] in allowed_jurisdiction_values):
                enum_ok = False
            py_int = _parse_int(item["publication_year"])
            if py_int is None:
                all_items_valid = False
                break
            if not (isinstance(item["url"], str) and item["url"].strip().lower().startswith(("http://", "https://"))):
                all_items_valid = False
                break
            topic_counts[item["topic"]] = topic_counts.get(item["topic"], 0) + 1

        raw_valid_structure = all_items_valid
        enums_valid = enum_ok
        if raw_valid_structure:
            per_topic = True
            for t in topics:
                c = topic_counts.get(t, 0)
                if not (2 <= c <= 5):
                    per_topic = False
                    break
            per_topic_counts_valid = per_topic

    scores["sources_raw_structure"] = 1.0 if raw_valid_structure else 0.0
    scores["sources_raw_values_per_topic_count"] = 1.0 if per_topic_counts_valid else 0.0
    scores["sources_raw_enums_valid"] = 1.0 if enums_valid and raw_valid_structure else 0.0

    ranked_rows = _safe_load_csv(sources_ranked_path) if sources_ranked_path.exists() else None
    ranked_structure_ok = False
    ranked_max_three_ok = False
    ranked_sorted_ok = False
    ranked_matches_raw_ok = False

    required_rank_cols = [
        "topic",
        "rank",
        "score",
        "title",
        "organization_name",
        "organization_type",
        "doc_type",
        "jurisdiction",
        "publication_year",
        "url",
    ]
    if isinstance(ranked_rows, list) and len(ranked_rows) >= 1:
        header_ok = True
        for row in ranked_rows:
            for col in required_rank_cols:
                if col not in row:
                    header_ok = False
                    break
            if not header_ok:
                break
        if header_ok:
            all_rows_valid = True
            per_topic_rows: Dict[str, List[Dict[str, str]]] = {}
            for r in ranked_rows:
                topic_val = r.get("topic", "")
                if topic_val not in topics:
                    all_rows_valid = False
                    break
                sc = _float(r.get("score"))
                if sc is None:
                    all_rows_valid = False
                    break
                rk = _parse_int(r.get("rank"))
                if rk is None or rk < 1:
                    all_rows_valid = False
                    break
                if _parse_int(r.get("publication_year")) is None:
                    all_rows_valid = False
                    break
                if r.get("organization_type") not in allowed_org_types:
                    all_rows_valid = False
                    break
                if r.get("doc_type") not in allowed_doc_types:
                    all_rows_valid = False
                    break
                if r.get("jurisdiction") not in allowed_jurisdiction_values:
                    all_rows_valid = False
                    break
                if not r.get("title", "").strip() or not r.get("organization_name", "").strip():
                    all_rows_valid = False
                    break
                if not r.get("url", "").strip().lower().startswith(("http://", "https://")):
                    all_rows_valid = False
                    break
                per_topic_rows.setdefault(topic_val, []).append(r)

            ranked_structure_ok = all_rows_valid

            if ranked_structure_ok:
                max_three = True
                for _, rows in per_topic_rows.items():
                    if len(rows) > 3:
                        max_three = False
                        break
                ranked_max_three_ok = max_three

            if ranked_structure_ok:
                sorted_ok = True
                for _, rows in per_topic_rows.items():
                    prev_score = None
                    expected_rank = 1
                    for row in rows:
                        sc = _float(row.get("score"))
                        rk = _parse_int(row.get("rank"))
                        if sc is None or rk is None:
                            sorted_ok = False
                            break
                        if prev_score is not None and sc > prev_score + 1e-12:
                            sorted_ok = False
                            break
                        if rk != expected_rank:
                            sorted_ok = False
                            break
                        prev_score = sc
                        expected_rank += 1
                    if not sorted_ok:
                        break
                ranked_sorted_ok = sorted_ok

            if ranked_structure_ok and isinstance(raw, list):
                raw_index: Dict[tuple, dict] = {}
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    key = (
                        item.get("topic"),
                        item.get("title"),
                        item.get("organization_name"),
                        item.get("url"),
                    )
                    raw_index[key] = item
                match_ok = True
                for row in ranked_rows:
                    key = (
                        row.get("topic"),
                        row.get("title"),
                        row.get("organization_name"),
                        row.get("url"),
                    )
                    if key not in raw_index:
                        match_ok = False
                        break
                    src = raw_index[key]
                    if str(src.get("organization_type")) != str(row.get("organization_type")):
                        match_ok = False
                        break
                    if str(src.get("doc_type")) != str(row.get("doc_type")):
                        match_ok = False
                        break
                    if str(src.get("jurisdiction")) != str(row.get("jurisdiction")):
                        match_ok = False
                        break
                    si = _parse_int(src.get("publication_year"))
                    ri = _parse_int(row.get("publication_year"))
                    if si is None or ri is None or si != ri:
                        match_ok = False
                        break
                ranked_matches_raw_ok = match_ok

    scores["sources_ranked_structure"] = 1.0 if ranked_structure_ok else 0.0
    scores["sources_ranked_max_three_per_topic"] = 1.0 if ranked_max_three_ok else 0.0
    scores["sources_ranked_sorted_and_rank_consistent"] = 1.0 if ranked_sorted_ok else 0.0
    scores["sources_ranked_matches_raw"] = 1.0 if ranked_matches_raw_ok else 0.0

    logs = _safe_load_jsonl(search_log_path) if search_log_path.exists() else None
    search_structure_ok = False
    search_coverage_ok = False
    if isinstance(logs, list) and len(logs) >= 1:
        struct_ok = True
        per_topic_seen: Dict[str, int] = {t: 0 for t in topics}
        for entry in logs:
            if not isinstance(entry, dict):
                struct_ok = False
                break
            for field in ["topic", "query", "engine", "timestamp", "notes"]:
                if field not in entry:
                    struct_ok = False
                    break
                if not isinstance(entry[field], str):
                    struct_ok = False
                    break
            if not struct_ok:
                break
            if entry["topic"] in per_topic_seen:
                per_topic_seen[entry["topic"]] += 1
        search_structure_ok = struct_ok
        if struct_ok:
            cov_ok = True
            for t in topics:
                if per_topic_seen.get(t, 0) < 1:
                    cov_ok = False
                    break
            search_coverage_ok = cov_ok

    scores["search_log_structure"] = 1.0 if search_structure_ok else 0.0
    scores["search_log_coverage_per_topic"] = 1.0 if search_coverage_ok else 0.0

    scoring_text = _safe_read_text(scoring_rules_path) if scoring_rules_path.exists() else None
    scoring_ok = False
    if isinstance(scoring_text, str) and scoring_text.strip():
        lower = scoring_text.lower()
        must_tokens = [
            "organization_type",
            "doc_type",
            "jurisdiction",
            "publication_year",
            "base",
            "bonus",
            "recency",
            "score",
        ]
        has_tokens = all(tok in lower for tok in must_tokens)
        has_tie = ("tie" in lower and ("break" in lower or "breaker" in lower or "tiebreak" in lower))
        mentions_org_types = any(t in lower for t in ["standards_body", "regulator", "industry_association", "official_portal"])
        mentions_doc_types = any(t in lower for t in ["standard", "regulation", "guidance"])
        mentions_allowed_j = any(j.lower() in lower for j in allowed_j) or ("us" in lower or "eu" in lower)
        scoring_ok = has_tokens and has_tie and mentions_org_types and mentions_doc_types and mentions_allowed_j
    scores["scoring_rules_contents_completeness"] = 1.0 if scoring_ok else 0.0

    email_text = _safe_read_text(email_path) if email_path.exists() else None
    email_required_ok = False
    email_refs_top_ok = False
    email_attached_ok = False
    if isinstance(email_text, str) and email_text.strip():
        to_ok = re.search(r"^to:\s*compliance@company\.example\s*$", email_text, flags=re.IGNORECASE | re.MULTILINE) is not None
        subj_ok = re.search(
            r"^subject:\s*request:\s*review of payment compliance sources for checkout service\s*$",
            email_text,
            flags=re.IGNORECASE | re.MULTILINE,
        ) is not None
        intro_ok = False
        if "go" in email_text.lower() or "golang" in email_text.lower():
            if "checkout" in email_text.lower() or "microservice" in email_text.lower():
                intro_ok = True
        email_required_ok = to_ok and subj_ok and intro_ok

        attach_ok = ("out/sources_ranked.csv" in email_text) and ("out/search_log.jsonl" in email_text)
        email_attached_ok = attach_ok

        if isinstance(ranked_rows, list):
            top_per_topic: Dict[str, Dict[str, str]] = {}
            for row in ranked_rows:
                try:
                    rk = int(row.get("rank", ""))
                except Exception:
                    continue
                if rk == 1:
                    t = row.get("topic", "")
                    if t and t not in top_per_topic:
                        top_per_topic[t] = row
            all_topics_ok = True
            for t in topics:
                if t not in top_per_topic:
                    all_topics_ok = False
                    break
            if all_topics_ok:
                per_topic_refs_ok = True
                for t, top in top_per_topic.items():
                    title = top.get("title", "")
                    org = top.get("organization_name", "")
                    if title and org and (title in email_text) and (org in email_text):
                        idx = email_text.find(title)
                        if idx != -1:
                            window = email_text[idx: idx + 300]
                            if "?" not in window:
                                per_topic_refs_ok = False
                                break
                        else:
                            per_topic_refs_ok = False
                            break
                    else:
                        per_topic_refs_ok = False
                        break
                email_refs_top_ok = per_topic_refs_ok
            else:
                email_refs_top_ok = False

    scores["email_required_fields"] = 1.0 if email_required_ok else 0.0
    scores["email_references_top_sources"] = 1.0 if email_refs_top_ok else 0.0
    scores["email_mentions_attachments"] = 1.0 if email_attached_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()