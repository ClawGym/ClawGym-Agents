import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_yaml_benefits(path: Path) -> Optional[List[Dict[str, object]]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    benefits: List[Dict[str, object]] = []
    current: Optional[Dict[str, object]] = None
    in_benefits = False
    for raw in lines:
        line = raw.rstrip()
        if not in_benefits:
            if line.strip().startswith("benefits:"):
                in_benefits = True
            continue
        if re.match(r'^\s*-\s*id:\s*', line):
            if current:
                benefits.append(current)
            m = re.match(r'^\s*-\s*id:\s*(.+?)\s*$', line)
            if not m:
                return None
            id_val = m.group(1).strip()
            id_val = id_val.strip('"').strip("'")
            current = {"id": id_val, "title": None, "keywords": [], "stat": None, "claim": None}
            continue
        if current is None:
            continue
        m_title = re.match(r'^\s*title:\s*(.+?)\s*$', line)
        m_keywords = re.match(r'^\s*keywords:\s*\[(.+)\]\s*$', line)
        m_stat = re.match(r'^\s*stat:\s*(.+?)\s*$', line)
        m_claim = re.match(r'^\s*claim:\s*(.+?)\s*$', line)
        if m_title:
            val = m_title.group(1).strip()
            current["title"] = val.strip('"').strip("'")
        elif m_keywords:
            inner = m_keywords.group(1).strip()
            items = []
            for part in inner.split(","):
                p = part.strip()
                if p.startswith('"') and p.endswith('"'):
                    p = p[1:-1]
                elif p.startswith("'") and p.endswith("'"):
                    p = p[1:-1]
                if p:
                    items.append(p)
            current["keywords"] = items
        elif m_stat:
            val = m_stat.group(1).strip()
            current["stat"] = val.strip('"').strip("'")
        elif m_claim:
            val = m_claim.group(1).strip()
            current["claim"] = val.strip('"').strip("'")
    if current:
        benefits.append(current)
    for b in benefits:
        if not all(k in b for k in ("id", "title", "keywords", "stat", "claim")):
            return None
        if b["id"] is None or b["title"] is None or b["stat"] is None or b["claim"] is None:
            return None
        if not isinstance(b["keywords"], list):
            return None
    return benefits


def _extract_quotes(text: str) -> List[str]:
    return re.findall(r'"([^"]+)"', text)


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+(?:'\w+)?\b", text))


def _split_paragraphs(text: str) -> List[str]:
    paragraphs = []
    current_lines = []
    for line in text.splitlines():
        if line.strip() == "":
            if current_lines:
                paragraphs.append("\n".join(current_lines).strip())
                current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        paragraphs.append("\n".join(current_lines).strip())
    paragraphs = [p for p in paragraphs if p.strip()]
    return paragraphs


def _compute_keyword_tally(notes_by_prospect: Dict[str, str], benefits: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    tally: Dict[str, Dict[str, object]] = {}
    benefit_kw = {}
    for b in benefits:
        kws = [str(k).lower() for k in b.get("keywords", [])]
        benefit_kw[b["id"]] = kws
        tally[b["id"]] = {"title": b["title"], "count": 0, "quotes": set()}
    for _pid, note_text in notes_by_prospect.items():
        if note_text is None:
            continue
        quotes = _extract_quotes(note_text)
        for q in quotes:
            q_lower = q.lower()
            for bid, kw_list in benefit_kw.items():
                if any(k in q_lower for k in kw_list):
                    tally[bid]["count"] += 1
                    tally[bid]["quotes"].add(q)
    return tally


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "run_sh_present": 0.0,
        "run_sh_has_comment_and_shebang": 0.0,
        "insights_exists_and_length": 0.0,
        "insights_fields_structure": 0.0,
        "insights_names_match_csv": 0.0,
        "insights_objections_from_notes": 0.0,
        "insights_matched_benefits_valid": 0.0,
        "insights_selected_stat_in_email": 0.0,
        "insights_quote_consistency": 0.0,
        "emails_present_for_all_prospects": 0.0,
        "emails_subject_includes_company": 0.0,
        "emails_word_count_and_paragraphs": 0.0,
        "emails_exactly_one_direct_quote_from_notes": 0.0,
        "emails_include_stat_from_yaml": 0.0,
        "emails_mention_company_and_role": 0.0,
        "emails_end_with_call_to_action": 0.0,
        "aggregates_exists_and_structure": 0.0,
        "aggregates_counts_match_keyword_mapping": 0.0,
    }

    prospects_csv_path = workspace / "input" / "prospects.csv"
    notes_dir = workspace / "input" / "notes"
    benefits_yaml_path = workspace / "input" / "product_benefits.yaml"

    prospects_rows = _load_csv_dicts(prospects_csv_path) or []
    prospects_by_id: Dict[str, Dict[str, str]] = {r.get("prospect_id", "").strip(): r for r in prospects_rows if r.get("prospect_id")}
    prospect_ids = list(prospects_by_id.keys())

    notes_by_prospect: Dict[str, Optional[str]] = {}
    for pid in prospect_ids:
        npath = notes_dir / f"{pid}.md"
        notes_by_prospect[pid] = _read_text(npath)

    benefits = _parse_yaml_benefits(benefits_yaml_path) or []
    benefits_by_id = {b["id"]: b for b in benefits}
    benefit_ids_set = set(benefits_by_id.keys())
    benefits_stats = [b["stat"] for b in benefits]
    benefits_titles_by_id = {b["id"]: b["title"] for b in benefits}

    run_sh_path = workspace / "run.sh"
    if run_sh_path.exists() and run_sh_path.is_file():
        scores["run_sh_present"] = 1.0
        content = _read_text(run_sh_path) or ""
        if content:
            lines = content.splitlines()
            shebang_ok = False
            if lines:
                first = lines[0].strip()
                if first.startswith("#!"):
                    shebang_ok = True
            comment_ok = any(re.search(r"#.*\b(rerun|re-run|adjust|paths|path|usage|run)\b", ln, flags=re.IGNORECASE) for ln in lines)
            if shebang_ok and comment_ok:
                scores["run_sh_has_comment_and_shebang"] = 1.0

    insights_path = workspace / "output" / "insights" / "prospect_insights.json"
    emails_dir = workspace / "output" / "emails"
    aggregates_path = workspace / "output" / "aggregates" / "objection_tally.csv"

    insights = _load_json(insights_path)
    insights_is_list = isinstance(insights, list)
    if insights_is_list and prospects_by_id:
        if len(insights) == len(prospect_ids):
            scores["insights_exists_and_length"] = 1.0

    if insights_is_list and len(insights) > 0:
        struct_ok = True
        for item in insights:
            if not isinstance(item, dict):
                struct_ok = False
                break
            req_keys = ["prospect_id", "name", "company", "role", "top_objection_phrases", "matched_benefit_ids", "selected_stat", "quote_used_in_email"]
            for k in req_keys:
                if k not in item:
                    struct_ok = False
                    break
            if not struct_ok:
                break
            if not isinstance(item.get("prospect_id"), str):
                struct_ok = False
                break
            if not isinstance(item.get("name"), str) or not isinstance(item.get("company"), str) or not isinstance(item.get("role"), str):
                struct_ok = False
                break
            top_obs = item.get("top_objection_phrases")
            mbids = item.get("matched_benefit_ids")
            if not isinstance(top_obs, list) or not (1 <= len(top_obs) <= 3) or not all(isinstance(x, str) for x in top_obs):
                struct_ok = False
                break
            if not isinstance(mbids, list) or not (1 <= len(mbids) <= 3) or not all(isinstance(x, str) for x in mbids):
                struct_ok = False
                break
            if not isinstance(item.get("selected_stat"), str) or not isinstance(item.get("quote_used_in_email"), str):
                struct_ok = False
                break
        if struct_ok:
            scores["insights_fields_structure"] = 1.0

    if insights_is_list and prospects_by_id:
        names_ok = True
        seen_ids = set()
        for item in insights:
            pid = item.get("prospect_id")
            if pid not in prospects_by_id:
                names_ok = False
                break
            seen_ids.add(pid)
            p = prospects_by_id[pid]
            if (item.get("name") or "").strip() != (p.get("name") or "").strip():
                names_ok = False
                break
            if (item.get("company") or "").strip() != (p.get("company") or "").strip():
                names_ok = False
                break
            if (item.get("role") or "").strip() != (p.get("role") or "").strip():
                names_ok = False
                break
        if names_ok and len(seen_ids) == len(prospect_ids):
            scores["insights_names_match_csv"] = 1.0

    if insights_is_list and prospects_by_id:
        objections_ok = True
        for item in insights:
            pid = item.get("prospect_id")
            note_text = notes_by_prospect.get(pid)
            if note_text is None:
                objections_ok = False
                break
            top_obs = item.get("top_objection_phrases") or []
            if not (1 <= len(top_obs) <= 3):
                objections_ok = False
                break
            for phrase in top_obs:
                if phrase not in note_text:
                    objections_ok = False
                    break
            if not objections_ok:
                break
            q_email = item.get("quote_used_in_email")
            if q_email not in top_obs or q_email not in note_text:
                objections_ok = False
                break
        if objections_ok:
            scores["insights_objections_from_notes"] = 1.0

    if insights_is_list and benefits_by_id and prospects_by_id:
        matched_ok = True
        for item in insights:
            pid = item.get("prospect_id")
            note_text = (notes_by_prospect.get(pid) or "").lower()
            for bid in item.get("matched_benefit_ids", []):
                if bid not in benefits_by_id:
                    matched_ok = False
                    break
                kws = [str(k).lower() for k in benefits_by_id[bid].get("keywords", [])]
                if not any(k in note_text for k in kws):
                    matched_ok = False
                    break
            if not matched_ok:
                break
        if matched_ok:
            scores["insights_matched_benefits_valid"] = 1.0

    emails_present = True
    email_texts: Dict[str, Optional[str]] = {}
    if prospect_ids:
        for pid in prospect_ids:
            ep = emails_dir / f"{pid}.txt"
            if not ep.exists():
                emails_present = False
            email_texts[pid] = _read_text(ep) if ep.exists() else None
    else:
        emails_present = False
    if emails_present and all(email_texts.get(pid) is not None for pid in prospect_ids):
        scores["emails_present_for_all_prospects"] = 1.0

    subject_ok_all = True
    if email_texts and prospects_by_id:
        for pid, etxt in email_texts.items():
            if etxt is None:
                subject_ok_all = False
                break
            lines = etxt.splitlines()
            if not lines:
                subject_ok_all = False
                break
            first = lines[0].strip()
            if not first.startswith("Subject:"):
                subject_ok_all = False
                break
            company = (prospects_by_id.get(pid, {}).get("company") or "").strip()
            if company and company not in first:
                subject_ok_all = False
                break
        if subject_ok_all:
            scores["emails_subject_includes_company"] = 1.0

    body_len_ok_all = True
    if email_texts:
        for pid, etxt in email_texts.items():
            if etxt is None:
                body_len_ok_all = False
                break
            lines = etxt.splitlines()
            if len(lines) < 2:
                body_len_ok_all = False
                break
            body = "\n".join(lines[1:]).strip()
            words = _count_words(body)
            if not (90 <= words <= 150):
                body_len_ok_all = False
                break
            paragraphs = _split_paragraphs(body)
            if not (2 <= len(paragraphs) <= 3):
                body_len_ok_all = False
                break
        if body_len_ok_all:
            scores["emails_word_count_and_paragraphs"] = 1.0

    quotes_ok_all = True
    if email_texts and notes_by_prospect:
        for pid, etxt in email_texts.items():
            if etxt is None:
                quotes_ok_all = False
                break
            lines = etxt.splitlines()
            body = "\n".join(lines[1:]) if len(lines) > 1 else ""
            quoted = _extract_quotes(body)
            if len(quoted) != 1:
                quotes_ok_all = False
                break
            note_text = notes_by_prospect.get(pid) or ""
            if quoted[0] not in note_text:
                quotes_ok_all = False
                break
        if quotes_ok_all:
            scores["emails_exactly_one_direct_quote_from_notes"] = 1.0

    stats_ok_all = True
    if email_texts and benefits_stats:
        for pid, etxt in email_texts.items():
            if etxt is None:
                stats_ok_all = False
                break
            lines = etxt.splitlines()
            body = "\n".join(lines[1:]) if len(lines) > 1 else ""
            if not any(stat in body for stat in benefits_stats):
                stats_ok_all = False
                break
        if stats_ok_all:
            scores["emails_include_stat_from_yaml"] = 1.0

    mentions_ok_all = True
    if email_texts and prospects_by_id:
        for pid, etxt in email_texts.items():
            if etxt is None:
                mentions_ok_all = False
                break
            lines = etxt.splitlines()
            body = "\n".join(lines[1:]) if len(lines) > 1 else ""
            company = (prospects_by_id.get(pid, {}).get("company") or "").strip()
            role = (prospects_by_id.get(pid, {}).get("role") or "").strip()
            if company and company not in body:
                mentions_ok_all = False
                break
            if role and role not in body:
                mentions_ok_all = False
                break
        if mentions_ok_all:
            scores["emails_mention_company_and_role"] = 1.0

    cta_ok_all = True
    if email_texts:
        for pid, etxt in email_texts.items():
            if etxt is None:
                cta_ok_all = False
                break
            lines = [ln.rstrip() for ln in etxt.splitlines()]
            last_nonempty = None
            for ln in reversed(lines):
                if ln.strip() != "":
                    last_nonempty = ln
                    break
            if last_nonempty is None or not last_nonempty.startswith("Call to action:"):
                cta_ok_all = False
                break
        if cta_ok_all:
            scores["emails_end_with_call_to_action"] = 1.0

    stat_in_email_ok = True
    if insights_is_list and benefits_stats and email_texts:
        for item in insights:
            pid = item.get("prospect_id")
            selected_stat = item.get("selected_stat")
            if selected_stat not in benefits_stats:
                stat_in_email_ok = False
                break
            etxt = email_texts.get(pid)
            if etxt is None:
                stat_in_email_ok = False
                break
            body = "\n".join(etxt.splitlines()[1:]) if len(etxt.splitlines()) > 1 else ""
            if selected_stat not in body:
                stat_in_email_ok = False
                break
        if stat_in_email_ok:
            scores["insights_selected_stat_in_email"] = 1.0

    quote_consistency_ok = True
    if insights_is_list and email_texts:
        for item in insights:
            pid = item.get("prospect_id")
            q = item.get("quote_used_in_email")
            top_obs = item.get("top_objection_phrases") or []
            etxt = email_texts.get(pid)
            if etxt is None:
                quote_consistency_ok = False
                break
            body = "\n".join(etxt.splitlines()[1:]) if len(etxt.splitlines()) > 1 else ""
            quoted = _extract_quotes(body)
            if len(quoted) != 1 or q not in quoted or q not in top_obs:
                quote_consistency_ok = False
                break
        if quote_consistency_ok:
            scores["insights_quote_consistency"] = 1.0

    tally = _compute_keyword_tally({pid: notes_by_prospect.get(pid) or "" for pid in prospect_ids}, benefits) if (prospect_ids and benefits) else {}
    agg_rows = _load_csv_dicts(aggregates_path) if aggregates_path.exists() else None
    if agg_rows is not None:
        try:
            with aggregates_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            header_ok = header_line == "benefit_id,benefit_title,count_quotes_matched,example_quote"
        except Exception:
            header_ok = False
        structure_ok = header_ok
        if structure_ok:
            for r in agg_rows:
                bid = r.get("benefit_id", "")
                btitle = r.get("benefit_title", "")
                cnt_str = r.get("count_quotes_matched", "")
                example = r.get("example_quote", "")
                if bid not in benefits_by_id:
                    structure_ok = False
                    break
                if btitle != benefits_titles_by_id.get(bid, ""):
                    structure_ok = False
                    break
                try:
                    cval = int(str(cnt_str).strip())
                    if cval < 0:
                        structure_ok = False
                        break
                except Exception:
                    structure_ok = False
                    break
                in_any_note = any((example and example in (notes_by_prospect.get(pid) or "")) for pid in prospect_ids)
                if not in_any_note and example != "":
                    if int(str(cnt_str).strip() or "0") > 0:
                        structure_ok = False
                        break
            if structure_ok:
                scores["aggregates_exists_and_structure"] = 1.0

    if agg_rows is not None and tally:
        rows_by_id = {r.get("benefit_id", ""): r for r in agg_rows}
        counts_ok = True
        for bid, info in tally.items():
            computed_count = info["count"]
            if computed_count > 0:
                if bid not in rows_by_id:
                    counts_ok = False
                    break
                r = rows_by_id[bid]
                try:
                    row_count = int(str(r.get("count_quotes_matched", "")).strip())
                except Exception:
                    counts_ok = False
                    break
                if row_count != computed_count:
                    counts_ok = False
                    break
                example = r.get("example_quote", "")
                if example not in info["quotes"]:
                    counts_ok = False
                    break
            else:
                if bid in rows_by_id:
                    try:
                        row_count = int(str(rows_by_id[bid].get("count_quotes_matched", "")).strip())
                    except Exception:
                        counts_ok = False
                        break
                    if row_count != 0:
                        counts_ok = False
                        break
        if counts_ok:
            scores["aggregates_counts_match_keyword_mapping"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()