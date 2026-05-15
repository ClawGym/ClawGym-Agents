import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return None


def count_words(text: str) -> int:
    if not text:
        return 0
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def find_md_basenames(proposals_dir: Path) -> List[str]:
    if not proposals_dir.exists():
        return []
    basenames = []
    for p in proposals_dir.iterdir():
        if p.is_file() and p.suffix.lower() == ".md":
            basenames.append(p.name)
    basenames.sort()
    return basenames


def parse_sections(lines: List[str], sections: List[str]) -> Dict[str, str]:
    content: Dict[str, str] = {}
    current = None
    buf: List[str] = []
    section_set = set(sections)
    for line in lines:
        stripped = line.strip()
        if stripped in section_set:
            if current is not None:
                content[current] = "\n".join(buf).strip()
            current = stripped
            buf = []
        else:
            if current is not None:
                buf.append(line)
    if current is not None:
        content[current] = "\n".join(buf).strip()
    return content


def extract_months(text: str) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"(\d+)\s*months?\b", text, flags=re.I)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def parse_proposal(path: Path) -> Optional[Dict[str, object]]:
    text = read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    title = None
    scholar = None
    for line in lines[:10]:
        m1 = re.match(r"\s*Title:\s*(.+)\s*$", line)
        if m1:
            title = m1.group(1).strip()
        m2 = re.match(r"\s*Scholar:\s*(.+)\s*$", line)
        if m2:
            scholar = m2.group(1).strip()
    if not title or not scholar:
        for line in lines:
            if not title:
                m1 = re.match(r"\s*Title:\s*(.+)\s*$", line)
                if m1:
                    title = m1.group(1).strip()
            if not scholar:
                m2 = re.match(r"\s*Scholar:\s*(.+)\s*$", line)
                if m2:
                    scholar = m2.group(1).strip()
            if title and scholar:
                break
    sections = parse_sections(lines, ["Approach", "Corpus", "Methods", "Deliverables", "Timeline", "Notes"])
    approach = sections.get("Approach", "")
    corpus = sections.get("Corpus", "")
    methods = sections.get("Methods", "")
    deliverables = sections.get("Deliverables", "")
    timeline_text = sections.get("Timeline", "")
    timeline_months = extract_months(timeline_text)

    scholar_first = None
    scholar_last = None
    if scholar:
        parts = scholar.strip().split()
        prefixes = {"Dr.", "Dr", "Prof.", "Prof"}
        clean_parts = [p for p in parts if p not in prefixes]
        if clean_parts:
            scholar_first = clean_parts[0]
            scholar_last = clean_parts[-1]
        else:
            if len(parts) >= 1:
                scholar_last = parts[-1]
            if len(parts) >= 2:
                scholar_first = parts[0]
    return {
        "file": path.name,
        "title": title or "",
        "scholar": scholar or "",
        "scholar_first": scholar_first or "",
        "scholar_last": scholar_last or "",
        "approach": approach,
        "corpus": corpus,
        "methods": methods,
        "deliverables": deliverables,
        "timeline_text": timeline_text,
        "timeline_months": timeline_months if timeline_months is not None else -1,
    }


def tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z\-]+", text.lower())
    return tokens


def select_keywords(text: str, min_len: int = 5) -> List[str]:
    toks = tokenize(text)
    stop = {
        "within", "their", "about", "which", "these", "those", "among", "across",
        "using", "based", "study", "project", "reader", "readers",
        "general", "should", "clear", "month", "months", "figure",
        "figures", "pages", "page"
    }
    keys = [t for t in toks if len(t) >= min_len and t not in stop]
    seen = set()
    uniq = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def has_month_pattern(text: str, number: int) -> bool:
    pattern = rf"\b{number}\s*(?:[-‑–—]|\s)?\s*months?\b"
    return re.search(pattern, text, flags=re.I) is not None


def line_contains_all_basenames(text: str, basenames: List[str]) -> bool:
    for line in text.splitlines():
        if all(b in line for b in basenames):
            return True
    return False


def check_summary_file(summary_path: Path, expected_title: str, expected_scholar: str) -> Tuple[float, float, float]:
    text = read_text_safe(summary_path)
    if text is None:
        return 0.0, 0.0, 0.0
    lines = text.splitlines()
    if len(lines) < 2:
        return 0.0, 0.0, 0.0
    line1 = lines[0].strip()
    line2 = lines[1].strip()
    struct_ok = 1.0 if (line1 == f"Title: {expected_title}" and line2 == f"Scholar: {expected_scholar}") else 0.0

    bullet_start_idx = None
    for i in range(2, len(lines)):
        if re.match(r"^\s*([-*+])\s+", lines[i]):
            bullet_start_idx = i
            break
    if bullet_start_idx is None:
        narrative_lines = lines[2:]
        bullets_lines = []
    else:
        narrative_lines = lines[2:bullet_start_idx]
        bullets_lines = lines[bullet_start_idx:]

    narrative_text = "\n".join([ln for ln in narrative_lines if ln.strip()])
    wc = count_words(narrative_text)
    wc_ok = 1.0 if 180 <= wc <= 220 else 0.0

    bullets = [ln for ln in bullets_lines if re.match(r"^\s*([-*+])\s+", ln)]
    bullets_count_ok = len(bullets) == 4
    risk_present = any(re.search(r"\brisk\b", b, flags=re.I) for b in bullets)
    bullets_ok = 1.0 if (bullets_count_ok and risk_present) else 0.0
    return struct_ok, wc_ok, bullets_ok


def check_summary_content(summary_path: Path, proposal: Dict[str, object]) -> float:
    text = read_text_safe(summary_path)
    if text is None:
        return 0.0
    lines = text.splitlines()
    content_text = "\n".join(lines[2:]).lower() if len(lines) >= 2 else text.lower()

    approach = str(proposal.get("approach", ""))
    methods = str(proposal.get("methods", ""))
    corpus = str(proposal.get("corpus", ""))
    deliverables = str(proposal.get("deliverables", ""))
    months = proposal.get("timeline_months", -1)

    kw_approach_methods = select_keywords(approach + " " + methods)
    kw_corpus = select_keywords(corpus)
    kw_deliv = select_keywords(deliverables)

    hits_am = sum(1 for k in kw_approach_methods[:10] if k in content_text)
    hits_corpus = sum(1 for k in kw_corpus[:10] if k in content_text)
    hits_deliv = sum(1 for k in kw_deliv[:10] if k in content_text)

    am_ok = hits_am >= 2
    corpus_ok = hits_corpus >= 1
    deliv_ok = hits_deliv >= 1
    timeline_ok = months != -1 and (has_month_pattern(content_text, int(months)) or str(months) in content_text)

    return 1.0 if (am_ok and corpus_ok and deliv_ok and timeline_ok) else 0.0


def check_comparison_report(path: Path, proposals: List[Dict[str, object]], basenames: List[str]) -> Dict[str, float]:
    scores = {
        "comparison_report_core_sections": 0.0,
        "comparison_report_deadline_sentence": 0.0,
        "comparison_report_proposal_listed": 0.0,
        "recommendation_justifies_priorities": 0.0,
    }
    text = read_text_safe(path)
    if text is None:
        return scores

    has_keywords = all(k.lower() in text.lower() for k in ["Timeline", "Corpus", "Methods", "Deliverables"])
    months_ok = True
    for p in proposals:
        m = p.get("timeline_months", -1)
        if m == -1:
            months_ok = False
            break
        if not has_month_pattern(text, int(m)):
            months_ok = False
            break
    scores["comparison_report_core_sections"] = 1.0 if (has_keywords and months_ok) else 0.0

    compliant = [p for p in proposals if isinstance(p.get("timeline_months"), int) and p.get("timeline_months") <= 10]
    deadline_ok = False
    ten_month_pattern = re.search(r"\b10\s*(?:[-‑–—]|\s)?\s*month", text, flags=re.I) is not None
    if ten_month_pattern and compliant:
        comp = compliant[0]
        comp_months = comp.get("timeline_months", None)
        if comp_months is not None and has_month_pattern(text, int(comp_months)):
            name_or_title_present = (str(comp.get("scholar_last", "")).lower() in text.lower()) or (str(comp.get("title", "")).lower() in text.lower())
            deadline_ok = name_or_title_present
    scores["comparison_report_deadline_sentence"] = 1.0 if deadline_ok else 0.0

    scores["comparison_report_proposal_listed"] = 1.0 if line_contains_all_basenames(text, basenames) else 0.0

    rec_present = re.search(r"\brecommend", text, flags=re.I) is not None
    priority_hits = 0
    for kw in ["schedule", "deadline", "accessibility", "clarity", "cross-cultural", "breadth"]:
        if re.search(rf"\b{re.escape(kw)}\b", text, flags=re.I):
            priority_hits += 1
    scores["recommendation_justifies_priorities"] = 1.0 if (rec_present and priority_hits >= 2) else 0.0

    return scores


def offer_decline_targets(proposals: List[Dict[str, object]]) -> Tuple[Optional[Dict[str, object]], Optional[Dict[str, object]]]:
    offer = None
    decline = None
    for p in proposals:
        months = p.get("timeline_months", -1)
        if isinstance(months, int) and months <= 10:
            offer = p
        elif isinstance(months, int) and months > 10:
            decline = p
    return offer, decline


def extract_deliverable_keywords(deliv_text: str) -> List[str]:
    kws = []
    if not deliv_text:
        return kws
    for kw in ["monograph", "diagram", "diagrams", "figure", "figures", "plates", "appendix", "dataset", "csv"]:
        if kw in deliv_text.lower():
            kws.append(kw)
    toks = select_keywords(deliv_text)
    for t in toks:
        if t not in kws and len(kws) < 10:
            kws.append(t)
    return kws


def check_offer_email(path: Path, offer_p: Dict[str, object]) -> Tuple[float, float]:
    text = read_text_safe(path)
    if text is None:
        return 0.0, 0.0
    lines = text.splitlines()
    if not lines:
        return 0.0, 0.0
    subj_expected = f"Subject: Commission Offer: {offer_p.get('title', '')}"
    subj_ok = lines[0].strip() == subj_expected

    body = "\n".join(lines[1:]).strip()
    scholar = offer_p.get("scholar", "")
    name_ok = (offer_p.get("scholar_last", "").lower() in body.lower()) or (scholar.lower() in body.lower())
    struct_ok = 1.0 if (subj_ok and name_ok) else 0.0

    title_ok = offer_p.get("title", "").lower() in body.lower()
    ten_month_ok = re.search(r"\b10\s*(?:[-‑–—]|\s)?\s*month", body, flags=re.I) is not None
    deliv_kws = extract_deliverable_keywords(str(offer_p.get("deliverables", "")))
    deliv_ok = any(kw in body.lower() for kw in [k.lower() for k in deliv_kws])
    wc = count_words(body)
    wc_ok = wc <= 200 and wc > 0
    content_ok = 1.0 if (title_ok and ten_month_ok and deliv_ok and wc_ok) else 0.0

    return struct_ok, content_ok


def check_decline_email(path: Path, decline_p: Dict[str, object]) -> Tuple[float, float]:
    text = read_text_safe(path)
    if text is None:
        return 0.0, 0.0
    lines = text.splitlines()
    if not lines:
        return 0.0, 0.0
    subj_expected = f"Subject: Regarding Your Proposal: {decline_p.get('title', '')}"
    subj_ok = lines[0].strip() == subj_expected

    body = "\n".join(lines[1:]).strip()
    scholar = decline_p.get("scholar", "")
    name_ok = (decline_p.get("scholar_last", "").lower() in body.lower()) or (scholar.lower() in body.lower())
    struct_ok = 1.0 if (subj_ok and name_ok) else 0.0

    positive_kws = []
    for sec in ["approach", "methods", "corpus", "deliverables"]:
        positive_kws.extend(select_keywords(str(decline_p.get(sec, ""))))
    pos_ok = any(kw in body.lower() for kw in [k.lower() for k in positive_kws[:15]])

    schedule_ok = (
        re.search(r"\b(schedule|timeline|deadline|timeframe)\b", body, flags=re.I) is not None
        or (isinstance(decline_p.get("timeline_months", None), int) and has_month_pattern(body, int(decline_p.get("timeline_months", -1))))
        or re.search(r"\b10\s*(?:[-‑–—]|\s)?\s*month", body, flags=re.I) is not None
    )
    wc = count_words(body)
    wc_ok = wc <= 200 and wc > 0
    content_ok = 1.0 if (pos_ok and schedule_ok and wc_ok) else 0.0

    return struct_ok, content_ok


def check_metadata(path: Path, proposals: List[Dict[str, object]]) -> float:
    text = read_text_safe(path)
    if text is None:
        return 0.0
    try:
        data = json.loads(text)
    except Exception:
        return 0.0
    if not isinstance(data, list):
        return 0.0
    expected = {}
    for p in proposals:
        expected[p["file"]] = {
            "title": p["title"],
            "scholar_last": p["scholar_last"],
            "timeline_months": p["timeline_months"],
        }
    found = {fn: False for fn in expected.keys()}
    for obj in data:
        if not isinstance(obj, dict):
            return 0.0
        if "file" not in obj or "title" not in obj or "scholar_last" not in obj or "timeline_months" not in obj:
            return 0.0
        fn = obj.get("file")
        if fn in expected:
            exp = expected[fn]
            tm = obj.get("timeline_months")
            if not isinstance(tm, (int, float)):
                return 0.0
            title_ok = obj.get("title") == exp["title"]
            scholar_ok = obj.get("scholar_last") == exp["scholar_last"]
            tm_ok = int(tm) == int(exp["timeline_months"])
            if title_ok and scholar_ok and tm_ok:
                found[fn] = True
    return 1.0 if all(found.values()) else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "summary_green_structure": 0.0,
        "summary_saffron_structure": 0.0,
        "summary_green_wordcount_180_220": 0.0,
        "summary_saffron_wordcount_180_220": 0.0,
        "summary_green_bullets_count_and_risk": 0.0,
        "summary_saffron_bullets_count_and_risk": 0.0,
        "summary_green_content_coverage": 0.0,
        "summary_saffron_content_coverage": 0.0,
        "comparison_report_core_sections": 0.0,
        "comparison_report_deadline_sentence": 0.0,
        "comparison_report_proposal_listed": 0.0,
        "recommendation_justifies_priorities": 0.0,
        "offer_email_correct_recipient_and_subject": 0.0,
        "offer_email_mentions_title_deadline_deliverables_under_200": 0.0,
        "decline_email_correct_recipient_and_subject": 0.0,
        "decline_email_positive_aspect_and_schedule_under_200": 0.0,
        "metadata_json_valid_and_complete": 0.0,
    }

    proposals_dir = workspace / "input" / "proposals"
    basenames = find_md_basenames(proposals_dir)
    proposals: List[Dict[str, object]] = []
    for b in basenames:
        p = parse_proposal(proposals_dir / b)
        if p:
            proposals.append(p)

    proposals_by_file = {p["file"]: p for p in proposals if isinstance(p, dict) and "file" in p}

    green = proposals_by_file.get("proposal_green.md")
    saffron = proposals_by_file.get("proposal_saffron.md")

    summaries_dir = workspace / "output" / "edited_summaries"
    green_summary = summaries_dir / "proposal_green.summary.md"
    saffron_summary = summaries_dir / "proposal_saffron.summary.md"

    if green:
        s_struct, s_wc, s_bul = check_summary_file(green_summary, green.get("title", ""), green.get("scholar", ""))
        scores["summary_green_structure"] = s_struct
        scores["summary_green_wordcount_180_220"] = s_wc
        scores["summary_green_bullets_count_and_risk"] = s_bul
        scores["summary_green_content_coverage"] = check_summary_content(green_summary, green)

    if saffron:
        s_struct, s_wc, s_bul = check_summary_file(saffron_summary, saffron.get("title", ""), saffron.get("scholar", ""))
        scores["summary_saffron_structure"] = s_struct
        scores["summary_saffron_wordcount_180_220"] = s_wc
        scores["summary_saffron_bullets_count_and_risk"] = s_bul
        scores["summary_saffron_content_coverage"] = check_summary_content(saffron_summary, saffron)

    comparison_path = workspace / "output" / "comparison_report.md"
    comp_scores = check_comparison_report(comparison_path, proposals, basenames)
    scores.update(comp_scores)

    offer_p, decline_p = offer_decline_targets(proposals)

    emails_dir = workspace / "output" / "emails"
    if offer_p:
        offer_filename = f"offer_{str(offer_p.get('scholar_last', '')).lower()}.txt"
        offer_path = emails_dir / offer_filename
        s1, s2 = check_offer_email(offer_path, offer_p)
        scores["offer_email_correct_recipient_and_subject"] = s1
        scores["offer_email_mentions_title_deadline_deliverables_under_200"] = s2
    if decline_p:
        decline_filename = f"decline_{str(decline_p.get('scholar_last', '')).lower()}.txt"
        decline_path = emails_dir / decline_filename
        d1, d2 = check_decline_email(decline_path, decline_p)
        scores["decline_email_correct_recipient_and_subject"] = d1
        scores["decline_email_positive_aspect_and_schedule_under_200"] = d2

    metadata_path = workspace / "output" / "metadata" / "processed_proposals.json"
    scores["metadata_json_valid_and_complete"] = check_metadata(metadata_path, proposals)

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()