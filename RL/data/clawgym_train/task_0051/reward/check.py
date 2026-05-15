import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_json_load(path: Path):
    try:
        return json.loads(_read_text(path))
    except Exception:
        return None


def _safe_csv_read(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def _safe_csv_dict_read(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames
        return rows, fieldnames
    except Exception:
        return None, None


class _ProfileHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []  # list of dicts with keys tag, id
        self.data_titles = []
        self.data_contact = []
        self.data_research = []
        self.awards = []
        self.selected_publications = []
        self.in_li = False
        self.current_li_buf = []

    def handle_starttag(self, tag, attrs):
        id_val = None
        for k, v in attrs:
            if k.lower() == "id":
                id_val = v
                break
        self.stack.append({"tag": tag, "id": id_val})
        if tag.lower() == "li":
            self.in_li = True
            self.current_li_buf = []

    def handle_endtag(self, tag):
        if tag.lower() == "li" and self.in_li:
            active_id = self._get_active_id()
            text = self._normalize_ws("".join(self.current_li_buf))
            if text:
                if active_id == "awards":
                    self.awards.append(text)
                elif active_id == "selected-publications":
                    self.selected_publications.append(text)
            self.in_li = False
            self.current_li_buf = []
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if not data:
            return
        active_id = self._get_active_id()
        s = self._normalize_ws(data)
        if not s:
            return
        if active_id == "titles":
            self.data_titles.append(s)
        elif active_id == "contact":
            self.data_contact.append(s)
        elif active_id == "research-areas":
            self.data_research.append(s)
        elif self.in_li and active_id in ("awards", "selected-publications"):
            self.current_li_buf.append(s)

    def _get_active_id(self):
        for item in reversed(self.stack):
            if item.get("id"):
                return item["id"]
        return None

    @staticmethod
    def _normalize_ws(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()


def _parse_department_profile_html(path: Path):
    html = _read_text(path)
    if not html:
        return None
    parser = _ProfileHTMLParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    titles_text = " ".join(parser.data_titles).strip()
    contact_text = " ".join(parser.data_contact).strip()
    research_text = " ".join(parser.data_research).strip()
    email_match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", contact_text)
    email = email_match.group(0) if email_match else ""
    research_clean = research_text
    m = re.search(r":", research_clean)
    if m:
        research_clean = research_clean[m.start() + 1 :]
    research_areas = [a.strip() for a in research_clean.split(";") if a.strip()]
    return {
        "current_title": titles_text.strip(),
        "email": email.strip(),
        "research_areas": research_areas,
        "awards": parser.awards,
        "selected_publications": parser.selected_publications,
    }


def _parse_simple_yaml(path: Path):
    text = _read_text(path)
    if not text:
        return None
    result = {}
    current_list_key = None
    try:
        for raw_line in text.splitlines():
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            if line.strip().startswith("#"):
                continue
            if line.lstrip().startswith("- "):
                if current_list_key is None:
                    return None
                item = line.strip()[2:].strip()
                result[current_list_key].append(item)
                continue
            if ":" in line:
                key, rest = line.split(":", 1)
                key = key.strip()
                value = rest.strip()
                if value == "":
                    current_list_key = key
                    result[current_list_key] = []
                else:
                    result[key] = value
                    current_list_key = None
            else:
                continue
        return result
    except Exception:
        return None


def _load_publications_csv(path: Path):
    rows, _ = _safe_csv_dict_read(path)
    if rows is None:
        return None
    pubs = []
    try:
        for r in rows:
            title = (r.get("title") or "").strip()
            year = int((r.get("year") or "0").strip())
            citations = int((r.get("citations") or "0").strip())
            authors = (r.get("authors") or "").strip()
            pubs.append({"title": title, "year": year, "citations": citations, "authors": authors})
        return pubs
    except Exception:
        return None


def _compute_top5_since_1995(publications):
    if publications is None:
        return None
    filtered = [p for p in publications if isinstance(p.get("year"), int) and p["year"] >= 1995]
    filtered.sort(key=lambda p: (-p["citations"], -p["year"], p["title"].lower()))
    top5 = filtered[:5]
    result = []
    for idx, p in enumerate(top5, start=1):
        result.append({"rank": idx, "title": p["title"], "year": p["year"], "citations": p["citations"]})
    return result


def _normalize_research_set_html(list_or_str):
    if isinstance(list_or_str, str):
        items = [x.strip() for x in list_or_str.split(";") if x.strip()]
    elif isinstance(list_or_str, list):
        items = [str(x).strip() for x in list_or_str if str(x).strip()]
    else:
        items = []
    return {x.lower() for x in items}


def _normalize_awards_set(list_or_str):
    if isinstance(list_or_str, str):
        items = []
        for part in re.split(r"[;\n]", list_or_str):
            if part.strip():
                items.append(part.strip())
    elif isinstance(list_or_str, list):
        items = [str(x).strip() for x in list_or_str if str(x).strip()]
    else:
        items = []
    return set(items)


def _read_email_file(path: Path) -> str:
    return _read_text(path)


def _check_email_address_and_context(content: str) -> float:
    if not content:
        return 0.0
    c = content.lower()
    has_address = "professor garoff" in c
    has_context = ("alumni spotlight" in c) and ("former student" in c or "former advisee" in c)
    return 1.0 if (has_address and has_context) else 0.0


def _check_email_bullets_questions(content: str) -> float:
    if not content:
        return 0.0
    lines = [ln.strip() for ln in content.splitlines()]
    bullets = [ln for ln in lines if ln.startswith("-") or ln.startswith("*")]
    if len(bullets) < 2:
        return 0.0
    joined = "\n".join(bullets).lower()
    if ("email" in joined) and ("award" in joined and "year" in joined) and ("research" in joined and "area" in joined):
        return 1.0
    return 0.0


def _check_email_publications_comparison(content: str) -> float:
    if not content:
        return 0.0
    c = content.lower()
    mentions_compare = ("selected publication" in c) and (("top 5" in c) or ("top five" in c))
    asks_preference = ("keep" in c or "adjust" in c or "update" in c or "change" in c)
    return 1.0 if (mentions_compare and asks_preference) else 0.0


def _check_email_courteous_closing(content: str) -> float:
    if not content:
        return 0.0
    closings = ["sincerely", "best regards", "best,", "thank you", "thanks", "warm regards", "regards,"]
    c = content.lower()
    if any(phrase in c for phrase in closings):
        return 1.0
    return 0.0


def _check_meeting_notes_sections(content: str) -> float:
    if not content:
        return 0.0
    c = content.lower()
    needed = ["summary", "discrepancies found", "action items", "next steps"]
    ok = all(sect in c for sect in needed)
    return 1.0 if ok else 0.0


def _check_meeting_notes_actions(content: str) -> float:
    if not content:
        return 0.0
    c = content.lower()
    send_email = ("send" in c and "email" in c)
    update_awards = (("update" in c or "updat" in c) and ("award" in c) and ("year" in c))
    finalize_pubs = (("finalize" in c or "finalise" in c or "finaliz" in c) and ("selected" in c and "publication" in c))
    return 1.0 if (send_email and update_awards and finalize_pubs) else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "top5_csv_correct": 0.0,
        "fact_check_report_structure": 0.0,
        "verified_fact_current_title": 0.0,
        "discrepancy_email_in_report": 0.0,
        "discrepancy_research_areas_in_report": 0.0,
        "discrepancy_awards_in_report": 0.0,
        "publications_check_selected_list_correct": 0.0,
        "publications_check_top5_list_correct": 0.0,
        "publications_check_diff_lists_correct": 0.0,
        "email_draft_address_and_context": 0.0,
        "email_draft_questions_bullets": 0.0,
        "email_draft_publications_comparison": 0.0,
        "email_draft_courteous_closing": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_action_items_present": 0.0,
    }

    dp_path = workspace / "input" / "department_profile.html"
    cv_path = workspace / "input" / "cv.yaml"
    pubs_path = workspace / "input" / "publications.csv"

    dp = _parse_department_profile_html(dp_path) if dp_path.exists() else None
    cv = _parse_simple_yaml(cv_path) if cv_path.exists() else None
    pubs = _load_publications_csv(pubs_path) if pubs_path.exists() else None
    computed_top5 = _compute_top5_since_1995(pubs) if pubs is not None else None

    expected_top5_csv_rows = None
    if computed_top5 is not None:
        expected_top5_csv_rows = [["rank", "title", "year", "citations"]]
        for item in computed_top5:
            expected_top5_csv_rows.append([str(item["rank"]), item["title"], str(item["year"]), str(item["citations"])])

    top5_out_path = workspace / "reports" / "top5_publications_since_1995.csv"
    if expected_top5_csv_rows is not None and top5_out_path.exists():
        actual_rows = _safe_csv_read(top5_out_path)
        if actual_rows is not None:
            actual_norm = [[cell.strip() for cell in row] for row in actual_rows]
            expected_norm = expected_top5_csv_rows
            if actual_norm == expected_norm:
                scores["top5_csv_correct"] = 1.0

    expected_selected_titles = dp["selected_publications"] if dp else None
    expected_top5_list = computed_top5 if computed_top5 is not None else None
    expected_top5_titles_set = set([x["title"] for x in expected_top5_list]) if expected_top5_list else None
    expected_missing_top = None
    expected_non_top_selected = None
    if expected_selected_titles is not None and expected_top5_titles_set is not None:
        selected_set = set(expected_selected_titles)
        expected_missing_top = sorted(list(expected_top5_titles_set - selected_set))
        expected_non_top_selected = sorted(list(selected_set - expected_top5_titles_set))

    report_path = workspace / "reports" / "garoff_fact_check_report.json"
    report = _safe_json_load(report_path) if report_path.exists() else None
    if report is not None and isinstance(report, dict):
        vf = report.get("verified_facts")
        disc = report.get("discrepancies")
        pubchk = report.get("publications_check")
        if isinstance(vf, list) and isinstance(disc, list) and isinstance(pubchk, dict):
            if all(k in pubchk for k in ["selected_on_profile", "top5_since_1995", "missing_top_papers", "non_top_selected"]):
                scores["fact_check_report_structure"] = 1.0

        if dp and cv:
            dp_title = (dp.get("current_title") or "").strip()
            cv_title = (cv.get("current_title") or "").strip()
            if dp_title and cv_title and dp_title == cv_title and isinstance(vf, list):
                found = False
                for item in vf:
                    if not isinstance(item, dict):
                        continue
                    field = item.get("field")
                    value = item.get("value")
                    sources = item.get("sources")
                    if field == "current_title" and isinstance(value, str) and value.strip() == dp_title and isinstance(sources, list):
                        src_set = set([str(s) for s in sources])
                        if "department_profile" in src_set and "cv" in src_set:
                            found = True
                            break
                scores["verified_fact_current_title"] = 1.0 if found else 0.0

        if dp and cv and isinstance(disc, list):
            dp_email = (dp.get("email") or "").strip()
            cv_email = (cv.get("email") or "").strip()
            if dp_email and cv_email and dp_email != cv_email:
                found_email = False
                for item in disc:
                    if not isinstance(item, dict):
                        continue
                    if item.get("field") == "email":
                        dpv = item.get("department_profile_value")
                        cvv = item.get("cv_value")
                        note = item.get("note")
                        if isinstance(dpv, str) and isinstance(cvv, str) and dpv.strip() == dp_email and cvv.strip() == cv_email and isinstance(note, str) and note.strip():
                            found_email = True
                            break
                scores["discrepancy_email_in_report"] = 1.0 if found_email else 0.0

            dp_ra = dp.get("research_areas") or []
            cv_ra = cv.get("research_areas") or []
            dp_ra_norm = _normalize_research_set_html(dp_ra)
            cv_ra_norm = _normalize_research_set_html(cv_ra)
            if dp_ra_norm and cv_ra_norm and dp_ra_norm != cv_ra_norm:
                found_ra = False
                for item in disc:
                    if not isinstance(item, dict):
                        continue
                    if item.get("field") == "research_areas":
                        dpv = item.get("department_profile_value")
                        cvv = item.get("cv_value")
                        note = item.get("note")
                        dpv_set = _normalize_research_set_html(dpv)
                        cvv_set = _normalize_research_set_html(cvv)
                        if dpv_set == dp_ra_norm and cvv_set == cv_ra_norm and isinstance(note, str) and note.strip():
                            found_ra = True
                            break
                scores["discrepancy_research_areas_in_report"] = 1.0 if found_ra else 0.0

            dp_aw = dp.get("awards") or []
            cv_aw = cv.get("awards") or []
            dp_aw_set = _normalize_awards_set(dp_aw)
            cv_aw_set = _normalize_awards_set(cv_aw)
            if dp_aw_set and cv_aw_set and dp_aw_set != cv_aw_set:
                found_aw = False
                for item in disc:
                    if not isinstance(item, dict):
                        continue
                    if item.get("field") == "awards":
                        dpv = item.get("department_profile_value")
                        cvv = item.get("cv_value")
                        note = item.get("note")
                        dpv_set = _normalize_awards_set(dpv)
                        cvv_set = _normalize_awards_set(cvv)
                        if dpv_set == dp_aw_set and cvv_set == cv_aw_set and isinstance(note, str) and note.strip():
                            found_aw = True
                            break
                scores["discrepancy_awards_in_report"] = 1.0 if found_aw else 0.0

        if report is not None and isinstance(report, dict) and "publications_check" in report:
            pc = report["publications_check"]
            if expected_selected_titles is not None and isinstance(pc.get("selected_on_profile"), list):
                sel = pc.get("selected_on_profile")
                if [str(x).strip() for x in sel] == expected_selected_titles:
                    scores["publications_check_selected_list_correct"] = 1.0
            if expected_top5_list is not None and isinstance(pc.get("top5_since_1995"), list):
                actual_top5 = pc.get("top5_since_1995")
                correct = True
                if len(actual_top5) != len(expected_top5_list):
                    correct = False
                else:
                    for exp, act in zip(expected_top5_list, actual_top5):
                        if not isinstance(act, dict):
                            correct = False
                            break
                        atitle = str(act.get("title") or "").strip()
                        ayear = act.get("year")
                        acit = act.get("citations")
                        arank = act.get("rank")
                        if atitle != exp["title"]:
                            correct = False
                            break
                        try:
                            ayear_i = int(ayear)
                            acit_i = int(acit)
                            arank_i = int(arank)
                        except Exception:
                            correct = False
                            break
                        if ayear_i != exp["year"] or acit_i != exp["citations"] or arank_i != exp["rank"]:
                            correct = False
                            break
                if correct:
                    scores["publications_check_top5_list_correct"] = 1.0
            miss = pc.get("missing_top_papers")
            non_top = pc.get("non_top_selected")
            if isinstance(miss, list) and isinstance(non_top, list) and expected_missing_top is not None and expected_non_top_selected is not None:
                miss_sorted = sorted([str(x).strip() for x in miss if str(x).strip()])
                non_top_sorted = sorted([str(x).strip() for x in non_top if str(x).strip()])
                if miss_sorted == expected_missing_top and non_top_sorted == expected_non_top_selected:
                    scores["publications_check_diff_lists_correct"] = 1.0

    email_path = workspace / "drafts" / "email_to_garoff.txt"
    email_content = _read_email_file(email_path) if email_path.exists() else ""
    scores["email_draft_address_and_context"] = _check_email_address_and_context(email_content)
    scores["email_draft_questions_bullets"] = _check_email_bullets_questions(email_content)
    scores["email_draft_publications_comparison"] = _check_email_publications_comparison(email_content)
    scores["email_draft_courteous_closing"] = _check_email_courteous_closing(email_content)

    notes_path = workspace / "meetings" / "alumni_spotlight_notes.md"
    notes_content = _read_text(notes_path) if notes_path.exists() else ""
    scores["meeting_notes_sections_present"] = _check_meeting_notes_sections(notes_content)
    scores["meeting_notes_action_items_present"] = _check_meeting_notes_actions(notes_content)

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()