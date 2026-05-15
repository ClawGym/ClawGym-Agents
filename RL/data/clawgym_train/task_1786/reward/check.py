import json
import csv
import sys
import re
import runpy
from html.parser import HTMLParser
from pathlib import Path


def read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def parse_yaml_config(path: Path):
    text = read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    cfg = {}
    i = 0

    def skip_blank(i0):
        i_local = i0
        while i_local < len(lines) and (lines[i_local].strip() == "" or lines[i_local].lstrip().startswith("#")):
            i_local += 1
        return i_local

    def parse_list(i0, indent_spaces):
        items = []
        i_local = i0
        while i_local < len(lines):
            line = lines[i_local]
            if line.strip() == "" or line.lstrip().startswith("#"):
                i_local += 1
                continue
            if not line.startswith(" " * indent_spaces):
                break
            stripped = line[indent_spaces:]
            if not stripped.startswith("- "):
                break
            items.append(stripped[2:].strip())
            i_local += 1
        return items, i_local

    def parse_kv_block(i0, indent_spaces):
        mapp = {}
        i_local = i0
        while i_local < len(lines):
            line = lines[i_local]
            if line.strip() == "" or line.lstrip().startswith("#"):
                i_local += 1
                continue
            if not line.startswith(" " * indent_spaces):
                break
            stripped = line[indent_spaces:]
            m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", stripped)
            if not m:
                break
            key = m.group(1)
            rest = m.group(2)
            if rest == "":
                next_idx = skip_blank(i_local + 1)
                if next_idx < len(lines) and lines[next_idx].startswith(" " * (indent_spaces + 2)):
                    if lines[next_idx].strip().startswith("- "):
                        lst, new_i = parse_list(next_idx, indent_spaces + 2)
                        mapp[key] = lst
                        i_local = new_i
                    else:
                        submap, new_i = parse_kv_block(next_idx, indent_spaces + 2)
                        mapp[key] = submap
                        i_local = new_i
                else:
                    mapp[key] = None
                    i_local += 1
            else:
                mapp[key] = rest.strip()
                i_local += 1
        return mapp, i_local

    while i < len(lines):
        i = skip_blank(i)
        if i >= len(lines):
            break
        line = lines[i]
        m_top = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if not m_top:
            i += 1
            continue
        key = m_top.group(1)
        rest = m_top.group(2)
        if rest == "":
            next_idx = skip_blank(i + 1)
            if next_idx < len(lines) and lines[next_idx].startswith("  "):
                if lines[next_idx].strip().startswith("- "):
                    lst, new_i = parse_list(next_idx, 2)
                    cfg[key] = lst
                    i = new_i
                else:
                    mp, new_i = parse_kv_block(next_idx, 2)
                    cfg[key] = mp
                    i = new_i
            else:
                cfg[key] = None
                i += 1
        else:
            cfg[key] = rest.strip()
            i += 1
    required_top = {"city", "required_sections", "law_section_id", "output_paths"}
    if not required_top.issubset(set(cfg.keys())):
        return None
    return cfg


class LawHTMLParser(HTMLParser):
    def __init__(self, target_id: str):
        super().__init__()
        self.target_id = target_id
        self.in_target = False
        self.section_level = 0
        self.in_h2 = False
        self.in_p = False
        self.code_section = ""
        self.current_p = []
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "section":
            attrs_dict = dict(attrs)
            if not self.in_target and attrs_dict.get("id") == self.target_id:
                self.in_target = True
                self.section_level = 1
            elif self.in_target:
                self.section_level += 1
        if self.in_target:
            if tag.lower() == "h2":
                self.in_h2 = True
            elif tag.lower() == "p":
                self.in_p = True
                self.current_p = []

    def handle_endtag(self, tag):
        if self.in_target:
            if tag.lower() == "h2":
                self.in_h2 = False
            elif tag.lower() == "p":
                self.in_p = False
                text = "".join(self.current_p).strip()
                if text:
                    self.paragraphs.append(text)
                self.current_p = []
        if tag.lower() == "section" and self.in_target:
            self.section_level -= 1
            if self.section_level <= 0:
                self.in_target = False

    def handle_data(self, data):
        if self.in_target:
            if self.in_h2:
                self.code_section += data
            if self.in_p:
                self.current_p.append(data)


def parse_law_section(html_path: Path, section_id: str):
    text = read_text(html_path)
    if text is None:
        return None
    parser = LawHTMLParser(section_id)
    try:
        parser.feed(text)
    except Exception:
        return None
    code_section = parser.code_section.strip()
    paragraphs = [p.strip() for p in parser.paragraphs]
    if not code_section or not paragraphs:
        return None
    requirement = None
    penalty = None
    for p in paragraphs:
        pl = p.lower()
        if requirement is None and ("leash" in pl or "restrained" in pl):
            requirement = p
        if penalty is None and pl.startswith("penalty:"):
            penalty = p
    return {
        "code_section": code_section,
        "paragraphs": paragraphs,
        "requirement": requirement,
        "penalty": penalty,
    }


def parse_incident_report(path: Path):
    text = read_text(path)
    if text is None:
        return None
    result = {
        "date": None,
        "time": None,
        "location": None,
        "dog_name": None,
        "owner_name": None,
        "neighbor_name": None,
    }
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^Date:\s*(.+)$", line)
        if m:
            result["date"] = m.group(1).strip()
            continue
        m = re.match(r"^Time:\s*(.+)$", line)
        if m:
            result["time"] = m.group(1).strip()
            continue
        m = re.match(r"^Location:\s*(.+)$", line)
        if m:
            result["location"] = m.group(1).strip()
            continue
        m = re.match(r"^Dog:\s*(.+)$", line)
        if m:
            dog_line = m.group(1).strip()
            name = dog_line.split("(")[0].split(",")[0].strip()
            result["dog_name"] = name
            continue
        m = re.match(r"^Owner:\s*(.+)$", line)
        if m:
            result["owner_name"] = m.group(1).strip()
            continue
        m = re.match(r"^Neighbor:\s*(.+)$", line)
        if m:
            result["neighbor_name"] = m.group(1).strip()
            continue
    return result


def parse_neighbor_statement(path: Path):
    text = read_text(path)
    if text is None:
        return None
    result = {
        "date": None,
        "time": None,
        "location": None,
    }
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^Date:\s*(.+)$", line)
        if m:
            result["date"] = m.group(1).strip()
            continue
        m = re.match(r"^Time:\s*(.+)$", line)
        if m:
            result["time"] = m.group(1).strip()
            continue
        m = re.match(r"^Location:\s*(.+)$", line)
        if m:
            result["location"] = m.group(1).strip()
            continue
    return result


def parse_medical_bills(csv_path: Path, tsv_path: Path):
    items = []
    total = 0.0
    # CSV
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                amt = safe_float(row.get("amount_usd"))
                if amt is None:
                    continue
                item = {
                    "provider": row.get("provider", ""),
                    "date": row.get("date", ""),
                    "description": row.get("description", ""),
                    "amount_usd": round(amt, 2),
                }
                items.append(item)
                total += amt
    except Exception:
        pass
    # TSV
    try:
        with tsv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                amt = safe_float(row.get("amount_usd"))
                if amt is None:
                    continue
                item = {
                    "provider": row.get("provider", ""),
                    "date": row.get("date", ""),
                    "description": row.get("description", ""),
                    "amount_usd": round(amt, 2),
                }
                items.append(item)
                total += amt
    except Exception:
        pass
    total = round(total, 2)
    return items, total


def load_schema(workspace: Path):
    schema_path = workspace / "config" / "schema.py"
    if not schema_path.exists():
        return None
    try:
        globs = runpy.run_path(str(schema_path))
        schema = globs.get("SCHEMA")
        if isinstance(schema, dict):
            return schema
    except Exception:
        return None
    return None


def extract_markdown_headings(md_text: str):
    headings = []
    lines = md_text.splitlines()
    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            headings.append((level, title, idx))
    return headings


def extract_section_text(md_text: str, section_title: str):
    lines = md_text.splitlines()
    headings = extract_markdown_headings(md_text)
    start_idx = None
    for _, title, idx in headings:
        if title == section_title:
            start_idx = idx + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for _, _, idx in headings:
        if idx > start_idx - 1:
            end_idx = idx
            break
    content = "\n".join(lines[start_idx:end_idx]).strip()
    return content


def normalize_damages_list(damages):
    norm = []
    for d in damages:
        provider = d.get("provider")
        date = d.get("date")
        desc = d.get("description")
        amt = d.get("amount_usd")
        amt_val = round(float(amt), 2) if isinstance(amt, (int, float)) else None
        norm.append((provider, date, desc, amt_val))
    return norm


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_file_exists": 0.0,
        "report_sections_ordered": 0.0,
        "report_notes_rabies": 0.0,
        "report_laws_section_content": 0.0,
        "structured_json_file_exists": 0.0,
        "structured_json_parsed": 0.0,
        "json_keys_match_schema": 0.0,
        "incident_fields_match_inputs": 0.0,
        "consistency_checks_required_present": 0.0,
        "damages_items_aggregated": 0.0,
        "damages_total_matches_sum": 0.0,
        "laws_data_correct": 0.0,
        "sources_list_matches_used_inputs": 0.0,
        "sources_inventory_file_exists": 0.0,
        "sources_inventory_valid_and_consistent": 0.0,
    }

    config_path = workspace / "config" / "report_config.yaml"
    config = parse_yaml_config(config_path)
    if config is None:
        return scores

    required_sections = config.get("required_sections") or []
    law_section_id = config.get("law_section_id")
    city = config.get("city")
    output_paths = config.get("output_paths") or {}
    validation = config.get("validation") or {}
    incident_required_fields = (validation.get("incident_fields") or [])

    report_path = workspace / output_paths.get("report_markdown", "output/case_summary.md")
    structured_json_path = workspace / output_paths.get("structured_json", "output/extracted_data.json")
    sources_inventory_path = workspace / output_paths.get("sources_inventory", "output/sources_inventory.json")

    used_input_paths = [
        "input/incident/incident_report.txt",
        "input/statements/neighbor_statement.md",
        "input/dog/dog_records.json",
        "input/medical/bills_urgentcare.csv",
        "input/medical/bills_pt.tsv",
        "input/laws/leash_law.html",
    ]

    incident_report = parse_incident_report(workspace / "input" / "incident" / "incident_report.txt")
    neighbor_stmt = parse_neighbor_statement(workspace / "input" / "statements" / "neighbor_statement.md")
    dog_records = read_json(workspace / "input" / "dog" / "dog_records.json")
    medical_items, medical_total = parse_medical_bills(
        workspace / "input" / "medical" / "bills_urgentcare.csv",
        workspace / "input" / "medical" / "bills_pt.tsv",
    )
    law_info = parse_law_section(workspace / "input" / "laws" / "leash_law.html", law_section_id) if isinstance(law_section_id, str) else None

    report_text = read_text(report_path)
    if report_path.exists() and report_text is not None:
        scores["report_file_exists"] = 1.0
        headings = extract_markdown_headings(report_text)
        titles = [t for _, t, _ in headings]
        pos = -1
        ok_order = True
        for sec in required_sections:
            if sec not in titles:
                ok_order = False
                break
            idx = [i for i, t in enumerate(titles) if t == sec][0]
            if idx <= pos:
                ok_order = False
                break
            pos = idx
        if ok_order and len(required_sections) > 0:
            scores["report_sections_ordered"] = 1.0

        notes_text = extract_section_text(report_text, "Notes")
        rabies_ok = False
        if notes_text is not None and isinstance(dog_records, dict):
            rabies = (((dog_records or {}).get("vaccinations") or {}).get("rabies") or {})
            status = rabies.get("status")
            valid_until = rabies.get("valid_until")
            if status and valid_until:
                status_variants = {status.lower()}
                if status.lower() == "up_to_date":
                    status_variants.add("up to date")
                notes_lower = notes_text.lower()
                if any(s in notes_lower for s in status_variants) and valid_until in notes_text:
                    rabies_ok = True
        if rabies_ok:
            scores["report_notes_rabies"] = 1.0

        laws_text = extract_section_text(report_text, "Applicable Local Laws")
        laws_ok = False
        if laws_text is not None and isinstance(law_info, dict):
            req = law_info.get("requirement")
            pen = law_info.get("penalty")
            code_section = law_info.get("code_section")
            if req and pen and code_section:
                if (req in laws_text) and (pen in laws_text) and (code_section in laws_text):
                    laws_ok = True
        if laws_ok:
            scores["report_laws_section_content"] = 1.0

    if structured_json_path.exists():
        scores["structured_json_file_exists"] = 1.0
    extracted_data = read_json(structured_json_path)
    if isinstance(extracted_data, dict):
        scores["structured_json_parsed"] = 1.0
        schema = load_schema(workspace)
        if isinstance(schema, dict):
            schema_keys = set(schema.keys())
            if schema_keys.issubset(set(extracted_data.keys())):
                scores["json_keys_match_schema"] = 1.0

        incident_json = extracted_data.get("incident") or {}
        inc_ok = True
        if isinstance(incident_report, dict):
            for field in incident_required_fields:
                exp = incident_report.get(field)
                got = incident_json.get(field)
                if exp != got or exp is None:
                    inc_ok = False
                    break
        else:
            inc_ok = False
        if inc_ok:
            scores["incident_fields_match_inputs"] = 1.0

        cc_list = extracted_data.get("consistency_checks")
        cc_ok = False
        if isinstance(cc_list, list):
            def find_check(field_kw, sources_req):
                for item in cc_list:
                    if not isinstance(item, dict):
                        continue
                    field = str(item.get("field", "")).lower()
                    sources = item.get("sources")
                    status = item.get("status")
                    details = item.get("details")
                    if field_kw in field and isinstance(sources, list) and status in {"ok", "mismatch", "missing"} and isinstance(details, str) and len(details) > 0:
                        if all(src in sources for src in sources_req):
                            return item
                return None

            date_sources = ["input/incident/incident_report.txt", "input/statements/neighbor_statement.md"]
            time_sources = ["input/incident/incident_report.txt", "input/statements/neighbor_statement.md"]
            dog_sources = ["input/incident/incident_report.txt", "input/dog/dog_records.json"]

            date_expected = None
            time_expected = None
            dog_expected = None
            if isinstance(incident_report, dict) and isinstance(neighbor_stmt, dict):
                if incident_report.get("date") and neighbor_stmt.get("date"):
                    date_expected = "ok" if incident_report.get("date") == neighbor_stmt.get("date") else "mismatch"
                else:
                    date_expected = None
                if incident_report.get("time") and neighbor_stmt.get("time"):
                    time_expected = "ok" if incident_report.get("time") == neighbor_stmt.get("time") else "mismatch"
                else:
                    time_expected = None
            if isinstance(incident_report, dict) and isinstance(dog_records, dict):
                dog_name_inc = incident_report.get("dog_name")
                dog_name_rec = dog_records.get("dog_name")
                if dog_name_inc and dog_name_rec:
                    dog_expected = "ok" if dog_name_inc == dog_name_rec else "mismatch"
                else:
                    dog_expected = None

            date_check = find_check("date", date_sources)
            time_check = find_check("time", time_sources)
            dog_check = find_check("dog", dog_sources)

            if date_check and time_check and dog_check:
                ok_status = True
                if date_expected and date_check.get("status") != date_expected:
                    ok_status = False
                if time_expected and time_check.get("status") != time_expected:
                    ok_status = False
                if dog_expected and dog_check.get("status") != dog_expected:
                    ok_status = False
                cc_ok = ok_status
        if cc_ok:
            scores["consistency_checks_required_present"] = 1.0

        damages_json = extracted_data.get("damages")
        damages_total_json = extracted_data.get("damages_total")
        dmg_ok = False
        if isinstance(damages_json, list):
            norm_expected = sorted(normalize_damages_list(medical_items))
            norm_got = sorted(normalize_damages_list(damages_json))
            amounts_numeric = all(isinstance(d.get("amount_usd"), (int, float)) for d in damages_json)
            if amounts_numeric and norm_expected == norm_got and len(damages_json) == len(medical_items):
                dmg_ok = True
        if dmg_ok:
            scores["damages_items_aggregated"] = 1.0

        dt_ok = False
        if isinstance(damages_json, list) and isinstance(damages_total_json, (int, float)):
            sum_json = 0.0
            all_numeric = True
            for d in damages_json:
                amt = d.get("amount_usd")
                if not isinstance(amt, (int, float)):
                    all_numeric = False
                    break
                sum_json += float(amt)
            sum_json = round(sum_json, 2)
            if all_numeric:
                if abs(sum_json - float(damages_total_json)) < 1e-6 and abs(sum_json - medical_total) < 1e-6:
                    dt_ok = True
        if dt_ok:
            scores["damages_total_matches_sum"] = 1.0

        laws_json = extracted_data.get("laws") or {}
        laws_ok_json = False
        if isinstance(laws_json, dict) and isinstance(law_info, dict):
            req = law_info.get("requirement")
            pen = law_info.get("penalty")
            code_section = law_info.get("code_section")
            if req and pen and code_section:
                city_ok = (laws_json.get("city") == city)
                code_ok = (laws_json.get("code_section") == code_section)
                req_ok = (laws_json.get("requirement") == req)
                pen_ok = (laws_json.get("penalty") == pen)
                if city_ok and code_ok and req_ok and pen_ok:
                    laws_ok_json = True
        if laws_ok_json:
            scores["laws_data_correct"] = 1.0

        sources_json = extracted_data.get("sources")
        sources_ok = False
        if isinstance(sources_json, list):
            sources_set = set(sources_json)
            expected_set = set(used_input_paths)
            if sources_set == expected_set:
                sources_ok = True
        if sources_ok:
            scores["sources_list_matches_used_inputs"] = 1.0

    if sources_inventory_path.exists():
        scores["sources_inventory_file_exists"] = 1.0
    inv = read_json(sources_inventory_path)
    inv_ok = False
    if isinstance(inv, list) and isinstance(extracted_data, dict):
        inv_paths = set()
        details_ok = True
        for item in inv:
            if not isinstance(item, dict):
                details_ok = False
                break
            p = item.get("path")
            fmt = item.get("format")
            b = item.get("bytes")
            if not isinstance(p, str) or not isinstance(fmt, str) or not isinstance(b, int):
                details_ok = False
                break
            actual_path = workspace / p
            if not actual_path.exists():
                details_ok = False
                break
            try:
                actual_size = actual_path.stat().st_size
            except Exception:
                details_ok = False
                break
            if actual_size != b:
                details_ok = False
                break
            ext = actual_path.suffix.lower().replace(".", "")
            if fmt.lower() != ext:
                details_ok = False
                break
            inv_paths.add(p)
        sources_json = extracted_data.get("sources") if isinstance(extracted_data, dict) else None
        if isinstance(sources_json, list) and details_ok:
            if set(sources_json) == inv_paths:
                inv_ok = True
    if inv_ok:
        scores["sources_inventory_valid_and_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()