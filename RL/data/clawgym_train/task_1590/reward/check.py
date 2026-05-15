import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse


def _read_text(path: Path) -> tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
        return True, text
    except Exception:
        return False, ""


def _parse_csv(path: Path) -> tuple[bool, list[str], list[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            content = f.read()
        if content.strip() == "":
            return False, [], []
        # Collect header order
        lines = content.splitlines()
        header_line = None
        for line in lines:
            if line.strip() != "":
                header_line = line
                break
        if header_line is None:
            return False, [], []
        header = next(csv.reader([header_line]))
        # Now use DictReader for rows
        rows = []
        reader = csv.DictReader(content.splitlines())
        for row in reader:
            # skip completely empty rows
            if not any((v or "").strip() for v in row.values()):
                continue
            rows.append(row)
        return True, header, rows
    except Exception:
        return False, [], []


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_simple_yaml_brief(path: Path) -> dict:
    ok, text = _read_text(path)
    if not ok:
        return {}
    lines = text.splitlines()
    result = {}
    # Helper to get list under a top-level key
    def get_list(key: str) -> list[str]:
        items = []
        in_section = False
        base_indent = None
        for ln in lines:
            if re.match(rf"^{key}:\s*$", ln.strip()) or re.match(rf"^{key}:\s*$", ln):
                in_section = True
                base_indent = len(ln) - len(ln.lstrip(' '))
                continue
            if in_section:
                if ln.strip() == "" or ln.strip().startswith("#"):
                    continue
                indent = len(ln) - len(ln.lstrip(' '))
                if indent <= base_indent:
                    break
                if ln.strip().startswith("- "):
                    val = ln.strip()[2:].strip()
                    items.append(_strip_quotes(val))
                else:
                    # non-list item ends section
                    break
        return items

    def get_scalar(key: str) -> str | None:
        for ln in lines:
            m = re.match(rf"^{key}:\s*(.+)\s*$", ln.strip())
            if m:
                return _strip_quotes(m.group(1))
        return None

    def get_nested_scalar(top_key: str, nested_key: str) -> str | None:
        in_section = False
        base_indent = None
        for ln in lines:
            if re.match(rf"^{top_key}:\s*$", ln.strip()) or re.match(rf"^{top_key}:\s*$", ln):
                in_section = True
                base_indent = len(ln) - len(ln.lstrip(' '))
                continue
            if in_section:
                if ln.strip() == "" or ln.strip().startswith("#"):
                    continue
                indent = len(ln) - len(ln.lstrip(' '))
                if indent <= base_indent:
                    break
                m = re.match(rf"^\s*{nested_key}:\s*(.+)\s*$", ln)
                if m:
                    return _strip_quotes(m.group(1))
        return None

    def get_nested_int(top_key: str, nested_key: str) -> int | None:
        val = get_nested_scalar(top_key, nested_key)
        if val is None:
            return None
        try:
            return int(str(val).strip())
        except Exception:
            return None

    result["campaign_name"] = get_scalar("campaign_name") or ""
    result["allowed_orgs"] = get_list("allowed_orgs")
    result["allowed_domains"] = get_list("allowed_domains")
    result["focus_topics"] = get_list("focus_topics")
    result["earliest_year"] = get_nested_int("constraints", "earliest_year") or None
    result["max_items"] = get_nested_int("constraints", "max_items") or None
    result["cadence"] = get_nested_scalar("posting_guidance", "cadence") or ""
    return result


def _extract_base_domain(host: str) -> str:
    host = (host or "").strip().lower()
    if host == "":
        return ""
    # remove port if present
    host = host.split(":")[0]
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _parse_url(url: str) -> tuple[bool, str, str]:
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https"):
            return False, "", ""
        if not u.netloc:
            return False, "", ""
        base_domain = _extract_base_domain(u.hostname or "")
        return True, u.hostname or "", base_domain
    except Exception:
        return False, "", ""


def _sentence_count(text: str) -> int:
    text = (text or "").strip()
    if text == "":
        return 0
    # Count sentence enders . ! ? not followed by a letter without space
    matches = re.findall(r"[.!?](?:\s|$)", text)
    if not matches:
        # If no terminal punctuation, count as 1 sentence if there are words
        return 1 if re.search(r"[A-Za-zÁÉÍÓÚáéíóúñÑü]", text) else 0
    return len(matches)


def _is_spanish_like(text: str, min_hits: int = 2) -> bool:
    text = (text or "").lower()
    # common Spanish function words and domain terms
    spanish_tokens = {
        "el", "la", "los", "las", "de", "del", "y", "para", "sobre", "en",
        "derechos", "humanos", "resumen", "síntesis", "justicia",
        "expresión", "juicio", "tortura", "prevención"
    }
    words = re.findall(r"\b[a-záéíóúñü]+\b", text)
    hits = sum(1 for w in words if w in spanish_tokens)
    return hits >= min_hits


def _has_terminology_pairs(text: str, min_pairs: int = 3) -> bool:
    t = (text or "").strip()
    if t == "":
        return False
    # Split by semicolons primarily
    parts = [p.strip() for p in re.split(r"[;|]", t) if p.strip()]
    if not parts:
        parts = [p.strip() for p in t.split(",") if p.strip()]
    pair_count = 0
    for p in parts:
        # Detect separators between EN and ES term
        if re.search(r"\s(?:-|—|:|=)\s", p):
            pair_count += 1
        else:
            # fallback: "English (Español)" pattern
            if re.search(r"\([^)]+\)", p):
                pair_count += 1
    return pair_count >= min_pairs


def _date_within_next_two_weeks(date_str: str) -> bool:
    try:
        due = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        return today <= due <= (today + timedelta(days=14))
    except Exception:
        return False


def _count_action_items(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if line.strip().startswith(("-", "*", "•")):
            # Look for owner and ISO date
            m = re.search(r"\b(Student|Mentor)\b", line, flags=re.IGNORECASE)
            d = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", line)
            if m and d and _date_within_next_two_weeks(d.group(1)):
                count += 1
    return count


def _contains_all_topics(text: str, topics: list[str]) -> bool:
    t = text.lower()
    for topic in topics:
        if topic.lower() not in t:
            return False
    return True


def _find_queries_and_engine(log_text: str) -> tuple[int, bool, dict]:
    lines = [ln.strip() for ln in log_text.splitlines() if ln.strip()]
    # Count distinct query-like bullet lines
    queries = set()
    for ln in lines:
        if ln.startswith(("-", "*", "•")):
            q = ln.lstrip("-*•").strip()
            if len(q.split()) >= 2:
                queries.add(q)
        elif re.search(r"\bquery\b\s*[:\-]", ln, flags=re.IGNORECASE):
            # Extract after 'query:'
            parts = re.split(r"\bquery\b\s*[:\-]\s*", ln, flags=re.IGNORECASE, maxsplit=1)
            if len(parts) == 2:
                q = parts[1].strip()
                if len(q.split()) >= 2:
                    queries.add(q)
    # Detect search engines
    engine_present = bool(re.search(r"\b(google|bing|duckduckgo|ecosia|brave|yahoo)\b", log_text, flags=re.IGNORECASE))
    # Org mentions
    org_hits = {
        "Amnesty International": bool(re.search(r"Amnesty International", log_text, flags=re.IGNORECASE)),
        "Human Rights Watch": bool(re.search(r"Human Rights Watch|HRW\b", log_text, flags=re.IGNORECASE)),
        "Office of the UN High Commissioner for Human Rights": bool(re.search(r"Office of the UN High Commissioner for Human Rights|OHCHR\b", log_text, flags=re.IGNORECASE)),
    }
    return len(queries), engine_present, org_hits


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "content_plan_exists_and_header": 0.0,
        "content_plan_row_count": 0.0,
        "content_plan_orgs_valid_unique": 0.0,
        "content_plan_years_and_domains_valid": 0.0,
        "content_plan_focus_topics_coverage": 0.0,
        "content_plan_summaries_en_sentences": 0.0,
        "content_plan_summaries_es_translation_like": 0.0,
        "content_plan_posts_en_one_sentence": 0.0,
        "content_plan_posts_es_translation_like": 0.0,
        "content_plan_terminology_notes_pairs": 0.0,
        "content_plan_exec_summary_yes_and_validation_comment": 0.0,
        "logs_search_queries_present_and_count": 0.0,
        "logs_contains_engine_and_org_mapping": 0.0,
        "meeting_notes_sections_and_references": 0.0,
        "meeting_notes_cadence_and_topics": 0.0,
        "meeting_notes_action_items_with_due_dates": 0.0,
        "meeting_notes_dependencies_risks": 0.0,
    }

    # Load brief.yaml
    brief_path = workspace / "input" / "brief.yaml"
    brief = _parse_simple_yaml_brief(brief_path)
    allowed_orgs = brief.get("allowed_orgs") or []
    allowed_domains = brief.get("allowed_domains") or []
    focus_topics = brief.get("focus_topics") or []
    earliest_year = brief.get("earliest_year")
    campaign_name = brief.get("campaign_name") or ""
    cadence = brief.get("cadence") or ""

    # Check outputs/content_plan.csv
    cp_path = workspace / "outputs" / "content_plan.csv"
    cp_ok, header, rows = _parse_csv(cp_path)
    required_cols = [
        "org",
        "report_title_en",
        "report_year",
        "report_link",
        "source_domain",
        "focus_topic",
        "summary_en",
        "summary_es",
        "post_idea_en",
        "post_idea_es",
        "terminology_notes",
        "executive_summary_check",
        "validation_comment",
    ]
    if cp_ok and header == required_cols:
        scores["content_plan_exists_and_header"] = 1.0
    else:
        scores["content_plan_exists_and_header"] = 0.0

    if cp_ok:
        # Row count exactly 3 (max_items)
        if len(rows) == 3:
            scores["content_plan_row_count"] = 1.0

        # Validate each row fields
        orgs_valid = True
        orgs_set = set()
        years_domains_valid = True
        focus_topics_set = set()
        summaries_en_ok = True
        summaries_es_ok = True
        posts_en_ok = True
        posts_es_ok = True
        terminology_ok = True
        exec_and_validation_ok = True

        for row in rows:
            org = (row.get("org") or "").strip()
            if org not in allowed_orgs:
                orgs_valid = False
            orgs_set.add(org)

            # year
            year_str = (row.get("report_year") or "").strip()
            try:
                y = int(year_str)
                if earliest_year is None or y < int(earliest_year):
                    years_domains_valid = False
            except Exception:
                years_domains_valid = False

            # link and domain
            link = (row.get("report_link") or "").strip()
            link_ok, host, base_dom = _parse_url(link)
            src_domain = (row.get("source_domain") or "").strip().lower()
            if not link_ok:
                years_domains_valid = False
            else:
                # domain checks
                if base_dom not in allowed_domains:
                    years_domains_valid = False
                if src_domain != base_dom:
                    years_domains_valid = False

            # focus topic
            ft = (row.get("focus_topic") or "").strip()
            if ft not in focus_topics:
                years_domains_valid = False
            focus_topics_set.add(ft)

            # summary_en sentences 1-2 and not empty
            sum_en = (row.get("summary_en") or "").strip()
            sc = _sentence_count(sum_en)
            if sc < 1 or sc > 2:
                summaries_en_ok = False

            # summary_es Spanish-like and not identical
            sum_es = (row.get("summary_es") or "").strip()
            if sum_es == "" or sum_es.strip() == sum_en.strip() or not _is_spanish_like(sum_es, min_hits=2):
                summaries_es_ok = False
            # optional: ensure 1-2 sentences too
            sc_es = _sentence_count(sum_es)
            if sc_es < 1 or sc_es > 2:
                summaries_es_ok = False

            # post_idea_en one sentence
            post_en = (row.get("post_idea_en") or "").strip()
            if _sentence_count(post_en) != 1:
                posts_en_ok = False

            # post_idea_es spanish-like translation, one sentence
            post_es = (row.get("post_idea_es") or "").strip()
            if post_es.strip() == post_en.strip() or not _is_spanish_like(post_es, min_hits=2) or _sentence_count(post_es) != 1:
                posts_es_ok = False

            # terminology notes at least three pairs
            terms = (row.get("terminology_notes") or "").strip()
            if not _has_terminology_pairs(terms, min_pairs=3):
                terminology_ok = False

            # executive_summary_check yes and validation comment 1-2 sentences with keywords
            esc = (row.get("executive_summary_check") or "").strip().lower()
            valc = (row.get("validation_comment") or "").strip()
            if esc != "yes":
                exec_and_validation_ok = False
            vc_sentences = _sentence_count(valc)
            if vc_sentences < 1 or vc_sentences > 2:
                exec_and_validation_ok = False
            # keywords
            if not (re.search(r"\b(official|domain)\b", valc, flags=re.IGNORECASE) and re.search(r"\b(executive|overview)\b", valc, flags=re.IGNORECASE)):
                exec_and_validation_ok = False

        # One report per allowed organization (all three, unique)
        if set(allowed_orgs) and orgs_valid and orgs_set == set(allowed_orgs):
            scores["content_plan_orgs_valid_unique"] = 1.0

        if years_domains_valid:
            scores["content_plan_years_and_domains_valid"] = 1.0

        # focus topics coverage: each topic represented at least once (here 3 topics, 3 rows)
        if set(focus_topics) and focus_topics_set == set(focus_topics):
            scores["content_plan_focus_topics_coverage"] = 1.0

        if summaries_en_ok:
            scores["content_plan_summaries_en_sentences"] = 1.0

        if summaries_es_ok:
            scores["content_plan_summaries_es_translation_like"] = 1.0

        if posts_en_ok:
            scores["content_plan_posts_en_one_sentence"] = 1.0

        if posts_es_ok:
            scores["content_plan_posts_es_translation_like"] = 1.0

        if terminology_ok:
            scores["content_plan_terminology_notes_pairs"] = 1.0

        if exec_and_validation_ok:
            scores["content_plan_exec_summary_yes_and_validation_comment"] = 1.0

    # logs/search_queries.txt
    logs_path = workspace / "logs" / "search_queries.txt"
    ok_log, log_text = _read_text(logs_path)
    if ok_log and log_text.strip():
        q_count, engine_present, org_hits = _find_queries_and_engine(log_text)
        if q_count >= 3:
            scores["logs_search_queries_present_and_count"] = 1.0
        if engine_present and all(org_hits.get(k, False) for k in org_hits):
            scores["logs_contains_engine_and_org_mapping"] = 1.0

    # outputs/meeting_notes.md
    mn_path = workspace / "outputs" / "meeting_notes.md"
    ok_mn, mn_text = _read_text(mn_path)
    if ok_mn and mn_text.strip():
        # Sections presence
        has_context = bool(re.search(r"\bContext\b", mn_text, flags=re.IGNORECASE))
        has_decisions = bool(re.search(r"\b(Decisions|Proposals)\b", mn_text, flags=re.IGNORECASE))
        has_actions = bool(re.search(r"\bAction Items\b", mn_text, flags=re.IGNORECASE))
        has_deps = bool(re.search(r"\b(Dependencies|Risks)\b", mn_text, flags=re.IGNORECASE))
        # References to campaign and outputs
        has_campaign = campaign_name and (campaign_name in mn_text)
        refs_ok = ("outputs/content_plan.csv" in mn_text) and ("logs/search_queries.txt" in mn_text)
        if has_context and has_decisions and has_actions and has_deps and has_campaign and refs_ok:
            scores["meeting_notes_sections_and_references"] = 1.0

        # Cadence and topics
        cadence_ok = False
        if cadence:
            # check "2-3 posts/week" or variant
            cadence_ok = bool(re.search(r"\b2\s*-\s*3\b.*\bposts?/?\s*week\b", mn_text, flags=re.IGNORECASE)) or \
                         bool(re.search(r"\b2\s*to\s*3\b.*\bposts?\s+(per\s+)?week\b", mn_text, flags=re.IGNORECASE))
        topics_ok = _contains_all_topics(mn_text, focus_topics) if focus_topics else False
        if cadence_ok and topics_ok:
            scores["meeting_notes_cadence_and_topics"] = 1.0

        # Action items with due dates and owners (>=5)
        action_items_count = _count_action_items(mn_text)
        if action_items_count >= 5:
            scores["meeting_notes_action_items_with_due_dates"] = 1.0

        # Dependencies/Risks keywords
        dep_ok = False
        if re.search(r"\btranslation\b", mn_text, flags=re.IGNORECASE) and re.search(r"\bapproval|review|terminology\b", mn_text, flags=re.IGNORECASE):
            dep_ok = True
        if dep_ok:
            scores["meeting_notes_dependencies_risks"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()