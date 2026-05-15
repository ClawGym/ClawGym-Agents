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


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def _to_bool_from_text(val: str):
    if isinstance(val, bool):
        return val
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in {"true", "yes", "1", "y"}:
        return True
    if s in {"false", "no", "0", "n"}:
        return False
    return None


class GuidelinesParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_h2 = False
        self.current_h2_text = ""
        self.active_section = None
        self.in_li = False
        self.current_li_text = ""
        self.selection_criteria = []
        self.accessibility = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "h2":
            self.in_h2 = True
            self.current_h2_text = ""
        elif tag.lower() == "li":
            self.in_li = True
            self.current_li_text = ""

    def handle_data(self, data):
        if self.in_h2:
            self.current_h2_text += data
        elif self.in_li:
            self.current_li_text += data

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "h2":
            self.in_h2 = False
            heading = self.current_h2_text.strip()
            self.active_section = heading
            self.current_h2_text = ""
        elif t == "li":
            self.in_li = False
            text = " ".join(self.current_li_text.strip().split())
            if self.active_section == "Selection Criteria":
                if text:
                    self.selection_criteria.append(text)
            elif self.active_section == "Accessibility":
                if text:
                    self.accessibility.append(text)
            self.current_li_text = ""


def _parse_guidelines(html_text: str):
    parser = GuidelinesParser()
    try:
        parser.feed(html_text)
    except Exception:
        return [], []
    return parser.selection_criteria, parser.accessibility


def _derive_rules(selection_criteria: list) -> dict:
    rules = {
        "allowed_ratings": None,
        "max_runtime": None,
        "require_captions": None
    }
    for item in selection_criteria:
        s = item.strip().lower()
        if "mpaa" in s and "g or pg" in s:
            rules["allowed_ratings"] = {"G", "PG"}
        if "runtime" in s and "120" in s:
            m = re.search(r"(\d+)", s)
            if m:
                try:
                    rules["max_runtime"] = int(m.group(1))
                except Exception:
                    rules["max_runtime"] = 120
            else:
                rules["max_runtime"] = 120
        if "caption" in s or "subtitle" in s:
            rules["require_captions"] = True
    return rules


def _safe_int(val):
    try:
        return int(val)
    except Exception:
        return None


def _first_n_words(text: str, n: int) -> str:
    if text is None:
        return ""
    words = re.split(r"\s+", text.strip())
    words = [w for w in words if w != ""]
    return " ".join(words[:n])


def _compute_suitability(movie: dict, rules: dict):
    reasons = []
    allowed = rules.get("allowed_ratings")
    rating = (movie.get("mpaa_rating") or "").strip().upper()
    if allowed is not None and rating not in allowed:
        reasons.append("Fails rating preference (not G/PG).")
    max_rt = rules.get("max_runtime")
    rt = _safe_int(movie.get("runtime_min"))
    if max_rt is not None and isinstance(rt, int) and rt > max_rt:
        reasons.append(f"Runtime exceeds {max_rt} minutes.")
    req_cap = rules.get("require_captions")
    has_cap = movie.get("has_captions")
    if not isinstance(has_cap, bool):
        has_cap = _to_bool_from_text(has_cap)
    if req_cap and has_cap is not True:
        reasons.append("Captions/subtitles not available.")
    suitable = len(reasons) == 0
    if suitable:
        reasons = ["meets all selection criteria"]
    return suitable, reasons


class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture_summary = False
        self.summary_tag = None
        self.summary_text_chunks = []
        self.ul_stack = []
        self.current_ul_items = None
        self.ul_lists = []
        self.capture_script = False
        self.script_id = None
        self.script_type = None
        self.catalog_script_content = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k.lower(): v for k, v in attrs}
        if attrs_dict.get("id") == "summary-counts":
            self.capture_summary = True
            self.summary_tag = tag.lower()
        if tag.lower() == "ul":
            self.current_ul_items = []
            self.ul_stack.append("ul")
        if tag.lower() == "li" and self.current_ul_items is not None:
            self.current_ul_items.append("")
        if tag.lower() == "script":
            self.script_id = attrs_dict.get("id")
            self.script_type = attrs_dict.get("type")
            if self.script_id == "catalog-data" and self.script_type == "application/json":
                self.capture_script = True

    def handle_data(self, data):
        if self.capture_summary:
            self.summary_text_chunks.append(data)
        if self.current_ul_items is not None and len(self.current_ul_items) > 0:
            li_text = self.current_ul_items[-1] + data
            self.current_ul_items[-1] = li_text
        if self.capture_script:
            self.catalog_script_content += data

    def handle_endtag(self, tag):
        if self.capture_summary and self.summary_tag and tag.lower() == self.summary_tag:
            self.capture_summary = False
            self.summary_tag = None
        if tag.lower() == "ul":
            if self.current_ul_items is not None:
                cleaned = [" ".join(t.strip().split()) for t in self.current_ul_items if t is not None and t.strip() != ""]
                self.ul_lists.append(cleaned)
            self.current_ul_items = None
            if self.ul_stack:
                self.ul_stack.pop()
        if tag.lower() == "script":
            if self.capture_script:
                self.capture_script = False

    def get_summary_text(self) -> str:
        txt = "".join(self.summary_text_chunks)
        return " ".join(txt.strip().split())


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "catalog_guidelines_match_input": 0.0,
        "catalog_movies_fields_match_input": 0.0,
        "catalog_short_note_correct": 0.0,
        "catalog_suitability_correct": 0.0,
        "selection_csv_structure_and_rows": 0.0,
        "site_summary_counts_correct": 0.0,
        "site_suitable_titles_list": 0.0,
        "site_embedded_catalog_json_exact": 0.0,
        "run_local_sh_serves_site": 0.0,
        "run_local_ps1_serves_site": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_environment_setup_content": 0.0,
        "meeting_notes_data_summary_correct": 0.0,
        "meeting_notes_action_items_sufficient": 0.0,
    }

    # Load inputs
    input_guidelines_path = workspace / "input" / "content_guidelines.html"
    input_movies_path = workspace / "input" / "movies.csv"
    guidelines_html = _read_text(input_guidelines_path)
    movies_rows = _load_csv_dicts(input_movies_path)

    # Parse guidelines and derive rules
    selection_criteria = []
    accessibility = []
    if guidelines_html:
        selection_criteria, accessibility = _parse_guidelines(guidelines_html)
    rules = _derive_rules(selection_criteria)

    # Compute expected from inputs
    expected_movies = {}
    if movies_rows is not None:
        for row in movies_rows:
            title = (row.get("title") or "").strip()
            year = _safe_int(row.get("year"))
            mpaa = (row.get("mpaa_rating") or "").strip()
            genre = (row.get("genre") or "").strip()
            runtime = _safe_int(row.get("runtime_min"))
            has_captions = _to_bool_from_text(row.get("has_captions"))
            description = (row.get("description") or "").strip()
            short_note = _first_n_words(description, 12)
            mv = {
                "title": title,
                "year": year,
                "mpaa_rating": mpaa,
                "genre": genre,
                "runtime_min": runtime,
                "has_captions": has_captions,
                "description": description,
                "short_note": short_note,
            }
            suitable, reasons = _compute_suitability(mv, rules)
            mv["suitable_per_guidelines"] = suitable
            mv["suitability_reasons"] = reasons
            expected_movies[title] = mv

    # Validate out/catalog.json
    catalog_path = workspace / "out" / "catalog.json"
    catalog_obj = _load_json(catalog_path)
    catalog_guidelines_match = False
    movies_fields_match = False
    short_notes_match = False
    suitability_match = False

    if catalog_obj and isinstance(catalog_obj, dict) and expected_movies:
        try:
            cat_sel = catalog_obj["guidelines"]["selection_criteria"]
            cat_acc = catalog_obj["guidelines"]["accessibility"]
            if cat_sel == selection_criteria and cat_acc == accessibility:
                catalog_guidelines_match = True
        except Exception:
            catalog_guidelines_match = False

        try:
            cat_movies = catalog_obj["movies"]
            if isinstance(cat_movies, list):
                by_title = {m.get("title", ""): m for m in cat_movies if isinstance(m, dict)}
                base_ok = True
                short_ok = True
                suit_ok = True
                for t, exp in expected_movies.items():
                    m = by_title.get(t)
                    if not m:
                        base_ok = False
                        short_ok = False
                        suit_ok = False
                        break
                    try:
                        # Base fields exact match and types
                        if m.get("title") != exp["title"]:
                            base_ok = False
                        if _safe_int(m.get("year")) != exp["year"]:
                            base_ok = False
                        if (m.get("mpaa_rating") or "") != exp["mpaa_rating"]:
                            base_ok = False
                        if (m.get("genre") or "") != exp["genre"]:
                            base_ok = False
                        if _safe_int(m.get("runtime_min")) != exp["runtime_min"]:
                            base_ok = False
                        # has_captions must be a boolean and same value
                        if not isinstance(m.get("has_captions"), bool):
                            base_ok = False
                        if bool(m.get("has_captions")) != bool(exp["has_captions"]):
                            base_ok = False
                        if (m.get("description") or "") != exp["description"]:
                            base_ok = False
                    except Exception:
                        base_ok = False
                    if (m.get("short_note") or "") != exp["short_note"]:
                        short_ok = False
                    if m.get("suitable_per_guidelines") != exp["suitable_per_guidelines"]:
                        suit_ok = False
                    reasons = m.get("suitability_reasons")
                    if not isinstance(reasons, list) or len(reasons) == 0:
                        suit_ok = False
                    else:
                        if exp["suitable_per_guidelines"]:
                            if reasons != ["meets all selection criteria"]:
                                suit_ok = False
                        else:
                            # Each violated rule should be represented in reasons text
                            fail_checks = []
                            if rules.get("allowed_ratings") is not None and exp["mpaa_rating"].strip().upper() not in rules["allowed_ratings"]:
                                fail_checks.append(lambda rs: any("rat" in r.lower() for r in rs))
                            if rules.get("max_runtime") is not None and isinstance(exp["runtime_min"], int) and exp["runtime_min"] > rules["max_runtime"]:
                                fail_checks.append(lambda rs: any("time" in r.lower() or "runtime" in r.lower() for r in rs))
                            if rules.get("require_captions") and not bool(exp["has_captions"]):
                                fail_checks.append(lambda rs: any("caption" in r.lower() or "subtitle" in r.lower() for r in rs))
                            for chk in fail_checks:
                                if not chk(reasons):
                                    suit_ok = False
                movies_fields_match = base_ok
                short_notes_match = short_ok
                suitability_match = suit_ok
        except Exception:
            movies_fields_match = False
            short_notes_match = False
            suitability_match = False

    if catalog_guidelines_match:
        scores["catalog_guidelines_match_input"] = 1.0
    if movies_fields_match:
        scores["catalog_movies_fields_match_input"] = 1.0
    if short_notes_match:
        scores["catalog_short_note_correct"] = 1.0
    if suitability_match:
        scores["catalog_suitability_correct"] = 1.0

    # Validate out/selection.csv
    selection_csv_path = workspace / "out" / "selection.csv"
    sel_rows = _load_csv_dicts(selection_csv_path)
    selection_ok = False
    if sel_rows is not None and expected_movies:
        header_line = ""
        try:
            with selection_csv_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip()
        except Exception:
            header_line = ""
        expected_header = "title,year,mpaa_rating,runtime_min,has_captions,genre,short_note"
        header_ok = (header_line == expected_header)
        expected_suitable = [m for m in expected_movies.values() if m["suitable_per_guidelines"]]
        expected_titles = {m["title"] for m in expected_suitable}
        actual_titles = {row.get("title", "").strip() for row in sel_rows}
        rows_ok = True
        if len(sel_rows) != len(expected_suitable) or actual_titles != expected_titles:
            rows_ok = False
        else:
            by_title_row = {row.get("title", "").strip(): row for row in sel_rows}
            for e in expected_suitable:
                row = by_title_row.get(e["title"])
                if row is None:
                    rows_ok = False
                    break
                # Ensure column order via DictReader fieldnames
                col_order_ok = list(row.keys()) == expected_header.split(",")
                if not col_order_ok:
                    rows_ok = False
                    break
                if _safe_int(row.get("year")) != e["year"]:
                    rows_ok = False
                    break
                if (row.get("mpaa_rating") or "").strip() != e["mpaa_rating"]:
                    rows_ok = False
                    break
                if _safe_int(row.get("runtime_min")) != e["runtime_min"]:
                    rows_ok = False
                    break
                has_cap_row = _to_bool_from_text(row.get("has_captions"))
                if has_cap_row is None or has_cap_row != bool(e["has_captions"]):
                    rows_ok = False
                    break
                if (row.get("genre") or "").strip() != e["genre"]:
                    rows_ok = False
                    break
                if (row.get("short_note") or "").strip() != e["short_note"]:
                    rows_ok = False
                    break
        selection_ok = header_ok and rows_ok

    if selection_ok:
        scores["selection_csv_structure_and_rows"] = 1.0

    # Validate out/site/index.html
    site_index_path = workspace / "out" / "site" / "index.html"
    site_html = _read_text(site_index_path)
    if site_html and expected_movies:
        sp = SiteParser()
        try:
            sp.feed(site_html)
        except Exception:
            pass
        total_count = len(expected_movies)
        suitable_count = sum(1 for m in expected_movies.values() if m["suitable_per_guidelines"])
        expected_summary = f"Total movies: {total_count}; Suitable: {suitable_count}"
        summary_text = sp.get_summary_text()
        if summary_text == expected_summary:
            scores["site_summary_counts_correct"] = 1.0
        expected_titles = {m["title"] for m in expected_movies.values() if m["suitable_per_guidelines"]}
        ul_match = False
        for ul in sp.ul_lists:
            if set(ul) == expected_titles and len(ul) == len(expected_titles):
                ul_match = True
                break
        if ul_match:
            scores["site_suitable_titles_list"] = 1.0
        catalog_text = _read_text(catalog_path)
        if sp.catalog_script_content != "" and catalog_text != "":
            if sp.catalog_script_content == catalog_text:
                scores["site_embedded_catalog_json_exact"] = 1.0

    # Validate run scripts
    run_sh = workspace / "run_local.sh"
    run_ps1 = workspace / "run_local.ps1"
    sh_text = _read_text(run_sh)
    ps1_text = _read_text(run_ps1)

    def _check_server_script(text: str) -> float:
        if not text:
            return 0.0
        has_cd = bool(re.search(r"\bcd\b.*out/site", text, flags=re.IGNORECASE)) or "out/site" in text.lower()
        has_http_server = "http.server" in text
        uses_python = bool(re.search(r"\bpython(\d(\.\d+)*)?\b", text)) or "-m http.server" in text
        has_port = re.search(r"(--bind|\-b|\s|^)?(8000)", text) is not None or "8000" in text
        # Port requirement is to serve on http://localhost:8000; accept if 8000 appears
        if has_cd and has_http_server and uses_python and has_port:
            return 1.0
        return 0.0

    scores["run_local_sh_serves_site"] = _check_server_script(sh_text)
    scores["run_local_ps1_serves_site"] = _check_server_script(ps1_text)

    # Validate out/meeting_notes.md
    notes_path = workspace / "out" / "meeting_notes.md"
    notes_text = _read_text(notes_path)
    if notes_text:
        sections = ["Environment Setup", "What Was Deployed", "Data Summary", "Action Items"]
        present = all(sec.lower() in notes_text.lower() for sec in sections)
        if present:
            scores["meeting_notes_sections_present"] = 1.0

        def get_section(sec_name: str) -> str:
            lines = notes_text.splitlines()
            start_idx = -1
            for i, line in enumerate(lines):
                if sec_name.lower() in line.lower():
                    start_idx = i
                    break
            if start_idx == -1:
                return ""
            end_idx = len(lines)
            for j in range(start_idx + 1, len(lines)):
                for other in sections:
                    if other.lower() in lines[j].lower():
                        end_idx = j
                        break
                if end_idx != len(lines):
                    break
            body = "\n".join(lines[start_idx + 1:end_idx]).strip()
            return body

        env_text = get_section("Environment Setup")
        dep_text = get_section("What Was Deployed")
        data_text = get_section("Data Summary")
        act_text = get_section("Action Items")

        env_ok = False
        if env_text:
            mentions_site = "out/site" in env_text
            mentions_run = ("run_local.sh" in env_text) or ("run_local.ps1" in env_text) or ("http.server" in env_text)
            mentions_data = ("input/movies.csv" in env_text) or ("input/content_guidelines.html" in env_text) or ("out/catalog.json" in env_text) or ("input/" in env_text)
            env_ok = mentions_site and mentions_run and mentions_data
        if env_ok:
            scores["meeting_notes_environment_setup_content"] = 1.0

        data_ok = False
        if data_text and expected_movies:
            total_count = len(expected_movies)
            suitable_count = sum(1 for m in expected_movies.values() if m["suitable_per_guidelines"])
            has_total = str(total_count) in data_text
            has_suitable = str(suitable_count) in data_text
            unsuitable = [m for m in expected_movies.values() if not m["suitable_per_guidelines"]]
            reason_keywords = {}
            for m in unsuitable:
                kws = []
                if rules.get("allowed_ratings") is not None and m["mpaa_rating"].strip().upper() not in rules["allowed_ratings"]:
                    kws.append("rat")
                if rules.get("max_runtime") is not None and isinstance(m["runtime_min"], int) and m["runtime_min"] > rules["max_runtime"]:
                    kws.append("time")
                if rules.get("require_captions") and not bool(m["has_captions"]):
                    kws.append("caption")
                reason_keywords[m["title"]] = kws
            bullet_lines = [line.strip() for line in data_text.splitlines() if re.match(r"^\s*[-*\u2022]\s+", line)]
            titles_ok = True
            for m in unsuitable:
                found = False
                for bl in bullet_lines:
                    if m["title"] in bl:
                        lower = bl.lower()
                        kw_expected = reason_keywords[m["title"]]
                        kw_ok = True
                        for kw in kw_expected:
                            if kw == "rat":
                                if "rat" not in lower:
                                    kw_ok = False
                                    break
                            elif kw == "time":
                                if ("runtime" not in lower) and ("time" not in lower):
                                    kw_ok = False
                                    break
                            elif kw == "caption":
                                if ("caption" not in lower) and ("subtitle" not in lower):
                                    kw_ok = False
                                    break
                        found = kw_ok
                        if found:
                            break
                if not found:
                    titles_ok = False
                    break
            data_ok = has_total and has_suitable and titles_ok
        if data_ok:
            scores["meeting_notes_data_summary_correct"] = 1.0

        actions_ok = False
        if act_text:
            bullets = [line.strip() for line in act_text.splitlines() if re.match(r"^\s*[-*\u2022]\s+", line)]
            guideline_kws = ["mpaa", "rating", "runtime", "minute", "captions", "subtitle", "large-print", "handout", "playback", "offline", "laptop"]
            tailored_count = 0
            for b in bullets:
                lb = b.lower()
                if any(kw in lb for kw in guideline_kws):
                    tailored_count += 1
            top3_present = any(("top 3" in b.lower() or "top three" in b.lower()) for b in bullets)
            date_placeholder = any(re.search(r"\b20\d{2}-\d{2}-\d{2}\b", b) or ("<date>" in b.lower()) or ("[date]" in b.lower()) or ("by DATE" in b) for b in bullets)
            actions_ok = (tailored_count >= 4) and top3_present and date_placeholder
        if actions_ok:
            scores["meeting_notes_action_items_sufficient"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()